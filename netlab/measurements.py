"""Convert cumulative TCP counters into interval measurements.

This module is independent of Linux. The TCP_INFO sampler supplies
snapshots; the iperf3 client is responsible for the payload-phase baseline.
"""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class CounterSnapshot:
    # One reading from one data socket. frozen=True prevents accidental edits to
    # a saved baseline. tcp_info.py supplies live snapshots on linux.
    # elapsed_s must come from a monotonic clock relative to the run's start.
    elapsed_s: float
    # These totals accumulate over the connection; they are not interval rates.
    # A2 Q1(c) uses acknowledged bytes, not bytes accepted by Python's send().
    bytes_acked_total: int
    total_retrans_segments: int

    def __post_init__(self) -> None:
        # Reject bad inputs immediately so they do not contaminate plots/tables.
        if not math.isfinite(self.elapsed_s) or self.elapsed_s < 0:
            raise ValueError("elapsed_s must be finite and nonnegative")
        for name in ("bytes_acked_total", "total_retrans_segments"):
            value = getattr(self, name)
            # bool is a subclass of int in Python, but True is not a valid counter.
            if isinstance(value, bool) or not isinstance(value, int) or value < 0:
                raise ValueError(f"{name} must be a nonnegative integer")


@dataclass(frozen=True)
class IntervalMeasurement:
    # One output row covers the interval ending at elapsed_s. Unit suffixes make
    # later CSV logs and A2 Q2 plots unambiguous: seconds, bytes, bits/s, segments.
    elapsed_s: float
    sample_interval_actual_s: float
    bytes_acked_delta: int
    goodput_bps: float
    retrans_segments_delta: int


def measure_interval(
    previous: CounterSnapshot, current: CounterSnapshot
) -> IntervalMeasurement:
    """Measure one socket's counters using actual monotonic elapsed time.

    The first snapshot is a baseline, not a zero-throughput sample. Decreasing
    counters indicate a reset, rollover, or mismatched socket; require a new
    baseline rather than reporting a negative rate or silently clamping it.
    """
    # A2 Q1(c): use actual elapsed time. Scheduling delays mean that a requested
    # 0.2-second interval may not be exactly 0.2 seconds in a real experiment.
    dt = current.elapsed_s - previous.elapsed_s
    if dt <= 0:
        # Equal timestamps would divide by zero; reversed timestamps are invalid.
        raise ValueError("sample timestamps must strictly increase")
    # Subtract successive cumulative counters to isolate this interval's activity.
    acked = current.bytes_acked_total - previous.bytes_acked_total
    retrans = current.total_retrans_segments - previous.total_retrans_segments
    if acked < 0 or retrans < 0:
        # Never turn a reset/mismatched socket into a misleading negative rate.
        raise ValueError("counters decreased; start a new baseline")
    return IntervalMeasurement(
        elapsed_s=current.elapsed_s,
        sample_interval_actual_s=dt,
        bytes_acked_delta=acked,
        # Assignment formula: delta acknowledged bytes / delta seconds * 8.
        # Multiplying by 8 converts bytes to bits; bps means bits per second.
        goodput_bps=acked * 8 / dt,
        # A2 Q2's loss signal: retransmissions in this interval are a loss proxy,
        # not an exact count of unique original packet drops or a loss probability.
        retrans_segments_delta=retrans,
    )
