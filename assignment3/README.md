# Build

Tested on Debian 13 ARM64, Linux `6.12.86+deb13-arm64`.

From the repository root:

```bash
sudo apt update
sudo apt install -y build-essential "linux-headers-$(uname -r)"
make
```
