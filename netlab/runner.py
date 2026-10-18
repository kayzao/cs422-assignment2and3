"""Destination replacement, matched repetitions, and persistent experiment logs."""

# tools for raw logs, input hashes, dependency versions, random selection, and saved files
import csv
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import random
import shutil
import subprocess
import time
import uuid

# combine the existing planner, environment check, and single-transfer implementation
from .experiments import Server, build_plan, load_servers
from .tcp_info import check_environment
from .transfer import SAMPLE_FIELDS, TransferError, run_transfer, utc_now
from .validation import validation_report


# writes a complete json file through a temporary file, then replaces the previous copy
# used for manifest and run updates so the report's saved configuration survives interrupted writes
def save_json(path: Path, value: dict) -> None:
    # replace atomically so an interrupted update leaves the previous manifest.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(value, indent=2, allow_nan=False) + "\n")
    temporary.replace(path)


# records the git commit and whether local source edits are present
# called when creating the manifest to support the report's reproduction instructions
def source_revision(root: Path) -> dict:
    # read the source revision without recording a local username or directory
    try:
        commit = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=root,
                                         stderr=subprocess.DEVNULL, text=True).strip()
        dirty = bool(subprocess.check_output(["git", "status", "--porcelain"], cwd=root,
                                             stderr=subprocess.DEVNULL, text=True))
        return {"commit": commit, "working_tree_dirty": dirty}
    except (OSError, subprocess.CalledProcessError):
        # the docker image omits .git; pass the source commit at image build time.
        return {"commit": os.environ.get("NETLAB_SOURCE_COMMIT", "unknown"),
                "working_tree_dirty": None}


