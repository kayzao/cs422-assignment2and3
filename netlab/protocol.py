"""the small subset of iperf3's control protocol needed for one tcp upload.

wire details are pinned to the official iperf3 3.17.1 source in protocol-notes.md.
this module never invokes the iperf3 client executable.

handles how client communicates with given server, used in transfer.py for an experiment
"""

# tools for addresses, json, sockets, binary messages, timeouts, and session ids
import ipaddress
import json
import math
import socket
import struct
import subprocess
import sys
import time
import uuid


# numbers used by iperf3 to say which stage the test is in in iperf_api.h
# checked the state definitions in iperf3 3.17.1's iperf_api.h to get these numbers
# they are fixed protocol values that our client must agree on with the server
TEST_START, TEST_RUNNING, TEST_END = 1, 2, 4
PARAM_EXCHANGE, CREATE_STREAMS = 9, 10
SERVER_TERMINATE, CLIENT_TERMINATE = 11, 12
EXCHANGE_RESULTS, DISPLAY_RESULTS, IPERF_DONE = 13, 14, 16
ACCESS_DENIED, SERVER_ERROR = -1, -2

# cap json messages at one megabyte so a bad length cannot trigger a huge read
# this size cap is our own limit for handling bad messages
MAX_JSON_BYTES = 1024 * 1024

# maps state numbers back to names so the logs and errors are easier to read
STATES = {value: name for name, value in list(globals().items())
          if name.isupper() and isinstance(value, int) and name != "MAX_JSON_BYTES"}


# marks rejected, incomplete, or unexpected iperf3 messages
# raised by these helpers and handled in transfer.py as failed attempts
# supports assignment 2 q1(a)'s rejection and premature-termination handling
class ProtocolError(RuntimeError):
    pass


# finds how much time is left before an operation's deadline
# used before reads, writes, and connections, and during cookie/drain waits
# supports timeout handling so a stalled server cannot hang a test
# monotonic time is unaffected by changes to the system clock
def remaining(deadline: float) -> float:
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TimeoutError("operation deadline expired")
    return seconds


# keeps reading until the full message arrives, since one recv may return only part
# used by recv_json and read_state for message lengths, bodies, states, and error codes
# supports iperf3 compatibility and early-disconnection handling
# each read uses the time left on the same deadline
def recv_exact(sock: socket.socket, size: int, deadline: float) -> bytes:
    """tcp may split a header or combine several messages in one packet."""
    pieces = bytearray()
    while len(pieces) < size:
        sock.settimeout(remaining(deadline))
        part = sock.recv(size - len(pieces))

        # an empty read means the server disconnected before the message finished
        if not part:
            raise ProtocolError("peer closed the connection before completing a message")
        pieces.extend(part)
    return bytes(pieces)


# sends all the supplied bytes, including any that a single send could leave over
# used for session cookies, json frames, and state messages during setup and shutdown
# supports complete iperf3 conversation and timeout handling
def send_bytes(sock: socket.socket, data: bytes, deadline: float) -> None:
    sock.settimeout(remaining(deadline))
    sock.sendall(data)


# converts a dictionary into the json format expected by the iperf3 server
# called by transfer.py to send the experiment parameters and final client results
# supports json exchange and proper termination
# needed to read the json framing helpers in iperf_api.c: the server expects a
# four-byte unsigned length in network byte order, followed by exactly that many bytes
def send_json(sock: socket.socket, value: dict, deadline: float) -> None:
    # encode compact json and reject nonstandard numbers or oversized messages
    body = json.dumps(value, separators=(",", ":"), allow_nan=False).encode("utf-8")
    if len(body) > MAX_JSON_BYTES:
        raise ProtocolError("outgoing JSON exceeds the size limit")

    # put the length in four bytes before the json, using network byte order
    # this tells the server exactly how many bytes to read for the message
    send_bytes(sock, struct.pack("!I", len(body)) + body, deadline)


# reads the server's length-prefixed json and returns it as a dictionary
# called by transfer.py to receive the server's results after sending has finished
# supports assignment 2 q1(a)(v): complete the result exchange before ending the test
# checked the matching reader in iperf_api.c to confirm the length excludes the
# header itself and that incoming results use the same framing as outgoing parameters
def recv_json(sock: socket.socket, deadline: float) -> dict:
    # read and validate the length before accepting the message body
    size = struct.unpack("!I", recv_exact(sock, 4, deadline))[0]
    if size == 0 or size > MAX_JSON_BYTES:
        raise ProtocolError(f"invalid JSON frame length: {size}")

    # called by the json decoder if the server supplies nan or infinity
    # rejects nonstandard numbers as part of q1(a)'s iperf3 message validation
    def reject_nonfinite(value):
        raise ValueError(f"nonstandard JSON number: {value}")

    # even a standard-looking number such as 1e999 can overflow python's float
    # reject it here so a bad server result becomes a logged, replaceable failure
    def finite_float(value):
        number = float(value)
        if not math.isfinite(number):
            raise ValueError("json number is outside the finite float range")
        return number

    # decode the full body, keeping the same deadline for the header and body
    try:
        value = json.loads(recv_exact(sock, size, deadline).decode("utf-8"),
                           parse_constant=reject_nonfinite, parse_float=finite_float)
    except (UnicodeError, ValueError) as error:
        raise ProtocolError("peer supplied invalid JSON") from error

    # iperf3 expects an object here, rather than a list, number, or other json value
    if not isinstance(value, dict):
        raise ProtocolError("expected a JSON object")
    return value


