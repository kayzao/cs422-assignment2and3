"""Read server candidates and prepare an offline, reproducible schedule."""

import csv
from dataclasses import dataclass
import math
from pathlib import Path
import random
from typing import Optional


# Server class that has read-only values after initialization, used
# as data record for each row
@dataclass(frozen=True)
class Server:
    host: str
    port: int
    # Optional keeps this compatible with Ubuntu/Mac Python 3.9.
    port_end: Optional[int] = None


def load_servers(path: Path) -> list[Server]:
    """Load host/port or IP/HOST/PORT CSV rows, ignores other metadata columns.

    PORT may be one integer or an inclusive range such as 5201-5210.
    """
    servers = []
    # prevents duplicate CSV rows
    seen = set()
    # newline="" lets the CSV reader handle platform-specific line endings
    with path.open(newline="", encoding="utf-8-sig") as handle:
        # DictReader maps column names to values
        reader = csv.DictReader(handle)
        columns = {name.strip().casefold(): name for name in (reader.fieldnames or [])}
        host_column = next((columns[name] for name in ("host", "ip/host", "ip")
                            if name in columns), None)
        port_column = columns.get("port")
        if host_column is None or port_column is None:
            raise ValueError("server CSV needs host (or IP/HOST) and port columns")
        for row in reader:
            # strip accidental spaces from copied server addresses. IP addresses
            # and hostnames are accepted, DNS/reachability checks happen later.
            host = (row.get(host_column) or "").strip()
            port_spec = (row.get(port_column) or "").strip()
            try:
                start_text, separator, end_text = port_spec.partition("-")
                if not start_text.isdecimal() or (separator and not end_text.isdecimal()) or (
                    separator and "-" in end_text
                ):
                    raise ValueError
                port = int(start_text)
                port_end = int(end_text) if separator else port
            except ValueError as error:
                # Include the CSV line so the user can fix a malformed entry.
                raise ValueError(f"CSV line {reader.line_num}: invalid port") from error
            if not host or any(c.isspace() for c in host) or "://" in host:
                raise ValueError(f"CSV line {reader.line_num}: supply a host, not a URL")
            if not (1 <= port <= port_end <= 65535):
                # A destination TCP port must be in the usable 16-bit range.
                raise ValueError(
                    f"CSV line {reader.line_num}: port/range must be within 1..65535"
                )

            # Deduplicate rows only when their advertised endpoint/range matches.
            key = (host.casefold(), port, port_end)
            if key not in seen:
                servers.append(Server(host, port, port_end if port_end != port else None))
                seen.add(key)
    if not servers:
        raise ValueError("server CSV contains no candidates")
    return servers

# Chooses the servers and ports for experiments, creating a schedule of runs for
# each congestion-control algorithm for comparison.
def build_plan(
    candidates: list[Server], *, destinations: int, algorithms: list[str],
    duration_s: float, interval_s: float, repetitions: int, seed: int,
) -> dict:
    """Select destinations once and rotate algorithm order across repetitions.

    A plan makes no network requests and does not verify server availability.
    Algorithm labels are unrestricted so a future custom controller can reuse
    the runner. The Linux execution layer must verify their actual availability.

    Returns a dictionary containing experiment settings and a runs list.
    Each run records its ID, repetition, requested algorithm, host, and port.
    """
    # Validate before generating any runs. This offline check cannot replace A2's
    # eventual bounded retries/replacement logic for unavailable public servers.
    if destinations < 1 or destinations > len(candidates):
        raise ValueError(f"destinations must be between 1 and {len(candidates)}")
    if repetitions < 1:
        raise ValueError("repetitions must be positive")
    if not all(math.isfinite(x) and x > 0 for x in (duration_s, interval_s)):
        raise ValueError("duration and interval must be finite and positive")
    if interval_s > duration_s:
        raise ValueError("sampling interval cannot exceed duration")
    if not algorithms or any(not a or a.isspace() for a in algorithms):
        raise ValueError("at least one nonempty algorithm is required")
    if len(set(algorithms)) != len(algorithms):
        # Repeating a name here would silently give that algorithm extra runs.
        raise ValueError("algorithms must not contain duplicates")

    # A local seeded generator avoids changing Python's global random state.
    rng = random.Random(seed)
    # sample() chooses without replacement, so every algorithm uses same dest set
    selected_candidates = rng.sample(candidates, destinations)
    # picks one concrete port from each selected server's range, once per plan.
    selected = [
        Server(server.host, rng.randint(server.port, server.port_end or server.port))
        for server in selected_candidates
    ]
    # Copy before shuffling so we do not mutate the caller's algorithm list.
    base_order = list(algorithms)
    rng.shuffle(base_order)
    runs = []
    for repetition in range(1, repetitions + 1):
        # Rotate who runs first to reduce a fixed test-order bias. With three
        # algorithms and three repetitions, each algorithm occupies each position.
        # Changing Internet conditions can still affect comparisons; log this order.
        shift = (repetition - 1) % len(base_order)
        order = base_order[shift:] + base_order[:shift]
        for server in selected:
            for algorithm in order:
                runs.append({
                    "run_id": f"run-{len(runs) + 1:04d}",
                    "destination_host": server.host,
                    "destination_port": server.port,
                    # live runner must also record the algorithm actually used.
                    "algorithm_requested": algorithm,
                    "repetition": repetition,
                })
    return {
        # Version the format so later readers can detect incompatible changes.
        "schema_version": 1,
        # Explicitly distinguish a schedule from successful measured experiments.
        "status": "planned_only",
        "seed": seed,
        "duration_s": duration_s,
        "interval_s": interval_s,
        "repetitions": repetitions,
        "selected_destinations": [
            {"host": server.host, "port": server.port} for server in selected
        ],
        "algorithms_requested": algorithms,
        "active_transfer_seconds": len(runs) * duration_s,
        "runs": runs,
    }


"""
{
    "schema_version": 1,
    "status": "planned_only",
    "seed": 42,
    "duration_s": 10.0,
    "interval_s": 1.0,
    "repetitions": 2,
    "selected_destinations": [
        {"host": "iperf.example.net", "port": 5201}
    ],
    "algorithms_requested": ["cubic", "reno"],
    "active_transfer_seconds": 40.0, #estimated total transfer time (# runs * duration per run)
    "runs": [
        {
            "run_id": "run-0001",
            "destination_host": "iperf.example.net",
            "destination_port": 5201,
            "algorithm_requested": "reno",
            "repetition": 1
        },
        {
            "run_id": "run-0002",
            "destination_host": "iperf.example.net",
            "destination_port": 5201,
            "algorithm_requested": "cubic",
            "repetition": 1
        }
        # Two more runs for repetition 2
    ]
}

"""
