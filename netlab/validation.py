"""Byte-accounting checks and a reviewable record of experiment shortfalls."""

# use the negotiated iperf block size when distinguishing an incomplete final read
from collections import Counter
import math

PAYLOAD_BLOCK_SIZE = 131072


# compares the sender's payload total with the receiver's application-level count
# used after q1(a) result exchange and during offline analysis of existing experiments
# iperf_tcp.c counts returned reads; net.c may wait for a complete negotiated block
# kernel acknowledgments alone do not prove the receiver application counted the last read
def assess_byte_count(sent: int, received) -> dict:
    check = {"sender_bytes": sent, "server_bytes": None,
             "block_size_bytes": PAYLOAD_BLOCK_SIZE, "status": "mismatch"}
    # reject malformed counts instead of accepting any positive json value
    if (isinstance(received, bool) or not isinstance(received, (int, float))
            or (isinstance(received, float) and
                (not math.isfinite(received) or not received.is_integer()))
            or received <= 0):
        return {**check, "reason": "server byte count must be a positive whole number"}
    received = int(received)
    missing = sent - received
    check.update(server_bytes=received, missing_bytes=missing)
    if missing == 0:
        return {**check, "status": "exact", "reason": "sender and server byte counts agree"}
    # allow only the observed final-block pattern, not an arbitrary percentage tolerance
    # retain it as a visible warning rather than claiming exact application-level delivery
    if (0 < missing < PAYLOAD_BLOCK_SIZE
            and received == sent // PAYLOAD_BLOCK_SIZE * PAYLOAD_BLOCK_SIZE):
        return {**check, "status": "partial_block", "reason":
                f"server reported {missing} fewer bytes, ending at a complete "
                f"{PAYLOAD_BLOCK_SIZE}-byte block; final-block accounting needs review"}
    return {**check, "reason":
            f"server reported {received} bytes for {sent} sent; discrepancy is not a final partial block"}


# summarizes accepted byte checks, failed stages, and excluded runs without changing raw data
# called by analysis.py for q1(a/b) failure evidence and the report's measurement limitations
# older manifests are rechecked too, even if they only recorded a boolean byte-count match
def validation_report(manifest: dict) -> dict:
    runs = manifest.get("runs", [])
    checks, failed, excluded = [], [], []
    for run in runs:
        if run.get("status") == "failed":
            failed.append({"run_id": run["run_id"],
                           "stage": run.get("failure_stage", "unknown"),
                           "step": run.get("result_exchange_step"),
                           "error": run.get("error"),
                           "payload_bytes_sent": run.get("payload_bytes_sent"),
                           "payload_bytes_acked": run.get("payload_bytes_acked"),
                           "drain_duration_s": run.get("drain_duration_s"),
                           "pending_payload_bytes": run.get("pending_payload_bytes"),
                           "last_payload_snapshot": run.get("last_payload_snapshot")})
        if run.get("status") != "complete":
            continue
        if not run.get("accepted"):
            excluded.append(run["run_id"])
            continue
        sent, received = run.get("payload_bytes_sent"), run.get("server_payload_bytes_received")
        if isinstance(sent, int) and not isinstance(sent, bool) and sent > 0:
            check = assess_byte_count(sent, received)
        else:
            check = {"status": "unavailable", "reason": "saved run lacks sender byte totals"}
        checks.append({"run_id": run["run_id"], **check})
    # keep protocol completion distinct from clean accounting; warnings never disappear in a pooled mean
    warnings = sum(item["status"] == "partial_block" for item in checks)
    errors = sum(item["status"] == "mismatch" for item in checks)
    unavailable = sum(item["status"] == "unavailable" for item in checks)
    shortfall = manifest.get("destination_shortfall", 0)
    return {"schema_version": 1,
            "status": "review_required" if not checks or warnings or errors or unavailable or failed or shortfall else "ok",
            "accepted_runs": len(checks), "byte_count_warnings": warnings,
            "byte_count_errors": errors, "byte_count_unavailable": unavailable,
            "byte_count_checks": checks, "failed_runs": failed,
            "failure_counts_by_stage": dict(Counter(item["stage"] for item in failed)),
            "completed_but_excluded_runs": excluded, "destination_shortfall": shortfall,
            "selection_note": "summaries include only complete matched destination sets; "
                              "timeouts and replacements can favor destinations that finish reliably"}
