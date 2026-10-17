# cs422-assignment2and3

A Python iperf3-compatible TCP upload client and measurement pipeline for
Assignment 2, with configuration and saved-data formats reusable for Assignment
3. The [implementation roadmap](PLAN.md) also covers the later algorithm work.

## Current implementation

- `plan`: seeded destination/port selection and repeated algorithm schedules.
- `check`: Linux socket algorithm selection and a C-checked TCP_INFO decoder.
- `run`: complete single-stream iperf3 uploads, live sampling, bounded failure
  handling and replacements, raw logs, summary tables, PDF plots, and observation
  notes in one command.
- `analyze`: regenerate tables and figures from saved data without network access.

Parts 1 and 2's implementation is present. Live public-server measurements,
Linux runtime validation on the execution machine, Docker execution, and the
report's interpretation must be completed before treating the assignment as done.
Local protocol interoperability can be checked against an unmodified iperf3
server; synthetic test counters are never assignment measurements. See the
[Parts 1 and 2 requirement audit](docs/assignment2-validation.md) for the exact
coverage, verification evidence, and remaining execution/report tasks.

## Install

Live experiments require Linux with the requested congestion algorithms
available. Offline planning, tests, and analysis also run on macOS. See
[environment setup](docs/environment.md) for generic Linux and SSH instructions.

Inside Ubuntu:

```bash
sudo apt update
sudo apt install -y python3 python3-venv git build-essential linux-libc-dev
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run.py check --algorithms cubic
```

The default test run skips the optional official-server interoperability test
unless `IPERF3_SERVER_BINARY` is supplied; this does not require installing an
iperf3 client for normal experiments. `check` without `--algorithms` verifies
CUBIC, Reno, and BBR for the later comparisons.

`check` changes no kernel settings. If an algorithm is unavailable, configure
the Linux host before running its experiments; a container shares that kernel.

## First short experiment: Parts 1 and 2

```bash
python3 run.py run --destinations 1 --duration 10 --interval 0.2 --repetitions 1 --algorithms cubic --max-attempts 6 --output results/first-cubic
```

This command contacts public servers and generates all output automatically.
The output directory must be new. A nonzero exit status indicates a destination
shortfall, interruption, invalid configuration, or another execution error;
inspect the manifest and attempt logs. Public-server restrictions and changes
in availability may require replacements.

For the larger Q1/Q2 dataset, choose a destination count, duration, and repetition
count you can justify, for example:

```bash
python3 run.py run --destinations 3 --duration 60 --interval 0.2 --repetitions 3 --algorithms cubic --output results/cubic-study
```

The assignment permits more or fewer than the suggested 10 destinations. The
defaults are 10 destinations, 60 seconds, 0.2-second intervals, 3 repetitions,
and CUBIC. These are configurable choices rather than fixed assignment values.

## Output

```text
results/<experiment>/
    manifest.json               configuration, kernel, algorithms, actual order
    servers.csv                 input list used by this experiment
    samples.csv                 raw baseline/transfer/drain measurements
    events.jsonl                protocol states and failures, without payloads
    attempts.jsonl              destination attempts and replacement outcomes
    runs/run-0001.json          individual run metadata and server results
    summary.csv                 min/median/mean/p95 by destination and algorithm
    per_run_summary.csv         the same statistics for individual runs
    observations.md             metric explanations and measured observation notes
    plots/
        goodput-destination-001.pdf
        representative-timeseries.pdf   four metric panels
        representative-scatter.pdf      three relationship panels
```

Results are ignored by Git because they can be large and require review before
publication. Preserve the real raw data for submission and explicitly add the
reviewed experiment directory if publishing it with the repository. Generated
metadata uses input basenames and hashes rather than personal home paths.

The representative destination is the first complete matched set. Invalid or
incomplete sets remain in raw logs but are excluded from accepted-run summaries.
Details of the counter layout, units, interval formula, loss proxy, percentile
method, and final-interval policy are in [measurements.md](docs/measurements.md).

Regenerate output offline:

```bash
python3 run.py analyze --results results/first-cubic
```

The observation notes contain measured facts and metric explanations. Review the
seven panels and add your interpretation of anomalies and congestion avoidance
to the final report; generated correlations do not establish their cause.

## Planning and command-line options

```bash
python3 run.py plan --destinations 2 --duration 10 --interval 0.2 --repetitions 3 --algorithms cubic reno bbr --seed 422
python3 run.py run --help
```

The bundled list `configs/listed_iperf3_servers.csv` comes from
[iperf3serverlist.net](https://iperf3serverlist.net/). Use `--servers path/to/list.csv`
to override it. `host,port` and `IP/HOST,PORT` headers are accepted. Inclusive
port ranges count as one candidate; one port is chosen and reused for its runs.

`--destinations`, `--duration`, `--interval`, `--repetitions`, `--algorithms`,
and `--seed` configure both planning and execution. `--max-attempts` bounds
candidate destination sets, defaulting to three times the requested count.
`--timeout`, `--drain-timeout`, `--stall-timeout`, `--pause`, and `--backoff`
bound protocol waits and control spacing between attempts.

The offline plan makes no connections. Live execution groups runs by destination
so a complete matched set can be accepted before moving to the next destination;
the manifest records the actual order and any replacements.

## Docker

Run Docker Engine on Linux. Build from a committed source revision:

```bash
docker build --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" -t cs422-netlab .
docker run --rm cs422-netlab check
mkdir -p results
docker run --rm --network host -v "$PWD/results:/results" cs422-netlab run --destinations 1 --duration 10 --interval 0.2 --repetitions 1 --algorithms cubic --max-attempts 6 --output /results/docker-first
```

The Dockerfile uses `FROM ubuntu:24.04`; its default command runs the full
CUBIC/Reno/BBR pipeline. The Linux host must supply the algorithms and required
TCP_INFO fields. Record the container network mode and VM network configuration
with final results. The image contains no iperf3 client executable.

## Code responsibilities and later work

| Module | Responsibility |
| --- | --- |
| `run.py` | Command-line options and dispatch |
| `netlab/experiments.py` | CSV input and reproducible planning |
| `netlab/protocol.py` | iperf3 framing, states, bounded connection operations |
| `netlab/transfer.py` | One upload and data-socket sampling |
| `netlab/tcp_info.py` | Linux decoding and algorithm/header checks |
| `netlab/measurements.py` | Counter differences and goodput calculation |
| `netlab/runner.py` | Repetitions, replacements, logs, and pipeline orchestration |
| `netlab/analysis.py` | Offline statistics, plots, and observation notes |

See [protocol-notes.md](docs/protocol-notes.md) for the pinned upstream references
and protocol-only interoperability check. Assignment 2 Part 3 still needs the
actual algorithm-comparison study and your congestion-control design. The same
runner accepts `--algorithms cubic reno bbr` and a future registered custom
algorithm; implementing the custom controller remains Assignment 3 work.
