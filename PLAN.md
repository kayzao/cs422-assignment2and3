# Assignment 2 and 3 implementation plan

Planning date: October 16, 2026. This is a plan, not implemented or validated software.

The repository initially contains only README.md. Both assignments list October 21, 2026 at 11:45 PM Eastern as their deadline. Protect October 19-20 for Assignment 3 and October 21 for reruns and reports. Do not spend the whole remaining schedule polishing Assignment 2.

Decisions from the user: development machine is an M5 MacBook Air running macOS; a Linux environment is still needed; keep both Assignment 3 implementation options open.

## 1. Environment first

Recommended arrangement:
- macOS for editing and Git.
- UTM running Ubuntu Server 24.04 ARM64 as a full Linux guest.
- Python experiments and Docker Engine run inside that Linux guest.
- Assignment 3's kernel/eBPF code, if selected, runs against the guest kernel.
- ns-3, if selected, can use the same Linux guest with a separate build environment.

UTM: choose Virtualize -> Linux and an ARM64 Ubuntu ISO. As a provisional starting allocation, use 4 vCPUs, 4 GB RAM, and 40 GB disk, adjusting for available host memory. Ubuntu Server is sufficient; a desktop GUI is optional. Use Git/SSH or a shared directory to make the repository available inside the guest. Install Docker Engine in Ubuntu; containers share the guest kernel and do not need another full VM.

Do not install or reconfigure anything on the Mac as part of this planning step. Before installing, check whether UTM or another suitable Linux VM already exists.

Environment acceptance gate:
- Record uname -r, uname -m, Ubuntu version, Python version, Git commit, and Docker version.
- Inspect available and allowed TCP congestion algorithms and the default algorithm.
- Confirm data sockets can select and read back cubic, reno, and bbr; distinguish absent modules from algorithms that are installed but not loaded.
- Verify TCP_INFO returns the required fields, including an acknowledged-byte counter.
- Record guest network mode and container network mode, and use them consistently.
- Do not continue with a silent BBR substitution. Resolve availability before collecting comparison data.
- If the local guest is unsuitable, use a Linux machine/remote Linux host with appropriate access rather than redesigning around macOS TCP.

Suggested read-only checks to run INSIDE Linux:
    uname -r
    uname -m
    cat /etc/os-release
    cat /proc/sys/net/ipv4/tcp_available_congestion_control
    cat /proc/sys/net/ipv4/tcp_allowed_congestion_control
    cat /proc/sys/net/ipv4/tcp_congestion_control

Dockerfile must start with FROM ubuntu:24.04. Record the actual Linux kernel separately; the base image does not provide the kernel.

## 2. Keep the code split by responsibility

Proposed structure; create components as they are needed, not empty placeholders:

    README.md
    PLAN.md
    Dockerfile
    requirements.txt
    run.py                       # one entry point: check, run, analyze
    netlab/
        protocol.py              # iperf3 control protocol and data-stream setup
        tcp_info.py              # Linux TCP_INFO decoder and socket algorithm helpers
        transfer.py              # one transfer, send loop, sampling, cleanup
        experiments.py           # destinations, repetitions, ordering, failures
        analysis.py              # statistics and PDF plots from saved data
    configs/
        servers.csv              # host,port plus optional provenance
        experiments.json         # saved experiment settings
    tests/                       # focused protocol/decoder/calculation checks
    docs/
        protocol-notes.md
        measurements.md
        algorithm-design.md      # A2 Q3(b), later implemented for A3
        environment.md
    results/<experiment-id>/
        manifest.json
        samples.csv
        attempts.jsonl
        summary.csv
        plots/
    reports/
        assignment2.md
        assignment3.md
    assignment3/                 # later: selected kernel/eBPF OR ns-3 implementation

The module names and CLI syntax are proposals, not assignment requirements. Keep dependencies small: Python standard library for sockets/protocol; matplotlib and a small statistics/data library if useful. Pin dependencies after the first working version.

Core design rule: protocol code creates a connected data socket; measurement code consumes that socket; analysis consumes saved measurements. Neither plotting nor protocol code should depend on a fixed list of algorithm names.

