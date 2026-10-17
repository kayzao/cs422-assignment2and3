"""Read Linux TCP_INFO without guessing the execution kernel's structure size."""

# tools for binary decoding, local header checks, and recording the execution environment
import json
from pathlib import Path
import platform
import socket
import struct
import subprocess
import sys
import tempfile


# byte offsets in the stable linux uapi prefix, checked by tools/tcp_info_layout.c.
# '=' uses native byte order but fixed integer sizes and no python-added padding.
# tcp_info is a local kernel structure; iperf's control messages use network order.
# needed to inspect struct tcp_info in the linux v6.12 uapi header for field
# order and 32/64-bit widths. these offsets decode the counters needed by q1(c)
# and q2(a); the c helper checks them against the installed headers before a run
# source: linux v6.12, include/uapi/linux/tcp.h
# also checked tcp_get_info in net/ipv4/tcp.c: rtt values are microseconds,
# acknowledged bytes and retransmissions are cumulative, and all-ones pacing is a sentinel
FIELDS = {
    "snd_mss_bytes": (16, "I"),
    "unacked_segments": (24, "I"),
    "rtt_us": (68, "I"),
    "rttvar_us": (72, "I"),
    "snd_cwnd_segments": (80, "I"),
    "total_retrans_segments": (100, "I"),
    "pacing_rate_Bps": (104, "Q"),
    "bytes_acked_total": (120, "Q"),
    "notsent_bytes": (144, "I"),
    "delivery_rate_Bps": (160, "Q"),
}
# fields needed by our measurement and baseline logic; missing values stop the run
REQUIRED = {
    "snd_mss_bytes", "unacked_segments", "rtt_us", "rttvar_us",
    "snd_cwnd_segments", "total_retrans_segments", "bytes_acked_total",
}
# saved with results so a later reader knows which decoder layout produced them
LAYOUT_VERSION = "linux-uapi-prefix-v1"


# stops live socket work on systems that do not use the linux decoder
# called by socket helpers and checks; enforces the assignment's linux execution requirement
def require_linux() -> None:
    if sys.platform != "linux":
        raise RuntimeError("live experiments require Linux; use the Ubuntu VM")


# turns one raw tcp_info snapshot into named values using the checked offsets
# called by read_tcp_info for q1(c) acknowledged bytes and q2(a) socket statistics
def decode_tcp_info(raw: bytes) -> dict:
    """Decode only fields present in the returned buffer; never invent zeros."""
    # record the actual buffer length and decode only fields that fit inside it
    decoded = {"tcp_info_length": len(raw)}
    for name, (offset, fmt) in FIELDS.items():
        if offset + struct.calcsize("=" + fmt) <= len(raw):
            value = struct.unpack_from("=" + fmt, raw, offset)[0]
            # linux uses all-ones when a pacing rate is unavailable/unlimited.
            decoded[name] = None if name == "pacing_rate_Bps" and value == 2**64 - 1 else value
        # required fields must exist; optional fields remain unavailable rather than becoming zeros
        elif name in REQUIRED:
            raise RuntimeError(f"TCP_INFO is too short for required field {name}")
        else:
            decoded[name] = None
    return decoded


# asks linux for the current statistics on the supplied socket, then decodes them
# used during checks and on the data socket throughout a transfer for q1(c) and q2(a)
def read_tcp_info(sock: socket.socket) -> dict:
    require_linux()
    return decode_tcp_info(sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_INFO, 1024))


# reads the congestion algorithm actually selected on a socket
# used after selection and connection to record the actual algorithm for q2 and q3(a)
def read_algorithm(sock: socket.socket) -> str:
    require_linux()
    # linux returns the algorithm name as bytes, possibly followed by null padding
    actual = sock.getsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, 64)
    return actual.split(b"\0", 1)[0].decode("ascii")


