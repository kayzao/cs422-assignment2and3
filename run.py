#!/usr/bin/env python3
"""Plan experiments, check Linux, run iperf3 uploads, and analyze saved data."""

# Standard-library tools handle CLI arguments, input hashes, JSON output,
# numeric validation, and file paths.
import argparse
import hashlib
import json
import math
from pathlib import Path

# Reuse the planner and CSV reader
from netlab.experiments import build_plan, load_servers

# allows commands when launched from another directory.
ROOT = Path(__file__).resolve().parent

# This entry point reads CLI options, calls the appropriate module, and returns
# an exit status that the shell or Docker can use to detect success or failure.
def main() -> int:
    # Define the four commands. Requiring a subcommand makes the user's intended
    # action explicit: plan, check Linux, run experiments, or analyze saved data.
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    plan = commands.add_parser("plan", help="print a schedule without contacting servers")
    live = commands.add_parser("run", help="run transfers and generate tables and PDF plots (Linux)")
    check = commands.add_parser("check", help="verify Linux socket algorithms and TCP_INFO layout")
    analyze = commands.add_parser("analyze", help="regenerate tables and figures offline")

    # Give the check command its algorithm list and the analysis command the
    # location of existing results. Neither needs the transfer's other options.
    check.add_argument("--algorithms", nargs="+", default=["cubic", "reno", "bbr"])
    analyze.add_argument("--results", type=Path, required=True)

    # Register shared experiment options once so plan and run accept the same
    # settings. These provide A2's configurable destinations, timing, and repeats.
    for command in (plan, live):
        # Use the bundled server list by default, with an optional replacement CSV
        # and destination count for A2 Q1(b).
        command.add_argument("--servers", type=Path, default=ROOT / "configs" / "listed_iperf3_servers.csv")
        command.add_argument("--destinations", type=int, default=10)

        # Default to CUBIC for Q2; nargs="+" also accepts several algorithm names
        # so Q3 can use the same pipeline for CUBIC, Reno, and BBR.
        command.add_argument("--algorithms", nargs="+", default=["cubic"])

        # Control each transfer's duration, the requested sampling interval, and
        # how often tests repeat. The seed makes random planning reproducible.
        command.add_argument("--duration", type=float, default=60)
        command.add_argument("--interval", type=float, default=0.2)
        command.add_argument("--repetitions", type=int, default=3)
        command.add_argument("--seed", type=int, default=422)

    # Live execution needs an output directory and a limit on replacement
    # candidates. The runner handles saving files and avoiding overwrites.
    live.add_argument("--output", type=Path, help="new result directory; existing directories are never overwritten")
    live.add_argument("--max-attempts", type=int, help="maximum candidate destination sets (default: 3 * destinations)")

    # Bound connection/control waits, the wait for remaining payload ACKs after
    # sending stops, and the time allowed without acknowledged-payload progress.
    live.add_argument("--timeout", type=float, default=8, help="connection/control operation timeout in seconds")
    live.add_argument("--drain-timeout", type=float, default=30, help="maximum time to wait for queued payload ACKs")
    # allow the receiver's final read to finish without lengthening connection attempts
    live.add_argument("--result-timeout", type=float, default=15, help="timeout for each final result/termination operation")
    live.add_argument("--stall-timeout", type=float, default=15, help="maximum time without acknowledged-payload progress")

    # Space out successful transfers and failed destination attempts instead of
    # immediately starting every subsequent connection.
    live.add_argument("--pause", type=float, default=1, help="seconds between completed transfers")
    live.add_argument("--backoff", type=float, default=1, help="seconds before a replacement destination")

    args = parser.parse_args()

    # Dispatch to the chosen module and turn common file, configuration, or
    # execution errors into readable CLI messages in the except block below.
    try:
        # if plan, read the CSV and build a schedule without contacting any server.
        if args.command == "plan":
            result = build_plan(
                load_servers(args.servers), destinations=args.destinations,
                algorithms=args.algorithms, duration_s=args.duration,
                interval_s=args.interval, repetitions=args.repetitions, seed=args.seed,
            )

            # Record which input was used. Its name and content hash support
            # reproduction without publishing an account's absolute home path.
            result["server_list_file"] = args.servers.name
            result["server_list_sha256"] = hashlib.sha256(args.servers.read_bytes()).hexdigest()

            print(json.dumps(result, indent=2, allow_nan=False))

        # if check, verify Linux socket algorithm selection and TCP_INFO offsets
        # before collecting measurements. Load this helper only when requested.
        elif args.command == "check":
            from netlab.tcp_info import check_environment

            # Require an algorithm to check, then print the verified environment
            # and decoder layout as JSON for inspection.
            if not args.algorithms:
                raise ValueError("specify at least one algorithm")
            print(json.dumps(check_environment(args.algorithms, ROOT), indent=2, allow_nan=False))

        # if analyze, regenerate tables, plots, and observation notes from saved
        # measurements. This command can run offline, including on macOS.
        elif args.command == "analyze":
            from netlab.analysis import analyze_results
            print(json.dumps(analyze_results(args.results), indent=2, allow_nan=False))

        # if run, the required subcommand must now be run. Delegate actual transfers,
        # sampling, replacement servers, logging, and analysis to the runner.
        else:
            from netlab.runner import run_experiment

            # Reject invalid wait settings before execution. Timeouts must be
            # positive and finite; optional pauses/backoff may also be zero.
            for name in ("timeout", "drain_timeout", "result_timeout", "stall_timeout", "pause", "backoff"):
                value = getattr(args, name)
                if not math.isfinite(value) or value < 0 or (name not in ("pause", "backoff") and value == 0):
                    raise ValueError(f"{name.replace('_', '-')} must be finite and "
                                     + ("nonnegative" if name in ("pause", "backoff") else "positive"))

            # Set a bounded default candidate budget for A2's replacement policy.
            # It must at least allow one attempt per requested destination.
            if args.max_attempts is None:
                args.max_attempts = 3 * args.destinations
            if args.max_attempts < args.destinations:
                raise ValueError("max-attempts must be at least destinations")

            # Execute the full pipeline and tell the user where its files were
            # saved. The runner reports whether the requested dataset is complete.
            output, incomplete = run_experiment(args, ROOT)
            print(f"Results: {output}")

            # Return status 1 for a shortfall or interruption so scripts and Docker
            # can distinguish incomplete experiments from successful ones.
            if incomplete:
                print("Some requested destination sets did not complete; see manifest.json and attempts.jsonl.")
                return 1

    # argparse prints a concise error and exits with status 2 for these common
    # failures, rather than displaying an internal Python traceback.
    except (OSError, ValueError, RuntimeError, KeyError) as error:
        parser.error(str(error))

    # Status 0 tells the caller that the selected command finished successfully.
    return 0


# Run the CLI only when this file is executed directly. Importing it leaves main()
# uncalled; SystemExit passes main's return status back to the shell or Docker.
if __name__ == "__main__":
    raise SystemExit(main())
