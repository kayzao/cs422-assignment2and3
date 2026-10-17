# Python iperf3 protocol implementation

`netlab/protocol.py` implements message framing and bounded socket operations.
`netlab/transfer.py` implements one forward TCP upload with one data stream.
The program uses Python sockets and never invokes an iperf3 client executable.

## Reference version

Wire details were checked against the official **iperf3 3.17.1** source:

- [Protocol states](https://github.com/esnet/iperf/blob/3.17.1/src/iperf_api.h)
- [Client state handling](https://github.com/esnet/iperf/blob/3.17.1/src/iperf_client_api.c)
- [Parameter and result exchange](https://github.com/esnet/iperf/blob/3.17.1/src/iperf_api.c)
- [Server state handling](https://github.com/esnet/iperf/blob/3.17.1/src/iperf_server_api.c)
- [TCP stream connection and cookie](https://github.com/esnet/iperf/blob/3.17.1/src/iperf_tcp.c)

These references describe the format; the Python implementation is independent.
Public server versions and policies can differ. A successful live test must
complete result exchange and termination, not just send some bytes.

## Sequence

1. Open the control connection and send a 37-byte ASCII session cookie,
   consisting of a 36-character UUID followed by NUL.
2. Receive `PARAM_EXCHANGE` (9). Send a UTF-8 JSON parameter object prefixed by
   its four-byte unsigned length in network byte order. Request one forward TCP
   stream, no omitted warmup, and a configurable transfer duration.
3. Receive `CREATE_STREAMS` (10). Create the data socket, set the congestion
   algorithm before `connect()`, connect to the control connection's resolved
   peer, verify the selected algorithm, and send the same cookie.
4. Receive `TEST_START` (1) and `TEST_RUNNING` (2). Wait for the data cookie's
   bytes to be acknowledged, then take the payload baseline.
5. Use a nonblocking send loop while servicing control readiness and sampling
   the data socket. The actual interval duration comes from a monotonic clock.
6. At the configured duration, stop sending. Sample while pending payload is
   acknowledged, up to the configured drain timeout. These samples have a
   separate phase and are excluded from active-transfer summaries.
7. Send `TEST_END` (4), receive `EXCHANGE_RESULTS` (13), send client results,
   and read server results. Result objects use the same length-prefixed framing.
8. Receive `DISPLAY_RESULTS` (14), close the data socket, send `IPERF_DONE`
   (16), and wait for the server to close its control connection.

The result object includes CPU utilization fields, retransmission support,
actual congestion algorithm, and the required per-stream fields. Its `bytes`
field describes payload accepted by `send()`, as expected by iperf3. Assignment
goodput is calculated separately from acknowledged-byte differences.

## Failure handling

- Read a state as a signed byte so access denial (-1) and server errors (-2)
  are recognized correctly. Decode the two network-order error integers.
- Read exact message lengths; TCP fragmentation and coalescing do not preserve
  application message boundaries. Reject oversized, truncated, or invalid JSON,
  including numbers that overflow to nonfinite Python floats.
- Apply absolute deadlines to each message operation and bounded connection,
  DNS resolution, payload-stall, and drain waits.
- Keep sampling when the send buffer is full. Independently check ACK progress
  at the stall deadline when the sampling interval is longer than that timeout.
  Treat an early data-socket close or unexpected control state as a failed run.
- Save the failure stage, reason, protocol events, and any samples already read.
  The destination runner tries a different candidate within `--max-attempts`.
- Accept a destination only when all its configured algorithm/repetition runs
  complete. A replacement gets a new full matched set; partial sets remain in
  raw logs but are excluded from aggregate plots and statistics.

Reverse mode, UDP, multiple parallel streams, and authenticated servers are
outside the assignment client's implemented subset. Restricted public servers
are logged as failures and replaced.

## Verification scope

The automated suite checks fragmented frames, truncated/oversized JSON,
signed server errors, timeout behavior, and destination replacement. An optional
test runs an unmodified local iperf3 server in server mode only:

```bash
IPERF3_SERVER_BINARY=/path/to/iperf3 python3 -m unittest discover -s tests -p test_interop.py -v
```

That optional test uses explicitly synthetic statistics to isolate protocol
behavior, including when run on macOS. It does not supply assignment results or
validate Linux TCP_INFO. Collect assignment measurements with `run.py run` on
Linux and preserve the resulting environment manifest.
