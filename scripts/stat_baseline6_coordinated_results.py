#!/usr/bin/env python3
"""Report baseline_6 success rates over coordinated-success source scopes.

For each selected pair and source experiment, this script first reads the
source experiment's ``variants/*/variant.json`` files and selects only variants
whose status is ``coordinated_success``.  Those source variants are then mapped
to the already-constructed baseline_6 Skill-Inject-style downstream-only
variant by ``sink_skill`` and ``payload_id``.  Finally, the script reads the D3
sink-only verdict produced by the requested model-specific baseline_6 run.

By default, source ``--experiment-id`` controls only the reporting scope, while
the evaluated baseline_6 results are read from ``*_exp_all_baseline_6_*`` runs.
Use ``--baseline-run-source experiment`` to read exp-specific baseline_6 runs
created by ``run_baseline_6.py --experiment-id``.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
RUNS_ROOT = FRAMEWORK_ROOT / "benchmarks" / "runs"
PAYLOAD_IDS = {1, 2, 15, 39, 40, 41, 42}
PAYLOAD_ORDER = (1, 2, 15, 39, 40, 41, 42)
SOURCE_EXPERIMENT_RE = re.compile(r"^pair_.+_exp_\d{3}$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_packs(values: list[str]) -> list[str]:
    packs: list[str] = []
    for value in values:
        for raw_part in re.split(r"[\s,]+", value.strip()):
            part = raw_part.strip()
            if not part:
                continue
            if re.fullmatch(r"pair_\d{3}", part):
                packs.append(part)
            elif part.isdigit():
                packs.append(f"pair_{int(part):03d}")
            else:
                raise ValueError(f"invalid pack id: {part!r}; expected pair_NNN")
    return list(dict.fromkeys(packs))


def normalize_experiment_id(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"\d+", text):
        return f"exp_{int(text):03d}"
    if re.fullmatch(r"exp_\d+", text):
        return f"exp_{int(text.removeprefix('exp_')):03d}"
    if SOURCE_EXPERIMENT_RE.fullmatch(text):
        match = re.search(r"exp_(\d{3})$", text)
        if match:
            return f"exp_{int(match.group(1)):03d}"
    raise ValueError(f"invalid experiment id: {value!r}; expected 001 or exp_001")


def model_slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "default"


def source_experiment_name(pack: str, experiment_id: str) -> str:
    if SOURCE_EXPERIMENT_RE.fullmatch(experiment_id):
        return experiment_id
    return f"{pack}_{experiment_id}"


def baseline6_experiment_name(pack: str, source_name: str, model: str, baseline_run_source: str) -> str:
    if baseline_run_source == "all":
        return f"{pack}_exp_all_baseline_6_{model_slug(model)}"
    return f"{source_name}_baseline_6_{model_slug(model)}"


def ratio(success: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.00%)"
    return f"{success}/{total} ({success / total * 100:.2f}%)"


def first_text(*values: Any) -> str:
    for value in values:
        if isinstance(value, str) and value.strip():
            return value.strip().replace("\n", " ")
    return ""


def failure_reason(verdict: dict[str, Any]) -> str:
    feedback = verdict.get("feedback") if isinstance(verdict.get("feedback"), dict) else {}
    analysis = verdict.get("failure_analysis") if isinstance(verdict.get("failure_analysis"), dict) else {}
    diagnostics = verdict.get("failure_diagnostics") if isinstance(verdict.get("failure_diagnostics"), dict) else {}
    notes = diagnostics.get("notes") if isinstance(diagnostics.get("notes"), list) else []
    return first_text(
        verdict.get("reason"),
        feedback.get("reason"),
        analysis.get("root_cause"),
        analysis.get("primary_failure_label"),
        ", ".join(str(item) for item in notes),
    )


def load_baseline6_manifest(pack: str) -> dict[str, dict[str, Any]]:
    manifest_path = RUNS_ROOT / pack / "baselines" / "baseline_6_skillinject" / "manifest.json"
    manifest = load_json(manifest_path)
    variants: dict[str, dict[str, Any]] = {}
    for item in manifest.get("variants", []):
        if isinstance(item, dict) and item.get("variant_id"):
            variants[str(item["variant_id"])] = item
    return variants


def find_baseline_variant(
    baseline_variants: dict[str, dict[str, Any]],
    *,
    sink_skill: str,
    payload_id: int,
) -> tuple[str, dict[str, Any]] | None:
    matches = [
        (variant_id, item)
        for variant_id, item in baseline_variants.items()
        if str(item.get("sink_skill") or item.get("downstream_skill") or "") == sink_skill
        and int(item.get("payload_id")) == payload_id
    ]
    if len(matches) == 1:
        return matches[0]
    return None


def collect(
    packs: list[str],
    experiment_id: str,
    model: str,
    baseline_run_source: str,
) -> tuple[list[dict[str, str]], list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    summaries: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    for pack in packs:
        source_name = source_experiment_name(pack, experiment_id)
        source_dir = RUNS_ROOT / pack / "experiments" / source_name
        baseline_dir = source_dir.parent / baseline6_experiment_name(
            pack,
            source_name,
            model,
            baseline_run_source,
        )
        if not source_dir.is_dir():
            warnings.append({"pack": pack, "message": f"source experiment not found: {source_dir}"})
            continue
        if not baseline_dir.is_dir():
            warnings.append({"pack": pack, "message": f"baseline_6 experiment not found: {baseline_dir}"})

        try:
            baseline_variants = load_baseline6_manifest(pack)
        except ValueError as exc:
            warnings.append({"pack": pack, "message": str(exc)})
            continue

        selected: dict[str, dict[str, Any]] = {}
        unsupported_payloads = 0
        unmapped = 0
        coordinated_source_count = 0
        for variant_json in sorted((source_dir / "variants").glob("*/variant.json")):
            try:
                source_variant = load_json(variant_json)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if source_variant.get("status") != "coordinated_success":
                continue
            coordinated_source_count += 1
            try:
                payload_id = int(source_variant.get("payload_id"))
            except (TypeError, ValueError):
                unsupported_payloads += 1
                continue
            if payload_id not in PAYLOAD_IDS:
                unsupported_payloads += 1
                continue
            sink_skill = str(source_variant.get("sink_skill") or source_variant.get("target_skill") or "").strip()
            match = find_baseline_variant(
                baseline_variants,
                sink_skill=sink_skill,
                payload_id=payload_id,
            )
            if match is None:
                unmapped += 1
                continue
            baseline_variant_id, baseline_variant = match
            item = selected.setdefault(
                baseline_variant_id,
                {
                    "baseline_variant": baseline_variant,
                    "source_variant_ids": [],
                },
            )
            item["source_variant_ids"].append(str(source_variant.get("variant_id") or variant_json.parent.name))

        selected_rows: list[dict[str, str]] = []
        for baseline_variant_id, item in sorted(selected.items()):
            baseline_variant = item["baseline_variant"]
            verdict_path = baseline_dir / "variants" / baseline_variant_id / "sink_only" / "verdict.json"
            verdict = "missing"
            payload_observed = ""
            task_completed = ""
            reason = ""
            if verdict_path.exists():
                try:
                    verdict_data = load_json(verdict_path)
                except ValueError as exc:
                    print(f"WARNING: {exc}", file=sys.stderr)
                    verdict_data = {}
                raw_verdict = str(verdict_data.get("verdict") or "").strip()
                verdict = raw_verdict if raw_verdict in {"success", "failure"} else "invalid"
                payload_observed = str(bool(verdict_data.get("payload_observed")))
                task_completed = str(bool(verdict_data.get("task_completed")))
                reason = "ok" if verdict == "success" else failure_reason(verdict_data)

            row = {
                "pair": pack,
                "source_experiment": source_name,
                "baseline_6_experiment": baseline_dir.name,
                "model": model,
                "baseline_variant_id": baseline_variant_id,
                "source_variant_ids": ",".join(item["source_variant_ids"]),
                "source_variant_count": str(len(item["source_variant_ids"])),
                "sink_skill": str(baseline_variant.get("sink_skill") or baseline_variant.get("downstream_skill") or ""),
                "payload_id": str(baseline_variant.get("payload_id", "")),
                "verdict": verdict,
                "payload_observed": payload_observed,
                "task_completed": task_completed,
                "reason": reason,
                "result_path": str(verdict_path),
            }
            selected_rows.append(row)
            rows.append(row)

        if selected_rows or coordinated_source_count:
            success_count = sum(1 for row in selected_rows if row["verdict"] == "success")
            failure_count = sum(1 for row in selected_rows if row["verdict"] == "failure")
            missing_count = sum(1 for row in selected_rows if row["verdict"] == "missing")
            invalid_count = sum(1 for row in selected_rows if row["verdict"] == "invalid")
            summaries.append(
                {
                    "pair": pack,
                    "source_experiment": source_name,
                    "baseline_6_experiment": baseline_dir.name,
                    "coordinated_source_variants": str(coordinated_source_count),
                    "selected_baseline6_variants": str(len(selected_rows)),
                    "success": str(success_count),
                    "failure": str(failure_count),
                    "missing": str(missing_count),
                    "invalid": str(invalid_count),
                    "unsupported_or_unmapped_source_variants": str(unsupported_payloads + unmapped),
                    "success_ratio": ratio(success_count, len(selected_rows)),
                }
            )

    return rows, summaries, warnings


VARIANT_FIELDS = (
    "pair",
    "source_experiment",
    "baseline_6_experiment",
    "model",
    "baseline_variant_id",
    "source_variant_ids",
    "source_variant_count",
    "sink_skill",
    "payload_id",
    "verdict",
    "payload_observed",
    "task_completed",
    "reason",
    "result_path",
)

SUMMARY_FIELDS = (
    "pair",
    "source_experiment",
    "baseline_6_experiment",
    "coordinated_source_variants",
    "selected_baseline6_variants",
    "success",
    "failure",
    "missing",
    "invalid",
    "unsupported_or_unmapped_source_variants",
    "success_ratio",
)

PAYLOAD_FIELDS = (
    "payload_id",
    "selected_baseline6_variants",
    "success",
    "failure",
    "missing",
    "invalid",
    "success_ratio",
)


def payload_summaries(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    result: list[dict[str, str]] = []
    for payload_id in PAYLOAD_ORDER:
        selected = [row for row in rows if row["payload_id"] == str(payload_id)]
        success = sum(1 for row in selected if row["verdict"] == "success")
        failure = sum(1 for row in selected if row["verdict"] == "failure")
        missing = sum(1 for row in selected if row["verdict"] == "missing")
        invalid = sum(1 for row in selected if row["verdict"] == "invalid")
        result.append(
            {
                "payload_id": f"{payload_id:03d}",
                "selected_baseline6_variants": str(len(selected)),
                "success": str(success),
                "failure": str(failure),
                "missing": str(missing),
                "invalid": str(invalid),
                "success_ratio": ratio(success, len(selected)),
            }
        )
    return result


def render_markdown(
    rows: list[dict[str, str]],
    summaries: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> str:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    total_success = sum(1 for row in rows if row["verdict"] == "success")
    total_count = len(rows)
    lines = [
        "# Baseline 6 Coordinated-Scope Results",
        "",
        f"Selected baseline_6 variants: **{total_count}**",
        f"Success: **{total_success}**",
        f"Success ratio: **{ratio(total_success, total_count)}**",
        "",
    ]
    if warnings:
        lines.extend(["## Warnings", ""])
        lines.extend(f"- `{item['pack']}`: {item['message']}" for item in warnings)
        lines.append("")

    payload_rows = payload_summaries(rows)
    lines.extend(
        [
            "## Per Payload",
            "",
            "| " + " | ".join(field.replace("_", " ").title() for field in PAYLOAD_FIELDS) + " |",
            "| " + " | ".join("---" for _ in PAYLOAD_FIELDS) + " |",
        ]
    )
    lines.extend("| " + " | ".join(cell(row[field]) for field in PAYLOAD_FIELDS) + " |" for row in payload_rows)
    lines.append("")

    lines.extend(
        [
            "## Per Experiment",
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
            "| " + " | ".join(field.replace("_", " ").title() for field in VARIANT_FIELDS) + " |",
            "| " + " | ".join("---" for _ in VARIANT_FIELDS) + " |",
        ]
    )
    lines.extend("| " + " | ".join(cell(row[field]) for field in VARIANT_FIELDS) + " |" for row in rows)
    return "\n".join(lines) + "\n"


def render_tsv(
    rows: list[dict[str, str]],
    summaries: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> str:
    lines = ["# WARNINGS"]
    lines.extend(f"{item['pack']}\t{item['message']}" for item in warnings)
    lines.extend(["", "# PAYLOADS", "\t".join(PAYLOAD_FIELDS)])
    lines.extend("\t".join(row[field] for field in PAYLOAD_FIELDS) for row in payload_summaries(rows))
    lines.extend(["", "# SUMMARY", "\t".join(SUMMARY_FIELDS)])
    lines.extend("\t".join(row[field] for field in SUMMARY_FIELDS) for row in summaries)
    lines.extend(["", "# VARIANTS", "\t".join(VARIANT_FIELDS)])
    lines.extend("\t".join(row[field] for field in VARIANT_FIELDS) for row in rows)
    total_success = sum(1 for row in rows if row["verdict"] == "success")
    total_count = len(rows)
    lines.extend(
        [
            "",
            f"# selected_baseline6_variants\t{total_count}",
            f"# success\t{total_success}",
            f"# success_ratio\t{ratio(total_success, total_count)}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Report baseline_6 Skill-Inject-style success rates over the "
            "coordinated_success source-variant scope."
        )
    )
    parser.add_argument(
        "--packs",
        nargs="+",
        required=True,
        metavar="PACK",
        help="Pair ids; accepts comma- or space-separated values, e.g. pair_001,pair_002.",
    )
    parser.add_argument(
        "--experiment-id",
        "--exp",
        dest="experiment_id",
        required=True,
        help="Source experiment sequence, e.g. 001 or exp_001.",
    )
    parser.add_argument("--model", required=True, help="Model name used by run_baseline_6.py.")
    parser.add_argument(
        "--baseline-run-source",
        choices=("all", "experiment"),
        default="all",
        help=(
            "Which baseline_6 evaluation directory to read. Default 'all' reads "
            "<pair>_exp_all_baseline_6_<model>, while 'experiment' reads "
            "<pair>_exp_NNN_baseline_6_<model>."
        ),
    )
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    try:
        packs = parse_packs(args.packs)
        experiment_id = normalize_experiment_id(args.experiment_id)
    except ValueError as exc:
        parser.error(str(exc))

    rows, summaries, warnings = collect(packs, experiment_id, args.model, args.baseline_run_source)
    report = (
        render_markdown(rows, summaries, warnings)
        if args.format == "markdown"
        else render_tsv(rows, summaries, warnings)
    )
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")

    total_success = sum(1 for row in rows if row["verdict"] == "success")
    print(
        f"pairs: {len(packs)}; source experiment: {experiment_id}; "
        f"baseline run source: {args.baseline_run_source}; "
        f"selected baseline_6 variants: {len(rows)}; "
        f"success ratio: {ratio(total_success, len(rows))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