# sets the data socket's requested congestion algorithm before connecting
# used by the environment check and transfer.py; supports q2 setup and q3(a) comparisons
def select_algorithm(sock: socket.socket, requested: str) -> str:
    """A2 Q3: call before connect(), then record the actual selected algorithm."""
    require_linux()
    # set the name and read it back so an experiment cannot silently use another algorithm
    sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_CONGESTION, requested.encode("ascii"))
    actual = read_algorithm(sock)
    if actual != requested:
        raise RuntimeError(f"requested {requested}, but socket selected {actual}")
    return actual


# checks local headers, readable kernel fields, and algorithm selection before any transfer
# called by the check command and runner.py; supports q2(a) decoding and report reproduction
def check_environment(algorithms: list[str], root: Path) -> dict:
    """Check local headers AND runtime support before contacting public servers."""
    require_linux()
    # use the c helper to compare our python offsets with the locally installed tcp.h
    source = root / "tools" / "tcp_info_layout.c"
    # compile in a temporary directory so no machine-specific binary enters git.
    with tempfile.TemporaryDirectory(prefix="netlab-layout-") as directory:
        binary = Path(directory) / "tcp-info-layout"
        # compile and run the helper with bounded waits, then read its json output
        try:
            subprocess.run(
                ["cc", "-std=c11", "-Wall", "-Wextra", "-Werror", str(source), "-o", str(binary)],
                check=True, capture_output=True, text=True, timeout=30,
            )
            output = subprocess.run(
                [str(binary)], check=True, capture_output=True, text=True, timeout=5,
            )
        # report missing build tools, compile errors, or timeouts before contacting a server
        except FileNotFoundError as error:
            raise RuntimeError("install build-essential and linux-libc-dev for the layout check") from error
        except subprocess.CalledProcessError as error:
            raise RuntimeError("TCP_INFO header check failed: " + error.stderr[-2000:]) from error
        except subprocess.TimeoutExpired as error:
            raise RuntimeError("TCP_INFO header check timed out") from error
        layout = json.loads(output.stdout)

    # the reference header describes one layout; this comparison is our check
    # that the current machine's headers agree. returned buffer length is checked
    # separately, since installed headers and the running kernel can differ
    for name, (offset, fmt) in FIELDS.items():
        expected = {"offset": offset, "size": struct.calcsize("=" + fmt)}
        if layout["fields"].get(name) != expected:
            raise RuntimeError(f"header layout disagrees with decoder for {name}")

    # check runtime support separately from headers, using fresh sockets without connecting
    actual = {}
    lengths = []
    for algorithm in algorithms:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            actual[algorithm] = select_algorithm(sock, algorithm)
            lengths.append(read_tcp_info(sock)["tcp_info_length"])
    # kernel and architecture matter for reproduction; account/hostname do not.
    release = {}
    for line in Path("/etc/os-release").read_text().splitlines():
        if "=" in line:
            key, value = line.split("=", 1)
            if key in ("ID", "VERSION_ID", "PRETTY_NAME"):
                release[key] = value.strip('"')
    # save the current algorithm configuration as well as the socket checks,
    # so the report can reproduce settings such as the allowed algorithm list
    congestion_control = {}
    for name, filename in (("available", "tcp_available_congestion_control"),
                           ("allowed", "tcp_allowed_congestion_control"),
                           ("default", "tcp_congestion_control")):
        try:
            congestion_control[name] = (Path("/proc/sys/net/ipv4") / filename).read_text().strip()
        except OSError:
            congestion_control[name] = None

    # return the verified layout and environment for the experiment manifest
    return {
        "kernel_release": platform.release(), "architecture": platform.machine(),
        "python_version": platform.python_version(), "os_release": release,
        "algorithms_verified": actual, "congestion_control": congestion_control,
        "decoder_version": LAYOUT_VERSION,
        "header_layout": layout, "runtime_tcp_info_lengths": lengths,
        "byte_order": sys.byteorder,
    }