## 3. Milestone A: one complete iperf3 transfer (A2 Q1)

Goal: first successful short upload to a standard public iperf3 server.

Implement a small explicit state machine:
- Open the TCP control connection and send the session cookie.
- Negotiate one forward TCP stream with the required JSON parameters.
- Create the data socket, select the requested congestion algorithm BEFORE connect(), then read back the actual algorithm.
- Associate the data connection with the same test.
- Wait for the server's running state before timed payload transmission.
- Keep processing control messages while sending.
- End the test, exchange required results, acknowledge completion, and close cleanly.
- Bound connection, negotiation, send-stall, and overall-run timeouts. Handle rejection, server errors, unexpected disconnects, and cancellation.

Implementation notes:
- TCP is a byte stream. Write an exact-read helper and handle partial writes.
- Control states and length-prefixed JSON need separate parsing; do not assume one recv() equals one message.
- Validate signed error states and cap received JSON sizes.
- Use the official source to verify wire details and required result fields; pin the consulted upstream revision in protocol notes.
- Start with one stream and client-to-server TCP only. Reverse mode, UDP, and multiple streams are out of scope.
- A successful data send followed by a failed result exchange is NOT a completed protocol test.
- Use packet capture only if protocol debugging needs it.
- Never invoke the iperf3 client binary or substitute a custom receiver.

Acceptance:
- Complete at least one public-server test, including result exchange and termination.
- Save a protocol event log without payload dumps.
- A failed/rejected destination exits within the configured bounds and records a reason.
- Focused tests cover fragmented/coalesced control messages and truncated JSON. These tests do not replace interoperability with a real iperf3 server.

## 4. Milestone B: trustworthy measurements (A2 Q1(c) and Q2(a))

Collect all Q2 metrics while implementing Q1's goodput. Do not build two samplers.

Minimal sample schema:
- schema_version, experiment_id, run_id, destination_host, destination_port
- algorithm_requested, algorithm_actual, repetition
- timestamp_utc, elapsed_s, sample_interval_actual_s, phase
- snd_cwnd_segments, snd_mss_bytes, rtt_us
- bytes_acked_total, bytes_acked_delta, goodput_bps
- total_retrans_segments, retrans_segments_delta

Recommended if exposed: rttvar_us, pacing_rate_Bps, delivery_rate_Bps, and additional cumulative counters. Missing optional fields are null, not zero. Field names, units, and exact counter semantics must be documented against the execution kernel.

Sampling design:
- Sample the DATA socket, never the control socket.
- Use a monotonic clock for elapsed time and rate calculations.
- Use cumulative acknowledged bytes and actual time differences:
      goodput_bps = 8 * bytes_acked_delta / sample_interval_actual_s
- Do not substitute bytes handed to send(), nominal interval, or a delivery-rate estimate for this formula.
- Start with 0.2-second sampling. Capture an initial baseline and a final sample before closing.
- Establish/document the payload-phase baseline so the iperf stream cookie is excluded from useful payload accounting.
- Separate active transfer and any bounded drain/cleanup samples; state which samples enter summaries.
- Prefer cumulative total retransmissions for the loss proxy if available. Difference it per interval, and optionally normalize by elapsed time. A retransmission count is not an exact independent count of original network packet losses.
- Preserve meaningful zero-throughput/loss intervals; flag invalid samples rather than silently inventing values.
- Make sure a blocked sender does not stop sampling or control-channel processing. Start with one sender worker and a coordinator handling sampling/control with bounded operations, or an equivalent readiness-based loop.

Decoder acceptance gate:
- Verify layout, offsets, units, and returned length against Linux UAPI headers for the execution environment; do not copy an unexplained struct format.
- A tiny C offsetof/sizeof helper may validate Python decoding during development.
- Treat kernel runtime support separately from header availability.
- Verify counters advance, units are plausible, cumulative counters are monotone, and interval arithmetic works on known fixture values.
- Fail clearly if acknowledged-byte or other required fields cannot be read.
- Save the kernel version, decoder layout/version, and any unsupported fields in the manifest.

