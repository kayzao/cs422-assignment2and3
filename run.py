#!/usr/bin/env python3
"""Offline tools; live experiments will be added after Linux verification."""

import argparse
import json
from pathlib import Path

from netlab.experiments import build_plan, load_servers


def main() -> None:
    # A2's report requires one entry point for the pipeline. Subcommands let us
    # add live transfers and analysis later while keeping offline planning usable.
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="print a schedule without contacting servers")
    # A2 Q1(b): accept server addresses/ports and a configurable destination count.
    plan.add_argument("--servers", type=Path, required=True)
    plan.add_argument("--destinations", type=int, default=10)
    # nargs="+" accepts multiple names, e.g. --algorithms cubic reno bbr (A2 Q3).
    # CUBIC alone is the initial choice for Q2; this planner does not select sockets.
    plan.add_argument("--algorithms", nargs="+", default=["cubic"])
    # A2 requires configurable duration, sampling interval, and repetitions.
    # These defaults are choices for our tool, not mandatory assignment values.
    plan.add_argument("--duration", type=float, default=60)
    plan.add_argument("--interval", type=float, default=0.2)
    plan.add_argument("--repetitions", type=int, default=3)
    # Saving a seed lets us reproduce the random destinations and initial order.
    plan.add_argument("--seed", type=int, default=422)
    args = parser.parse_args()
    try:
        # Keep file parsing and scheduling separate from the command-line layer
        # so a future Linux runner can reuse them without parsing CLI arguments.
        result = build_plan(
            load_servers(args.servers), destinations=args.destinations,
            algorithms=args.algorithms, duration_s=args.duration,
            interval_s=args.interval, repetitions=args.repetitions, seed=args.seed,
        )
    except (OSError, ValueError) as error:
        # Show invalid files/settings as CLI errors instead of Python tracebacks.
        parser.error(str(error))
    # Retain input provenance for reproduction. This JSON describes planned runs;
    # actual algorithms, failures, and measurements must be recorded during execution.
    result["server_list_file"] = str(args.servers)
    # Reject NaN/Infinity in JSON rather than producing a nonstandard manifest.
    print(json.dumps(result, indent=2, allow_nan=False))


if __name__ == "__main__":
    # Importing this module for reuse does not execute the command-line program.
    main()
