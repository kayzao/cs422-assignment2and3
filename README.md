# cs422-assignment2and3

TCP measurement experiments for Assignment 2 and a future congestion controller
implementation for Assignment 3. The overall roadmap is in [PLAN.md](PLAN.md).

## What works now

The offline starter uses only the Python standard library (Python 3.10+):

- `netlab/measurements.py`: calculates acknowledged goodput and interval
  retransmissions from cumulative counters and actual elapsed time.
- `netlab/experiments.py`: reads server-list CSV files and builds a reproducible
  schedule with the same destinations for every algorithm. It rotates algorithm
  order across repetitions.
- `run.py plan`: prints that schedule as JSON without opening network connections.

Live iperf3 transfers, Linux TCP_INFO decoding, plotting, and Docker support are
still to be implemented. Schedule entries are plans, not measured results.

## Linux environment and SSH

See [docs/environment.md](docs/environment.md) for the current Ubuntu VM details,
Mac-to-Ubuntu SSH command, initial repository transfer, and remaining checks.
The documented kernel and congestion-control values were observed in a user
screenshot; live socket selection and TCP_INFO decoding still need verification.

## Try this on macOS while Ubuntu installs

From this repository's directory:

```bash
python3 --version
python3 -m unittest discover -s tests -v
python3 run.py plan --servers configs/servers.example.csv --destinations 2 --duration 10 --interval 0.2 --repetitions 3 --algorithms cubic reno bbr --seed 422
```

The example file uses reserved `.example` hosts, not public iperf3 servers.
Create `configs/servers.csv` with real hostnames and ports selected from
https://iperf3serverlist.net/ before preparing real experiments. The planner does
not test whether servers are reachable or whether algorithms exist on the kernel.

```csv
host,port
server-a.example,5201
server-b.example,5202
```

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

## Next work

1. Review the two small modules and reproduce the goodput calculation by hand.
2. Prepare the real server CSV and try different schedule sizes/seeds.
3. Define the full sample CSV schema (run ID, destination, algorithm, timestamp,
   cwnd, RTT, counters, interval metrics, units, and phase).
4. Add summary statistics and plots that consume saved samples; they can be
   developed on macOS using clearly labeled synthetic fixtures.
5. In Ubuntu, verify congestion control availability, implement the iperf3
   protocol, and connect the live TCP_INFO sampler to these helpers.

Algorithm names are configuration values, so Reno, BBR, and a future registered
custom algorithm can reuse the same runner. The planner's sequential schedule
also avoids deliberately making local tests compete with one another.
