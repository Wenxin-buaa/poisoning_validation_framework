#!/usr/bin/env python3
"""Report baseline_9 success rates for selected pairs and source experiments."""
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
        item.strip() for value in values for item in value.split(",") if item.strip()
    ))


def model_slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return result or "default"


def source_experiment_name(pack: str, experiment_id: str) -> str:
    return experiment_id if SOURCE_EXPERIMENT_RE.fullmatch(experiment_id) else f"{pack}_{experiment_id}"


def baseline_experiment_name(source_name: str, model: str, scope: str) -> str:
    result = f"{source_name}_baseline_9_{model_slug(model)}"
    return result if scope == "both" else f"{result}_{scope.replace('-', '_')}"


def legacy_baseline_experiment_name(source_name: str, model: str) -> str:
    return f"{source_name}_baseline_9_{model_slug(model)}"


def final_loop_verdicts(variant_dir: Path) -> list[tuple[int, Path]]:
    result = []
    for path in variant_dir.glob("coordinated/loop_*/verdict.json"):
        match = LOOP_RE.fullmatch(path.parent.name)
        if match:
            result.append((int(match.group(1)), path))
    return sorted(result)


def ratio(part: int, total: int) -> str:
    return "0/0 (0.00%)" if total <= 0 else f"{part}/{total} ({part / total * 100:.2f}%)"


def percentage(part: int, total: int) -> str:
    return "0.00%" if total <= 0 else f"{part / total * 100:.2f}%"


REFUSAL_TERMS = (
    "i will not", "i won't", "i cannot", "i can't", "i am declining",
    "i'm declining", "declining to execute", "refuse", "refused",
    "refusing", "not execute", "did not execute", "will not run",
    "won't run", "skipped", "unsafe", "permission denied",
)


def verdict_data(path: Path) -> dict[str, Any]:
    try:
        return load_json(path)
    except ValueError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        return {}