## 5. Milestone C: destinations and reproducible runs (A2 Q1(b), ready for Q3)

- Accept a server-list file with addresses and ports; record its provenance from iperf3serverlist.net.
- Randomly choose destinations with a saved random seed.
- Start development with one destination and 10-second runs.
- Run measured experiments sequentially so concurrent local tests do not compete.
- Log every attempt, including failure stage, reason, timestamps, and whether samples are incomplete.
- Use bounded attempts, backoff, and replacement candidates. Report requested versus successful destination count.
- Freeze the selected destination list for comparison runs. Do not randomly pick a new list for each algorithm.
- If a destination must be replaced during comparisons, collect the matched algorithm set on the replacement or explicitly report the missing comparisons.
- Choose and save one representative destination before selecting attractive-looking plots.
- Store requested AND actual congestion algorithm, durations, intervals, test order, seeds, repetitions, and environment in manifest.json.
- Keep run IDs unique and preserve partial data; exclude incomplete runs from successful-run summaries with an explicit reason.

Proposed CLI shape:
    python run.py check
    python run.py run --servers configs/servers.csv --destinations 1 --duration 10 --interval 0.2 --repetitions 1 --algorithms cubic
    python run.py analyze --results results/<experiment-id>

Later, the same run command accepts --algorithms cubic reno bbr, or an arbitrary registered custom algorithm name. Provide a single command/config that runs the entire required pipeline, including analysis, without manual file editing.

Suggested final experiment scale: configurable; start with 3-5 destinations, 60 seconds, 0.2-second sampling, and 3 repetitions if practical. The assignment permits fewer than the suggested default of 10; justify the actual choice. Five destinations x three algorithms x three repetitions x 60 seconds is 45 minutes of active transfer, before retries and overhead.

## 6. Milestone D: complete Parts 1 and 2 output

Q1:
- Goodput time-series PDFs for every destination.
- Summary table: minimum, median, mean, and 95th-percentile interval goodput by destination/algorithm, with per-run results retained.
- State percentile method, sample inclusion policy, treatment of incomplete intervals, and whether any averages are time-weighted.

Q2 using CUBIC or the recorded OS default:
- Four time-series panels: cwnd, RTT, interval retransmission proxy, and goodput.
- Three scatter panels: cwnd-goodput, RTT-goodput, and interval loss-proxy-goodput.
- Same representative destination and documented units.
- Observations explain window-limited rate, RTT/queueing, losses/recovery, BDP, and anomalies using the actual traces.
- Do not infer causation from a scatter plot alone or claim that zero observed retransmits means no congestion.

Analysis must read stored data and run without network access. Plots should group by recorded algorithm and work when another algorithm is added. Keep separate runs distinct in plots; do not connect their timestamps into one artificial trace.

Parts 1 and 2 are done when one command produces raw measurements, Q1 tables/plots, all Q2 plots, and a draft explanation from Linux/Docker. Do not spend extra days on styling.

## 7. Leave these extension points for A2 Q3 and A3

A2 Q3(a):
- Add Reno and BBR to configuration, not separate client implementations.
- Use the same destinations, duration, interval, and representative destination.
- Repeat runs and rotate/counterbalance algorithm order, saving the schedule.
- Generate the same seven plot types per algorithm with consistent axes.
- Compare throughput AND RTT, and discuss changing paths, queueing, loss, BDP, and variability.

A2 Q3(b):
- Choose a deliberately small algorithm using RTT, a loss proxy, and throughput.
- Specify units, initial state, parameter values, update trigger, bounds, and loss/timeout responses.
- Distinguish per-ACK updates from once-per-RTT/sampling updates; they are not interchangeable.
- Discuss fairness, convergence, assumptions, and limitations.
- Design around signals obtainable inside the future TCP implementation. Python TCP_INFO is an observer, not a mechanism for assigning the kernel's cwnd.
- Keep pseudocode and future kernel/ns-3 behavior aligned; record any changes.

