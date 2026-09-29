#!/usr/bin/env python3
"""Report baseline_2 step results for coordinated-success source variants.

The source experiment determines eligibility: only variants whose top-level
variant.json has status ``coordinated_success`` are included.  Each matching
``<source-experiment>_baseline_2_*`` evaluation directory is reported
separately, because the suffix normally identifies a target model.

Examples:
    python3.11 stat_baseline2_coordinated_results.py 'exp_00*'
    python3.11 stat_baseline2_coordinated_results.py exp_001 exp_002 \
        --format tsv --output baseline2_results.tsv
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
RUNS_ROOT = FRAMEWORK_ROOT / "benchmarks" / "runs"
SOURCE_EXPERIMENT_RE = re.compile(r"^pair_.+_exp_\d+$")
BASELINE2_SUFFIX_RE = re.compile(r"^(.+)_baseline_2_(.+)$")
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


def source_experiments(patterns: list[str]) -> list[Path]:
    result = []
    for path in RUNS_ROOT.glob("pair_*/experiments/*"):
        if path.is_dir() and SOURCE_EXPERIMENT_RE.fullmatch(path.name) and matches_pattern(path.name, patterns):
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
    """Return reason, primary label, secondary labels, and diagnostic summary."""
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


def collect(patterns: list[str]) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for source_dir in source_experiments(patterns):
        source_variants = {}
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
            for variant_id, source_variant in source_variants.items():
                eval_variant_dir = baseline_dir / "variants" / variant_id
                verdicts = final_verdict_paths(eval_variant_dir)
                if not verdicts:
                    rows.append(
                        row_for_missing(source_dir, baseline_dir, model, variant_id, source_variant)
                    )
                    continue
                loop_number, verdict_path = verdicts[-1]
                try:
                    verdict = load_json(verdict_path)
                except ValueError as exc:
                    print(f"WARNING: {exc}", file=sys.stderr)
                    rows.append(
                        row_for_missing(source_dir, baseline_dir, model, variant_id, source_variant, loop_number)
                    )
                    continue
                rows.append(make_row(source_dir, baseline_dir, model, variant_id, source_variant, verdict, loop_number))
    return rows


def base_row(source_dir: Path, baseline_dir: Path, model: str, variant_id: str, source_variant: dict[str, Any]) -> dict[str, str]:
    return {
        "pair": str(source_variant.get("pack_id") or source_dir.parent.parent.name),
        "source_experiment": source_dir.name,
        "baseline_2_experiment": baseline_dir.name,
        "model": model,
        "variant_id": variant_id,
        "payload_id": str(source_variant.get("payload_id", "")),
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
        row["result_path"] = str(baseline_dir / "variants" / variant_id / f"coordinated/loop_{loop:03d}/session/verdict.json")
    return row


def make_row(source_dir: Path, baseline_dir: Path, model: str, variant_id: str, source_variant: dict[str, Any], verdict: dict[str, Any], loop: int) -> dict[str, str]:
    row = base_row(source_dir, baseline_dir, model, variant_id, source_variant)
    row["result_path"] = str(baseline_dir / "variants" / variant_id / f"coordinated/loop_{loop:03d}/session/verdict.json")
    for label in ("step_1", "step_2"):
        step = verdict.get(label)
        if not isinstance(step, dict):
            continue
        status = step.get("verdict")
        if status in {"success", "failure"}:
            row[label] = status
        # baseline_2 step_2 can preserve a failed D6 verdict in d6_verdict
        # while its own execution-only verdict is success.  Report causes
        # only for the final baseline_2 failure state.
        if status == "failure":
            reason, primary, secondary, details = failure_details(step)
            row[f"{label}_failure_reason"] = reason
            row[f"{label}_primary_label"] = primary
            row[f"{label}_secondary_labels"] = secondary
            row[f"{label}_failure_details"] = details
    row["combination"] = f"{row['step_1']}/{row['step_2']}"
    return row


FIELDS = (
    "pair", "source_experiment", "baseline_2_experiment", "model", "variant_id", "payload_id",
    "step_1", "step_2", "combination",
    "step_1_failure_reason", "step_1_primary_label", "step_1_secondary_labels", "step_1_failure_details",
    "step_2_failure_reason", "step_2_primary_label", "step_2_secondary_labels", "step_2_failure_details",
    "result_path",
)

HEADERS = {
    "pair": "Pair", "source_experiment": "Source experiment", "baseline_2_experiment": "Baseline-2 experiment",
    "model": "Model", "variant_id": "Variant", "payload_id": "Payload", "step_1": "Step 1",
    "step_2": "Step 2", "combination": "Combination", "step_1_failure_reason": "Step 1 reason",
    "step_1_primary_label": "Step 1 primary label", "step_1_secondary_labels": "Step 1 secondary labels",
    "step_1_failure_details": "Step 1 failure details", "step_2_failure_reason": "Step 2 reason",
    "step_2_primary_label": "Step 2 primary label", "step_2_secondary_labels": "Step 2 secondary labels",
    "step_2_failure_details": "Step 2 failure details", "result_path": "Result path",
}


def render_markdown(rows: list[dict[str, str]]) -> str:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Baseline 2 Coordinated-Success Results", "",
        f"Total rows: **{len(rows)}**", "",
        "| " + " | ".join(HEADERS[field] for field in FIELDS) + " |",
        "| " + " | ".join("---" for _ in FIELDS) + " |",
    ]
    lines.extend("| " + " | ".join(cell(row[field]) for field in FIELDS) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def render_tsv(rows: list[dict[str, str]]) -> str:
    lines = ["\t".join(FIELDS)]
    lines.extend("\t".join(row[field] for field in FIELDS) for row in rows)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report baseline_2 step results for coordinated_success variants.")
    parser.add_argument("experiment_patterns", nargs="+", help="Experiment names or patterns, e.g. 'exp_00*'.")
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    rows = collect(args.experiment_patterns)
    report = render_markdown(rows) if args.format == "markdown" else render_tsv(rows)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")
    print(
        f"Matched source experiments: {len(source_experiments(args.experiment_patterns))}; rows: {len(rows)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
