#!/usr/bin/env python3
"""Report coordinated-success variants and their successful loops.

The source experiment directory is treated as the authority for the variant
status.  A loop is counted as successful only when its own verdict.json has
``verdict == "success"``.  This keeps baseline evaluation directories and
stale loop metadata from being mistaken for source experiment results.

Examples:
    python3.11 stat_coordinated_success_loops.py 'exp_00*'
    python3.11 stat_coordinated_success_loops.py exp_001 exp_002 \
        --format tsv --output coordinated_success.tsv
    python3.11 stat_coordinated_success_loops.py --conditional-rate \
        --packs pair_001,pair_002 --exp 003
"""
from __future__ import annotations

import argparse
import fnmatch
import json
import re
import sys
from pathlib import Path


SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
RUNS_ROOT = FRAMEWORK_ROOT / "benchmarks" / "runs"
LOOP_RE = re.compile(r"loop_(\d+)$")
SOURCE_EXPERIMENT_RE = re.compile(r"^pair_.+_exp_\d+$")
SINK_ONLY_FAILURE_VERDICTS = {"failure", "inconclusive"}


def load_json(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def matching_experiments(
    patterns: list[str],
    include_suffixed: bool,
    packs: list[str] | None = None,
) -> list[Path]:
    matches: list[Path] = []
    for experiment_dir in RUNS_ROOT.glob("pair_*/experiments/*"):
        if not experiment_dir.is_dir():
            continue
        if packs and experiment_dir.parent.parent.name not in packs:
            continue
        name = experiment_dir.name
        if not any(
            fnmatch.fnmatchcase(name, pattern)
            or fnmatch.fnmatchcase(name, f"*_{pattern}")
            for pattern in patterns
        ):
            continue
        if not include_suffixed and not SOURCE_EXPERIMENT_RE.fullmatch(name):
            continue
        matches.append(experiment_dir)
    return sorted(matches, key=lambda p: (p.parent.parent.name, p.name))


def selected_experiments(
    *,
    packs_text: str,
    exp: str,
    experiment_id_template: str,
) -> list[Path]:
    exp_number = normalize_exp_number(exp)
    packs = parse_packs(packs_text)
    matches: list[Path] = []
    for pack in packs:
        experiment_id = experiment_id_template.format(pack=pack, exp=exp_number)
        experiment_dir = RUNS_ROOT / pack / "experiments" / experiment_id
        if experiment_dir.is_dir():
            matches.append(experiment_dir)
        else:
            print(f"WARNING: missing experiment directory: {experiment_dir}", file=sys.stderr)
    return matches


def normalize_exp_number(exp: str) -> str:
    value = str(exp).strip()
    if value.startswith("exp_"):
        value = value.removeprefix("exp_")
    if not value.isdigit():
        raise ValueError(f"--exp must be a number or exp_NNN, got {exp!r}")
    return f"{int(value):03d}"


def parse_packs(text: str | list[str]) -> list[str]:
    packs: list[str] = []
    values = [text] if isinstance(text, str) else text
    for value in values:
        for raw_part in re.split(r"[\s,]+", value.strip()):
            part = raw_part.strip()
            if not part:
                continue
            packs.extend(expand_pack_part(part))
    return list(dict.fromkeys(packs))


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


def successful_loops(variant_dir: Path) -> list[int]:
    coordinated_dir = variant_dir / "coordinated"
    loops: list[int] = []
    if not coordinated_dir.is_dir():
        return loops
    for loop_dir in coordinated_dir.iterdir():
        match = LOOP_RE.fullmatch(loop_dir.name)
        if not match or not loop_dir.is_dir():
            continue
        verdict_path = loop_dir / "verdict.json"
        if not verdict_path.is_file():
            continue
        try:
            verdict = load_json(verdict_path)
        except ValueError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            continue
        if verdict.get("verdict") == "success":
            loops.append(int(match.group(1)))
    return sorted(set(loops))


def coordinated_task_completed(variant_dir: Path) -> bool:
    """Return task_completed from the latest successful coordinated loop."""
    coordinated_dir = variant_dir / "coordinated"
    successful_verdicts: list[tuple[int, dict]] = []
    if not coordinated_dir.is_dir():
        return False
    for loop_dir in coordinated_dir.iterdir():
        match = LOOP_RE.fullmatch(loop_dir.name)
        if not match or not loop_dir.is_dir():
            continue
        verdict_path = loop_dir / "verdict.json"
        if not verdict_path.is_file():
            continue
        try:
            verdict = load_json(verdict_path)
        except ValueError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            continue
        if verdict.get("verdict") == "success":
            successful_verdicts.append((int(match.group(1)), verdict))
    if not successful_verdicts:
        return False
    return bool(max(successful_verdicts, key=lambda item: item[0])[1].get("task_completed"))


def collect(
    patterns: list[str],
    include_suffixed: bool,
    packs: list[str] | None = None,
) -> list[dict[str, str]]:
    rows: list[dict[str, str]] = []
    for experiment_dir in matching_experiments(patterns, include_suffixed, packs):
        variants_dir = experiment_dir / "variants"
        if not variants_dir.is_dir():
            continue
        for variant_json in sorted(variants_dir.glob("*/variant.json")):
            try:
                variant = load_json(variant_json)
            except ValueError as exc:
                print(f"WARNING: {exc}", file=sys.stderr)
                continue
            if variant.get("status") != "coordinated_success":
                continue

            loops = successful_loops(variant_json.parent)
            if not loops:
                print(
                    "WARNING: coordinated_success variant has no successful "
                    f"loop verdict: {variant_json}",
                    file=sys.stderr,
                )
            rows.append(
                {
                    "pair": str(variant.get("pack_id") or experiment_dir.parent.parent.name),
                    "experiment": str(variant.get("experiment_id") or experiment_dir.name),
                    "variant_id": str(variant.get("variant_id") or variant_json.parent.name),
                    "payload_id": str(variant.get("payload_id", "")),
                    "upstream_skill": str(variant.get("upstream_skill", "")),
                    "sink_skill": str(variant.get("sink_skill") or variant.get("target_skill", "")),
                    "successful_loops": ",".join(f"loop_{n:03d}" for n in loops),
                    "first_success_loop": f"loop_{loops[0]:03d}" if loops else "",
                    "final_success_loop": f"loop_{loops[-1]:03d}" if loops else "",
                }
            )
    return rows


def sink_only_verdict(variant: dict, variant_dir: Path) -> str:
    value = str(variant.get("sink_only_verdict") or "").strip()
    if value:
        return value
    verdict_path = variant_dir / "sink_only" / "verdict.json"
    if not verdict_path.is_file():
        return ""
    try:
        verdict = load_json(verdict_path)
    except ValueError as exc:
        print(f"WARNING: {exc}", file=sys.stderr)
        return ""
    return str(verdict.get("verdict") or "").strip()


def collect_conditional_rate(experiment_dirs: list[Path]) -> dict:
    pair_rows: list[dict[str, str]] = []
    payload_counts: dict[str, dict[str, int]] = {}
    coordinated_success_loop_counts = {loop_number: 0 for loop_number in range(1, 13)}
    totals = {
        "experiments": len(experiment_dirs),
        "variants": 0,
        "coordinated_success_variants": 0,
        "non_sink_only_success": 0,
        "coordinated_success_after_excluding_sink_only_success": 0,
        "coordinated_success_task_completed": 0,
        "sink_only_failed": 0,
        "coordinated_success_after_sink_only_failure": 0,
        "sink_only_success": 0,
        "sink_only_missing_or_pending": 0,
    }

    for experiment_dir in experiment_dirs:
        variants_dir = experiment_dir / "variants"
        pair_total = 0
        pair_non_sink_success = 0
        pair_coordinated_success_excluding_sink_success = 0
        pair_coordinated_success_task_completed = 0
        pair_sink_failed = 0
        pair_coordinated_success = 0
        pair_sink_success = 0
        pair_sink_missing = 0
        if variants_dir.is_dir():
            for variant_json in sorted(variants_dir.glob("*/variant.json")):
                try:
                    variant = load_json(variant_json)
                except ValueError as exc:
                    print(f"WARNING: {exc}", file=sys.stderr)
                    continue
                pair_total += 1
                payload_id = str(variant.get("payload_id", ""))
                if variant.get("status") == "coordinated_success":
                    totals["coordinated_success_variants"] += 1
                    successful_loop_numbers = successful_loops(variant_json.parent)
                    if len(successful_loop_numbers) > 1:
                        print(
                            "WARNING: coordinated_success variant has multiple "
                            f"successful loops; using the first: {variant_json}",
                            file=sys.stderr,
                        )
                    if successful_loop_numbers:
                        first_success_loop = successful_loop_numbers[0]
                        if first_success_loop in coordinated_success_loop_counts:
                            coordinated_success_loop_counts[first_success_loop] += 1
                    else:
                        print(
                            "WARNING: coordinated_success variant has no successful "
                            f"loop verdict: {variant_json}",
                            file=sys.stderr,
                        )
                payload_counts.setdefault(
                    payload_id,
                    {
                        "variants": 0,
                        "non_sink_only_success": 0,
                        "coordinated_success_after_excluding_sink_only_success": 0,
                        "coordinated_success_task_completed": 0,
                        "sink_only_failed": 0,
                        "coordinated_success_after_sink_only_failure": 0,
                        "sink_only_success": 0,
                        "sink_only_missing_or_pending": 0,
                    },
                )
                payload_counts[payload_id]["variants"] += 1
                verdict = sink_only_verdict(variant, variant_json.parent)
                if verdict == "success":
                    pair_sink_success += 1
                    payload_counts[payload_id]["sink_only_success"] += 1
                    continue
                pair_non_sink_success += 1
                payload_counts[payload_id]["non_sink_only_success"] += 1
                if variant.get("status") == "coordinated_success":
                    pair_coordinated_success_excluding_sink_success += 1
                    payload_counts[payload_id]["coordinated_success_after_excluding_sink_only_success"] += 1
                    if coordinated_task_completed(variant_json.parent):
                        pair_coordinated_success_task_completed += 1
                        payload_counts[payload_id]["coordinated_success_task_completed"] += 1
                if verdict in SINK_ONLY_FAILURE_VERDICTS:
                    pair_sink_failed += 1
                    payload_counts[payload_id]["sink_only_failed"] += 1
                    if variant.get("status") == "coordinated_success":
                        pair_coordinated_success += 1
                        payload_counts[payload_id]["coordinated_success_after_sink_only_failure"] += 1
                    continue
                pair_sink_missing += 1
                payload_counts[payload_id]["sink_only_missing_or_pending"] += 1

        totals["variants"] += pair_total
        totals["non_sink_only_success"] += pair_non_sink_success
        totals["coordinated_success_after_excluding_sink_only_success"] += (
            pair_coordinated_success_excluding_sink_success
        )
        totals["coordinated_success_task_completed"] += pair_coordinated_success_task_completed
        totals["sink_only_failed"] += pair_sink_failed
        totals["coordinated_success_after_sink_only_failure"] += pair_coordinated_success
        totals["sink_only_success"] += pair_sink_success
        totals["sink_only_missing_or_pending"] += pair_sink_missing
        pair_rows.append(
            {
                "pair": experiment_dir.parent.parent.name,
                "experiment": experiment_dir.name,
                "variants": str(pair_total),
                "non_sink_only_success": str(pair_non_sink_success),
                "coordinated_success_after_excluding_sink_only_success": str(
                    pair_coordinated_success_excluding_sink_success
                ),
                "success_rate_excluding_sink_only_success": format_rate(
                    pair_coordinated_success_excluding_sink_success,
                    pair_non_sink_success,
                ),
                "coordinated_success_task_completed": str(pair_coordinated_success_task_completed),
                "coordinated_success_task_completed_rate": format_rate(
                    pair_coordinated_success_task_completed,
                    pair_coordinated_success_excluding_sink_success,
                ),
                "sink_only_failed": str(pair_sink_failed),
                "coordinated_success_after_sink_only_failure": str(pair_coordinated_success),
                "conditional_success_rate": format_rate(pair_coordinated_success, pair_sink_failed),
                "sink_only_success": str(pair_sink_success),
                "sink_only_missing_or_pending": str(pair_sink_missing),
            }
        )

    return {
        "totals": {
            **totals,
            "success_rate_excluding_sink_only_success": format_rate(
                totals["coordinated_success_after_excluding_sink_only_success"],
                totals["non_sink_only_success"],
            ),
            "coordinated_success_task_completed_rate": format_rate(
                totals["coordinated_success_task_completed"],
                totals["coordinated_success_after_excluding_sink_only_success"],
            ),
            "conditional_success_rate": format_rate(
                totals["coordinated_success_after_sink_only_failure"],
                totals["sink_only_failed"],
            ),
        },
        "pairs": pair_rows,
        "coordinated_success_loops": [
            {
                "loop": f"loop_{loop_number:03d}",
                "coordinated_success_variants": str(count),
                "success_rate": format_rate(
                    count,
                    totals["coordinated_success_variants"],
                ),
            }
            for loop_number, count in coordinated_success_loop_counts.items()
        ],
        "payloads": [
            {
                "payload_id": payload_id,
                **{key: str(value) for key, value in counts.items()},
                "success_rate_excluding_sink_only_success": format_rate(
                    counts["coordinated_success_after_excluding_sink_only_success"],
                    counts["non_sink_only_success"],
                ),
                "coordinated_success_task_completed_rate": format_rate(
                    counts["coordinated_success_task_completed"],
                    counts["coordinated_success_after_excluding_sink_only_success"],
                ),
                "conditional_success_rate": format_rate(
                    counts["coordinated_success_after_sink_only_failure"],
                    counts["sink_only_failed"],
                ),
            }
            for payload_id, counts in sorted(payload_counts.items(), key=lambda item: int(item[0]) if item[0].isdigit() else 999999)
        ],
    }


def format_rate(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "NA"
    return f"{numerator / denominator:.4f}"


FIELDS = (
    "pair",
    "experiment",
    "variant_id",
    "payload_id",
    "upstream_skill",
    "sink_skill",
    "successful_loops",
    "first_success_loop",
    "final_success_loop",
)


def markdown(rows: list[dict[str, str]]) -> str:
    headers = {
        "pair": "Pair",
        "experiment": "Experiment",
        "variant_id": "Variant",
        "payload_id": "Payload",
        "upstream_skill": "Upstream",
        "sink_skill": "Sink",
        "successful_loops": "Successful loops",
        "first_success_loop": "First success",
        "final_success_loop": "Final success",
    }

    def cell(value: str) -> str:
        return value.replace("|", "\\|").replace("\n", " ")

    lines = [
        "# Coordinated Success Loops",
        "",
        f"Total coordinated-success variants: **{len(rows)}**",
        "",
        "| " + " | ".join(headers[field] for field in FIELDS) + " |",
        "| " + " | ".join("---" for _ in FIELDS) + " |",
    ]
    lines.extend(
        "| " + " | ".join(cell(row[field]) for field in FIELDS) + " |"
        for row in rows
    )
    return "\n".join(lines) + "\n"


def tsv(rows: list[dict[str, str]]) -> str:
    lines = ["\t".join(FIELDS)]
    lines.extend("\t".join(row[field] for field in FIELDS) for row in rows)
    return "\n".join(lines) + "\n"


CONDITIONAL_FIELDS = (
    "pair",
    "experiment",
    "variants",
    "non_sink_only_success",
    "coordinated_success_after_excluding_sink_only_success",
    "success_rate_excluding_sink_only_success",
    "coordinated_success_task_completed",
    "coordinated_success_task_completed_rate",
    "sink_only_failed",
    "coordinated_success_after_sink_only_failure",
    "conditional_success_rate",
    "sink_only_success",
    "sink_only_missing_or_pending",
)


PAYLOAD_CONDITIONAL_FIELDS = (
    "payload_id",
    "variants",
    "non_sink_only_success",
    "coordinated_success_after_excluding_sink_only_success",
    "success_rate_excluding_sink_only_success",
    "coordinated_success_task_completed",
    "coordinated_success_task_completed_rate",
    "sink_only_failed",
    "coordinated_success_after_sink_only_failure",
    "conditional_success_rate",
    "sink_only_success",
    "sink_only_missing_or_pending",
)


LOOP_FIELDS = (
    "loop",
    "coordinated_success_variants",
    "success_rate",
)


def conditional_markdown(summary: dict) -> str:
    totals = summary["totals"]
    lines = [
        "# Coordinated Conditional Success Rate",
        "",
        "Primary rate: `coordinated_success / (variants - sink_only_success)`.",
        "Conditional rate: variants where sink-only verdict is `failure` or `inconclusive`.",
        "",
        f"Matched experiments: **{totals['experiments']}**",
        f"Total variants: **{totals['variants']}**",
        f"Total coordinated_success variants: **{totals['coordinated_success_variants']}**",
        f"Non sink-only-success variants: **{totals['non_sink_only_success']}**",
        f"Coordinated successes after excluding sink-only success: **{totals['coordinated_success_after_excluding_sink_only_success']}**",
        f"Success rate excluding sink-only success: **{totals['success_rate_excluding_sink_only_success']}**",
        f"Coordinated successes with task_completed: **{totals['coordinated_success_task_completed']}**",
        f"Task-completed rate among coordinated_success: **{totals['coordinated_success_task_completed_rate']}**",
        f"Sink-only failed variants: **{totals['sink_only_failed']}**",
        f"Coordinated successes after sink-only failure: **{totals['coordinated_success_after_sink_only_failure']}**",
        f"Conditional success rate: **{totals['conditional_success_rate']}**",
        "",
        "## By Pair",
        "",
        "| Pair | Experiment | Variants | Non sink-only success | Coordinated success after excluding sink-only success | Success rate excluding sink-only success | Coordinated success task_completed | Task-completed rate among coordinated_success | Sink-only failed | Coordinated success after sink-only failure | Conditional success rate | Sink-only success | Sink-only missing/pending |",
        "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
    ]
    lines.extend(
        "| " + " | ".join(str(row[field]) for field in CONDITIONAL_FIELDS) + " |"
        for row in summary["pairs"]
    )
    lines.extend(
        [
            "",
            "## By Payload",
            "",
            "| Payload | Variants | Non sink-only success | Coordinated success after excluding sink-only success | Success rate excluding sink-only success | Coordinated success task_completed | Task-completed rate among coordinated_success | Sink-only failed | Coordinated success after sink-only failure | Conditional success rate | Sink-only success | Sink-only missing/pending |",
            "| --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- | --- |",
        ]
    )
    lines.extend(
        "| " + " | ".join(str(row[field]) for field in PAYLOAD_CONDITIONAL_FIELDS) + " |"
        for row in summary["payloads"]
    )
    lines.extend(
        [
            "",
            "## By Successful Loop",
            "",
            "Denominator: all `coordinated_success` variants in the selected packs and experiment.",
            "",
            "| Loop | Coordinated success variants | Success rate |",
            "| --- | --- | --- |",
        ]
    )
    lines.extend(
        "| " + " | ".join(str(row[field]) for field in LOOP_FIELDS) + " |"
        for row in summary["coordinated_success_loops"]
    )
    return "\n".join(lines) + "\n"


def conditional_tsv(summary: dict) -> str:
    lines = ["section\t" + "\t".join(CONDITIONAL_FIELDS)]
    lines.extend("pair\t" + "\t".join(str(row[field]) for field in CONDITIONAL_FIELDS) for row in summary["pairs"])
    lines.append("")
    lines.append("section\t" + "\t".join(PAYLOAD_CONDITIONAL_FIELDS))
    lines.extend("payload\t" + "\t".join(str(row[field]) for field in PAYLOAD_CONDITIONAL_FIELDS) for row in summary["payloads"])
    lines.append("")
    lines.append("section\t" + "\t".join(LOOP_FIELDS))
    lines.extend("loop\t" + "\t".join(str(row[field]) for field in LOOP_FIELDS) for row in summary["coordinated_success_loops"])
    totals = summary["totals"]
    lines.append("")
    lines.append(
        "total\t"
        + "\t".join(
            str(
                totals.get(
                    {
                        "pair": "experiments",
                        "experiment": "success_rate_excluding_sink_only_success",
                    }.get(field, field),
                    "",
                )
            )
            for field in CONDITIONAL_FIELDS
        )
    )
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="List coordinated_success variants and successful coordinated loops."
    )
    parser.add_argument(
        "experiment_patterns",
        nargs="*",
        help="Experiment names or shell-style patterns, e.g. 'exp_00*'.",
    )
    parser.add_argument(
        "--conditional-rate",
        action="store_true",
        help=(
            "Report coordinated-success rates for selected packs and one experiment "
            "number, including per-payload statistics."
        ),
    )
    parser.add_argument(
        "--packs",
        default="",
        metavar="PACK",
        help=(
            "Restrict statistics to pair ids or ranges; accepts comma- or "
            "quoted space-separated values, e.g. pair_001,pair_002 or '001..007 009'."
        ),
    )
    parser.add_argument(
        "--exp",
        default="",
        help="Experiment number for --conditional-rate, e.g. 003 or exp_003.",
    )
    parser.add_argument(
        "--experiment-id-template",
        default="{pack}_exp_{exp}",
        help="Template for --conditional-rate experiment ids. Default: {pack}_exp_{exp}.",
    )
    parser.add_argument(
        "--format",
        choices=("markdown", "tsv"),
        default="markdown",
        help="Report format (default: markdown).",
    )
    parser.add_argument("--output", type=Path, help="Write the report to this path instead of stdout.")
    parser.add_argument(
        "--include-suffixed-experiments",
        action="store_true",
        help="Also include directories such as exp_001_baseline_2_... .",
    )
    args = parser.parse_args()

    if args.conditional_rate:
        if not args.packs or not args.exp:
            parser.error("--conditional-rate requires --packs and --exp")
        try:
            experiment_dirs = selected_experiments(
                packs_text=args.packs,
                exp=args.exp,
                experiment_id_template=args.experiment_id_template,
            )
        except ValueError as exc:
            parser.error(str(exc))
        summary = collect_conditional_rate(experiment_dirs)
        report = conditional_markdown(summary) if args.format == "markdown" else conditional_tsv(summary)
        if args.output:
            args.output.parent.mkdir(parents=True, exist_ok=True)
            args.output.write_text(report, encoding="utf-8")
            print(f"Report: {args.output}", file=sys.stderr)
        else:
            print(report, end="")
        totals = summary["totals"]
        print(
            f"Matched experiments: {totals['experiments']}; "
            f"coordinated_success_variants: {totals['coordinated_success_variants']}; "
            f"non_sink_only_success: {totals['non_sink_only_success']}; "
            f"coordinated_success_after_excluding_sink_only_success: "
            f"{totals['coordinated_success_after_excluding_sink_only_success']}; "
            f"success_rate_excluding_sink_only_success: "
            f"{totals['success_rate_excluding_sink_only_success']}; "
            f"coordinated_success_task_completed: "
            f"{totals['coordinated_success_task_completed']}; "
            f"coordinated_success_task_completed_rate: "
            f"{totals['coordinated_success_task_completed_rate']}; "
            f"sink_only_failed: {totals['sink_only_failed']}; "
            f"coordinated_success_after_sink_only_failure: "
            f"{totals['coordinated_success_after_sink_only_failure']}; "
            f"conditional_success_rate: {totals['conditional_success_rate']}",
            file=sys.stderr,
        )
        return 0

    if not args.experiment_patterns and not args.packs:
        parser.error("provide experiment patterns or --packs unless --conditional-rate is used")

    try:
        packs = parse_packs(args.packs)
    except ValueError as exc:
        parser.error(str(exc))
    patterns = args.experiment_patterns or ["*"]
    rows = collect(patterns, args.include_suffixed_experiments, packs)
    report = markdown(rows) if args.format == "markdown" else tsv(rows)
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(report, encoding="utf-8")
        print(f"Report: {args.output}", file=sys.stderr)
    else:
        print(report, end="")
    print(
        f"Matched source experiments: {len(matching_experiments(patterns, args.include_suffixed_experiments, packs))}; "
        f"coordinated_success variants: {len(rows)}",
        file=sys.stderr,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
