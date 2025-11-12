import ast
import copy
import fnmatch
import json
import logging
import pathlib
import pprint
import shlex
import re
import subprocess
import tempfile
import textwrap
import tomllib
import typing
import configparser

import pyproject_fmt
import tomlkit
import tox_toml_fmt
import yaml
from packaging.requirements import Requirement
from pip._internal.req import parse_requirements
from pip._internal.network.session import PipSession
import ruamel.yaml

logger = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO)


class AtomMapping:
    def __init__(self):
        self._container = {}

    def __getitem__(self, key):
        return self._container[key]

    def __setitem__(self, key, value):
        return self._container.__setitem__(key, value)

    def as_dict(self):
        return self._container


ValueType = (
    bool | int | str | AtomMapping | list[bool | int | str | list[str] | AtomMapping]
)
Transformer = typing.Callable[[str, ValueType], tuple[str, ValueType]]


def identity(path: str, value: ValueType) -> tuple[str, ValueType]:
    return path, value


def boolean_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    value = value.lower()
    assert value in ("true", "false")
    return path, value == "true"


def comma_separated_list_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    return path, [v.strip() for v in value.split(",") if v.strip()]


def equal_mapping_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    lines = [v.strip() for v in value.splitlines() if v.strip()]
    mapping = AtomMapping()
    for line in lines:
        key, value = line.split("=", maxsplit=1)
        mapping[key.strip()] = value.strip()
    return path, mapping


def remove_comments(string: str) -> str:
    no_comments = re.sub("(?<!\\\\)#.+$", "", string, flags=re.M)
    return no_comments.replace("\\#", "#")


def newline_separated_list_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    value = remove_comments(value)
    value = value.replace("\\\n", " ")
    return path, [v.strip() for v in value.splitlines() if v.strip()]


def command_lines_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    path, value = newline_separated_list_value(path, value)
    commands = [
        [
            (part if part != "{posargs}" else {"replace": "posargs", "extend": "true"})
            for part in shlex.split(line)
        ]
        for line in value
        if not line.startswith("#")
    ]
    return path, commands


def move_up(n) -> Transformer:
    def move_func(path: str, value: ValueType) -> tuple[str, ValueType]:
        path = path.split("/")
        path = ["", *path[1 + n :]]
        path = "/".join(path)
        return path, value

    return move_func


def change_parent(change: typing.Callable[[str], str]) -> Transformer:
    def change_parent_func(path: str, value: ValueType) -> tuple[str, ValueType]:
        paths = path.split("/")
        paths[-2] = change(paths[-2])
        return "/".join(paths), value

    return change_parent_func


def compose(*funcs: Transformer) -> Transformer:
    def composed(path: str, value: ValueType):
        for f in reversed(funcs):
            path, value = f(path, value)
        return path, value

    return composed


TRANSFORMERS: dict[str, Transformer] = {
    "/tox/skipsdist": compose(move_up(1), boolean_value),
    "/tox/skip_missing_interpreters": compose(move_up(1), boolean_value),
    "/tox/envlist": compose(move_up(1), comma_separated_list_value),
    "/vars/*": identity,
    "/testenv/setenv": compose(
        change_parent(lambda p: "env_run_base"), equal_mapping_value
    ),
    "/testenv/passenv": compose(
        change_parent(lambda p: "env_run_base"), newline_separated_list_value
    ),
    "/testenv/allowlist_externals": compose(
        change_parent(lambda p: "env_run_base"), newline_separated_list_value
    ),
    "/testenv:*/description": change_parent(lambda p: p.replace("testenv:", "env/")),
    "/testenv:*/deps": compose(
        change_parent(lambda p: p.replace("testenv:", "env/")),
        newline_separated_list_value,
    ),
    "/testenv:*/commands": compose(
        change_parent(lambda p: p.replace("testenv:", "env/")),
        command_lines_value,
    ),
    "/testenv:*/allowlist_externals": compose(
        change_parent(lambda p: p.replace("testenv:", "env/")),
        newline_separated_list_value,
    ),
    "/testenv:*/setenv": compose(
        change_parent(lambda p: p.replace("testenv:", "env/")), equal_mapping_value
    ),
}


def flatten_with_prefix(obj: dict, prefix: str) -> dict[str, ValueType]:
    result = {}
    for key, value in obj.items():
        flat_key = f"{prefix}/{key}"
        if not isinstance(value, dict):
            result[flat_key] = value
        else:
            result.update(flatten_with_prefix(value, flat_key))
    return result


