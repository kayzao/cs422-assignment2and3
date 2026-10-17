# Linux environment and optional SSH access

## Requirements and environment checks

The offline planner and tests use Python 3.9+ and the standard library. Live
Assignment 2 experiments require Linux with CUBIC, Reno, and BBR available.
A native Linux installation or Linux virtual machine can provide that kernel.
Match the guest architecture to the virtualization host when applicable.

The assignment's Dockerfile must use `FROM ubuntu:24.04`. A container uses its
host's Linux kernel; the image does not supply its own kernel.

Run these checks inside the Linux execution environment:

```bash
cat /etc/os-release
uname -r
uname -m
python3 --version
cat /proc/sys/net/ipv4/tcp_available_congestion_control
cat /proc/sys/net/ipv4/tcp_allowed_congestion_control
cat /proc/sys/net/ipv4/tcp_congestion_control
```

Record the OS, kernel, architecture, Python version, container configuration,
and algorithms with the final results. Verify each requested algorithm can be
selected and read back on a data socket before collecting comparison data.
Validate TCP_INFO field layout, returned length, and units against that kernel.
These socket checks are not implemented by the offline planner.

If BBR is provided as a loadable module, it may need to be loaded after boot:

```bash
sudo modprobe tcp_bbr
```

Module loading does not guarantee the kernel supports BBR. Recheck available
and allowed algorithms; report unsupported configurations explicitly.

## Optional SSH access to a Linux VM

All hostnames and usernames below are placeholders. Replace `linux-user` with
the Linux account name and `vm-host` with the VM's reachable address. Find the
account and address in the VM console with `whoami` and `hostname -I`.

If the VM needs an SSH server, run inside Ubuntu:

```bash
sudo apt update
sudo apt install -y openssh-server
sudo systemctl enable --now ssh
systemctl status ssh --no-pager
```

Then connect from the development machine:

```bash
ssh linux-user@vm-host
```

For a first connection, compare the presented host-key fingerprint with this
command run directly in the VM console:

```bash
sudo ssh-keygen -lf /etc/ssh/ssh_host_ed25519_key.pub
```

Enter credentials only in the SSH prompt. Commands in the resulting session
run inside Linux; `exit` returns to the development machine's shell.
See the [Ubuntu OpenSSH documentation](https://ubuntu.com/server/docs/openssh-server/).

## Copy the repository

To copy local, unpushed work, run the following from the repository's parent
directory on the development machine. The destination directory must not
already exist:

```bash
scp -r ./cs422-assignment2and3 linux-user@vm-host:~/
```

For later updates, use Git push/pull or an explicit sync workflow that preserves
any independent VM changes.

## Run the offline starter on Linux

Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv python3-pip git build-essential
cd ~/cs422-assignment2and3
python3 -m unittest discover -s tests -v
python3 run.py plan --destinations 2 --duration 10 --interval 0.2 --repetitions 3 --algorithms cubic reno bbr
```

The default server list is `configs/listed_iperf3_servers.csv`. Use
`--servers path/to/file.csv` to select another list. Planning makes no network
connections and does not validate live iperf3 behavior or algorithm support.

## Remaining environment and integration work

1. Implement and validate data-socket algorithm selection and TCP_INFO decoding.
2. Install Docker Engine in Linux using the
   [official Ubuntu instructions](https://docs.docker.com/engine/install/ubuntu/),
   then build the required Ubuntu 24.04 image once its Dockerfile is implemented.
3. Implement a complete short Python upload to a standard public iperf3 server,
   including result exchange and termination.
4. Attach sampling of acknowledged bytes, cwnd, RTT, and a documented loss proxy
   to the data socket; feed cumulative counters into `netlab/measurements.py`.
5. Add raw logs, summary statistics, PDF plots, and bounded retries/replacements.
6. Collect repeated CUBIC/Reno/BBR experiments under the same recorded settings.

For Assignment 3, choose one implementation route after a minimal kernel/eBPF
build/load check or stable ns-3 build. Keep machine-specific addresses, account
names, and setup notes in an untracked `docs/environment.local.md` file.
