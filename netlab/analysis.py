"""Offline A2 Q1 tables, Q2 PDF figures, and measured observation notes."""

# tools for saved measurements, grouping samples, and calculating summary statistics
import csv
from collections import defaultdict
import json
import math
from pathlib import Path
import statistics


# columns for summary table, with extra rtt and time-weighted results
SUMMARY_FIELDS = [
    "destination_host", "destination_port", "algorithm_actual", "successful_runs",
    "interval_count", "minimum_goodput_bps", "median_goodput_bps", "mean_goodput_bps",
    "p95_goodput_bps", "time_weighted_mean_goodput_bps", "mean_rtt_us",
    "p95_rtt_us", "retrans_segments", "sampled_transfer_seconds",
]
# plot fields, labels, and scale conversions from raw units to readable axes
METRICS = [
    ("snd_cwnd_segments", "Congestion window (segments)", 1),
    ("rtt_us", "RTT (ms)", 0.001),
    ("retrans_segments_delta", "Retransmissions / interval", 1),
    ("goodput_bps", "Goodput (Mbit/s)", 1e-6),
]


# loads matplotlib with a backend that works without a desktop window
# called before experiments and plotting to support q2(b) pdf generation in ubuntu and docker
def ensure_plotting():
    # load plotting only when needed so the offline planner does not require matplotlib
    try:
        import matplotlib
        # headless operation works in ubuntu server and docker without a desktop.
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as error:
        raise RuntimeError("install the plotting dependency: python3 -m pip install -r requirements.txt") from error
    return plt


# finds a percentile by interpolating between sorted sample values
# called by summarize for q1(c)'s p95 table; the chosen method is also recorded in the report notes
def percentile(values: list[float], fraction: float) -> float:
    """Type-7 percentile: linearly interpolate at index (n - 1) * fraction."""
    # reject an empty dataset or invalid percentile before sorting and interpolating
    if not values or not 0 <= fraction <= 1:
        raise ValueError("percentile needs data and a fraction between 0 and 1")
    ordered = sorted(values)
    index = (len(ordered) - 1) * fraction
    low, high = math.floor(index), math.ceil(index)
    return ordered[low] + (ordered[high] - ordered[low]) * (index - low)


# calculates goodput and rtt statistics for one destination/algorithm group or one run
# called during analysis for q1(c) tables and the measured facts used in q2(c) notes
def summarize(rows: list[dict]) -> dict:
    # collect the interval values and actual durations for this destination/algorithm or run
    goodput = [row["goodput_bps"] for row in rows]
    rtt = [row["rtt_us"] for row in rows]
    elapsed = sum(row["sample_interval_actual_s"] for row in rows)
    # keep the required equal-weight statistics alongside a mean weighted by actual interval time
    return {
        "destination_host": rows[0]["destination_host"],
        "destination_port": rows[0]["destination_port"],
        "algorithm_actual": rows[0]["algorithm_actual"],
        "successful_runs": len({row["run_id"] for row in rows}), "interval_count": len(rows),
        "minimum_goodput_bps": min(goodput), "median_goodput_bps": statistics.median(goodput),
        "mean_goodput_bps": statistics.mean(goodput), "p95_goodput_bps": percentile(goodput, 0.95),
        "time_weighted_mean_goodput_bps": 8 * sum(row["bytes_acked_delta"] for row in rows) / elapsed,
        "mean_rtt_us": statistics.mean(rtt), "p95_rtt_us": percentile(rtt, 0.95),
        "retrans_segments": sum(row["retrans_segments_delta"] for row in rows),
        "sampled_transfer_seconds": elapsed,
    }