def flatten(obj: dict) -> dict[str, ValueType]:
    obj = copy.deepcopy(obj)
    return flatten_with_prefix(obj, "")


def unflatten(obj: dict) -> dict:
    obj = copy.deepcopy(obj)
    result = {}
    for key_path, value in obj.items():
        cursor = result
        keys = key_path.split("/")
        for key in keys[1:-1]:
            if key in cursor:
                cursor = cursor[key]
            else:
                cursor[key] = {}
                cursor = cursor[key]
        cursor[keys[-1]] = value.as_dict() if isinstance(value, AtomMapping) else value
    return result


class Uvify:
    def __init__(self, project: pathlib.Path | str):
        self.project = pathlib.Path(project)
        self.charmcraft_file = self.project / "charmcraft.yaml"
        self.yaml = ruamel.yaml.YAML()
        self.yaml.default_flow_style = True
        self.yaml.preserve_quotes = True
        self.charmcraft = self.yaml.load(self.charmcraft_file.read_text())
        self.metadata_file = self.project / "metadata.yaml"
        if not self.metadata_file.is_file():
            self.metadata_file = self.charmcraft_file
        self.metadata = yaml.safe_load(self.metadata_file.read_text())
        self.requirements_file = self.project / "requirements.txt"
        self.tox_ini_file = self.project / "tox.ini"
        self.tox_ini = self._load_tox_ini()
        self.resolved_tox_ini = self._load_resolve_tox_ini()
        self.tox_vars = self._parse_tox_vars()
        self.tox_toml_file = self.project / "tox.toml"
        self.tox_toml = self._load_tox_toml()
        self.pyproject_file = self.project / "pyproject.toml"
        self.pyproject = tomllib.loads(self.pyproject_file.read_text())
        self.licenserc_yaml_file = self.project / ".licenserc.yaml"
        self.licenserc_yaml = self.yaml.load(self.licenserc_yaml_file.read_text())
        self.project_name = self._get_project_name()
        self.python_version = self._get_python_version()
        self.dependencies = self._load_dependencies()
        self.dependency_groups = self._load_dependency_groups()
        self.conflicts = []

    def _parse_tox_vars(self):
        tox_vars = {}
        for var, value in self.tox_ini["vars"].items():
            if not var.endswith("_path"):
                raise ValueError(f"unknown tox variable in tox.ini: '{var}'")
            if "[vars]" not in value:
                tox_vars[var] = value
                continue
            # this is a compound variable
            values = [v.strip() for v in value.strip().split() if v.strip()]
            resolved_values = []
            for v in values:
                match = re.match(r"\{\[vars]([a-z0-9_-]+)}", v)
                if match:
                    var_name = match.group(1)
                    resolved_values.append(tox_vars[var_name])
                else:
                    resolved_values.append(v)
            tox_vars[var] = resolved_values
        return tox_vars

    def _get_python_version(self):
        for ubuntu_version, python_version in [("20.04", "3.8"), ("22.04", "3.10")]:
            if ubuntu_version in self.charmcraft_file.read_text():
                return python_version
        return "3.12"

    def _get_project_name(self):
        try:
            git_url = subprocess.check_output(
                ["git", "remote", "get-url", "origin"],
                cwd=self.project,
                encoding="utf-8",
            ).strip()
            return git_url.removesuffix(".git").split("/")[-1]
        except subprocess.CalledProcessError:
            logger.warning(
                "unable to determine project name, use default project name 'charm'"
            )
            return "charm"

    def _parse_ini(self, content: str):
        ini = configparser.ConfigParser()
        ini.read_string(content)
        tox_config = {}
        for section in ini.sections():
            tox_config[section] = {}
            for option in ini.options(section):
                tox_config[section][option] = ini.get(section, option)
        return tox_config

    def _load_tox_ini(self):
        return self._parse_ini(self.tox_ini_file.read_text(encoding="utf-8"))

    def _load_resolve_tox_ini(self):
        envs = [
            env.removeprefix("testenv:")
            for env in self.tox_ini
            if env.startswith("testenv:")
        ]
        resolved_tox = subprocess.check_output(
            ["tox", "config", "-e", ",".join(envs)],
            cwd=self.project,
            encoding="utf-8",
        ).strip()
        return self._parse_ini(resolved_tox)

    def _load_tox_toml(self):
        flatten_tox_config = flatten(self.tox_ini)
        transformed_tox_toml = {}
        for key, value in flatten_tox_config.items():
            transformed = False
            for pattern, transform in TRANSFORMERS.items():
                if not fnmatch.fnmatch(key, pattern):
                    continue
                new_key, new_value = transform(key, value)
                transformed_tox_toml[new_key] = new_value
                transformed = True
                break
            if not transformed:
                raise ValueError(f"unknown key: {key}")
        tox_toml = unflatten(transformed_tox_toml)
        for env in tox_toml["env"].values():
            commands = env["commands"]
            replaced_commands = []
            for command in commands:
                replaced_command = []
                for c in command:
                    if not isinstance(c, str):
                        replaced_command.append(c)
                        continue
                    match = re.match(r"\{\[vars]([a-z0-9_-]+)}", c)
                    if match and isinstance(self.tox_vars[match.group(1)], list):
                        replaced_command.append(
                            {
                                "replace": "ref",
                                "of": ["vars", match.group(1)],
                                "extend": True,
                            }
                        )
                    else:
                        replaced_command.append(c)
                replaced_commands.append(replaced_command)
            env["commands"] = replaced_commands
        tox_toml["vars"] = self.tox_vars
        return tox_toml

    def _load_lib_pydeps(self):
        dependencies = []

        for file in self.project.glob("lib/charms/**/*.py"):
            tree = ast.parse(file.read_text(encoding="utf-8"), file.name)
            for node in tree.body:
                if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                    continue
                targets = (
                    node.targets if isinstance(node, ast.Assign) else [node.target]
                )
                if any(isinstance(t, ast.Name) and t.id == "PYDEPS" for t in targets):
                    dependencies.extend(ast.literal_eval(node.value))
        return dependencies

    def _pip_dryrun(self, requirements: list[str]):
        with tempfile.NamedTemporaryFile(
            dir=self.project, suffix=".json", mode="r"
        ) as tmp:
            subprocess.check_call(
                [
                    "pip",
                    "install",
                    *requirements,
                    "--dry-run",
                    "--report",
                    tmp.name,
                    "--ignore-installed",
                ],
                stdout=subprocess.DEVNULL,
            )
            report = json.loads(tmp.read())
            return report["install"]

    def _parse_requirements(self, requirements: list[str]):
        resolved_requirements = []
        with tempfile.NamedTemporaryFile(
            dir=self.project, suffix=".txt", mode="w"
        ) as tmp:
            tmp.write("\n".join(requirements))
            tmp.flush()
            requirements = [
                r.requirement
                for r in parse_requirements(tmp.name, session=PipSession())
            ]

        for requirement in requirements:
            if ":" not in requirement or "@" in requirement.split(":")[0]:
                resolved_requirements.append(requirement)
                continue
            resolved_package_name = self._pip_dryrun([requirement])[0]["metadata"][
                "name"
            ]
            resolved_requirements.append(f"{resolved_package_name} @ {requirement}")
        return resolved_requirements

    def _pin_requirements(self, requirements: list[str]):
        installed = self._pip_dryrun(requirements)
        pinned_requirements = []
        for requirement in requirements:
            req = Requirement(requirement)
            if req.url:
                pinned_requirements.append(requirement)
                continue
            for installed_req in installed:
                if installed_req["metadata"]["name"].lower().replace("_", "-") == req.name.lower().replace("_", "-"):
                    version = installed_req["metadata"]["version"]
                    pinned_requirements.append(f"{req.name}=={version}")
                    break
        return sorted(set(pinned_requirements))

    def _load_dependencies(self):
        requirements = self.requirements_file.read_text().splitlines()
        dependencies = self._parse_requirements(requirements) + self._load_lib_pydeps()
        return self._pin_requirements(dependencies)

    def _load_dependency_groups(self):
        groups = {}
        for key, value in self.resolved_tox_ini.items():
            match = re.match("testenv:(.+)", key)
            if not match:
                continue
            env = match.group(1)
            dependencies = [
                dep.strip() for dep in value["deps"].splitlines() if dep.strip()
            ]
            dependencies = self._parse_requirements(dependencies)
            excluded_dependencies = []
            for dependency in dependencies:
                included_in_main = False
                for main_dependency in self.dependencies:
                    req = Requirement(dependency)
                    main_req = Requirement(main_dependency)
                    if req.name == main_req.name and req.extras == main_req.extras:
                        included_in_main = True
                        break
                if not included_in_main:
                    excluded_dependencies.append(dependency)
            groups[env] = sorted(set(excluded_dependencies))
        return groups

    @staticmethod
    def reset(project: str | pathlib.Path):
        subprocess.check_call(["git", "reset", "--hard", "HEAD"], cwd=project)

    def migrate_uv(self):
        self.pyproject["project"] = {
            "name": self.project_name,
            "version": "0.0.0",
            "description": self.metadata["summary"],
            "readme": "README.md",
            "requires-python": f">={self.python_version}",
            "dependencies": self.dependencies,
        }
        self.pyproject["dependency-groups"] = self.dependency_groups
        self.pyproject["tool"]["codespell"] = {
            "skip": "build,lib,venv,icon.svg,.tox,.git,.mypy_cache,.ruff_cache,.coverage,htmlcov,uv.lock,grafana_dashboards"
        }
        self.pyproject["tool"]["uv"] = {"package": False}
        if self.conflicts:
            self.pyproject["tool"]["uv"]["conflicts"] = self.conflicts
        for env, env_config in self.tox_toml["env"].items():
            del env_config["deps"]
            env_config["dependency_groups"] = [env]
        self.tox_toml["env_run_base"]["runner"] = "uv-venv-lock-runner"
        self.tox_toml["requires"] = ["tox>=4.21"]
        self.tox_toml["no_package"] = True
        if any("git" in dep for dep in self.dependencies):
            self.charmcraft["parts"]["charm"] = self.yaml.load(
                textwrap.dedent(
                    """
                    source: .
                    plugin: uv
                    build-snaps:
                      - astral-uv
                    build-packages:
                      - git
                    """
                )
            )
        else:
            self.charmcraft["parts"]["charm"] = self.yaml.load(
                textwrap.dedent(
                    """
                    source: .
                    plugin: uv
                    build-snaps:
                      - astral-uv
                    """
                )
            )
        dump_dir = [
            self.project / d for d in ("script", "scripts", "template", "templates")
        ]
        dump_dir = [d for d in dump_dir if d.exists()]
        if dump_dir:
            dump_part_text = textwrap.dedent(
                f"""
                plugin: dump
                source: .
                stage:
                """
            )
            for dump in dump_dir:
                dump_part_text += f"  - {dump.name}\n"
            self.charmcraft["parts"]["dump"] = self.yaml.load(dump_part_text)
        self.licenserc_yaml["header"]["paths-ignore"].append(self.yaml.load("'uv.lock'"))

    def migrate_ruff(self):
        ruff_config = {
            "target-version": "py310",
            "line-length": 99,
            "lint": {
                "select": [
                    "A",
                    "E",
                    "W",
                    "F",
                    "C",
                    "N",
                    "D",
                    "I",
                    "B",
                    "CPY",
                    "RUF",
                    "S",
                    "SIM",
                    "UP",
                    "TC",
                ],
                "ignore": [
                    "B904",
                    "D107",
                    "D203",
                    "D204",
                    "D205",
                    "D213",
                    "D215",
                    "D400",
                    "D404",
                    "D406",
                    "D407",
                    "D408",
                    "D409",
                    "D413",
                    "E501",
                    "TC002",
                    "TC006",
                    "S105",
                    "S603",
                    "UP006",
                    "UP007",
                    "UP035",
                    "UP045",
                ],
                "per-file-ignores": {
                    "tests/*": [
                        "B011",
                        "D100",
                        "D101",
                        "D102",
                        "D103",
                        "D104",
                        "D212",
                        "D415",
                        "D417",
                        "S",
                    ]
                },
                "flake8-copyright": {
                    "author": "Canonical Ltd.",
                    "notice-rgx": "Copyright\\s\\d{4}([-,]\\d{4})*\\s+",
                    "min-file-size": 1,
                },
                "mccabe": {"max-complexity": 10},
                "pydocstyle": {"convention": "google"},
            },
        }

        self.pyproject["tool"]["ruff"] = ruff_config
        self.pyproject["dependency-groups"]["lint"] = sorted(
            [
                "ruff",
                *[
                    dep
                    for dep in self.pyproject["dependency-groups"]["lint"]
                    if "flake" not in dep
                    and "pydocstyle" not in dep
                    and "pylint" not in dep
                    and "black" not in dep
                    and "isort" not in dep
                ],
            ]
        )

        self.pyproject["tool"].pop("isort", None)
        self.pyproject["tool"].pop("flake8", None)
        self.pyproject["tool"].pop("pylint", None)
        self.pyproject["tool"].pop("black", None)

        self.tox_toml["env"]["lint"] = {
            "description": "Check code against coding style standards",
            "commands": [
                ["codespell", "{toxinidir}"],
                [
                    "ruff",
                    "format",
                    "--check",
                    "--diff",
                    {
                        "replace": "ref",
                        "of": [
                            "vars",
                            "all_path",
                        ],
                        "extend": True,
                    },
                ],
                [
                    "ruff",
                    "check",
                    {
                        "replace": "ref",
                        "of": [
                            "vars",
                            "all_path",
                        ],
                        "extend": True,
                    },
                ],
                [
                    "mypy",
                    {
                        "replace": "ref",
                        "of": [
                            "vars",
                            "all_path",
                        ],
                        "extend": True,
                    },
                ],
            ],
            "dependency_groups": ["lint"],
        }

        self.tox_toml["env"]["fmt"] = {
            "description": "Apply coding style standards to code",
            "commands": [
                [
                    "ruff",
                    "check",
                    "--fix",
                    "--fix-only",
                    {
                        "replace": "ref",
                        "of": [
                            "vars",
                            "all_path",
                        ],
                        "extend": True,
                    },
                ],
                [
                    "ruff",
                    "format",
                    {
                        "replace": "ref",
                        "of": [
                            "vars",
                            "all_path",
                        ],
                        "extend": True,
                    },
                ],
            ],
            "dependency_groups": ["fmt"],
        }

        self.tox_toml["env"].pop("src-docs", None)
        self.pyproject["dependency-groups"].pop("src-docs", None)
        self.pyproject["dependency-groups"]["fmt"] = ["ruff"]

    def _add_license(self, file: pathlib.Path):
        if file.read_text().startswith("# Copyright 2025 Canonical Ltd."):
            return
        header = textwrap.dedent(
            """\
            # Copyright 2025 Canonical Ltd.
            # See LICENSE file for licensing details.

            """
        )
        file.write_text(header + file.read_text())

    def _format(self):
        self._add_license(self.pyproject_file)
        self._add_license(self.tox_toml_file)
        self._add_license(self.charmcraft_file)
        tox_toml_fmt.run([str(self.tox_toml_file), "-n"])
        pyproject_fmt.run([str(self.pyproject_file), "-n"])
        subprocess.check_call(
            ["/snap/bin/uv", "tool", "run", "tox", "-e", "fmt"], cwd=self.project
        )

    def _sync(self):
        cmd = ["/snap/bin/uv", "sync"]
        if not self.conflicts:
            cmd.append("--all-groups")
        subprocess.check_call(cmd, cwd=self.project)

    def write(self):
        self.tox_ini_file.unlink()
        self.tox_toml_file.write_text(tomlkit.dumps(self.tox_toml))
        self.pyproject_file.write_text(tomlkit.dumps(self.pyproject))
        self.yaml.dump(self.charmcraft, self.charmcraft_file.open("w"))
        self.yaml.dump(self.licenserc_yaml, self.licenserc_yaml_file.open("w"))
        for workflow_file in (self.project / ".github/workflows").glob("*ml"):
            workflow = self.yaml.load(workflow_file)
            changed = False
            for job in workflow["jobs"].values():
                job_uses = job.get("uses", "")
                if job_uses.startswith(
                    "canonical/operator-workflows/.github/workflows/test.yaml"
                ) or job_uses.startswith(
                    "canonical/operator-workflows/.github/workflows/integration_test.yaml"
                ):
                    job["with"]["with-uv"] = True
                    changed = True
            if changed:
                self.yaml.dump(workflow, workflow_file.open("w"))
        self._sync()
        for requirements in self.project.glob("**/requirements*.txt"):
            if "doc" in str(requirements):
                continue
            requirements.unlink()
        self._format()


project = "../synapse-operator"
Uvify.reset(project)
u = Uvify(project)
u.conflicts = [
    [{"group": "integration-juju3"}, {"group": "integration"}, {"group": "lint"}],
]
u.migrate_uv()
u.migrate_ruff()
u.write()