A3 Option 1:
- First prove a minimal module/eBPF congestion algorithm can build, load, register, and be selected in the guest kernel.
- Keep kernel support, headers/BTF/tools, and permissions as an early feasibility check.
- Add the custom algorithm by name to the existing Python runner.
- Reuse sampling and seven plots; use 10-second tests for all four algorithms and multiple runs.
- Add throughput/RTT aggregate statistics and exact build/load/reproduction instructions.
- Kernel/eBPF changes live separately from the Python iperf client.

A3 Option 2:
- First prove the selected stable ns-3 release builds and has the required baseline algorithms.
- Implement the custom TCP algorithm inside ns-3.
- Separate topology/workload configuration from the congestion algorithm.
- Required model: two ToRs, two spines, 16 servers/ToR, 100-Gbps server links, 400-Gbps ToR-spine links, 500-ns one-way propagation per link.
- Required workload: 992 directed 64-MB flows, all starting simultaneously.
- Fix and document routing/path selection and buffer/queue configuration across algorithms; cite buffer-size justification.
- Measure receiver-observed completion times, unfinished flows, mean and p99; use TcpNewReno as the Reno baseline.
- Reuse analysis conventions and report automation, but keep flow completion data separate from live TCP_INFO samples.

Do not implement both Assignment 3 paths. Choose by the end of October 17 after a short feasibility check. Keeping options open in the shared client should not become a generic simulation framework.

## 8. Schedule and completion checkpoints

These are planning targets, not guarantees; protocol and kernel setup are the main unknowns.

- Oct 16 evening: Linux VM and environment gate; protocol research; first handshake if time allows.
- Oct 17: complete one short end-to-end iperf3 transfer, validate TCP_INFO, and produce one destination's seven plots. Decide A3 path after a minimal build/load or ns-3 build check.
- Oct 18: finish A2 destination automation, multi-algorithm runs, and design pseudocode. Draft the A2 report as measurements arrive.
- Oct 19-20: implement and evaluate A3; allow time for kernel or simulation debugging and reruns.
- Oct 21: clean reproduction runs, final plots/analysis, repository links, separate PDF reports, and oral-exam preparation. Avoid major new features.

If an Oct 17 checkpoint slips: reduce nonessential plotting polish and the configurable destination count first. Preserve correctness, all required metrics, all baseline algorithms, repetitions, and the A3 workload requirements.

## 9. Submission and verification checklist

- One PDF for each assignment, with repository/code links and embedded plots.
- Raw measurements, configuration, dependencies, and exact reproduction commands.
- Dockerfile for A2; full Linux kernel/environment documentation.
- Exact stable ns-3 version OR exact kernel/build/load requirements for A3.
- Brief AI-use acknowledgment and ability to explain code, counter semantics, figures, and algorithm decisions.
- No private lecture PDFs uploaded into the public repository.
- No actual experiments, package installs, VM setup, or implementation have been performed by creating this plan.

## Sources

Assignment requirements were checked against the user's local assignment-2.pdf and assignment-3.pdf. The public technical references below inform implementation planning; pin source revisions during implementation.

- UTM Ubuntu guide (guide title is 22.04; use it for VM workflow, with the selected 24.04 ARM64 image): https://docs.getutm.app/guides/ubuntu/
- Ubuntu 24.04 image directory: https://download.cdimage.ubuntu.com/ubuntu/releases/24.04/release/
- Docker Engine on Ubuntu, including ARM64: https://docs.docker.com/engine/install/ubuntu/
- iperf3 protocol overview (older overview; verify exact details against source): https://github.com/esnet/iperf/wiki/IperfProtocolStates
- iperf3 client: https://github.com/esnet/iperf/blob/master/src/iperf_client_api.c
- iperf3 protocol implementation: https://github.com/esnet/iperf/blob/master/src/iperf_api.c
- Linux TCP socket options: https://man7.org/linux/man-pages/man7/tcp.7.html
- Linux TCP UAPI header: https://github.com/torvalds/linux/blob/master/include/uapi/linux/tcp.h
