import copy
import fnmatch
import pathlib
import shlex
import typing
import configparser
import tomlkit
import tox_toml_fmt
import yaml
from pip._internal.req import parse_requirements
from pip._internal.network.session import PipSession


class Mapping:
    def __init__(self):
        self._container = {}

    def __getitem__(self, key):
        return self._container[key]

    def __setitem__(self, key, value):
        return self._container.__setitem__(key, value)

    def as_dict(self):
        return self._container


ValueType = bool | int | str | list[bool | int | str | list[str]] | Mapping
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
    mapping = Mapping()
    for line in lines:
        key, value = line.split("=", maxsplit=1)
        mapping[key.strip()] = value.strip()
    return path, mapping


def newline_separated_list_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    value = value.replace("\\\n", " ")
    return path, [v.strip() for v in value.splitlines() if v.strip()]


def command_lines_value(path: str, value: ValueType) -> tuple[str, ValueType]:
    path, value = newline_separated_list_value(path, value)
    commands = [shlex.split(line) for line in value if not line.startswith("#")]
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
    "/testenv/setenv": compose(change_parent(lambda p: "env_run_base"), equal_mapping_value),
    "/testenv/passenv": compose(
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
        cursor[keys[-1]] = value.as_dict() if isinstance(value, Mapping) else value
    return result

def load_ini_file(file):
    tox_ini = configparser.ConfigParser()
    tox_ini.read(file)
    tox_config = {}
    for section in tox_ini.sections():
        tox_config[section] = {}
        for option in tox_ini.options(section):
            tox_config[section][option] = tox_ini.get(section, option)
    return tox_config


def convert_to_toml(source, destination):
    tox_config = load_ini_file(source)
    flatten_tox_config = flatten(tox_config)
    vars = tox_config["vars"]
    if "all_path" in vars:
        new_all_path = " ".join(
            [f"{{[vars]{var}}}" for var in vars if var.endswith("_path") and var != "all_path"]
        )
        del flatten_tox_config["/vars/all_path"]
        for key in flatten_tox_config:
            flatten_tox_config[key] = flatten_tox_config[key].replace(
                "{[vars]all_path}", new_all_path
            )
    transformed_tox_config = {}
    for key, value in flatten_tox_config.items():
        transformed = False
        for pattern, transform in TRANSFORMERS.items():
            if not fnmatch.fnmatch(key, pattern):
                continue
            new_key, new_value = transform(key, value)
            transformed_tox_config[new_key] = new_value
            transformed = True
            break
        if not transformed:
            raise ValueError(f"unknown key: {key}")
    tomlkit.dump(unflatten(transformed_tox_config), open(destination, "w"))
    tox_toml_fmt.run([destination, "-n"])


def migrate_tox_toml(project: pathlib.Path):
    project = pathlib.Path(project)
    ini_file = project / "tox.ini"
    toml_file = project / "tox.toml"
    convert_to_toml(ini_file, toml_file)
    ini_file.unlink()


def load_requirements_txt(path: pathlib.Path) -> list[str]:
    path = pathlib.Path(path)
    requirements = []
    for requirement in parse_requirements(str(path.resolve()), session=PipSession()):
        requirements.append(requirement.requirement)
    return requirements


def extract_dependency_groups(tox_path: pathlib.Path) -> list[str]:



def migrate_uv(project: pathlib.Path):
    project = pathlib.Path(project)
    pyproject_file = project / "pyproject.toml"
    pyproject = tomlkit.loads(pyproject_file.read_text())
    charmcraft_file = project / "charmcraft.yaml"
    charmcraft = yaml.safe_load(charmcraft_file.read_text())
    metadata_file = project / "metadata.yaml"
    if metadata_file.exists():
        metadata = yaml.safe_load((project / "metadata.yaml").read_text())
        name = metadata["name"]
        summary = metadata["summary"]
    else:
        name = charmcraft["name"]
        summary = charmcraft["summary"]
    """
    [project]
    name = "pollen-operator"
    version = "1.0.0"
    description = "A Juju charm deploying and managing Pollen on a machine."
    readme = "README.md"
    requires-python = ">=3.10"
    dependencies = [
        "ops~=3.0",
        "pydantic~=2.11",
        "cosl~=1.0",
    ]
    """
    python_version = "3.12"
    for ubuntu_version, python_version in [("20.04", "3.8"), ("22.04", "3.10")]:
        if ubuntu_version in charmcraft_file.read_text():
            break
    pyproject["project"] = {
        "name": name + "-operator",
        "version": "0.0.0",
        "description": summary,
        "readme": "README.md",
        "requires-python": f">={python_version}",
        "dependencies": load_requirements_txt(project / "requirements.txt"),
    }
    pyproject["tool"]["black"]["target-version"] = ["py" + python_version.replace(".", "")]
    pyproject["tool"]["uv"] = {"package": "false"}

    print(tomlkit.dumps(pyproject))


migrate_uv(".")
