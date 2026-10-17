# Assignment 2: Parts 1 and 2 requirement audit

## Conclusion

The implementation covers the programming requirements for Parts 1 and 2.
Local tests and standard-server protocol checks pass. This is not a claim that
all submission requirements are finished: live public-server measurements on
the execution Linux kernel, Docker execution, and the report's interpretation
of real traces remain to be completed.

The source requirements are Assignment 2's handout, Questions 1 and 2 and the
shared report instructions. Part 3's comparison study and algorithm design are
outside this audit's completion scope.

## Requirement coverage

| Handout requirement | Implementation and saved evidence | Verification status |
| --- | --- | --- |
| Q1(a): socket client written in Python | `protocol.py` and `transfer.py`; production code never invokes an iperf3 client binary | Implemented; local standard-server protocol check passed |
| Compatibility with public standard iperf3 servers | Implements the official single-stream forward TCP protocol; uses the bundled public server list | Local unmodified-server interoperability passed; a successful public-server run remains required |
| Establish control connection | `connect_control`, cookie exchange, bounded DNS and connection attempts | Local protocol flow and framing checked |
| JSON parameter exchange | Length-prefixed parameters with server-readable keys | Standard-server check and fragmented/invalid-message checks passed |
| Open data connection | Separate socket to the resolved control peer, same session cookie | Standard-server check passed |
| Continuous sending for configurable duration | Nonblocking payload sends and monotonic duration deadline | Standard-server check passed; live Linux run pending |
| Proper termination | TEST_END, result exchange, DISPLAY_RESULTS, IPERF_DONE, and server closure | Standard-server check passed |
| Nonresponsive/overloaded or rejecting servers | Bounded connect/control waits; signed access-denied and server-error states | Timeout/error framing and runner failure checks passed |
| Premature termination | Detects EOF, early data close, unexpected control state, and incomplete messages | Truncated-message checks passed; broader live behavior remains an execution check |
| Q1(b): randomly choose configurable n | Seeded planner; `--destinations` defaults to 10, configurable CSV input | Planner and actual-list parsing checks passed |
| Record selected addresses and ports | Manifest, raw samples, per-run metadata, and attempt log | Runner checks and complete local pipeline check passed |
| Log failure, use bounded replacements, report shortfall | `--max-attempts`, failure stage/reason, seeded reserves, explicit destination shortfall | Replacement and exhausted-attempt checks passed |
| Q1(c): goodput from successive cumulative ACK counters and actual time | `measure_interval`; data-socket TCP_INFO; payload cookie excluded by the baseline | Arithmetic/decoder fixtures passed; actual Linux counters pending |
| Regular configurable sampling | Requested `--interval`; actual interval saved with each row | Implemented; sample values and rate consistency checked in local synthetic-counter pipeline |
| Goodput time series for all destinations | One goodput PDF per accepted destination | PDF generation checks and visual review passed |
| Min/median/mean/p95 table per destination/algorithm | `summary.csv` and `per_run_summary.csv`; explicit percentile/inclusion rules | Known-value statistics and zero-rate checks passed |
| Q2: CUBIC or OS default, actual algorithm recorded consistently | Default request is CUBIC; socket readback before and after connect; analysis groups by actual algorithm | Implemented; execution-machine check remains required |
| Q2(a): timestamp, cwnd, RTT, loss signal, and goodput together | `samples.csv`; data socket only; UTC and elapsed time; cumulative retransmission delta proxy | Schema/decoder/calculation checks passed; live Linux samples pending |
| Recommended RTT variation, pacing, cumulative bytes, delivery rate | Recorded when exposed by the kernel; missing optional fields are blank | Fixture and short-buffer checks passed |
| Store CSV/JSON with units, destination, algorithm, and run ID | Explicit field names and identifiers in raw logs and metadata | Complete local pipeline check passed |
| Document kernel decoding, interval formula, and loss proxy | `measurements.md`, C layout helper, environment manifest, observed returned lengths | Reference-source review and fixtures passed; installed Linux header check pending |
| Q2(b)(i): cwnd, RTT, loss-proxy, and throughput time series | Four panels in `representative-timeseries.pdf` | PDF generation and visual review passed |
| Q2(b)(ii): cwnd/goodput, RTT/goodput, loss/goodput scatter plots | Three panels in `representative-scatter.pdf` | PDF generation and visual review passed |
| Q2(c): explain metric meanings, effects in congestion avoidance, and actual anomalies | Generated `observations.md` provides definitions, measured facts, and correlation notes | Starting material implemented; the student must interpret real traces in the final report |
| Single entry point, raw data, options, dependencies, reproduction | `run.py run` executes transfers and analysis; `analyze` replays saved data; README documents settings | Offline CLI, dependency checks, and complete local pipeline check passed |
| Ubuntu 24.04 Docker image and host-kernel information | Dockerfile uses `FROM ubuntu:24.04`; manifest stores kernel, layout, and congestion-control configuration | Files reviewed; Docker build/run pending on a supported Linux host |
| Final PDF with plots, code links, interpretation, AI acknowledgment | Outputs and documentation provide inputs for the report | Final submission artifact and oral-exam preparation remain student work |

