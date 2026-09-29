#!/usr/bin/env python3
"""Report baseline_4 coordinated results and success ratios.

The source experiment directory is treated as the authority for eligibility:
only variants whose top-level variant.json has status ``coordinated_success``
are included. Each matching ``<source-experiment>_baseline_4_*`` evaluation
directory is reported separately, because the suffix normally identifies a
target model.

Examples:
    python3.11 stat_baseline4_coordinated_results.py 'exp_00*'
    python3.11 stat_baseline4_coordinated_results.py exp_001 exp_002 \
        --format tsv --output baseline4_results.tsv
    python3.11 stat_baseline4_coordinated_results.py \
        --packs pair_001,pair_002 --experiment-id exp_002 --min-loop 5
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
BASELINE4_SUFFIX_RE = re.compile(r"^(.+)_baseline_4_(.+)$")
LOOP_RE = re.compile(r"loop_(\d+)$")


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def matches_pattern(values: list[str], patterns: list[str]) -> bool:
    return any(
        fnmatch.fnmatchcase(value, pattern)
        or fnmatch.fnmatchcase(value, f"*_{pattern}")
        for value in values
        for pattern in patterns
    )


def parse_packs(values: list[str]) -> list[str]:
    """Parse comma/space-separated pair ids while preserving numeric ids."""
    packs: list[str] = []
    for value in values:
        for raw_part in re.split(r"[\s,]+", value.strip()):
            part = raw_part.strip()
            if not part:
                continue
            if re.fullmatch(r"pair_\d{3}", part):
                packs.append(part)
                continue
            if part.isdigit():
                packs.append(f"pair_{int(part):03d}")
                continue
            raise ValueError(f"invalid pack id: {part!r}; expected pair_NNN")
    return list(dict.fromkeys(packs))


def normalize_experiment_id(value: str) -> str:
    text = value.strip()
    if re.fullmatch(r"\d+", text):
        return f"exp_{int(text):03d}"
    if re.fullmatch(r"exp_\d+", text):
        number = int(text.removeprefix("exp_"))
        return f"exp_{number:03d}"
    raise ValueError(f"invalid experiment id: {value!r}; expected exp_NNN")


def source_experiments(
    patterns: list[str],
    packs: list[str] | None = None,
    experiment_id: str | None = None,
) -> list[Path]:
    result = []
    for path in RUNS_ROOT.glob("pair_*/experiments/*"):
        if not path.is_dir() or not SOURCE_EXPERIMENT_RE.fullmatch(path.name):
            continue
        pair_name = path.parent.parent.name
        if packs and pair_name not in packs:
            continue
        if experiment_id and not (
            path.name == experiment_id or path.name.endswith(f"_{experiment_id}")
        ):
            continue
        if matches_pattern([path.name, pair_name], patterns):
            result.append(path)
    return sorted(result, key=lambda p: (p.parent.parent.name, p.name))


def baseline4_experiments(source_experiment: Path) -> list[Path]:
    experiments_dir = source_experiment.parent
    prefix = f"{source_experiment.name}_baseline_4_"
    return sorted(
        path
        for path in experiments_dir.iterdir()
        if path.is_dir() and path.name.startswith(prefix)
    )


def final_verdict_paths(variant_dir: Path) -> list[tuple[int, Path]]:
    paths = []
    for path in variant_dir.glob("coordinated/loop_*/verdict.json"):
        match = LOOP_RE.fullmatch(path.parent.name)
        if match:
            paths.append((int(match.group(1)), path))
    return sorted(paths)


def source_final_success_loop(variant_dir: Path) -> int | None:
    """Return the source variant's final successful coordinated loop."""
    successful_loops: list[int] = []
    for loop_number, verdict_path in final_verdict_paths(variant_dir):
        try:
            verdict = load_json(verdict_path)
        except ValueError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            continue
        if verdict.get("verdict") == "success":
            successful_loops.append(loop_number)
    return max(successful_loops) if successful_loops else None


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


