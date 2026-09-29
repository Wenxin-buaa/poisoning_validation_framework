#!/usr/bin/env python3
"""Report baseline_2 stepwise results and four-way outcome ratios.

The source experiment directory is treated as the eligibility authority:
only variants whose top-level variant.json has status ``coordinated_success``
are included. Each matching ``<source-experiment>_baseline_2_*`` evaluation
directory is reported separately, because the suffix normally identifies a
target model.

The report emphasizes the four combinations of step verdicts:
``success/success``, ``success/failure``, ``failure/success``, and
``failure/failure``.

Examples:
    python3.11 stat_baseline2_stepwise_results.py --experiment exp_001
    python3.11 stat_baseline2_stepwise_results.py --experiment exp_001 --pair pair_001 --pair pair_002
    python3.11 stat_baseline2_stepwise_results.py --experiment exp_002 \
        --format tsv --output baseline2_stepwise.tsv
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
RUNS_ROOT = FRAMEWORK_ROOT / "benchmarks" / "runs"
SOURCE_EXPERIMENT_RE = re.compile(r"^pair_.+_exp_\d+$")
LOOP_RE = re.compile(r"loop_(\d+)$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def matches_pattern(name: str, patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(name, pattern)
        or fnmatch.fnmatchcase(name, f"*_{pattern}")
        for pattern in patterns
    )


def source_experiments(patterns: list[str], pairs: set[str] | None = None) -> list[Path]:
    result = []
    for path in RUNS_ROOT.glob("pair_*/experiments/*"):
        if not path.is_dir() or not SOURCE_EXPERIMENT_RE.fullmatch(path.name):
            continue
        pair_id = path.parent.parent.name
        if pairs is not None and pair_id not in pairs:
            continue
        if matches_pattern(path.name, patterns):
            result.append(path)
    return sorted(result, key=lambda p: (p.parent.parent.name, p.name))


def baseline2_experiments(source_experiment: Path) -> list[Path]:
    experiments_dir = source_experiment.parent
    prefix = f"{source_experiment.name}_baseline_2_"
    return sorted(
        path
        for path in experiments_dir.iterdir()
        if path.is_dir() and path.name.startswith(prefix)
    )


def final_verdict_paths(variant_dir: Path) -> list[tuple[int, Path]]:
    paths = []
    for path in variant_dir.glob("coordinated/loop_*/session/verdict.json"):
        match = LOOP_RE.fullmatch(path.parent.parent.name)
        if match:
            paths.append((int(match.group(1)), path))
    return sorted(paths)


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")
    return ""


def failure_details(step: dict[str, Any]) -> tuple[str, str, str, str]:
    failure_analysis = step.get("failure_analysis")
    if not isinstance(failure_analysis, dict):
        failure_analysis = {}
    diagnostics = step.get("failure_diagnostics")
    if not isinstance(diagnostics, dict):
        diagnostics = {}

    reason = first_text(step.get("reason"), step.get("error"), diagnostics.get("reason"))
    primary = first_text(
        failure_analysis.get("primary_failure_label"),
        diagnostics.get("primary_failure_label"),
    )
    secondary_value = failure_analysis.get("secondary_failure_labels")
    if isinstance(secondary_value, list):
        secondary = ", ".join(str(item) for item in secondary_value if str(item).strip())
    else:
        secondary = first_text(secondary_value)

    summary_parts: list[str] = []
    root_cause = first_text(failure_analysis.get("root_cause"), diagnostics.get("root_cause"))
    if root_cause:
        summary_parts.append(f"root_cause: {root_cause}")
    notes = diagnostics.get("notes")
    if isinstance(notes, list):
        note_text = ", ".join(str(item) for item in notes if str(item).strip())
        if note_text:
            summary_parts.append(f"notes: {note_text}")
    missing = diagnostics.get("missing_trace_template_channels")
    if isinstance(missing, list) and missing:
        summary_parts.append("missing_channels: " + ", ".join(map(str, missing)))
    coordination_failures = diagnostics.get("coordination_failures")
    if isinstance(coordination_failures, list) and coordination_failures:
        summary_parts.append("coordination_failures: " + ", ".join(map(str, coordination_failures)))
    if not summary_parts:
        summary_parts.append(first_text(step.get("feedback"), step.get("evidence")))
    return reason, primary, secondary, "; ".join(part for part in summary_parts if part)


def combination(step_1: str, step_2: str) -> str:
    return f"{step_1}/{step_2}"


def ratio(count: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.00%)"
    return f"{count}/{total} ({(count / total) * 100:.2f}%)"


def base_row(source_dir: Path, baseline_dir: Path, model: str, variant_id: str, source_variant: dict[str, Any]) -> dict[str, str]:
    return {
        "pair": str(source_variant.get("pack_id") or source_dir.parent.parent.name),
        "source_experiment": source_dir.name,
        "baseline_2_experiment": baseline_dir.name,
        "model": model,
        "variant_id": variant_id,
        "payload_id": str(source_variant.get("payload_id", "")),
        "final_loop": "",
        "step_1": "missing",
        "step_2": "missing",
        "combination": "missing/missing",
        "step_1_failure_reason": "",
        "step_1_primary_label": "",
        "step_1_secondary_labels": "",
        "step_1_failure_details": "",
        "step_2_failure_reason": "",
        "step_2_primary_label": "",
        "step_2_secondary_labels": "",
        "step_2_failure_details": "",
        "result_path": "",
    }


def row_for_missing(source_dir: Path, baseline_dir: Path, model: str, variant_id: str, source_variant: dict[str, Any], loop: int | None = None) -> dict[str, str]:
    row = base_row(source_dir, baseline_dir, model, variant_id, source_variant)
    if loop is not None:
        row["final_loop"] = f"loop_{loop:03d}"
        row["result_path"] = str(baseline_dir / "variants" / variant_id / f"coordinated/loop_{loop:03d}/session/verdict.json")
    return row


def make_row(source_dir: Path, baseline_dir: Path, model: str, variant_id: str, source_variant: dict[str, Any], verdict: dict[str, Any], loop: int) -> dict[str, str]:
    row = base_row(source_dir, baseline_dir, model, variant_id, source_variant)
    row["final_loop"] = f"loop_{loop:03d}"
    row["result_path"] = str(baseline_dir / "variants" / variant_id / f"coordinated/loop_{loop:03d}/session/verdict.json")

    for label in ("step_1", "step_2"):
        step = verdict.get(label)
        if not isinstance(step, dict):
            continue
        status = step.get("verdict")
        if status in {"success", "failure"}:
            row[label] = status
        if status == "failure":
            reason, primary, secondary, details = failure_details(step)
            row[f"{label}_failure_reason"] = reason
            row[f"{label}_primary_label"] = primary
            row[f"{label}_secondary_labels"] = secondary
            row[f"{label}_failure_details"] = details

    row["combination"] = combination(row["step_1"], row["step_2"])
    return row


def collect(patterns: list[str], pairs: set[str] | None = None) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    summaries: list[dict[str, str]] = []
    missing: list[dict[str, str]] = []

    for source_dir in source_experiments(patterns, pairs):
        source_variants: dict[str, dict[str, Any]] = {}
        for path in sorted((source_dir / "variants").glob("*/variant.json")):
            try:
                variant = load_json(path)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if variant.get("status") == "coordinated_success":
                source_variants[path.parent.name] = variant

        for baseline_dir in baseline2_experiments(source_dir):
            model = baseline_dir.name.removeprefix(f"{source_dir.name}_baseline_2_")
            eval_rows: list[dict[str, str]] = []
            for variant_id, source_variant in source_variants.items():
                eval_variant_dir = baseline_dir / "variants" / variant_id
                verdicts = final_verdict_paths(eval_variant_dir)
                if not verdicts:
                    row = row_for_missing(source_dir, baseline_dir, model, variant_id, source_variant)
                    missing.append(row)
                else:
                    loop_number, verdict_path = verdicts[-1]
                    try:
                        verdict = load_json(verdict_path)
                    except ValueError as exc:
                        print(f"WARNING: {exc}", file=sys.stderr)
                        row = row_for_missing(source_dir, baseline_dir, model, variant_id, source_variant, loop_number)
                        missing.append(row)
                    else:
                        row = make_row(source_dir, baseline_dir, model, variant_id, source_variant, verdict, loop_number)
                        eval_rows.append(row)
                rows.append(row)

            if eval_rows:
                counts = Counter(row["combination"] for row in eval_rows)
                total_count = len(eval_rows)
                summaries.append(
                    {
                        "pair": str(source_dir.parent.parent.name),
                        "source_experiment": source_dir.name,
                        "baseline_2_experiment": baseline_dir.name,
                        "model": model,
                        "variants": str(total_count),
                        "success_success": str(counts.get("success/success", 0)),
                        "success_success_ratio": ratio(counts.get("success/success", 0), total_count),
                        "success_failure": str(counts.get("success/failure", 0)),
                        "success_failure_ratio": ratio(counts.get("success/failure", 0), total_count),
                        "failure_success": str(counts.get("failure/success", 0)),
                        "failure_success_ratio": ratio(counts.get("failure/success", 0), total_count),
                        "failure_failure": str(counts.get("failure/failure", 0)),
                        "failure_failure_ratio": ratio(counts.get("failure/failure", 0), total_count),
                        "success_total": str(counts.get("success/success", 0) + counts.get("failure/success", 0)),
                        "success_total_ratio": ratio(counts.get("success/success", 0) + counts.get("failure/success", 0), total_count),
                        "failure_total": str(counts.get("success/failure", 0) + counts.get("failure/failure", 0)),
                        "failure_total_ratio": ratio(counts.get("success/failure", 0) + counts.get("failure/failure", 0), total_count),
                    }
                )
    return rows, summaries, missing


FIELDS = (
    "pair",
    "source_experiment",
    "baseline_2_experiment",
    "model",
    "variant_id",
    "payload_id",
    "final_loop",
    "step_1",
    "step_2",
    "combination",
    "step_1_failure_reason",
    "step_1_primary_label",
    "step_1_secondary_labels",
    "step_1_failure_details",
    "step_2_failure_reason",
    "step_2_primary_label",
    "step_2_secondary_labels",
    "step_2_failure_details",
    "result_path",
)

SUMMARY_FIELDS = (
    "pair",
    "source_experiment",
    "baseline_2_experiment",
    "model",
    "variants",
    "success_success",
    "success_success_ratio",
    "success_failure",
    "success_failure_ratio",
    "failure_success",
    "failure_success_ratio",
    "failure_failure",
    "failure_failure_ratio",
    "success_total",
    "success_total_ratio",
    "failure_total",
    "failure_total_ratio",
)


def render_markdown(rows: list[dict[str, str]], summaries: list[dict[str, str]], missing: list[dict[str, str]]) -> str:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    total = len([row for row in rows if row["step_1"] != "missing" and row["step_2"] != "missing"])
    counts = Counter(row["combination"] for row in rows if row["step_1"] != "missing" and row["step_2"] != "missing")
    lines = [
        "# Baseline 2 Stepwise Results",
        "",
        f"Total evaluated variants: **{total}**",
        f"Missing variants: **{len(missing)}**",
        "",
        "## Overall matrix",
        "",
        "| Combination | Count | Ratio |",
        "|---|---:|---:|",
    ]
    for combo in ("success/success", "success/failure", "failure/success", "failure/failure"):
        lines.append(f"| {combo} | {counts.get(combo, 0)} | {ratio(counts.get(combo, 0), total)} |")

    lines.extend(
        [
            "",
            "## Per experiment",
            "",
            "| " + " | ".join(field.replace("_", " ").title() for field in SUMMARY_FIELDS) + " |",
            "| " + " | ".join("---" for _ in SUMMARY_FIELDS) + " |",
        ]
    )
    lines.extend("| " + " | ".join(cell(row[field]) for field in SUMMARY_FIELDS) + " |" for row in summaries)

    lines.extend(
        [
            "",
            "## Variants",
            "",
            "| " + " | ".join(field.replace("_", " ").title() for field in FIELDS) + " |",
            "| " + " | ".join("---" for _ in FIELDS) + " |",
        ]
    )
    lines.extend("| " + " | ".join(cell(row[field]) for field in FIELDS) + " |" for row in rows)

    if missing:
        lines.extend(
            [
                "",
                "## Missing variants",
                "",
                "| Variant | Baseline 2 Experiment | Result Path |",
                "|---|---|---|",
            ]
        )
        lines.extend(
            f"| {cell(row['variant_id'])} | {cell(row['baseline_2_experiment'])} | {cell(row['result_path'])} |"
            for row in missing
        )
    return "\n".join(lines) + "\n"


def render_tsv(rows: list[dict[str, str]], summaries: list[dict[str, str]], missing: list[dict[str, str]]) -> str:
    lines = ["# SUMMARY"]
    lines.append("\t".join(SUMMARY_FIELDS))
    lines.extend("\t".join(row[field] for field in SUMMARY_FIELDS) for row in summaries)
    lines.append("")
    lines.append("# VARIANTS")
    lines.append("\t".join(FIELDS))
    lines.extend("\t".join(row[field] for field in FIELDS) for row in rows)
    lines.append("")
    lines.append("# MISSING")
    lines.append("\t".join(("variant_id", "baseline_2_experiment", "result_path")))
    lines.extend(
        "\t".join((row["variant_id"], row["baseline_2_experiment"], row["result_path"]))
        for row in missing
    )
    total = len([row for row in rows if row["step_1"] != "missing" and row["step_2"] != "missing"])
    counts = Counter(row["combination"] for row in rows if row["step_1"] != "missing" and row["step_2"] != "missing")
    lines.extend(
        [
            "",
            "# OVERALL",
            f"total_variants\t{total}",
            f"success/success\t{counts.get('success/success', 0)}\t{ratio(counts.get('success/success', 0), total)}",
            f"success/failure\t{counts.get('success/failure', 0)}\t{ratio(counts.get('success/failure', 0), total)}",
            f"failure/success\t{counts.get('failure/success', 0)}\t{ratio(counts.get('failure/success', 0), total)}",
            f"failure/failure\t{counts.get('failure/failure', 0)}\t{ratio(counts.get('failure/failure', 0), total)}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report baseline_2 stepwise results and four-way outcome ratios.")
    parser.add_argument("experiment_patterns", nargs="*", help="Experiment names or patterns, e.g. 'exp_00*'.")
    parser.add_argument(
        "--experiment",
        dest="single_experiment",
        help="Restrict the report to one source experiment, e.g. exp_001 or exp_002.",
    )
    parser.add_argument(
        "--pair",
        dest="pair_values",
        action="append",
        metavar="PAIR",
        help="Restrict to one pair. Repeat the option or use comma-separated values, e.g. --pair pair_001 --pair pair_002.",
    )
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    if args.single_experiment:
        patterns = [args.single_experiment]
    elif args.experiment_patterns:
        patterns = args.experiment_patterns
    else:
        parser.error("provide either --experiment or one or more experiment patterns")

    pairs = {
        pair.strip()
        for value in args.pair_values or []
        for pair in value.split(",")
        if pair.strip()
    }
    rows, summaries, missing = collect(patterns, pairs or None)
    report = render_markdown(rows, summaries, missing) if args.format == "markdown" else render_tsv(rows, summaries, missing)
    if args.output is None and args.single_experiment:
        suffix = ".md" if args.format == "markdown" else ".tsv"
        args.output = FRAMEWORK_ROOT / "benchmarks" / "results_statics" / f"baseline_2_{args.single_experiment}{suffix}"
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")
    print(
        f"Matched source experiments: {len(source_experiments(patterns, pairs or None))}; "
        f"baseline_2 experiments: {len(summaries)}; "
        f"evaluated variants: {len([row for row in rows if row['step_1'] != 'missing' and row['step_2'] != 'missing'])}; "
        f"missing variants: {len(missing)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
