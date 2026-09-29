#!/usr/bin/env python3
"""Report baseline_1 success rates for selected pairs and source experiments.

Only source variants whose source ``variant.json`` has
``status == coordinated_success`` are eligible. For each matching model-specific
baseline_1 experiment, this script reads:

* ``sink_only/verdict.json`` for D3;
* the latest ``coordinated/loop_*/verdict.json`` for D6.

The execution scope controls which result columns are reported:
``sink-only``, ``coordinated``, or ``both``. A missing verdict is reported as
missing and is not silently counted as failure.

Single-scope baseline_1 runs are stored separately from ``both`` runs:
``..._baseline_1_<model>_sink_only`` and
``..._baseline_1_<model>_coordinated``. If a scoped directory does not exist,
the report falls back to the legacy unscoped directory for compatibility.
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


def split_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(
        item.strip()
        for value in values
        for item in value.split(",")
        if item.strip()
    ))


def model_slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return result or "default"


def scope_slug(execution_scope: str) -> str:
    return execution_scope.replace("-", "_")


def source_experiment_name(pack: str, experiment_id: str) -> str:
    if SOURCE_EXPERIMENT_RE.fullmatch(experiment_id):
        return experiment_id
    return f"{pack}_{experiment_id}"


def baseline_experiment_name(source_name: str, model: str, execution_scope: str) -> str:
    base = f"{source_name}_baseline_1_{model_slug(model)}"
    if execution_scope == "both":
        return base
    return f"{base}_{scope_slug(execution_scope)}"


def legacy_baseline_experiment_name(source_name: str, model: str) -> str:
    return f"{source_name}_baseline_1_{model_slug(model)}"


def final_loop_verdicts(variant_dir: Path) -> list[tuple[int, Path]]:
    result: list[tuple[int, Path]] = []
    for path in variant_dir.glob("coordinated/loop_*/verdict.json"):
        match = LOOP_RE.fullmatch(path.parent.name)
        if match:
            result.append((int(match.group(1)), path))
    return sorted(result)


def ratio(success: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.00%)"
    return f"{success}/{total} ({success / total * 100:.2f}%)"


def percentage(part: int, total: int) -> str:
    if total <= 0:
        return "0.00%"
    return f"{part / total * 100:.2f}%"


REFUSAL_TERMS = (
    "i will not",
    "i won't",
    "i cannot",
    "i can't",
    "i am declining",
    "i'm declining",
    "declining to execute",
    "refuse",
    "refused",
    "refusing",
    "not execute",
    "did not execute",
    "will not run",
    "won't run",
    "skipped",
    "unsafe",
    "permission denied",
)


def verdict_data(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except ValueError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        return {}


def failure_reason_category(verdict: dict[str, Any]) -> str:
    """Classify a failure as refusal-like or other."""
    if str(verdict.get("verdict") or "").strip() != "failure":
        return ""

    texts: list[str] = []
    for key in ("reason", "error"):
        if verdict.get(key):
            texts.append(str(verdict[key]))
    for key in ("failure_diagnostics", "failure_analysis", "feedback"):
        value = verdict.get(key)
        if isinstance(value, dict):
            for nested_key in (
                "reason",
                "summary",
                "root_cause",
                "primary_failure_label",
                "improvement_strategy",
            ):
                if value.get(nested_key):
                    texts.append(str(value[nested_key]))
            for nested_key in ("possible_refusal_or_skip", "secondary_failure_labels", "notes"):
                nested = value.get(nested_key)
                if isinstance(nested, list):
                    texts.extend(str(item) for item in nested)
                elif nested:
                    texts.append(str(nested))
    haystack = " ".join(texts).lower()
    return "refuse" if any(term in haystack for term in REFUSAL_TERMS) else "other"


def verdict_value(path: Path) -> tuple[str, str]:
    data = verdict_data(path)
    value = str(data.get("verdict") or "").strip()
    if value not in {"success", "failure"}:
        return "invalid", ""
    return value, failure_reason_category(data)


def collect(
    packs: list[str],
    experiment_id: str,
    model: str,
    execution_scope: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    for pack in packs:
        source_name = source_experiment_name(pack, experiment_id)
        source_dir = RUNS_ROOT / pack / "experiments" / source_name
        if not source_dir.is_dir():
            warnings.append({"pack": pack, "message": f"source experiment not found: {source_dir}"})
            continue

        baseline_dir = source_dir.parent / baseline_experiment_name(source_name, model, execution_scope)
        legacy_baseline_dir = source_dir.parent / legacy_baseline_experiment_name(source_name, model)
        if not baseline_dir.is_dir():
            if execution_scope != "both" and legacy_baseline_dir.is_dir():
                warnings.append({
                    "pack": pack,
                    "message": (
                        f"scoped baseline_1 experiment not found, using legacy directory: "
                        f"{baseline_dir} -> {legacy_baseline_dir}"
                    ),
                })
                baseline_dir = legacy_baseline_dir
            else:
                warnings.append({"pack": pack, "message": f"baseline_1 experiment not found: {baseline_dir}"})

        for variant_json in sorted((source_dir / "variants").glob("*/variant.json")):
            try:
                source_variant = load_json(variant_json)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if source_variant.get("status") != "coordinated_success":
                continue

            variant_id = variant_json.parent.name
            row = {
                "pack": pack,
                "source_experiment": source_name,
                "baseline_1_experiment": baseline_dir.name,
                "model": model,
                "variant_id": variant_id,
                "payload_id": str(source_variant.get("payload_id", "")),
                "sink_only": "not_selected" if execution_scope == "coordinated" else "missing",
                "coordinated": "not_selected" if execution_scope == "sink-only" else "missing",
                "sink_only_path": "",
                "coordinated_path": "",
                "sink_only_failure_reason": "",
                "coordinated_failure_reason": "",
            }
            eval_variant_dir = baseline_dir / "variants" / variant_id

            if execution_scope in {"sink-only", "both"}:
                sink_path = eval_variant_dir / "sink_only" / "verdict.json"
                row["sink_only_path"] = str(sink_path)
                if sink_path.exists():
                    row["sink_only"], row["sink_only_failure_reason"] = verdict_value(sink_path)

            if execution_scope in {"coordinated", "both"}:
                coordinated = final_loop_verdicts(eval_variant_dir)
                if coordinated:
                    loop_number, coordinated_path = coordinated[-1]
                    row["coordinated"], row["coordinated_failure_reason"] = verdict_value(coordinated_path)
                    row["coordinated_path"] = str(coordinated_path)
                    row["coordinated_loop"] = f"loop_{loop_number:03d}"
                else:
                    row["coordinated_loop"] = ""

            rows.append(row)

    return rows, warnings


def scope_fields(scope: str) -> list[str]:
    if scope == "sink-only":
        return ["sink_only"]
    if scope == "coordinated":
        return ["coordinated"]
    return ["sink_only", "coordinated"]


def summarize(rows: list[dict[str, str]], scope: str) -> dict[str, str]:
    fields = scope_fields(scope)
    selected_rows = [row for row in rows if all(row[field] != "not_selected" for field in fields)]
    summary: dict[str, str] = {
        "eligible_variants": str(len(selected_rows)),
        "execution_scope": scope,
    }
    for field in fields:
        counts = Counter(row[field] for row in selected_rows)
        evaluated = counts["success"] + counts["failure"]
        summary[f"{field}_success"] = str(counts["success"])
        summary[f"{field}_failure"] = str(counts["failure"])
        summary[f"{field}_missing"] = str(len(selected_rows) - evaluated)
        summary[f"{field}_success_rate"] = ratio(counts["success"], evaluated)
        summary[f"{field}_coverage"] = ratio(evaluated, len(selected_rows))
        failures = counts["failure"]
        refusal_count = sum(
            row[f"{field}_failure_reason"] == "refuse"
            for row in selected_rows
            if row[field] == "failure"
        )
        other_count = failures - refusal_count
        summary[f"{field}_failure_refuse"] = str(refusal_count)
        summary[f"{field}_failure_other"] = str(other_count)
        summary[f"{field}_failure_refuse_ratio"] = ratio(refusal_count, failures)
        summary[f"{field}_failure_other_ratio"] = ratio(other_count, failures)

    if scope == "both":
        complete = [
            row for row in selected_rows
            if row["sink_only"] in {"success", "failure"}
            and row["coordinated"] in {"success", "failure"}
        ]
        both_success = sum(
            row["sink_only"] == "success" and row["coordinated"] == "success"
            for row in complete
        )
        summary["both_evaluated"] = str(len(complete))
        summary["both_success"] = str(both_success)
        summary["both_success_rate"] = ratio(both_success, len(complete))
    return summary


def render_markdown(rows: list[dict[str, str]], warnings: list[dict[str, str]], scope: str) -> str:
    overall = summarize(rows, scope)
    fields = scope_fields(scope)
    lines = [
        "# Baseline 1 Results",
        "",
        f"Execution scope: **{scope}**",
        f"Eligible variants: **{overall['eligible_variants']}**",
        "",
        "## Overall success rate",
        "",
        "| Evaluation | Success | Failure | Missing | Success rate | Coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for field in fields:
        lines.append(
            f"| {field} | {overall[f'{field}_success']} | "
            f"{overall[f'{field}_failure']} | {overall[f'{field}_missing']} | "
            f"{overall[f'{field}_success_rate']} | {overall[f'{field}_coverage']} |"
        )
    if scope == "both":
        lines.append(
            f"| both success | {overall['both_success']} | - | - | "
            f"{overall['both_success_rate']} | {overall['both_evaluated']}/{overall['eligible_variants']} |"
        )
    lines.extend([
        "",
        "## Failure reason composition",
        "",
        "| Evaluation | Refuse | Other | Failure total |",
        "|---|---:|---:|---:|",
    ])
    for field in fields:
        lines.append(
            f"| {field} | {overall[f'{field}_failure_refuse']} "
            f"({percentage(int(overall[f'{field}_failure_refuse']), int(overall[f'{field}_failure']))}) | "
            f"{overall[f'{field}_failure_other']} "
            f"({percentage(int(overall[f'{field}_failure_other']), int(overall[f'{field}_failure']))}) | "
            f"{overall[f'{field}_failure']} |"
        )
    lines.extend([
        "",
        "## Per pair",
        "",
        "| Pair | Source experiment | Baseline experiment | Eligible | "
        + " | ".join(
            f"{field} success rate | {field} failure refuse/other"
            for field in fields
        )
        + " |",
        "|---|---|---|---:|" + "---:|---:|" * len(fields),
    ])
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(
            (row["pack"], row["source_experiment"], row["baseline_1_experiment"]),
            [],
        ).append(row)
    for (pack, source, baseline), group in sorted(groups.items()):
        group_summary = summarize(group, scope)
        rates = " | ".join(
            f"{group_summary[f'{field}_success_rate']} | "
            f"{group_summary[f'{field}_failure_refuse_ratio']} / "
            f"{group_summary[f'{field}_failure_other_ratio']}"
            for field in fields
        )
        lines.append(f"| {pack} | {source} | {baseline} | {group_summary['eligible_variants']} | {rates} |")

    lines.extend([
        "",
        "## Variants",
        "",
        "| Pack | Source experiment | Baseline experiment | Variant | Payload | "
        + " | ".join(f"{field} | {field} failure reason" for field in fields)
        + " |",
        "|---|---|---|---|---:|" + "---|---:|" * len(fields),
    ])
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                [row["pack"], row["source_experiment"], row["baseline_1_experiment"],
                 row["variant_id"], row["payload_id"]]
                + sum(
                    ([row[field], row[f"{field}_failure_reason"]] for field in fields),
                    [],
                )
            )
            + " |"
        )

    if warnings:
        lines.extend(["", "## Warnings", "", *[f"- {item['pack']}: {item['message']}" for item in warnings]])
    return "\n".join(lines) + "\n"


def render_tsv(rows: list[dict[str, str]], warnings: list[dict[str, str]], scope: str) -> str:
    overall = summarize(rows, scope)
    fields = scope_fields(scope)
    lines = ["# OVERALL", "metric\tvalue"]
    for key, value in overall.items():
        lines.append(f"{key}\t{value}")
    variant_fields = sum(
        ([field, f"{field}_failure_reason"] for field in fields),
        [],
    )
    lines.extend(["", "# VARIANTS", "\t".join(
        ["pack", "source_experiment", "baseline_1_experiment", "variant_id", "payload_id"] + variant_fields
    )])
    for row in rows:
        lines.append("\t".join(
            [row["pack"], row["source_experiment"], row["baseline_1_experiment"],
             row["variant_id"], row["payload_id"]]
            + sum(
                ([row[field], row[f"{field}_failure_reason"]] for field in fields),
                [],
            )
        ))
    if warnings:
        lines.extend(["", "# WARNINGS", "pack\tmessage"])
        lines.extend(f"{item['pack']}\t{item['message']}" for item in warnings)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report baseline_1 success rates.")
    parser.add_argument(
        "--pack", action="append", required=True,
        help="Pair id(s), repeatable or comma-separated, e.g. --pack pair_001,pair_002.",
    )
    parser.add_argument(
        "--experiment-id", required=True,
        help="Source experiment suffix such as exp_001, or a full name such as pair_001_exp_001.",
    )
    parser.add_argument(
        "--execution-scope", choices=("sink-only", "coordinated", "both"), default="both",
        help="Report sink-only D3, coordinated D6, or both. Default: both.",
    )
    parser.add_argument("--model", required=True, help="Baseline_1 model name used in --model.")
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    packs = split_values(args.pack)
    if not packs:
        parser.error("--pack did not contain any pair ids")

    rows, warnings = collect(packs, args.experiment_id, args.model, args.execution_scope)
    report = (
        render_markdown(rows, warnings, args.execution_scope)
        if args.format == "markdown"
        else render_tsv(rows, warnings, args.execution_scope)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")

    overall = summarize(rows, args.execution_scope)
    print(
        f"Matched pairs: {len(packs)}; eligible variants: {overall['eligible_variants']}; "
        f"scope: {args.execution_scope}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