def collect(
    patterns: list[str],
    packs: list[str] | None = None,
    experiment_id: str | None = None,
    min_loop: int | None = None,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows: list[dict[str, str]] = []
    summaries: list[dict[str, str]] = []
    for source_dir in source_experiments(patterns, packs, experiment_id):
        source_variants: dict[str, dict[str, Any]] = {}
        for path in sorted((source_dir / "variants").glob("*/variant.json")):
            try:
                variant = load_json(path)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if variant.get("status") == "coordinated_success":
                source_variants[path.parent.name] = variant

        selected_rows: list[dict[str, str]] = []
        for variant_id, source_variant in source_variants.items():
            candidate_rows: list[dict[str, str]] = []
            for baseline_dir in baseline4_experiments(source_dir):
                model = baseline_dir.name.removeprefix(f"{source_dir.name}_baseline_4_")
                eval_variant_dir = baseline_dir / "variants" / variant_id
                verdicts = final_verdict_paths(eval_variant_dir)
                if not verdicts:
                    row = row_for_missing(source_dir, baseline_dir, model, variant_id, source_variant)
                else:
                    loop_number, verdict_path = verdicts[-1]
                    try:
                        verdict = load_json(verdict_path)
                    except ValueError as exc:
                        print(f"WARNING: {exc}", file=sys.stderr)
                        row = row_for_missing(source_dir, baseline_dir, model, variant_id, source_variant, loop_number)
                    else:
                        row = make_row(source_dir, baseline_dir, model, variant_id, source_variant, verdict, loop_number)
                candidate_rows.append(row)

            if not candidate_rows:
                continue

            selected = choose_best_row(candidate_rows)
            if min_loop is not None:
                # --min-loop filters the source experiment's coordinated
                # success loop, not whether baseline_4 has already produced a
                # verdict for this variant.
                row_loop = parse_loop_number(selected["source_final_loop"])
                if row_loop is None or row_loop < min_loop:
                    continue
            selected_rows.append(selected)
            rows.append(selected)

        if selected_rows:
            success_count = sum(1 for row in selected_rows if row["verdict"] == "success")
            total_count = len(selected_rows)
            summaries.append(
                {
                    "pair": str(source_dir.parent.parent.name),
                    "source_experiment": source_dir.name,
                    "variants": str(total_count),
                    "success": str(success_count),
                    "failure": str(total_count - success_count),
                    "success_ratio": ratio(success_count, total_count),
                }
            )
    return rows, summaries


def choose_best_row(candidate_rows: list[dict[str, str]]) -> dict[str, str]:
    def score(row: dict[str, str]) -> tuple[int, int, str, str]:
        verdict_rank = {"success": 3, "failure": 2, "missing": 1}.get(row["verdict"], 0)
        loop_number = parse_loop_number(row["final_loop"]) or 0
        return (verdict_rank, loop_number, row["baseline_4_experiment"], row["result_path"])

    return max(candidate_rows, key=score)


def parse_loop_number(value: str) -> int | None:
    match = LOOP_RE.fullmatch(value.strip())
    return int(match.group(1)) if match else None


def base_row(source_dir: Path, baseline_dir: Path, model: str, variant_id: str, source_variant: dict[str, Any]) -> dict[str, str]:
    source_loop = source_final_success_loop(source_dir / "variants" / variant_id)
    return {
        "pair": str(source_variant.get("pack_id") or source_dir.parent.parent.name),
        "source_experiment": source_dir.name,
        "baseline_4_experiment": baseline_dir.name,
        "model": model,
        "variant_id": variant_id,
        "payload_id": str(source_variant.get("payload_id", "")),
        "source_final_loop": f"loop_{source_loop:03d}" if source_loop is not None else "",
        "final_loop": "",
        "verdict": "missing",
        "reason": "",
        "result_path": "",
    }


def row_for_missing(
    source_dir: Path,
    baseline_dir: Path,
    model: str,
    variant_id: str,
    source_variant: dict[str, Any],
    loop: int | None = None,
) -> dict[str, str]:
    row = base_row(source_dir, baseline_dir, model, variant_id, source_variant)
    if loop is not None:
        row["final_loop"] = f"loop_{loop:03d}"
        row["result_path"] = str(baseline_dir / "variants" / variant_id / f"coordinated/loop_{loop:03d}/verdict.json")
    return row


def make_row(
    source_dir: Path,
    baseline_dir: Path,
    model: str,
    variant_id: str,
    source_variant: dict[str, Any],
    verdict: dict[str, Any],
    loop: int,
) -> dict[str, str]:
    row = base_row(source_dir, baseline_dir, model, variant_id, source_variant)
    row["final_loop"] = f"loop_{loop:03d}"
    row["result_path"] = str(baseline_dir / "variants" / variant_id / f"coordinated/loop_{loop:03d}/verdict.json")
    status = verdict.get("verdict")
    row["verdict"] = status if status in {"success", "failure"} else "missing"
    if row["verdict"] == "failure":
        row["reason"] = failure_reason(verdict)
    elif row["verdict"] == "success":
        row["reason"] = "ok"
    return row


def ratio(success: int, total: int) -> str:
    if total <= 0:
        return "0/0 (0.00%)"
    return f"{success}/{total} ({(success / total) * 100:.2f}%)"


VARIANT_FIELDS = (
    "pair",
    "source_experiment",
    "baseline_4_experiment",
    "model",
    "variant_id",
    "payload_id",
    "source_final_loop",
    "final_loop",
    "verdict",
    "reason",
    "result_path",
)

SUMMARY_FIELDS = (
    "pair",
    "source_experiment",
    "variants",
    "success",
    "failure",
    "success_ratio",
)


def render_markdown(rows: list[dict[str, str]], summaries: list[dict[str, str]]) -> str:
    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    total_success = sum(1 for row in rows if row["verdict"] == "success")
    total_count = len(rows)
    lines = [
        "# Baseline 4 Coordinated Results",
        "",
        f"Total variants: **{total_count}**",
        f"Success: **{total_success}**",
        f"Success ratio: **{ratio(total_success, total_count)}**",
        "",
        "## Per Experiment",
        "",
        "| " + " | ".join(field.replace("_", " ").title() for field in SUMMARY_FIELDS) + " |",
        "| " + " | ".join("---" for _ in SUMMARY_FIELDS) + " |",
    ]
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


def render_tsv(rows: list[dict[str, str]], summaries: list[dict[str, str]]) -> str:
    lines = ["# SUMMARY"]
    lines.append("\t".join(SUMMARY_FIELDS))
    lines.extend("\t".join(row[field] for field in SUMMARY_FIELDS) for row in summaries)
    lines.append("")
    lines.append("# VARIANTS")
    lines.append("\t".join(VARIANT_FIELDS))
    lines.extend("\t".join(row[field] for field in VARIANT_FIELDS) for row in rows)
    total_success = sum(1 for row in rows if row["verdict"] == "success")
    total_count = len(rows)
    lines.extend(
        [
            "",
            f"# total_variants\t{total_count}",
            f"# success\t{total_success}",
            f"# success_ratio\t{ratio(total_success, total_count)}",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(description="Report baseline_4 coordinated results and success ratios.")
    parser.add_argument(
        "experiment_patterns",
        nargs="*",
        help="Optional experiment names or patterns, e.g. 'exp_00*'.",
    )
    parser.add_argument(
        "--packs",
        nargs="+",
        default=[],
        metavar="PACK",
        help="Restrict to pair ids; accepts comma- or space-separated values, e.g. pair_001,pair_002.",
    )
    parser.add_argument(
        "--experiment-id",
        "--exp",
        dest="experiment_id",
        help="Restrict to one experiment sequence, e.g. exp_002 or 002.",
    )
    parser.add_argument(
        "--min-loop",
        type=int,
        help="Only include variants whose final coordinated loop is at least this number.",
    )
    parser.add_argument("--format", choices=("markdown", "tsv"), default="markdown")
    parser.add_argument("--output", type=Path, help="Write report here instead of stdout.")
    args = parser.parse_args()

    if not args.experiment_patterns and not args.packs and not args.experiment_id:
        parser.error("provide experiment patterns, --packs, or --experiment-id")
    if args.min_loop is not None and args.min_loop < 0:
        parser.error("--min-loop must be non-negative")

    try:
        packs = parse_packs(args.packs)
        experiment_id = (
            normalize_experiment_id(args.experiment_id)
            if args.experiment_id
            else None
        )
    except ValueError as exc:
        parser.error(str(exc))

    patterns = args.experiment_patterns or ["*"]
    rows, summaries = collect(patterns, packs, experiment_id, args.min_loop)
    report = render_markdown(rows, summaries) if args.format == "markdown" else render_tsv(rows, summaries)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")
    print(
        f"Matched source experiments: {len(source_experiments(patterns, packs, experiment_id))}; "
        f"source-variant rows: {len(rows)}; "
        f"source-experiment summaries: {len(summaries)}; "
        f"min loop: {args.min_loop if args.min_loop is not None else 'none'}; "
        f"success ratio: {ratio(sum(1 for row in rows if row['verdict'] == 'success'), len(rows))}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
