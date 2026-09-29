#!/usr/bin/env python3
"""Report baseline_7 sink-only D3 results and success rates.

The source experiment directory is the authority for eligibility: only variants
whose top-level source ``variant.json`` has ``status == coordinated_success``
are included in the denominator. For each selected pair and the single selected
experiment id, this script reads the model-specific baseline_7 D3 verdict at:

    <source-experiment>_baseline_7_<model_slug>/variants/<variant>/sink_only/verdict.json

Missing verdicts are reported separately and are not silently counted as
failures. The success rate is computed over evaluated variants
(``success + failure``), while coverage reports evaluated/eligible.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
RUNS_ROOT = FRAMEWORK_ROOT / "benchmarks" / "runs"
SOURCE_EXPERIMENT_RE = re.compile(r"^pair_.+_exp_\d{3}$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def split_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(
        item.strip()
        for value in values
        for item in re.split(r"[\s,]+", value.strip())
        if item.strip()
    ))


def parse_packs(values: list[str]) -> list[str]:
    packs: list[str] = []
    for value in split_values(values):
        if re.fullmatch(r"pair_\d{3}", value):
            packs.append(value)
        elif value.isdigit():
            packs.append(f"pair_{int(value):03d}")
        else:
            raise ValueError(f"invalid pack id: {value!r}; expected pair_NNN")
    return list(dict.fromkeys(packs))


def normalize_experiment_token(value: str) -> str:
    text = value.strip()
    if "," in text:
        raise ValueError("--experiment-id accepts exactly one experiment id")
    if re.fullmatch(r"\d{1,3}", text):
        return f"exp_{int(text):03d}"
    if re.fullmatch(r"exp_\d{1,3}", text):
        return f"exp_{int(text.removeprefix('exp_')):03d}"
    if SOURCE_EXPERIMENT_RE.fullmatch(text):
        return text
    raise ValueError(f"invalid experiment id: {value!r}; expected exp_001, 002, 003, or pair_NNN_exp_001")


def source_experiment_name(pack: str, experiment_token: str) -> str:
    if SOURCE_EXPERIMENT_RE.fullmatch(experiment_token):
        if not experiment_token.startswith(f"{pack}_"):
            raise ValueError(f"full experiment id {experiment_token!r} does not belong to {pack}")
        return experiment_token
    return f"{pack}_{experiment_token}"


def model_slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return result or "default"


def baseline7_experiment_name(source_name: str, model: str) -> str:
    return f"{source_name}_baseline_7_{model_slug(model)}"


def ratio(success: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.00%)"
    return f"{success}/{total} ({success / total * 100:.2f}%)"


def percentage(part: int, total: int) -> str:
    if total <= 0:
        return "0.00%"
    return f"{part / total * 100:.2f}%"


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")
    return ""


def failure_reason(verdict: dict[str, Any]) -> str:
    return first_text(
        verdict.get("reason"),
        (verdict.get("feedback") or {}).get("reason") if isinstance(verdict.get("feedback"), dict) else "",
        (verdict.get("failure_analysis") or {}).get("reason") if isinstance(verdict.get("failure_analysis"), dict) else "",
        (verdict.get("failure_diagnostics") or {}).get("reason") if isinstance(verdict.get("failure_diagnostics"), dict) else "",
    )


def verdict_value(path: Path) -> tuple[str, str, str, str]:
    try:
        verdict = load_json(path)
    except ValueError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        return "invalid", "", "", ""
    value = str(verdict.get("verdict") or "").strip()
    if value not in {"success", "failure"}:
        return "invalid", "", "", ""
    reason = "ok" if value == "success" else failure_reason(verdict)
    return (
        value,
        str(verdict.get("payload_observed", "")),
        str(verdict.get("task_completed", "")),
        reason,
    )


def collect(
    packs: list[str],
    experiment_token: str,
    model: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    for pack in packs:
        source_name = source_experiment_name(pack, experiment_token)
        source_dir = RUNS_ROOT / pack / "experiments" / source_name
        if not source_dir.is_dir():
            warnings.append({"pack": pack, "message": f"source experiment not found: {source_dir}"})
            continue

        baseline_name = baseline7_experiment_name(source_name, model)
        baseline_dir = source_dir.parent / baseline_name
        if not baseline_dir.is_dir():
            warnings.append({"pack": pack, "message": f"baseline_7 experiment not found: {baseline_dir}"})

        for variant_json in sorted((source_dir / "variants").glob("*/variant.json")):
            try:
                source_variant = load_json(variant_json)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if source_variant.get("status") != "coordinated_success":
                continue

            variant_id = variant_json.parent.name
            verdict_path = baseline_dir / "variants" / variant_id / "sink_only" / "verdict.json"
            verdict = "missing"
            payload_observed = ""
            task_completed = ""
            reason = ""
            if verdict_path.exists():
                verdict, payload_observed, task_completed, reason = verdict_value(verdict_path)

            rows.append(
                {
                    "pack": pack,
                    "source_experiment": source_name,
                    "baseline_7_experiment": baseline_name,
                    "model": model,
                    "variant_id": variant_id,
                    "payload_id": str(source_variant.get("payload_id", "")),
                    "upstream_skill": str(source_variant.get("upstream_skill") or source_variant.get("hook_skill") or ""),
                    "sink_skill": str(source_variant.get("sink_skill") or source_variant.get("target_skill") or ""),
                    "verdict": verdict,
                    "payload_observed": payload_observed,
                    "task_completed": task_completed,
                    "reason": reason,
                    "result_path": str(verdict_path),
                }
            )

    return rows, warnings


def summarize(rows: list[dict[str, str]]) -> dict[str, str]:
    counts = Counter(row["verdict"] for row in rows)
    evaluated = counts["success"] + counts["failure"]
    return {
        "eligible_variants": str(len(rows)),
        "evaluated": str(evaluated),
        "success": str(counts["success"]),
        "failure": str(counts["failure"]),
        "missing": str(len(rows) - evaluated),
        "success_rate": ratio(counts["success"], evaluated),
        "coverage": ratio(evaluated, len(rows)),
    }


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


def render_markdown(rows: list[dict[str, str]], warnings: list[dict[str, str]]) -> str:
    overall = summarize(rows)
    lines = [
        "# Baseline 7 Sink-Only Replay Results",
        "",
        f"Eligible coordinated_success variants: **{overall['eligible_variants']}**",
        f"Evaluated variants: **{overall['evaluated']}**",
        f"Success: **{overall['success']}**",
        f"Failure: **{overall['failure']}**",
        f"Missing: **{overall['missing']}**",
        f"Success rate: **{overall['success_rate']}**",
        f"Coverage: **{overall['coverage']}**",
        "",
        "## Per Pair",
        "",
        "| Pair | Source Experiment | Baseline Experiment | Eligible | Evaluated | Success | Failure | Missing | Success Rate | Coverage |",
        "|---|---|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(
            (row["pack"], row["source_experiment"], row["baseline_7_experiment"]),
            [],
        ).append(row)
    for (pack, source, baseline), group in sorted(groups.items()):
        summary = summarize(group)
        lines.append(
            f"| {pack} | {source} | {baseline} | {summary['eligible_variants']} | "
            f"{summary['evaluated']} | {summary['success']} | {summary['failure']} | "
            f"{summary['missing']} | {summary['success_rate']} | {summary['coverage']} |"
        )

    lines.extend(
        [
            "",
            "## Failure Reason Composition",
            "",
            "| Reason | Count | Share Of Failures |",
            "|---|---:|---:|",
        ]
    )
    failure_rows = [row for row in rows if row["verdict"] == "failure"]
    reason_counts = Counter(row["reason"] or "failure" for row in failure_rows)
    for reason, count in sorted(reason_counts.items(), key=lambda item: (-item[1], item[0])):
        lines.append(f"| {markdown_cell(reason)} | {count} | {percentage(count, len(failure_rows))} |")
    if not reason_counts:
        lines.append("| - | 0 | 0.00% |")

    lines.extend(
        [
            "",
            "## Variants",
            "",
            "| Pair | Source Experiment | Baseline Experiment | Variant | Payload | Upstream | Sink | Verdict | Payload Observed | Task Completed | Reason | Result Path |",
            "|---|---|---|---|---:|---|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        fields = (
            "pack",
            "source_experiment",
            "baseline_7_experiment",
            "variant_id",
            "payload_id",
            "upstream_skill",
            "sink_skill",
            "verdict",
            "payload_observed",
            "task_completed",
            "reason",
            "result_path",
        )
        lines.append("| " + " | ".join(markdown_cell(row[field]) for field in fields) + " |")

    if warnings:
        lines.extend(["", "## Warnings", ""])
        lines.extend(f"- {item['pack']}: {item['message']}" for item in warnings)
    return "\n".join(lines) + "\n"


def render_tsv(rows: list[dict[str, str]], warnings: list[dict[str, str]]) -> str:
    overall = summarize(rows)
    lines = ["# OVERALL", "metric\tvalue"]
    lines.extend(f"{key}\t{value}" for key, value in overall.items())
    fields = (
        "pack",
        "source_experiment",
        "baseline_7_experiment",
        "model",
        "variant_id",
        "payload_id",
        "upstream_skill",
        "sink_skill",
        "verdict",
        "payload_observed",
        "task_completed",
        "reason",
        "result_path",
    )
    lines.extend(["", "# VARIANTS", "\t".join(fields)])
    lines.extend("\t".join(row[field] for field in fields) for row in rows)
    if warnings:
        lines.extend(["", "# WARNINGS", "pack\tmessage"])
        lines.extend(f"{item['pack']}\t{item['message']}" for item in warnings)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report baseline_7 D3 success rates over source "
            "coordinated_success variants."
        )
    )
    parser.add_argument(
        "--pack",
        "--packs",
        action="append",
        required=True,
        help="Pair id(s), repeatable or comma-separated, e.g. --pack pair_001,pair_002.",
    )
    parser.add_argument(
        "--experiment-id",
        "--exp",
        required=True,
        help="Single source experiment id, e.g. exp_001, 002, 003, or pair_001_exp_001.",
    )
    parser.add_argument("--model", required=True, help="Model name used when running baseline_7.")
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    try:
        packs = parse_packs(args.pack)
        experiment_token = normalize_experiment_token(args.experiment_id)
    except ValueError as exc:
        parser.error(str(exc))
    if not packs:
        parser.error("--pack did not contain any pair ids")

    rows, warnings = collect(packs, experiment_token, args.model)
    report = render_markdown(rows, warnings) if args.format == "markdown" else render_tsv(rows, warnings)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")

    overall = summarize(rows)
    print(
        f"Matched pairs: {len(packs)}; eligible variants: {overall['eligible_variants']}; "
        f"evaluated: {overall['evaluated']}; success rate: {overall['success_rate']}; "
        f"coverage: {overall['coverage']}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
