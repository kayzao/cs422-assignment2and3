"""Execute one iperf3 upload while sampling the same Linux data socket."""

# tools for timestamps, socket readiness, transfer timing, and payload bytes
from datetime import datetime, timezone
import math
import os
import select
import socket
import time

# reuse the protocol conversation and measurement helpers while keeping one transfer here
from . import protocol as wire
from .measurements import CounterSnapshot, measure_interval
from .tcp_info import read_algorithm, read_tcp_info, select_algorithm


# fixed csv columns for q2(a), including ids, actual algorithm, explicit units, and phase
SAMPLE_FIELDS = [
    "schema_version", "experiment_id", "run_id", "destination_host", "destination_port",
    "algorithm_requested", "algorithm_actual", "repetition", "timestamp_utc",
    "elapsed_s", "sample_interval_actual_s", "phase", "snd_cwnd_segments",
    "snd_mss_bytes", "rtt_us", "rttvar_us", "bytes_acked_total", "bytes_acked_delta",
    "goodput_bps", "total_retrans_segments", "retrans_segments_delta",
    "pacing_rate_Bps", "delivery_rate_Bps", "unacked_segments", "notsent_bytes",
    "tcp_info_length",
]


# creates a readable utc timestamp when a sample, event, or result is recorded
# used by this file and runner.py for q2(a) timestamps and experiment logs
def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


# carries the partial run metadata back to runner.py when any stage fails
class TransferError(RuntimeError):
    """Carry partial metadata out to the runner so failed attempts stay visible."""

    # keeps the failure stage and partial results when a transfer fails
    # called by the error handler so runner.py can log q1(a) failures and choose q1(b) replacements
    def __init__(self, stage: str, cause: Exception, result: dict):
        super().__init__(f"{stage}: {cause}")
        self.stage = stage
        self.result = result


