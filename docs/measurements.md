# Measurement definitions and analysis policy

## Source and decoder

All statistics come from the **data socket** using
`getsockopt(IPPROTO_TCP, TCP_INFO)`. The control connection is never sampled.
The decoder references the stable prefix of
[Linux's TCP UAPI structure at v6.12](https://github.com/torvalds/linux/blob/v6.12/include/uapi/linux/tcp.h).
It uses native byte order with fixed-size integers, not iperf3's network order.
Counter assignments, RTT units, and the pacing-rate sentinel were also checked
in [tcp_get_info at v6.12](https://github.com/torvalds/linux/blob/v6.12/net/ipv4/tcp.c).

`python3 run.py check` compiles `tools/tcp_info_layout.c` against the installed
`linux/tcp.h` and checks every decoded field's offset and size. It separately
checks the buffer length returned by the running kernel and verifies socket
algorithm selection. Header support and kernel runtime support are distinct.
The same checks run before live transfers. Required missing fields cause an
error; unavailable optional fields are blank in CSV, never invented zeros.

| Saved field | Linux member | Offset | Units |
| --- | --- | ---: | --- |
| `snd_mss_bytes` | `tcpi_snd_mss` | 16 | bytes/segment |
| `unacked_segments` | `tcpi_unacked` | 24 | segments |
| `rtt_us` | `tcpi_rtt` | 68 | microseconds |
| `rttvar_us` | `tcpi_rttvar` | 72 | microseconds |
| `snd_cwnd_segments` | `tcpi_snd_cwnd` | 80 | segments |
| `total_retrans_segments` | `tcpi_total_retrans` | 100 | cumulative segments |
| `pacing_rate_Bps` | `tcpi_pacing_rate` | 104 | bytes/second |
| `bytes_acked_total` | `tcpi_bytes_acked` | 120 | cumulative bytes |
| `notsent_bytes` | `tcpi_notsent_bytes` | 144 | bytes |
| `delivery_rate_Bps` | `tcpi_delivery_rate` | 160 | bytes/second |

Byte counters and rates at offsets 104, 120, and 160 use unsigned 64-bit
integers; other table fields use unsigned 32-bit integers. The kernel's
all-ones pacing-rate sentinel is recorded as unavailable. The manifest records
the header layout, kernel, architecture, byte order, and observed buffer lengths.
The manifest also records the available, allowed, and default congestion-control
configuration when those procfs settings are readable.

## Goodput and loss proxy

Every interval records:

```text
dt = current_monotonic_time - previous_monotonic_time
bytes_acked_delta = current.bytes_acked_total - previous.bytes_acked_total
goodput_bps = 8 * bytes_acked_delta / dt
retrans_segments_delta = current.total_retrans_segments - previous.total_retrans_segments
```

The iperf data cookie is fully acknowledged before the payload baseline. This
also puts connection setup outside the measured payload interval. The baseline
row has blank goodput and zero interval duration; it is not a zero-rate sample.
Decreasing counters and non-increasing timestamps fail the run rather than
producing misleading negative rates.

The retransmission delta is a **loss proxy**, not an exact count of original
packet drops or a loss probability. Reordering and spurious retransmissions can
affect it. The available delivery-rate estimate is logged as an additional
metric, not substituted for the assignment's acknowledged-goodput formula.

## Saved data

`samples.csv` includes explicit units in field names, a UTC timestamp, monotonic
elapsed time, actual sampling interval, destination, experiment/run IDs,
requested and actual algorithms, repetition, and phase (`baseline`, `transfer`,
or `drain`). The coordinator uses nonblocking sends so a full send buffer does
not stop control processing or sampling.

`manifest.json` records configuration, actual run order, complete versus failed
runs, accepted matched sets, replacement attempts, environment, dependency
versions, source revision, and source-list hash. The input CSV is copied to
`servers.csv`. Account names, hostnames of the execution machine, absolute home
paths, and environment-variable dumps are excluded from generated metadata.
`events.jsonl` stores protocol states and failure stages; `attempts.jsonl` stores
destination-attempt starts and outcomes. Per-run JSON files retain server results.

## Inclusion and statistics

- Tables and figures use `transfer` intervals from complete, accepted matched
  destination sets. Every configured algorithm and repetition must succeed for
  the destination to be accepted.
- Failed and partial destination sets remain in raw logs but are excluded.
  The requested count, successful count, and shortfall are explicit.
- Baseline and drain samples are excluded from active-transfer statistics.
  Drain ACKs describe delivery after sending has stopped; keeping them separate
  avoids extending the configured active-transfer period in the plots.
- Valid zero-goodput intervals and final partial intervals are retained.
- `summary.csv` pools active intervals by destination and actual algorithm;
  `per_run_summary.csv` preserves per-run results.
- Minimum, median, arithmetic mean, and p95 operate on interval goodput values
  with equal weight. A separate time-weighted mean is total acknowledged bits
  divided by total sampled active time. This distinction matters when intervals
  differ in duration.
- Percentiles use linear interpolation at index `(n - 1) * p` (type 7).

## Figures and observations

Every accepted destination has a goodput time-series PDF. The representative
destination is the first completed matched set, selected without comparing its
performance. Its four time-series panels show cwnd, RTT, interval retransmissions,
and goodput. Three scatter panels compare cwnd, RTT, and retransmissions against
goodput. Different algorithms use consistent row scales, and repetitions are
separate traces rather than one concatenated timeline.

`observations.md` gives metric explanations, inclusion rules, measured ranges,
zero-rate intervals, retransmission totals, and correlations. Add your own
interpretation of actual anomalies and congestion-avoidance behavior for Q2(c).
Correlation alone does not establish causation. Internet paths, VM scheduling,
and container/VM network configuration can change between runs; record the
configuration and discuss those limitations in the report.
