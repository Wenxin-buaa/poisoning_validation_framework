#!/usr/bin/env python3
"""Report baseline_10 skill-scanner detection rates."""
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


def main() -> int:
    parser = argparse.ArgumentParser(description="Report baseline_10 skill-scanner results.")
    parser.add_argument(
        "--pack",
        action="append",
        required=True,
        help="Pair id/range, repeatable and/or comma-separated. Examples: pair_001, 001, 001..010.",
    )
    parser.add_argument(
        "--experiment-id",
        "--exp",
        required=True,
        help="Source experiment id such as exp_001, 001, or pair_001_exp_001.",
    )
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    packs = parse_packs(args.pack)
    rows, warnings = collect(packs, normalize_experiment_token(args.experiment_id))
    report = render_markdown(rows, warnings) if args.format == "markdown" else render_tsv(rows, warnings)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")

    summary = summarize(rows)
    print(
        f"Matched pairs: {len(packs)}; eligible variants: {summary['eligible_variants']}; "
        f"evaluated: {summary['evaluated']}; detection_rate: {summary['detection_rate']}",
        file=sys.stderr,
    )
    return 0


def collect(packs: list[str], experiment_token: str) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    for pack in packs:
        source_name = source_experiment_name(pack, experiment_token)
        source_dir = RUNS_ROOT / pack / "experiments" / source_name
        if not source_dir.is_dir():
            warnings.append({"pack": pack, "message": f"source experiment not found: {source_dir}"})
            continue
        baseline_name = f"{source_name}_baseline_10_skill_scanner"
        baseline_dir = source_dir.parent / baseline_name
        if not baseline_dir.is_dir():
            warnings.append({"pack": pack, "message": f"baseline_10 experiment not found: {baseline_dir}"})

        for variant_json in sorted((source_dir / "variants").glob("*/variant.json")):
            try:
                source_variant = load_json(variant_json)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if source_variant.get("status") != "coordinated_success":
                continue

            variant_id = variant_json.parent.name
            verdict_path = baseline_dir / "variants" / variant_id / "baseline_10_verdict.json"
            row = {
                "pack": pack,
                "source_experiment": source_name,
                "baseline_10_experiment": baseline_name,
                "variant_id": variant_id,
                "payload_id": str(source_variant.get("payload_id", "")),
                "upstream_skill": str(source_variant.get("upstream_skill") or source_variant.get("hook_skill") or ""),
                "sink_skill": str(source_variant.get("sink_skill") or source_variant.get("target_skill") or ""),
                "verdict": "missing",
                "max_severity": "",
                "flagged_roles": "",
                "finding_counts": "",
                "result_path": str(verdict_path),
            }
            if verdict_path.exists():
                try:
                    verdict = load_json(verdict_path)
                    row.update(row_from_verdict(verdict))
                except ValueError as exc:
                    row["verdict"] = "invalid"
                    row["max_severity"] = ""
                    print(f"WARNING: {exc}", file=sys.stderr)
            rows.append(row)
    return rows, warnings


def row_from_verdict(verdict: dict[str, Any]) -> dict[str, str]:
    role_results = verdict.get("role_results") if isinstance(verdict.get("role_results"), list) else []
    finding_counts = []
    for result in role_results:
        if not isinstance(result, dict):
            continue
        finding_counts.append(
            f"{result.get('role')}={result.get('findings_count', 0)}"
            f"/actionable={result.get('actionable_findings_count', 0)}"
        )
    return {
        "verdict": str(verdict.get("verdict") or ""),
        "max_severity": str(verdict.get("max_severity") or ""),
        "flagged_roles": ",".join(str(item) for item in verdict.get("flagged_roles", []) or []),
        "finding_counts": ";".join(finding_counts),
    }