# reads the server's next state and records it in the protocol log
# used by expect_state during setup/shutdown and directly by transfer.py while active
# supports handling of busy servers, rejection, and early termination
# traced iperf_handle_message_client to confirm signed one-byte states and the
# two network-order 32-bit error codes sent after a server-error state
def read_state(sock: socket.socket, deadline: float, event) -> int:
    # use a signed byte because rejection and server error are negative numbers
    state = struct.unpack("!b", recv_exact(sock, 1, deadline))[0]
    event({"event": "state_received", "state": STATES.get(state, str(state))})

    # stop the test if the server rejects it, reports an error, or ends it early
    if state == ACCESS_DENIED:
        raise ProtocolError("server denied access (busy, overloaded, or restricted)")
    if state == SERVER_ERROR:
        # a server error is followed by an iperf error code and a system error code
        code, system_error = struct.unpack("!ii", recv_exact(sock, 8, deadline))
        raise ProtocolError(f"server error: iperf_code={code}, errno={system_error}")
    if state == SERVER_TERMINATE:
        raise ProtocolError("server terminated the test prematurely")
    return state


# checks that the conversation is moving to the stage transfer.py expects
# called before parameter exchange, stream creation, payload start, and result exchange
# supports required iperf3 sequence instead of sending data too early
def expect_state(sock: socket.socket, expected: int, deadline: float, event) -> None:
    actual = read_state(sock, deadline, event)
    if actual != expected:
        raise ProtocolError(f"expected {STATES[expected]}, received {STATES.get(actual, actual)}")


# sends a state number to the server and records it in the same protocol log
# called by transfer.py to announce the end of sending and final test completion
# supports assignment 2 q1(a)(v)'s requirement to terminate using iperf3 semantics
def send_state(sock: socket.socket, state: int, deadline: float, event) -> None:
    send_bytes(sock, struct.pack("!b", state), deadline)
    event({"event": "state_sent", "state": STATES[state]})


# creates the session cookie that links the control and data connections
# called once per test, then the same cookie is sent on both connections
# iperf3 expects 36 ascii characters followed by a null byte, making 37 bytes
# checked the cookie length in iperf.h and its comparison in iperf_tcp_accept
# this is why both connections send the same 37 bytes before any test payload
def new_cookie() -> bytes:
    return str(uuid.uuid4()).encode("ascii") + b"\0"


# opens the control connection used to negotiate and manage the experiment
# called by transfer.py at the beginning of each server test, before parameter exchange
def connect_control(host: str, port: int, timeout_s: float) -> socket.socket:
    # share one deadline across address lookup and connection attempts
    deadline = time.monotonic() + timeout_s
    try:
        # a numeric ip can be used directly, without looking up a hostname
        address = ipaddress.ip_address(host)
    except ValueError:
        # the separate lookup process is our timeout design for public-server failures
        # hostname lookup has no built-in timeout, so run it in a separate process
        # that can be stopped if it takes too long
        script = ("import json,socket,sys; print(json.dumps(socket.getaddrinfo("
                  "sys.argv[1],int(sys.argv[2]),type=socket.SOCK_STREAM)))")

        # ask the lookup process for possible addresses, using only the time left
        try:
            result = subprocess.run([sys.executable, "-c", script, host, str(port)],
                                    capture_output=True, text=True, check=True,
                                    timeout=remaining(deadline))
        except subprocess.TimeoutExpired as error:
            raise TimeoutError("DNS resolution timed out") from error
        except subprocess.CalledProcessError as error:
            raise ProtocolError(f"could not resolve destination {host}") from error
        addresses = json.loads(result.stdout)
    else:
        # choose the socket family for ipv4 or ipv6 and use the numeric address
        family = socket.AF_INET6 if address.version == 6 else socket.AF_INET
        addresses = [(family, socket.SOCK_STREAM, 0, "", (host, port))]

    # try the available addresses until one connects or the shared deadline ends
    last_error = None
    for family, kind, protocol, _, address in addresses:
        sock = socket.socket(family, kind, protocol)
        try:
            sock.settimeout(remaining(deadline))
            sock.connect(tuple(address))

            # send small control messages promptly rather than waiting to group them
            # checked iperf_connect, which also disables nagle on the control socket
            sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
            return sock
        except OSError as error:
            # keep the latest reason and close this socket before trying another
            last_error = error
            sock.close()

    # report the last connection failure if none of the addresses worked
    raise ProtocolError(f"could not connect to {host}:{port}: {last_error}")
