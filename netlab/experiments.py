"""Read server candidates and prepare an offline, reproducible schedule."""

import csv
from dataclasses import asdict, dataclass
import math
from pathlib import Path
import random


@dataclass(frozen=True)
class Server:
    # A2 Q1(b) needs both address and port. Two ports on the same host are
    # distinct candidate endpoints, even though they may share a network path.
    host: str
    port: int


def load_servers(path: Path) -> list[Server]:
    """Load host,port CSV rows; preserve order and remove duplicates."""
    servers = []
    # Membership checks prevent duplicate CSV rows from biasing random selection.
    seen = set()
    # newline="" lets the CSV reader handle platform-specific line endings;
    # utf-8-sig also accepts CSV files containing a UTF-8 byte-order mark.
    with path.open(newline="", encoding="utf-8-sig") as handle:
        # DictReader maps column names to values, so column order is flexible.
        reader = csv.DictReader(handle)
        if not reader.fieldnames or not {"host", "port"} <= set(reader.fieldnames):
            raise ValueError("server CSV needs host and port columns")
        for row in reader:
            # Strip accidental spaces from copied server addresses. IP addresses
            # and hostnames are accepted; DNS/reachability checks happen later.
            host = (row.get("host") or "").strip()
            try:
                port = int(row.get("port") or "")
            except ValueError as error:
                # Include the CSV line so the user can fix a malformed entry.
                raise ValueError(f"CSV line {reader.line_num}: invalid port") from error
            if not host or any(c.isspace() for c in host) or "://" in host:
                raise ValueError(f"CSV line {reader.line_num}: supply a host, not a URL")
            if not 1 <= port <= 65535:
                # A destination TCP port must be in the usable 16-bit range.
                raise ValueError(f"CSV line {reader.line_num}: port outside 1..65535")
            # Names are case-insensitive. Keep the first spelling for display.
            key = (host.casefold(), port)
            if key not in seen:
                servers.append(Server(host, port))
                seen.add(key)
    if not servers:
        raise ValueError("server CSV contains no candidates")
    return servers


def build_plan(
    candidates: list[Server], *, destinations: int, algorithms: list[str],
    duration_s: float, interval_s: float, repetitions: int, seed: int,
) -> dict:
    """Select destinations once and rotate algorithm order across repetitions.

    A plan makes no network requests and does not verify server availability.
    Algorithm labels are unrestricted so a future custom controller can reuse
    the runner. The Linux execution layer must verify their actual availability.
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
    # sample() chooses without replacement. Select once so every algorithm uses
    # the same destination set, as required for the A2 Q3(a) comparison.
    selected = rng.sample(candidates, destinations)
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
                    # Unique within this plan; the live runner also needs an
                    # experiment ID to distinguish separate executions of plans.
                    "run_id": f"run-{len(runs) + 1:04d}",
                    "destination_host": server.host,
                    "destination_port": server.port,
                    # A2 Q3 requires setting this before data-socket connect().
                    # The live runner must also record the algorithm actually used.
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
        # asdict() turns dataclass objects into JSON-serializable dictionaries.
        "selected_destinations": [asdict(server) for server in selected],
        "algorithms_requested": algorithms,
        # A planning estimate only: setup, retries, and cleanup add elapsed time.
        "active_transfer_seconds": len(runs) * duration_s,
        "runs": runs,
    }