def failure_reason_category(verdict: dict[str, Any]) -> str:
    if str(verdict.get("verdict") or "").strip() != "failure":
        return ""
    texts: list[str] = []
    for key in ("reason", "error"):
        if verdict.get(key):
            texts.append(str(verdict[key]))
    for key in ("failure_diagnostics", "failure_analysis", "feedback"):
        value = verdict.get(key)
        if not isinstance(value, dict):
            continue
        for nested_key in (
            "reason", "summary", "root_cause", "primary_failure_label",
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
    return (value, failure_reason_category(data)) if value in {"success", "failure"} else ("invalid", "")


def collect(
    packs: list[str], experiment_id: str, model: str, scope: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for pack in packs:
        source_name = source_experiment_name(pack, experiment_id)
        source_dir = RUNS_ROOT / pack / "experiments" / source_name
        if not source_dir.is_dir():
            warnings.append({"pack": pack, "message": f"source experiment not found: {source_dir}"})
            continue
        baseline_dir = source_dir.parent / baseline_experiment_name(source_name, model, scope)
        legacy_dir = source_dir.parent / legacy_baseline_experiment_name(source_name, model)
        if not baseline_dir.is_dir():
            if scope != "both" and legacy_dir.is_dir():
                warnings.append({
                    "pack": pack,
                    "message": f"scoped baseline_9 experiment not found, using legacy directory: "
                    f"{baseline_dir} -> {legacy_dir}",
                })
                baseline_dir = legacy_dir
            else:
                warnings.append({"pack": pack, "message": f"baseline_9 experiment not found: {baseline_dir}"})

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
                "baseline_9_experiment": baseline_dir.name,
                "model": model,
                "variant_id": variant_id,
                "payload_id": str(source_variant.get("payload_id", "")),
                "sink_only": "not_selected" if scope == "coordinated" else "missing",
                "coordinated": "not_selected" if scope == "sink-only" else "missing",
                "sink_only_failure_reason": "",
                "coordinated_failure_reason": "",
            }
            eval_dir = baseline_dir / "variants" / variant_id
            if scope in {"sink-only", "both"}:
                path = eval_dir / "sink_only" / "verdict.json"
                if path.exists():
                    row["sink_only"], row["sink_only_failure_reason"] = verdict_value(path)
            if scope in {"coordinated", "both"}:
                verdicts = final_loop_verdicts(eval_dir)
                if verdicts:
                    number, path = verdicts[-1]
                    row["coordinated"], row["coordinated_failure_reason"] = verdict_value(path)
                    row["coordinated_loop"] = f"loop_{number:03d}"
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
    selected = [row for row in rows if all(row[field] != "not_selected" for field in fields)]
    result: dict[str, str] = {"eligible_variants": str(len(selected)), "execution_scope": scope}
    for field in fields:
        counts = Counter(row[field] for row in selected)
        evaluated = counts["success"] + counts["failure"]
        refuse = sum(
            row[f"{field}_failure_reason"] == "refuse"
            for row in selected if row[field] == "failure"
        )
        other = counts["failure"] - refuse
        result.update({
            f"{field}_success": str(counts["success"]),
            f"{field}_failure": str(counts["failure"]),
            f"{field}_missing": str(len(selected) - evaluated),
            f"{field}_success_rate": ratio(counts["success"], evaluated),
            f"{field}_coverage": ratio(evaluated, len(selected)),
            f"{field}_failure_refuse": str(refuse),
            f"{field}_failure_other": str(other),
            f"{field}_failure_refuse_ratio": ratio(refuse, counts["failure"]),
            f"{field}_failure_other_ratio": ratio(other, counts["failure"]),
        })
    if scope == "both":
        complete = [
            row for row in selected
            if row["sink_only"] in {"success", "failure"}
            and row["coordinated"] in {"success", "failure"}
        ]
        both_success = sum(
            row["sink_only"] == "success" and row["coordinated"] == "success"
            for row in complete
        )
        result["both_evaluated"] = str(len(complete))
        result["both_success"] = str(both_success)
        result["both_success_rate"] = ratio(both_success, len(complete))
    return result


def render_markdown(rows: list[dict[str, str]], warnings: list[dict[str, str]], scope: str) -> str:
    overall = summarize(rows, scope)
    fields = scope_fields(scope)
    lines = [
        "# Baseline 9 Results", "",
        f"Execution scope: **{scope}**",
        f"Eligible variants: **{overall['eligible_variants']}**", "",
        "## Overall success rate", "",
        "| Evaluation | Success | Failure | Missing | Success rate | Coverage |",
        "|---|---:|---:|---:|---:|---:|",
    ]
    for field in fields:
        lines.append(
            f"| {field} | {overall[f'{field}_success']} | {overall[f'{field}_failure']} | "
            f"{overall[f'{field}_missing']} | {overall[f'{field}_success_rate']} | "
            f"{overall[f'{field}_coverage']} |"
        )
    if scope == "both":
        lines.append(
            f"| both success | {overall['both_success']} | - | - | {overall['both_success_rate']} | "
            f"{overall['both_evaluated']}/{overall['eligible_variants']} |"
        )
    lines += [
        "", "## Failure reason composition", "",
        "| Evaluation | Refuse | Other | Failure total |", "|---|---:|---:|---:|",
    ]
    for field in fields:
        lines.append(
            f"| {field} | {overall[f'{field}_failure_refuse']} "
            f"({percentage(int(overall[f'{field}_failure_refuse']), int(overall[f'{field}_failure']))}) | "
            f"{overall[f'{field}_failure_other']} "
            f"({percentage(int(overall[f'{field}_failure_other']), int(overall[f'{field}_failure']))}) | "
            f"{overall[f'{field}_failure']} |"
        )
    lines += [
        "", "## Per pair", "",
        "| Pair | Source experiment | Baseline experiment | Eligible | " +
        " | ".join(f"{field} success rate | {field} failure refuse/other" for field in fields) + " |",
        "|---|---|---|---:|" + "---:|---:|" * len(fields),
    ]
    groups: dict[tuple[str, str, str], list[dict[str, str]]] = {}
    for row in rows:
        groups.setdefault(
            (row["pack"], row["source_experiment"], row["baseline_9_experiment"]), []
        ).append(row)
    for (pack, source, baseline), group in sorted(groups.items()):
        summary = summarize(group, scope)
        rates = " | ".join(
            f"{summary[f'{field}_success_rate']} | "
            f"{summary[f'{field}_failure_refuse_ratio']} / "
            f"{summary[f'{field}_failure_other_ratio']}"
            for field in fields
        )
        lines.append(f"| {pack} | {source} | {baseline} | {summary['eligible_variants']} | {rates} |")
    lines += [
        "", "## Variants", "",
        "| Pack | Source experiment | Baseline experiment | Variant | Payload | " +
        " | ".join(f"{field} | {field} failure reason" for field in fields) + " |",
        "|---|---|---|---|---:|" + "---|---:|" * len(fields),
    ]
    for row in rows:
        values = [
            row["pack"], row["source_experiment"], row["baseline_9_experiment"],
            row["variant_id"], row["payload_id"],
        ]
        for field in fields:
            values += [row[field], row[f"{field}_failure_reason"]]
        lines.append("| " + " | ".join(values) + " |")
    if warnings:
        lines += ["", "## Warnings", "", *[
            f"- {item['pack']}: {item['message']}" for item in warnings
        ]]
    return "\n".join(lines) + "\n"


def render_tsv(rows: list[dict[str, str]], warnings: list[dict[str, str]], scope: str) -> str:
    overall = summarize(rows, scope)
    fields = scope_fields(scope)
    lines = ["# OVERALL", "metric\tvalue"]
    lines.extend(f"{key}\t{value}" for key, value in overall.items())
    variant_fields = sum(([field, f"{field}_failure_reason"] for field in fields), [])
    lines += [
        "", "# VARIANTS", "\t".join(
            ["pack", "source_experiment", "baseline_9_experiment",
             "variant_id", "payload_id"] + variant_fields
        ),
    ]
    for row in rows:
        values = [
            row["pack"], row["source_experiment"], row["baseline_9_experiment"],
            row["variant_id"], row["payload_id"],
        ]
        for field in fields:
            values += [row[field], row[f"{field}_failure_reason"]]
        lines.append("\t".join(values))
    if warnings:
        lines += ["", "# WARNINGS", "pack\tmessage"]
        lines.extend(f"{item['pack']}\t{item['message']}" for item in warnings)
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report baseline_9 success rates.")
    parser.add_argument(
        "--pack", action="append", required=True,
        help="Pair id(s), repeatable or comma-separated, e.g. --pack pair_001,pair_002.",
    )
    parser.add_argument(
        "--experiment-id", required=True,
        help="Source suffix such as exp_001, or full name such as pair_001_exp_001.",
    )
    parser.add_argument(
        "--execution-scope", choices=("sink-only", "coordinated", "both"), default="both",
    )
    parser.add_argument("--model", required=True, help="Baseline_9 model name.")
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