# writes a header and summary rows to a csv file
# called for pooled and per-run tables so q1(c) results can be used in the report
def write_table(path: Path, rows: list[dict], fields: list[str]) -> None:
    with path.open("w", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


# loads saved samples, keeps accepted transfer intervals, and checks their numeric values
# called before analysis so q1(c) and q2 results exclude incomplete runs and non-transfer phases
def load_samples(output: Path, manifest: dict) -> list[dict]:
    # use the manifest's accepted runs so failed or incomplete destination sets cannot enter plots
    accepted = {run["run_id"]: run for run in manifest["runs"]
                if run["status"] == "complete" and run.get("accepted")}
    # restore csv text, integer counters, and floating-point rates to their intended types
    text_fields = {"experiment_id", "run_id", "destination_host", "algorithm_requested",
                   "algorithm_actual", "timestamp_utc", "phase"}
    integer_fields = {"schema_version", "destination_port", "repetition", "snd_cwnd_segments",
                      "snd_mss_bytes", "rtt_us", "rttvar_us", "bytes_acked_total",
                      "bytes_acked_delta", "total_retrans_segments", "retrans_segments_delta",
                      "pacing_rate_Bps", "delivery_rate_Bps", "unacked_segments",
                      "notsent_bytes", "tcp_info_length"}
    # read active-transfer samples only; baseline and drain rows stay in the raw file
    rows = []
    with (output / "samples.csv").open(newline="") as handle:
        for source in csv.DictReader(handle):
            if source["run_id"] not in accepted or source["phase"] != "transfer":
                continue
            row = {key: value if key in text_fields else (
                       (int(value) if key in integer_fields else float(value)) if value else None)
                   for key, value in source.items()}
            # fail on corrupted logs rather than silently dropping inconvenient
            # zero-throughput intervals or producing plausible-looking graphs.
            for key in ("elapsed_s", "sample_interval_actual_s", "goodput_bps", "rtt_us",
                        "snd_cwnd_segments", "bytes_acked_delta", "retrans_segments_delta"):
                if row[key] is None or not math.isfinite(row[key]) or row[key] < 0:
                    raise ValueError(f"invalid {key} in run {row['run_id']}")
            if row["sample_interval_actual_s"] <= 0:
                raise ValueError("sampling intervals must be positive")
            # check the sampled algorithm against the recorded run before accepting the row
            record = accepted[row["run_id"]]
            if row["algorithm_actual"] != record["algorithm_actual"]:
                raise ValueError("sample algorithm disagrees with the run metadata")
            rows.append(row)
    return rows


# calculates pearson correlation, returning no value when a variable is constant
# called while writing observation notes as an optional aid for q2(c) interpretation
def correlation(xs, ys):
    # measure association around each variable's mean; constant values have no defined correlation
    mean_x, mean_y = statistics.mean(xs), statistics.mean(ys)
    dx, dy = [x - mean_x for x in xs], [y - mean_y for y in ys]
    denominator = math.sqrt(sum(x*x for x in dx) * sum(y*y for y in dy))
    return sum(x*y for x, y in zip(dx, dy)) / denominator if denominator else None


# builds notes explaining the metrics and describing the saved measurements
# called during analysis to provide a starting point for the student's q2(c) observations
def observation_notes(rows: list[dict], representative: dict, manifest: dict) -> str:
    # start with metric explanations, destination counts, and the analysis inclusion policy
    notes = [
        "# Measurement observations for Assignment 2",
        "",
        "These notes summarize saved measurements. Review the figures and add your",
        "interpretation of the particular paths, anomalies, and run-to-run variability.",
        "",
        f"Successful destinations: {len(manifest['successful_destinations'])} / {manifest['requested_destinations']}.",
        f"Destination shortfall: {manifest.get('destination_shortfall', 0)}.",
        "",
        "## What the metrics mean",
        "",
        "- Congestion window is the sender's allowed outstanding data, in segments.",
        "  An approximate window-limited rate is cwnd * MSS * 8 / RTT; receiver",
        "  windows, application limits, and path capacity can impose lower rates.",
        "- RTT includes propagation and queueing. Rising RTT can be consistent with",
        "  queue buildup, but Internet path changes and scheduling can also affect it.",
        "- Interval retransmissions are a loss proxy, not a packet-loss probability.",
        "  Recovery can reduce goodput. Zero retransmissions alone do not prove an",
        "  uncongested path; reordering and spurious retransmissions complicate interpretation.",
        "- Goodput is newly acknowledged application bytes * 8 / actual interval time.",
        "  It measures successful TCP delivery acknowledgments rather than send-buffer writes.",
        "- The bandwidth-delay product is bandwidth * RTT (in bytes after unit",
        "  conversion); enough in-flight data is needed to utilize a path.",
        "",
        "## Sample policy",
        "",
        "Tables and figures use active-transfer intervals from accepted, complete",
        "matched destination sets. Baselines, drain intervals, failed runs, and",
        "completed runs from incomplete destination sets remain in the raw logs",
        "but are excluded. Zero-goodput intervals and the final partial interval",
        "are retained. Arithmetic means and percentiles give every interval equal",
        "weight; a separate time-weighted goodput mean is also reported. Percentiles",
        "use linear interpolation at index (n-1)*p, also called type 7.",
        "",
    ]
    # report the lack of completed data rather than inventing observations or figures
    if not representative:
        notes += ["No destination completed a full matched set; no measured figures were generated."]
        return "\n".join(notes) + "\n"
    notes += ["## Representative destination", "",
              f"{representative['host']}:{representative['port']}; selected by the recorded",
              "first-completed-matched-set rule, before comparing performance.", ""]
    # restrict measured observations to the recorded representative destination and group by algorithm
    grouped = defaultdict(list)
    for row in rows:
        if (row["destination_host"] == representative["host"] and
                row["destination_port"] == representative["port"]):
            grouped[row["algorithm_actual"]].append(row)
    # describe measured ranges, zero-goodput intervals, and retransmissions for q2(c)
    for algorithm, group in sorted(grouped.items()):
        summary = summarize(group)
        cwnd = [row["snd_cwnd_segments"] for row in group]
        rtt = [row["rtt_us"] / 1000 for row in group]
        goodput = [row["goodput_bps"] for row in group]
        zero_count = sum(value == 0 for value in goodput)
        notes += [f"### {algorithm}", "",
                  f"- Runs: {summary['successful_runs']}; intervals: {len(group)}.",
                  f"- Mean goodput: {summary['mean_goodput_bps']/1e6:.3f} Mbit/s; "
                  f"p95: {summary['p95_goodput_bps']/1e6:.3f} Mbit/s.",
                  f"- Sampled cwnd range: {min(cwnd):g}–{max(cwnd):g} segments.",
                  f"- Sampled RTT range: {min(rtt):.3f}–{max(rtt):.3f} ms.",
                  f"- Retransmissions during active samples: {summary['retrans_segments']:g}; "
                  f"zero-goodput intervals: {zero_count}."]
        # add optional correlations as descriptive evidence for reviewing the scatter plots
        for key, label, _ in METRICS[:3]:
            value = correlation([row[key] for row in group], goodput)
            description = "undefined (a variable is constant)" if value is None else f"{value:.3f}"
            notes.append(f"- Pearson correlation, {label} vs goodput: {description}.")
        notes += ["", "Correlations describe association. Explain any visible recovery episodes,",
                  "RTT changes, startup effects, and variation between repetitions using",
                  "the actual time series; these data alone do not identify their cause.", ""]
    return "\n".join(notes) + "\n"


# reads saved data and generates tables, observation notes, and all required pdf plots
# called after live execution or by run.py analyze; provides q1(c) and q2(b) outputs offline
def analyze_results(output: Path) -> dict:
    # read the saved configuration and measurements without opening any network connection
    manifest = json.loads((output / "manifest.json").read_text())
    rows = load_samples(output, manifest)
    # group by destination/algorithm for pooled tables and by run id to preserve repetitions
    by_endpoint = defaultdict(list)
    by_run = defaultdict(list)
    for row in rows:
        by_endpoint[(row["destination_host"], row["destination_port"], row["algorithm_actual"])].append(row)
        by_run[row["run_id"]].append(row)
    # write q1(c) tables and q2(c) starting notes before making the figures
    summaries = [summarize(group) for _, group in sorted(by_endpoint.items())]
    run_summaries = [{"run_id": key, **summarize(group)} for key, group in sorted(by_run.items())]
    write_table(output / "summary.csv", summaries, SUMMARY_FIELDS)
    write_table(output / "per_run_summary.csv", run_summaries, ["run_id"] + SUMMARY_FIELDS)
    representative = manifest.get("representative_destination")
    (output / "observations.md").write_text(observation_notes(rows, representative, manifest))
    # prepare the plot directory; no accepted samples means there are no measured plots to generate
    plots = output / "plots"
    plots.mkdir(exist_ok=True)
    if not rows:
        return {"accepted_runs": 0, "plots": []}
    plt = ensure_plotting()
    files = []

    # saves one pdf, closes its figure, and records the output filename
    # called for each q1(c) and q2(b) figure to keep output handling consistent
    def save(fig, name):
        fig.savefig(plots / name, format="pdf", bbox_inches="tight",
                    metadata={"Title": name.removesuffix(".pdf"), "Creator": "netlab"})
        plt.close(fig)
        files.append("plots/" + name)

    # make q1(c)'s goodput-over-time figure for every accepted destination
    destinations = sorted({(row["destination_host"], row["destination_port"]) for row in rows})
    for index, endpoint in enumerate(destinations, 1):
        fig, ax = plt.subplots(figsize=(9, 4), layout="constrained")
        # draw each repetition as its own trace instead of joining different runs into one timeline
        for run_id, group in sorted(by_run.items()):
            if (group[0]["destination_host"], group[0]["destination_port"]) != endpoint:
                continue
            group = sorted(group, key=lambda row: row["elapsed_s"])
            ax.plot([row["elapsed_s"] for row in group], [row["goodput_bps"]/1e6 for row in group],
                    label=f"{group[0]['algorithm_actual']} rep {int(group[0]['repetition'])}", alpha=0.8)
        ax.set(title=f"Goodput — {endpoint[0]}:{endpoint[1]}", xlabel="Elapsed time (s)", ylabel="Goodput (Mbit/s)")
        ax.grid(alpha=0.25)
        ax.set_xlim(left=0)
        ax.set_ylim(bottom=0)
        ax.legend(fontsize=8)
        save(fig, f"goodput-destination-{index:03d}.pdf")

    # select the same representative destination for all q2 figures and later q3 comparisons
    rep_runs = {key: group for key, group in by_run.items()
                if representative and group[0]["destination_host"] == representative["host"]
                and group[0]["destination_port"] == representative["port"]}
    algorithms = sorted({group[0]["algorithm_actual"] for group in rep_runs.values()})
    # create four time-series rows and three scatter rows, sharing scales across algorithms
    if algorithms:
        title = f"Representative destination: {representative['host']}:{representative['port']}"
        fig, axes = plt.subplots(4, len(algorithms), squeeze=False, figsize=(5*len(algorithms), 11),
                                 sharex=True, sharey="row", layout="constrained")
        scatter, scatter_axes = plt.subplots(3, len(algorithms), squeeze=False,
                                            figsize=(5*len(algorithms), 9), sharex="row",
                                            sharey="row", layout="constrained")
        fig.suptitle(title)
        scatter.suptitle(title)
        # give each algorithm a column and each repetition a separately labeled trace or point set
        for column, algorithm in enumerate(algorithms):
            for run_id, group in sorted(rep_runs.items()):
                if group[0]["algorithm_actual"] != algorithm:
                    continue
                group = sorted(group, key=lambda row: row["elapsed_s"])
                label = f"rep {int(group[0]['repetition'])}"
                # plot cwnd, rtt, interval retransmissions, and goodput against elapsed time for q2(b)(i)
                for row_index, (key, ylabel, scale) in enumerate(METRICS):
                    ax = axes[row_index, column]
                    ax.plot([row["elapsed_s"] for row in group], [row[key]*scale for row in group],
                            label=label, alpha=0.8)
                    ax.set(ylabel=ylabel, title=algorithm if row_index == 0 else None)
                    ax.grid(alpha=0.25)
                    if row_index == 3:
                        ax.set_xlabel("Elapsed time (s)")
                # plot cwnd, rtt, and the loss proxy against goodput for q2(b)(ii)
                for row_index, (key, xlabel, scale) in enumerate(METRICS[:3]):
                    ax = scatter_axes[row_index, column]
                    ax.scatter([row[key]*scale for row in group], [row["goodput_bps"]/1e6 for row in group],
                               label=label, alpha=0.6, s=12)
                    ax.set(xlabel=xlabel, ylabel="Goodput (Mbit/s)",
                           title=algorithm if row_index == 0 else None)
                    ax.grid(alpha=0.25)
            axes[0, column].legend(fontsize=8)
            scatter_axes[0, column].legend(fontsize=8)
        # all recorded metrics are nonnegative. give an all-zero loss signal a
        # 0..1 axis instead of matplotlib's default negative fractional counts.
        from matplotlib.ticker import MaxNLocator
        for row_index, (key, _, scale) in enumerate(METRICS):
            maximum = max(row[key] * scale for group in rep_runs.values() for row in group)
            axes[row_index, 0].set_ylim(0, maximum * 1.05 if maximum else 1)
            axes[row_index, 0].set_xlim(left=0)
            if row_index in (0, 2):
                axes[row_index, 0].yaxis.set_major_locator(MaxNLocator(integer=True))
        for row_index, (key, _, scale) in enumerate(METRICS[:3]):
            maximum = max(row[key] * scale for group in rep_runs.values() for row in group)
            scatter_axes[row_index, 0].set_xlim(0, maximum * 1.05 if maximum else 1)
            scatter_axes[row_index, 0].set_ylim(bottom=0)
            if row_index in (0, 2):
                scatter_axes[row_index, 0].xaxis.set_major_locator(MaxNLocator(integer=True))
        # save the seven required panels in two pdfs, alongside the per-destination goodput figures
        save(fig, "representative-timeseries.pdf")
        save(scatter, "representative-scatter.pdf")
    # return a small output summary for run.py analyze to print
    return {"accepted_runs": len(by_run), "plots": files}
