# Deploy the chrony charm

## What you'll do
This tutorial will walk you through deploying the chrony charm; you will:
1. Deploy and configure the chrony charm
2. Enable NTS for the chrony charm
3. Use the chrony charm as a time server

## Requirements
* LXD installed and bootstrapped.
* A host machine with Juju version 3.4 or above and a Juju controller bootstrapped.

## Create a Juju model
Since the clock is a kernel function, we will need to use LXD virtual machines
instead of containers.
```
ubuntu@laptop:~$ juju add-model test-chrony
ubuntu@laptop:~$ juju set-model-constraints virt-type=virtual-machine
```

## Deploy the chrony charm and confirm the chrony charm are deployed
Deploy the latest chrony charm.
```
ubuntu@laptop:~$ juju deploy chrony --channel latest/edge
```
Run `juju status`. You should see something like this (IPs will be different):
```
Model          Controller  Cloud/Region      Version  SLA          Timestamp
test-chrony    lxd         lxd/default       3.5.2    unsupported  07:20:46Z

App     Version  Status   Scale  Charm   Channel      Rev  Exposed  Message
chrony           blocked      1  chrony  latest/edge   35  no       no time source configured

Unit       Workload  Agent  Machine  Public address  Ports    Message
chrony/0*  blocked   idle   0        10.81.171.230   123/udp  no time source configured

Machine  State    Address        Inst id        Base          AZ  Message
0        started  10.81.171.230  juju-728b65-0  ubuntu@24.04      Running
```

## Configure the time source for chrony charm
We must configure a time source for the Chrony charm so it can serve time to 
other NTP clients.
In this example, we will use an upstream NTP server (ntp.ubuntu.com) 
as the time source and set the iburst option to true for this source.

```
ubuntu@laptop:~$ juju config chrony "sources=ntp://ntp.ubuntu.com?iburst=true"
```

Once the source is configured, the chrony charm should enter the active state 
in the `juju status` table.

## Use the chrony charm as a time source
You can now use the chrony charm as a time source to set up time synchronisation
on any servers. 
Let's try this by creating a LXD virtual machine and installing chrony on the 
virtual machine and using it as an NTP client.

```
ubuntu@laptop:~$ lxc launch ubuntu:24.04 ntp-client --vm
ubuntu@laptop:~$ lxc shell ntp-client
root@ntp-client:~# sudo apt install chrony
```

After the installation is complete, modify `/etc/chrony/chrony.conf` inside the
virtual machine by commenting out all the default NTP sources 
(lines that start with `pool` or `server`). 
Then, add the following lines to the configuration file to use the chrony 
charm as the time source. 
Make sure to change the chrony charm address in the example (10.81.171.230) 
to the actual address used in your deployment. 
You can find the correct address using the `juju status` command.

```
server 10.81.171.230 iburst
```

After modifying the chrony configuration file, run `sudo systemctl restart chrony`
in the virtual machine to apply changes.

You can exit the virtual machine shell and get back to the host machine
using the exit command.

```
root@ntp-client:~# exit
```

<!-- vale Canonical.007-Headings-sentence-case = NO -->
## Enable NTS
The NTS protocol is a security enhancement over the NTP protocol. 
It adds authentication to the NTP protocol to prevent time results from being 
tampered with by a malicious actor. 
To enable the NTS protocol in the chrony charm, provide a TLS certificate to 
the chrony charm.

You can either use the `ntp-certificates` configuration of the chrony charm 
or a `tls-certificate` provider charm, and providing the certificate via 
Juju integration.
In this example, we will use the `self-signed-certificates` charm to provide 
the TLS certificate. 

Configure the chrony charm's `server-name` configuration with a test value 
(ntp.example.com), as it is required for the `tls-certificate` integration, 
then deploy the `self-signed-certificates` charm and relate it to the chrony 
charm.

```
ubuntu@laptop:~$ juju config chrony server-name=ntp.example.com
ubuntu@laptop:~$ juju deploy self-signed-certificates
ubuntu@laptop:~$ juju integrate chrony self-signed-certificates
```

Next, we will retrieve the root certificate from the `self-signed-certificates`
charm and use it to configure the chrony client to use NTS when communicating 
with the chrony charm.


```
ubuntu@laptop:~$ juju run self-signed-certificates/0 get-ca-certificate | \
  awk '{gsub(/^ */, "")} /-----BEGIN CERTIFICATE-----/{print; flag=1; next} /-----END CERTIFICATE-----/{print; flag=0} flag {print}' | \
  lxc exec ntp-client tee /etc/chrony/nts.crt && lxc exec ntp-client chown _chrony:_chrony /etc/chrony/nts.crt
```

You will need to add an entry to `/etc/hosts` inside the virtual machine with 
the `server-name` value we just set and the IP address of the chrony charm.

```
10.81.171.230 ntp.example.com
```

After that, enable NTS in the chrony client configuration and restart the 
chrony client inside the virtual machine.

```
server ntp.example.com nts iburst certset 1
ntstrustedcerts 1 /etc/chrony/nts.crt
```

Wait a few seconds, and you should see that the chrony client is synchronised 
with the chrony charm.

```
ubuntu@laptop:~$ lxc exec ntp-client chronyc tracking
Reference ID    : 0A51AB43 (ntp.example.com)
Stratum         : 4
Ref time (UTC)  : Fri Sep 13 15:47:07 2024
System time     : 0.000000026 seconds slow of NTP time
Last offset     : +0.000024886 seconds
RMS offset      : 0.000024886 seconds
Frequency       : 31.247 ppm slow
Residual freq   : +3.838 ppm
Skew            : 67.618 ppm
Root delay      : 0.231240883 seconds
Root dispersion : 0.015818920 seconds
Update interval : 2.0 seconds
Leap status     : Normal
```

## Clean up the environment
You can now clean up the environment by removing the Juju model and the NTP
client virtual machine.

```
ubuntu@laptop:~$ juju destroy-model test-chrony
ubuntu@laptop:~$ lxc delete ntp-client --force
```