def summarize(rows: list[dict[str, str]]) -> dict[str, str]:
    counts = Counter(row["verdict"] for row in rows)
    evaluated = counts["detected"] + counts["not_detected"]
    severity_counts = Counter(row["max_severity"] or "missing" for row in rows)
    role_counts = Counter()
    for row in rows:
        for role in row["flagged_roles"].split(","):
            if role:
                role_counts[role] += 1
    return {
        "eligible_variants": str(len(rows)),
        "evaluated": str(evaluated),
        "detected": str(counts["detected"]),
        "not_detected": str(counts["not_detected"]),
        "technical": str(counts["technical"]),
        "missing": str(counts["missing"]),
        "invalid": str(counts["invalid"]),
        "detection_rate": ratio(counts["detected"], evaluated),
        "coverage": ratio(evaluated, len(rows)),
        "severity_counts": ", ".join(f"{k}={v}" for k, v in sorted(severity_counts.items())),
        "flagged_role_counts": ", ".join(f"{k}={v}" for k, v in sorted(role_counts.items())) or "none",
    }


def render_markdown(rows: list[dict[str, str]], warnings: list[dict[str, str]]) -> str:
    summary = summarize(rows)
    lines = [
        "# Baseline 10 Skill-Scanner Results",
        "",
        "## Summary",
        "",
        f"- Eligible coordinated_success variants: {summary['eligible_variants']}",
        f"- Evaluated variants: {summary['evaluated']}",
        f"- Detected: {summary['detected']}",
        f"- Not detected: {summary['not_detected']}",
        f"- Technical: {summary['technical']}",
        f"- Missing: {summary['missing']}",
        f"- Invalid: {summary['invalid']}",
        f"- Detection rate: {summary['detection_rate']}",
        f"- Coverage: {summary['coverage']}",
        f"- Max severity counts: {summary['severity_counts']}",
        f"- Flagged role counts: {summary['flagged_role_counts']}",
        "",
    ]
    if warnings:
        lines.extend(["## Warnings", ""])
        for warning in warnings:
            lines.append(f"- {warning['pack']}: {warning['message']}")
        lines.append("")
    lines.extend(
        [
            "## Rows",
            "",
            "| Pack | Experiment | Variant | Payload | Upstream | Sink | Verdict | Max Severity | Flagged Roles | Finding Counts |",
            "|---|---|---|---:|---|---|---|---|---|---|",
        ]
    )
    for row in rows:
        lines.append(
            "| "
            + " | ".join(
                markdown_cell(row[key])
                for key in (
                    "pack",
                    "source_experiment",
                    "variant_id",
                    "payload_id",
                    "upstream_skill",
                    "sink_skill",
                    "verdict",
                    "max_severity",
                    "flagged_roles",
                    "finding_counts",
                )
            )
            + " |"
        )
    lines.append("")
    return "\n".join(lines)


def render_tsv(rows: list[dict[str, str]], warnings: list[dict[str, str]]) -> str:
    columns = [
        "pack",
        "source_experiment",
        "baseline_10_experiment",
        "variant_id",
        "payload_id",
        "upstream_skill",
        "sink_skill",
        "verdict",
        "max_severity",
        "flagged_roles",
        "finding_counts",
        "result_path",
    ]
    lines = ["\t".join(columns)]
    for row in rows:
        lines.append("\t".join(row.get(column, "").replace("\t", " ") for column in columns))
    return "\n".join(lines) + "\n"


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
    for value in split_values(values):
        packs.extend(expand_pack_part(value))
    return list(dict.fromkeys(packs))


def split_values(values: list[str]) -> list[str]:
    return [
        item.strip()
        for value in values
        for item in re.split(r"[\s,]+", value.strip())
        if item.strip()
    ]


def expand_pack_part(part: str) -> list[str]:
    normalized = part.strip().strip("{}")
    range_match = re.fullmatch(r"(?:pair_)?(\d{1,3})\.\.(?:pair_)?(\d{1,3})", normalized)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        step = 1 if end >= start else -1
        return [f"pair_{number:03d}" for number in range(start, end + step, step)]
    single_match = re.fullmatch(r"(?:pair_)?(\d{1,3})", normalized)
    if single_match:
        return [f"pair_{int(single_match.group(1)):03d}"]
    if re.fullmatch(r"pair_\d{3}", normalized):
        return [normalized]
    raise ValueError(f"invalid pack id/range: {part!r}")


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


def ratio(success: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.00%)"
    return f"{success}/{total} ({success / total * 100:.2f}%)"


def markdown_cell(value: str) -> str:
    return value.replace("|", "\\|").replace("\n", " ")


if __name__ == "__main__":
    raise SystemExit(main())
