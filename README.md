# cs422-assignment2and3

TCP measurement experiments for Assignment 2 and a future congestion controller
implementation for Assignment 3. The overall roadmap is in [PLAN.md](PLAN.md).

## What works now

The offline starter uses only the Python standard library (Python 3.9+):

- `netlab/measurements.py`: calculates acknowledged goodput and interval
  retransmissions from cumulative counters and actual elapsed time.
- `netlab/experiments.py`: reads server-list CSV files and builds a reproducible
  schedule with the same destinations for every algorithm. It rotates algorithm
  order across repetitions.
- `run.py plan`: prints that schedule as JSON without opening network connections.

Live iperf3 transfers, Linux TCP_INFO decoding, plotting, and Docker support are
still to be implemented. Schedule entries are plans, not measured results.

## Linux environment

Live experiments require a Linux kernel with the requested congestion-control
algorithms available. See [docs/environment.md](docs/environment.md) for generic
Linux setup, optional SSH access, and the remaining environment checks.

## Quick start

The offline planner and tests also run on macOS. From this repository's directory:

```bash
python3 --version
python3 -m unittest discover -s tests -v
python3 run.py plan --destinations 2 --duration 10 --interval 0.2 --repetitions 3 --algorithms cubic reno bbr --seed 422
```

The default file is `configs/listed_iperf3_servers.csv`, a bundled public
server list from [iperf3serverlist.net](https://iperf3serverlist.net/). The parser
accepts its `IP/HOST` and `PORT` columns and ignores other metadata. Port ranges
such as `5201-5210` count as one server row; the planner chooses one port uniformly within the range and reuses it for every algorithm
and repetition. The planner does not test server reachability or kernel support.

Use `--servers path/to/another.csv` to override the default.

The same seed and inputs produce the same schedule. Two destinations, three
algorithms, and three repetitions produce 18 runs. At 10 seconds each, their
active transfer budget would be 180 seconds, excluding setup, retries, and cleanup.

## Understand the measurement calculation

If the acknowledged-byte counter rises from 1,000 to 101,000 bytes over 0.25
seconds, interval goodput is:

```text
8 * (101000 - 1000) / 0.25 = 3,200,000 bits/second
```

The code deliberately preserves zero-goodput intervals. It rejects decreasing
counters and non-increasing timestamps, which require a new baseline or a
recorded sampling error. The first snapshot is a baseline, not a zero-rate sample.
Retransmissions are a documented loss proxy, not an exact packet-loss probability.

When the Linux sampler is added, take these counters from the data socket and
establish the payload baseline so iperf3's connection cookie is excluded. Do not
use bytes passed to `send()` as acknowledged bytes.

## Remaining implementation

1. Verify Linux socket algorithm selection and the required TCP_INFO fields.
2. Implement a complete Python iperf3 upload, including negotiation, result
   exchange, termination, and bounded error handling.
3. Add live data-socket sampling and CSV/JSON logging with explicit units,
   destination, algorithm, run ID, and transfer phase.
4. Add summary statistics and PDF plots from saved samples.
5. Add bounded destination replacements and repeated algorithm comparisons.
6. Add the Ubuntu 24.04 Docker image, full pipeline command, and reports.

Algorithm names are configuration values, so Reno, BBR, and a future registered
custom algorithm can reuse the same runner. The planner's sequential schedule
also avoids deliberately making local tests compete with one another.