## What was actually verified locally

- All **23 tests passed** under Python 3.9 and Python 3.12 with the optional
  official-server test enabled. Dependency consistency checks also passed.
- An unmodified official iperf3 3.17.1 server completed setup, data transfer,
  result exchange, and termination with this Python client. Only its server
  mode was invoked; no iperf3 client executable performed the experiment.
- A complete local pipeline check exercised standard-server protocol behavior,
  raw CSV logging, accepted-run metadata, statistics, notes, and PDF generation.
- Those local protocol/pipeline checks used explicitly synthetic counters on
  macOS. They do not prove the execution kernel's counter layout, units, or
  accuracy, and their data are not assignment measurements.
- Synthetic PDF figures were visually reviewed. No synthetic experiment data
  were committed as real results.
- Nonfinite JSON overflow and stall detection with long sampling intervals were
  corrected during the audit. Failure, replacement, shortfall, and interruption
  behavior have focused checks.

## Required Ubuntu execution

Update the Ubuntu checkout to the committed implementation first. Use matching
committed source revisions for final measurements. From its repository directory:

```bash
sudo apt update
sudo apt install -y python3 python3-venv git build-essential linux-libc-dev
python3 -m venv .venv
source .venv/bin/activate
python3 -m pip install -r requirements.txt
python3 -m unittest discover -s tests -v
python3 run.py check --algorithms cubic
python3 run.py run --destinations 1 --duration 10 --interval 0.2 --repetitions 1 --algorithms cubic --max-attempts 6 --output results/first-cubic
```

The optional server test is normally skipped in Ubuntu unless its binary path
is explicitly provided. The production experiment command contacts the public
servers itself using Python, with no iperf3 executable requirement.

A successful smoke run must have exit status 0, manifest status `complete`, zero
destination shortfall, an accepted run with `protocol_complete: true`, actual
algorithm `cubic`, raw transfer samples, summary CSV files, and the three PDFs
(one destination goodput PDF plus the four-panel and three-panel PDFs). Inspect
actual counter progress and plausible units before collecting the larger study.
An existing output directory is deliberately rejected; choose a new directory
for each execution.

Then collect an appropriately justified larger Q1/Q2 dataset, for example:

```bash
python3 run.py run --destinations 3 --duration 60 --interval 0.2 --repetitions 3 --algorithms cubic --output results/cubic-study
python3 run.py analyze --results results/cubic-study
```

## Docker execution

Use Docker Engine on Linux. Record the VM and container networking configuration.
Build from a committed checkout:

```bash
docker build --build-arg SOURCE_COMMIT="$(git rev-parse HEAD)" -t cs422-netlab .
docker run --rm cs422-netlab check --algorithms cubic
mkdir -p results
docker run --rm --network host -v "$PWD/results:/results" cs422-netlab run --destinations 1 --duration 10 --interval 0.2 --repetitions 1 --algorithms cubic --max-attempts 6 --output /results/docker-first
```

The container uses its Linux host's kernel. Loading BBR or changing allowed
algorithms, if needed for Part 3, is a host configuration task; the client does
not silently substitute another algorithm.

## Finishing the report

Review the actual figures and generated notes. Explain what cwnd, RTT, the loss
proxy, and goodput show during congestion avoidance, and identify anomalies with
specific timestamps or intervals. State the loss-proxy limitation, units,
percentile method, zero/final-interval policy, destination shortfalls, and any
incomplete excluded runs. Embed the figures and summary table, link the source
functions, acknowledge AI assistance briefly, and retain the real raw data and
exact reproduction commands. Part 3 additionally requires the three-algorithm
study and congestion-control design; those are not finished by a CUBIC-only run.
