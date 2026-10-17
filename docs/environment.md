# Linux environment and SSH

## Environment recorded on October 16, 2026

Observed in the user's Ubuntu terminal screenshot:

| Setting | Value |
| --- | --- |
| Guest OS | Ubuntu 26.04.1 LTS |
| Kernel | 7.0.0-38-generic |
| Architecture | aarch64 |
| Ubuntu username | kayzao_ubuntu |
| Guest IPv4 address | 192.168.64.4 |
| Available congestion controls | reno cubic bbr |
| Allowed congestion controls | reno cubic bbr |
| Default congestion control | cubic |

The host is an Apple Silicon Mac running UTM. Ubuntu 26.04 is the guest OS;
Assignment 2's Dockerfile must still use `FROM ubuntu:24.04`. The container will
use the guest's Linux kernel, so record both versions in the final report.

A TCP connection check from the Mac confirmed port 22 was reachable. Successful
SSH authentication has not yet been verified. The address may change after VM
network changes; run `hostname -I` inside Ubuntu to find its current address.

## Connect from the Mac

Keep Ubuntu running. In the Mac's Terminal application:

```bash
ssh kayzao_ubuntu@192.168.64.4
```

On the first connection, SSH asks to trust the VM's host key. You can compare
its fingerprint with this command run in the Ubuntu console:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

After accepting the VM's host key, enter the Ubuntu user's password in your own
terminal. Password characters are not displayed while typing. Do not enter your
Mac password unless you deliberately chose the same password in Ubuntu.

The shell prompt should now belong to `kayzao_ubuntu`. Commands typed in that
session run inside Linux. Type `exit` to return to the Mac shell.

If SSH later stops responding, use the Ubuntu console:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
systemctl status ssh --no-pager
hostname -I
```

Do not change UTM networking or open firewall ports while the direct connection
already works. Ubuntu reference: https://ubuntu.com/server/docs/openssh-server/

## Initial repository copy without pushing to GitHub

The current commits are local until explicitly pushed. Cloning GitHub now may
therefore omit the latest work. For the first copy, run this from the MAC shell
while the destination directory does not yet exist:

```bash
scp -r /Users/kelvinzhao/Code/cs422-assignment2and3 kayzao_ubuntu@192.168.64.4:~/
```

This copies the small current repository, including its Git history. For later
updates, choose a normal push/pull workflow or an explicit file-sync workflow;
do not repeatedly copy entire repositories over independent VM edits.

## Run the offline starter inside Linux

In the Ubuntu SSH session:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git build-essential
cd ~/cs422-assignment2and3
python3 -m unittest discover -s tests -v
python3 run.py plan --servers configs/servers.example.csv --destinations 2 --duration 10 --interval 0.2 --repetitions 3 --algorithms cubic reno bbr
```

The CSV contains placeholder hosts. This command plans runs without contacting
servers; passing it does not validate live iperf3 protocol behavior.

## Remaining environment checks and implementation order

1. Verify each requested algorithm can be selected and read back on a data socket,
   and validate TCP_INFO's required fields and units against the execution kernel.
2. Install Docker Engine inside Ubuntu, then build the required Ubuntu 24.04 image.
   Use Docker's current Ubuntu/ARM64 instructions:
   https://docs.docker.com/engine/install/ubuntu/
3. Implement one complete, short Python iperf3 upload to a standard public server,
   including negotiation, result exchange, and termination.
4. Attach the sampler to the data socket; collect acknowledged bytes, cwnd, RTT,
   and a documented loss proxy; feed cumulative counters into measurements.py.
5. Add raw CSV/JSON logging, summary statistics, and the required PDF plots.
6. Add bounded retries/replacements and repeated CUBIC/Reno/BBR experiments.

BBR was loaded with `sudo modprobe tcp_bbr`. Check availability after reboot;
module loading and kernel configuration are separate from this repository.
Keep both Assignment 3 choices open until a minimal kernel/eBPF build/load check
or stable ns-3 baseline build confirms the preferred route is feasible.