# traced the client and server state handlers to work out the full q1(a) sequence,
# especially when data may start and which side sends results first
# source: iperf3 3.17.1, iperf_client_api.c
# source: iperf3 3.17.1, iperf_server_api.c
# runs one iperf3 upload and samples its data socket until the test is properly finished
# called once per scheduled run by runner.py; implements q1(a), q1(c), and q2(a)
def run_transfer(run: dict, duration_s: float, interval_s: float, timeout_s: float,
                 drain_timeout_s: float, stall_timeout_s: float, sample, event,
                 reader=read_tcp_info, algorithm_selector=select_algorithm,
                 algorithm_reader=read_algorithm) -> dict:
    """One forward stream, bounded protocol operations, and no iperf executable.

    sample/event callbacks write raw data as it arrives, preserving partial runs.
    Injected readers exist for protocol tests; the CLI always uses Linux TCP_INFO.
    """
    # track both sockets for cleanup and keep the current stage for meaningful failure logs
    control = data = None
    stage = "control_connect"
    result = {"started_utc": utc_now(), "protocol_complete": False}
    # each blocking control operation has a deadline. this outer deadline also
    # bounds the whole attempt if the peer repeatedly changes protocol stages.
    overall_deadline = time.monotonic() + duration_s + drain_timeout_s + 8 * timeout_s

    # gives the next control operation its deadline without exceeding the attempt's time budget
    # used during setup and shutdown for q1(a) timeout handling
    def deadline():
        return min(overall_deadline, time.monotonic() + timeout_s)

    # adds a timestamp before handing a protocol event to runner.py for saving
    # used for state changes and failures so q1(a) attempts can be inspected later
    def record_event(value):
        event({"timestamp_utc": utc_now(), **value})

    # start q1(a) by opening the control connection and sending the session cookie
    try:
        control = wire.connect_control(run["destination_host"], run["destination_port"], timeout_s)
        result["resolved_peer_ip"] = control.getpeername()[0]
        cookie = wire.new_cookie()
        wire.send_bytes(control, cookie, deadline())
        # wait for parameter exchange before sending the json settings
        stage = "parameter_exchange"
        wire.expect_state(control, wire.PARAM_EXCHANGE, deadline(), record_event)
        # a2 q1(a): speak iperf3's json negotiation, not an arbitrary tcp upload.
        # the server stores integer seconds; our monotonic timer controls the
        # exact requested duration even for a fractional development test.
        # checked send_parameters and get_parameters for the json field names
        # and integer duration. our single-stream settings use that server-readable format
        # source: iperf3 3.17.1, iperf_api.c
        parameters = {"tcp": True, "omit": 0, "time": math.ceil(duration_s),
                      "num": 0, "blockcount": 0, "parallel": 1, "len": 131072,
                      "client_version": "3.17.1-compatible-netlab"}
        wire.send_json(control, parameters, deadline())
        record_event({"event": "parameters_sent", "parameters": parameters})
        wire.expect_state(control, wire.CREATE_STREAMS, deadline(), record_event)

        # open a separate payload connection and select its congestion algorithm before connect
        stage = "data_connect"
        data = socket.socket(control.family, socket.SOCK_STREAM)
        # select before connect(), as required for the later a2 q3 comparison.
        actual = algorithm_selector(data, run["algorithm_requested"])
        result["algorithm_actual"] = actual
        data.settimeout(timeout_s)
        # reuse the resolved control peer: two dns answers must not split a test
        # between different machines behind one public hostname.
        data.connect(control.getpeername())
        # confirm the algorithm again on the connected data socket for q2's actual-algorithm record
        actual = algorithm_reader(data)
        if actual != run["algorithm_requested"]:
            raise RuntimeError(f"connected data socket uses {actual}, not the requested algorithm")
        result["algorithm_actual"] = actual
        # record the counter before the data cookie, then wait for the server's start states
        before_cookie = reader(data)["bytes_acked_total"]
        wire.send_bytes(data, cookie, deadline())
        stage = "test_start"
        wire.expect_state(control, wire.TEST_START, deadline(), record_event)
        wire.expect_state(control, wire.TEST_RUNNING, deadline(), record_event)

        # iperf_tcp_connect sends the cookie on the data socket before the payload
        # our q1(c) measurement choice is to wait for those bytes to be acknowledged
        # before taking the baseline, so the cookie does not inflate payload goodput
        # source: iperf3 3.17.1, iperf_tcp.c
        stage = "payload_baseline"
        cookie_deadline = deadline()
        while True:
            baseline_info = reader(data)
            if baseline_info["bytes_acked_total"] >= before_cookie + len(cookie):
                break
            wire.remaining(cookie_deadline)
            readable, _, _ = select.select([control], [], [], 0.005)
            if readable:
                state = wire.read_state(control, cookie_deadline, record_event)
                raise wire.ProtocolError(f"unexpected state {state} before payload")

        # start payload timing and keep the initial counters for q1(c) interval differences
        start = time.monotonic()
        process_start = os.times()
        previous = CounterSnapshot(0.0, baseline_info["bytes_acked_total"],
                                   baseline_info["total_retrans_segments"])
        result["payload_baseline_bytes_acked"] = previous.bytes_acked_total
        result["payload_baseline_retrans_segments"] = previous.total_retrans_segments
        # a baseline has no interval rate. blank goodput avoids adding a fake
        # zero sample to the plots and summary table.
        sample({**run, **baseline_info, "schema_version": 1,
                "algorithm_actual": actual, "timestamp_utc": utc_now(),
                "elapsed_s": 0.0, "sample_interval_actual_s": 0.0,
                "phase": "baseline", "bytes_acked_delta": 0,
                "goodput_bps": None, "retrans_segments_delta": 0})
        last_ack_progress = start
        last_seen_acked_total = baseline_info["bytes_acked_total"]

        # reads data-socket counters, calculates interval goodput, and sends the row to the logger
        # called during transfer and drain; supplies the q1(c) and q2(a) measurements
        def take_sample(phase):
            nonlocal previous, last_ack_progress, last_seen_acked_total
            info = reader(data)
            now = time.monotonic()
            current = CounterSnapshot(now - start, info["bytes_acked_total"],
                                      info["total_retrans_segments"])
            # use acknowledged-byte changes and actual elapsed time, as required by q1(c)
            measured = measure_interval(previous, current)
            if current.bytes_acked_total < last_seen_acked_total:
                raise ValueError("acknowledged-byte counter decreased between reads")
            if current.bytes_acked_total > last_seen_acked_total:
                last_ack_progress = now
            last_seen_acked_total = current.bytes_acked_total
            # attach ids, timestamps, tcp values, and calculated interval values to the same row
            sample({**run, **info, "schema_version": 1, "algorithm_actual": actual,
                    "timestamp_utc": utc_now(), "elapsed_s": measured.elapsed_s,
                    "sample_interval_actual_s": measured.sample_interval_actual_s,
                    "bytes_acked_delta": measured.bytes_acked_delta,
                    "goodput_bps": measured.goodput_bps,
                    "retrans_segments_delta": measured.retrans_segments_delta,
                    "phase": phase})
            # use this snapshot as the next baseline so intervals do not count the same bytes twice
            previous = current
            return info

        # send until the configured end time; nonblocking writes leave time for sampling and control
        stage = "payload_transfer"
        data.setblocking(False)
        payload = os.urandom(131072)  # reuse a buffer; avoid allocation in every send.
        sent = 0
        next_sample = start + interval_s
        end = start + duration_s
        while time.monotonic() < end:
            now = time.monotonic()
            # sample when due and move to the next scheduled time if the loop was delayed
            if now >= next_sample:
                take_sample("transfer")
                # missed deadlines do not create fabricated zero-length samples.
                next_sample = start + (math.floor((time.monotonic() - start) / interval_s) + 1) * interval_s
            # check fresh counters before declaring a stall: the configured sample
            # interval can be longer than the stall timeout. these extra checks do
            # not change the baseline or create extra measurement rows
            if now - last_ack_progress >= stall_timeout_s:
                observed = reader(data)["bytes_acked_total"]
                if observed < last_seen_acked_total:
                    raise ValueError("acknowledged-byte counter decreased between reads")
                if observed == last_seen_acked_total:
                    raise TimeoutError("no acknowledged-payload progress within stall timeout")
                last_seen_acked_total = observed
                last_ack_progress = time.monotonic()
            # wake for the stall deadline even if the send buffer is blocked and
            # the next scheduled measurement is much later
            wait = max(0.0, min(next_sample, end, overall_deadline,
                                last_ack_progress + stall_timeout_s) - time.monotonic())
            # an unexpected state or early data close makes this a failed q1(a) transfer
            readable, writable, _ = select.select([control, data], [data], [], wait)
            if control in readable:
                state = wire.read_state(control, deadline(), record_event)
                raise wire.ProtocolError(f"unexpected state {state} during transfer")
            if data in readable:
                message = data.recv(1)
                raise wire.ProtocolError("data socket closed prematurely" if not message
                                         else "unexpected data from upload receiver")
            # send when the socket has space; count the bytes actually accepted if a write is partial
            if data in writable and time.monotonic() < end:
                try:
                    count = data.send(payload)
                except BlockingIOError:
                    continue
                if count <= 0:
                    raise wire.ProtocolError("data socket stopped accepting bytes")
                sent += count

        # keep the final active interval, even when it is shorter than the requested sampling interval
        info = take_sample("transfer")
        result["active_transfer_s"] = previous.elapsed_s
        result["payload_bytes_sent"] = sent
        record_event({"event": "payload_stopped", "bytes_sent": sent})

        # stop sending, but leave the data socket open while queued payload is
        # acknowledged. separate drain samples from the active-transfer analysis.
        stage = "payload_drain"
        drain_deadline = min(overall_deadline, time.monotonic() + drain_timeout_s)
        while info["bytes_acked_total"] - baseline_info["bytes_acked_total"] < sent:
            wait = min(interval_s, wire.remaining(drain_deadline))
            readable, _, _ = select.select([control, data], [], [], wait)
            if control in readable:
                state = wire.read_state(control, deadline(), record_event)
                raise wire.ProtocolError(f"unexpected state {state} during drain")
            if data in readable:
                raise wire.ProtocolError("data socket closed before drain completed")
            info = take_sample("drain")
        result["payload_bytes_acked"] = info["bytes_acked_total"] - baseline_info["bytes_acked_total"]
        result["drain_duration_s"] = previous.elapsed_s - result["active_transfer_s"]

        # follow the result-exchange order checked in iperf_server_api.c and iperf_api.c
        stage = "result_exchange"
        wire.send_state(control, wire.TEST_END, deadline(), record_event)
        wire.expect_state(control, wire.EXCHANGE_RESULTS, deadline(), record_event)
        # prepare cpu and retransmission totals for the standard iperf3 result object
        process_end = os.times()
        elapsed = max(previous.elapsed_s, 1e-9)
        user_cpu = 100 * (process_end.user - process_start.user) / elapsed
        system_cpu = 100 * (process_end.system - process_start.system) / elapsed
        retrans = previous.total_retrans_segments - baseline_info["total_retrans_segments"]
        # these are iperf3's required result fields. protocol byte counts describe
        # send() progress; our assignment goodput still comes only from ack deltas.
        # inspected send_results and get_results to find the cpu and per-stream
        # fields a standard server reads, including shared fields unused by tcp
        # also checked iperf_exchange_results: the client sends its results first
        # source: iperf3 3.17.1, iperf_api.c
        client_results = {
            "cpu_util_total": user_cpu + system_cpu, "cpu_util_user": user_cpu,
            "cpu_util_system": system_cpu, "sender_has_retransmits": 1,
            "congestion_used": actual,
            "streams": [{"id": 1, "bytes": sent, "retransmits": retrans,
                         "jitter": 0, "errors": 0, "packets": 0,
                         "omitted_errors": 0, "omitted_packets": 0,
                         "start_time": 0, "end_time": previous.elapsed_s}],
        }
        wire.send_json(control, client_results, deadline())
        # require a valid receiving stream result before declaring protocol completion
        server_results = wire.recv_json(control, deadline())
        streams = server_results.get("streams")
        if not isinstance(streams, list) or len(streams) != 1 or not isinstance(streams[0], dict):
            raise wire.ProtocolError("server returned no valid single-stream results")
        received = streams[0].get("bytes")
        if (streams[0].get("id") != 1 or isinstance(received, bool)
                or not isinstance(received, (int, float)) or received <= 0):
            raise wire.ProtocolError("server did not report receiving payload on stream 1")
        result["server_results"] = server_results
        result["server_payload_bytes_received"] = received
        result["server_byte_count_matches_sender"] = received == sent
        wire.expect_state(control, wire.DISPLAY_RESULTS, deadline(), record_event)
        # checked iperf_client_end and the server's done-state handling to confirm
        # the data-socket close and final completion message used for q1(a)(v)
        # source: iperf3 3.17.1, iperf_client_api.c
        # source: iperf3 3.17.1, iperf_server_api.c
        stage = "test_termination"
        data.close()
        data = None
        wire.send_state(control, wire.IPERF_DONE, deadline(), record_event)
        # the standard server closes its control connection after processing done.
        control.settimeout(wire.remaining(deadline()))
        if control.recv(1):
            raise wire.ProtocolError("unexpected bytes after IPERF_DONE")
        # only mark success after result exchange, the final done message, and server closure
        result.update(protocol_complete=True, finished_utc=utc_now())
        record_event({"event": "protocol_complete"})
        return result
    # save the failure stage and partial metadata so runner.py can log and replace the destination
    except (OSError, RuntimeError, ValueError, OverflowError) as error:
        result.update(finished_utc=utc_now(), failure_stage=stage, error=str(error))
        record_event({"event": "failure", "stage": stage, "reason": str(error)})
        raise TransferError(stage, error, result) from error
    # close any remaining sockets after success or failure
    finally:
        for sock in (data, control):
            if sock is not None:
                sock.close()