# runs the configured destination sets, saves raw data, then generates analysis outputs
# called by run.py run; coordinates q1(b), q1(c), q2, and later q3(a) comparisons
def run_experiment(args, root: Path) -> tuple[Path, bool]:
    # load the analysis helpers only when the full pipeline is requested
    from .analysis import analyze_results, ensure_plotting

    # fail before contacting servers if analysis dependencies or linux facilities
    # are absent. never silently substitute a different congestion algorithm.
    ensure_plotting()
    candidates = load_servers(args.servers)
    plan = build_plan(candidates, destinations=args.destinations, algorithms=args.algorithms,
                      duration_s=args.duration, interval_s=args.interval,
                      repetitions=args.repetitions, seed=args.seed)
    environment = check_environment(args.algorithms, root)
    # create a new output directory and copy the exact input list for reproduction
    experiment_id = "experiment-" + uuid.uuid4().hex[:12]
    output = args.output or Path("results") / experiment_id
    output.mkdir(parents=True, exist_ok=False)
    (output / "runs").mkdir()
    shutil.copyfile(args.servers, output / "servers.csv")

    # keep the planner's first draw, then use a seeded reserve for replacements.
    # one range is one candidate; choose a concrete port only once per candidate.
    endpoints = [Server(item["host"], item["port"]) for item in plan["selected_destinations"]]
    selected_hosts = {server.host.casefold() for server in endpoints}
    reserve = [server for server in candidates if server.host.casefold() not in selected_hosts]
    rng = random.Random(args.seed + 1)
    rng.shuffle(reserve)
    endpoints += [Server(s.host, rng.randint(s.port, s.port_end or s.port)) for s in reserve]
    # take one destination's algorithm/repetition order as the template for every candidate
    first = plan["selected_destinations"][0]
    # reuse the recorded repetition/algorithm ordering for every destination.
    template = [run for run in plan["runs"]
                if run["destination_host"] == first["host"] and run["destination_port"] == first["port"]]
    # save configuration, software versions, input identity, selection rules, and actual run outcomes
    manifest = {
        "schema_version": 1, "experiment_id": experiment_id, "status": "running",
        "started_utc": utc_now(), "source": source_revision(root), "environment": environment,
        "python_packages": {package.metadata["Name"]: package.version
                            for package in metadata.distributions() if package.metadata["Name"]},
        "config": {"destinations": args.destinations, "algorithms": args.algorithms,
                   "duration_s": args.duration, "interval_s": args.interval,
                   "repetitions": args.repetitions, "seed": args.seed,
                   "max_attempts": args.max_attempts, "timeout_s": args.timeout,
                   "drain_timeout_s": args.drain_timeout, "stall_timeout_s": args.stall_timeout,
                   "result_timeout_s": getattr(args, "result_timeout", 15),
                   "pause_s": args.pause, "backoff_s": args.backoff},
        # store input provenance without exporting a developer's home directory.
        "server_list": {"name": args.servers.name,
                        "sha256": hashlib.sha256(args.servers.read_bytes()).hexdigest(),
                        "saved_copy": "servers.csv", "source": "https://iperf3serverlist.net/"},
        "sample_policy": {"summary_phase": "transfer", "exclude_baseline_and_drain": True,
                          "exclude_unaccepted_destination_sets": True,
                          "percentile_method": "linear interpolation, index=(n-1)*p (type 7)"},
        "requested_destinations": args.destinations, "successful_destinations": [],
        "representative_destination": None, "representative_selection": "first completed matched destination set",
        "attempts": [], "runs": [],
    }
    # save the initial manifest before any network attempt begins
    save_json(output / "manifest.json", manifest)
    interrupted = False
    # open raw sample, protocol-event, and destination-attempt logs for q1(b) and q2(a)
    try:
        with (output / "samples.csv").open("w", newline="") as samples_file, \
                (output / "events.jsonl").open("w") as events_file, \
                (output / "attempts.jsonl").open("w") as attempts_file:
            writer = csv.DictWriter(samples_file, fieldnames=SAMPLE_FIELDS)
            writer.writeheader()

            # writes each received sample row immediately and flushes the file
            # passed into run_transfer so q2(a) raw measurements remain available after a failed test
            def sample(row):
                writer.writerow(row)
                samples_file.flush()

            # appends one event as a json line and flushes it immediately
            # used by the per-run event helper to preserve q1(a) protocol progress and failures
            def log_event(row):
                events_file.write(json.dumps(row, allow_nan=False) + "\n")
                events_file.flush()

            # try the requested destinations and seeded replacements within the configured attempt limit
            for attempt_number, server in enumerate(endpoints[:args.max_attempts], 1):
                # stop once enough full destination sets have completed
                if len(manifest["successful_destinations"]) == args.destinations:
                    break
                # record the attempt before its first transfer so a later failure still has context
                endpoint = {"host": server.host, "port": server.port}
                attempt = {"attempt": attempt_number, **endpoint, "started_utc": utc_now(),
                           "status": "running", "run_ids": []}
                attempts_file.write(json.dumps({"event": "attempt_started", **attempt}) + "\n")
                attempts_file.flush()
                records = []
                manifest["attempts"].append(attempt)
                # give every planned algorithm/repetition pair its own run id and initial status
                for scheduled in template:
                    run = {"experiment_id": experiment_id,
                           "run_id": f"run-{len(manifest['runs']) + 1:04d}",
                           "destination_host": server.host, "destination_port": server.port,
                           "algorithm_requested": scheduled["algorithm_requested"],
                           "repetition": scheduled["repetition"]}
                    record = {**run, "status": "running", "accepted": False}
                    manifest["runs"].append(record)
                    records.append(record)
                    attempt["run_ids"].append(run["run_id"])
                    save_json(output / "manifest.json", manifest)
                    print(f"{run['run_id']}: {server.host}:{server.port} "
                          f"{run['algorithm_requested']} repetition {run['repetition']}", flush=True)

                    # adds the experiment and run ids to each timestamped transfer event
                    # passed into run_transfer so q1(a) failure logs identify the exact attempted run
                    def event(row):
                        log_event({"experiment_id": experiment_id, "run_id": run["run_id"], **row})

                    # run one transfer and preserve either its successful result or its failure details
                    try:
                        result = run_transfer(run, args.duration, args.interval, args.timeout,
                                              args.drain_timeout, args.stall_timeout, sample, event,
                                              result_timeout_s=getattr(args, "result_timeout", 15))
                        record.update(result, status="complete")
                        # show q1(a) accounting warnings immediately instead of hiding them in run json
                        for warning in result.get("warnings", []):
                            print(f"  warning: {warning}", flush=True)
                    except TransferError as error:
                        record.update(error.result, status="failed")
                        attempt.update(status="failed", error=str(error), failure_stage=error.stage)
                        print(f"  failed: {error}", flush=True)
                        # q1(a) diagnostics show whether a timeout left queued payload or only control work
                        if record.get("result_exchange_step"):
                            print(f"  result step: {record['result_exchange_step']}", flush=True)
                        snapshot = record.get("last_payload_snapshot")
                        if snapshot:
                            print(f"  pending payload: {record['pending_payload_bytes']} bytes; "
                                  f"not yet sent: {snapshot['notsent_bytes']} bytes; "
                                  f"unacknowledged: {snapshot['unacked_segments']} segments", flush=True)
                    # save each outcome immediately, and stop this candidate's set after any failed run
                    save_json(output / "runs" / (run["run_id"] + ".json"), record)
                    save_json(output / "manifest.json", manifest)
                    if record["status"] != "complete":
                        break
                    if args.pause:
                        time.sleep(args.pause)

                # accept a destination only after all configured repetitions and algorithms succeed
                if all(record["status"] == "complete" for record in records):
                    attempt["status"] = "complete"
                    for record in records:
                        record["accepted"] = True
                        save_json(output / "runs" / (record["run_id"] + ".json"), record)
                    manifest["successful_destinations"].append(endpoint)
                    # choose q2's representative by completion order rather than by attractive-looking results
                    if manifest["representative_destination"] is None:
                        manifest["representative_destination"] = endpoint
                else:
                    # if any comparison run fails, keep its data but replace the
                    # whole destination set. this preserves matched comparisons.
                    for record in records:
                        record["exclusion_reason"] = "incomplete matched destination set"
                        save_json(output / "runs" / (record["run_id"] + ".json"), record)
                # finish the attempt log, update the manifest, and apply a pause before a replacement
                attempt["finished_utc"] = utc_now()
                attempts_file.write(json.dumps({"event": "attempt_finished", **attempt}) + "\n")
                attempts_file.flush()
                save_json(output / "manifest.json", manifest)
                if attempt["status"] == "failed" and args.backoff:
                    time.sleep(args.backoff)
    # preserve an interrupted experiment and let offline analysis use any already accepted sets
    except KeyboardInterrupt:
        interrupted = True
        manifest["status"] = "interrupted"
    # mark unexpected failures before passing the error back to the command-line layer
    except Exception:
        manifest["status"] = "failed"
        raise
    # finish outstanding records and report q1(b)'s requested-versus-successful destination shortfall
    finally:
        manifest["finished_utc"] = utc_now()
        for record in manifest["runs"]:
            if record["status"] == "running":
                record.update(status=manifest["status"], finished_utc=manifest["finished_utc"],
                              exclusion_reason="execution stopped before completion")
                save_json(output / "runs" / (record["run_id"] + ".json"), record)
        for attempt in manifest["attempts"]:
            if attempt["status"] == "running":
                attempt.update(status=manifest["status"], finished_utc=manifest["finished_utc"])
                with (output / "attempts.jsonl").open("a") as handle:
                    handle.write(json.dumps({"event": "attempt_finished", **attempt}) + "\n")
        manifest["destination_shortfall"] = args.destinations - len(manifest["successful_destinations"])
        if manifest["status"] == "running":
            manifest["status"] = "complete" if not manifest["destination_shortfall"] else "shortfall"
        save_json(output / "manifest.json", manifest)

    # analysis reads only persisted measurements, so it is repeatable offline.
    analyze_results(output)
    # make q1(a/b) review requirements visible even when the destination count is complete
    quality = validation_report(manifest)
    print(f"Validation: {quality['status']}; {quality['byte_count_warnings']} byte-count warnings; "
          f"{len(quality['failed_runs'])} failed runs. See {output / 'validation.json'}", flush=True)
    # tell run.py where results are saved and whether it should return an incomplete status
    return output, bool(manifest["destination_shortfall"] or interrupted)
