#!/usr/bin/env python3
"""Classify selected skill pairs and summarize success by function category.

The classification is loaded from the repository's pair manifests. For each
selected pair and experiment, every ``variants/*/variant.json`` is one sample.
The denominator is therefore the total number of variants, while the main rates
are:

    coordinated_success / all_variants
    sink_only_success / all_variants
    fail / all_variants

Examples:
    python3.11 stat_pair_function_categories.py
    python3.11 stat_pair_function_categories.py --exp 001 002 003
    python3.11 stat_pair_function_categories.py --pairs all-ran --exp 002
    python3.11 stat_pair_function_categories.py --exp 001..003 --format json
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


SCRIPT_DIR = Path(__file__).resolve().parent
FRAMEWORK_ROOT = SCRIPT_DIR.parent
BENCHMARKS_ROOT = FRAMEWORK_ROOT / "benchmarks"
RUNS_ROOT = BENCHMARKS_ROOT / "runs"
STATIC_CLASSIFICATION_PATH = (
    BENCHMARKS_ROOT / "pair_classification_static_20260820" / "pair_classification.json"
)
FAST_MANIFEST_DIR = (
    BENCHMARKS_ROOT
    / "candidate_skill_pairs_fast_semantic_static_20260820_v5"
    / "source_manifests"
)
LEGACY_FAST_MANIFEST_DIR = (
    BENCHMARKS_ROOT
    / "candidate_skill_pairs_fast_semantic_static_20260813_v5"
    / "source_manifests"
)
DIVERSE_MANIFEST_DIR = (
    BENCHMARKS_ROOT
    / "candidate_skill_pairs_replacements_diverse_static_20260823_v5"
    / "source_manifests"
)
REPLACEMENT_PAIR_NUMBERS = set(range(96, 116)) | set(range(144, 160))
EXPERIMENT_RE = re.compile(r"^pair_\d+_exp_(\d+)$")

DEFAULT_PAIR_TEXT = (
    "pair_001,pair_002,pair_004,pair_005,pair_006,pair_007,pair_009,"
    "pair_010,pair_011,pair_012,pair_013,pair_015,pair_016,pair_017,"
    "pair_022,pair_023,pair_025,pair_027,pair_028,pair_030,pair_032,"
    "pair_034,pair_038,pair_039,pair_040,pair_041,pair_042,pair_044,"
    "pair_054,pair_055,pair_056,pair_057,pair_060,pair_061,pair_082,"
    "pair_083,pair_084,pair_085,pair_087,pair_088,pair_089,pair_090,"
    "pair_093,pair_094,pair_095,pair_096,pair_098,pair_099,pair_100,"
    "pair_108,pair_113,pair_117,pair_119,pair_120,pair_121,pair_125,"
    "pair_126,pair_143,pair_147,pair_153,pair_157,pair_159"
)

BROAD_CATEGORIES = (
    "Business",
    "Data",
    "Design / QA",
    "Knowledge",
    "Docs / Publishing",
    "Software",
)


def load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"expected JSON object: {path}")
    return value


def parse_pair_token(token: str) -> list[str]:
    token = token.strip()
    if not token:
        return []
    token = token.strip("{}")
    match = re.fullmatch(r"(?:pair_)?(\d{1,3})\.\.(?:pair_)?(\d{1,3})", token)
    if match:
        start, end = (int(match.group(1)), int(match.group(2)))
        step = 1 if end >= start else -1
        return [f"pair_{n:03d}" for n in range(start, end + step, step)]
    match = re.fullmatch(r"(?:pair_)?(\d{1,3})", token)
    if match:
        return [f"pair_{int(match.group(1)):03d}"]
    raise ValueError(f"invalid pair token: {token!r}")


def parse_pairs(text: str) -> list[str]:
    if text.strip().lower() in {"all", "all-ran", "all_run", "all-run", "ran"}:
        return []
    pairs: list[str] = []
    for token in re.split(r"[\s,]+", text.strip()):
        pairs.extend(parse_pair_token(token))
    return list(dict.fromkeys(pairs))


def ran_pairs_for_experiments(exp_ids: list[str]) -> list[str]:
    pairs: set[str] = set()
    for pair_dir in RUNS_ROOT.glob("pair_*"):
        if not pair_dir.is_dir():
            continue
        experiments_dir = pair_dir / "experiments"
        for exp_id in exp_ids:
            root = experiments_dir / f"{pair_dir.name}_{exp_id}"
            if (root / "variants").is_dir():
                pairs.add(pair_dir.name)
    return sorted(pairs)


def parse_experiments(values: list[str]) -> list[str]:
    experiments: list[str] = []
    for value in values:
        for token in re.split(r"[\s,]+", value.strip()):
            if not token:
                continue
            token = token.removeprefix("exp_")
            match = re.fullmatch(r"(\d+)\.\.(\d+)", token)
            if match:
                start, end = int(match.group(1)), int(match.group(2))
                step = 1 if end >= start else -1
                experiments.extend(f"exp_{n:03d}" for n in range(start, end + step, step))
                continue
            if not token.isdigit():
                raise ValueError(f"invalid experiment token: {value!r}")
            experiments.append(f"exp_{int(token):03d}")
    return list(dict.fromkeys(experiments))


def category_from_domain(domain: str, producer: str = "", consumer: str = "") -> str:
    domain_text = domain.lower()
    if any(word in domain_text for word in ("wiki", "knowledge")):
        return "Knowledge"
    if any(word in domain_text for word in ("business", "marketing", "product", "strategy", "career")):
        return "Business"
    if any(
        word in domain_text
        for word in ("data", "analytics", "metric", "reporting", "experimentation", "observability", "visualization")
    ):
        return "Data"
    if any(
        word in domain_text
        for word in (
            "software",
            "backend",
            "python",
            "javascript",
            "migration",
            "automation",
            "shell",
            "infra",
            "kubernetes",
            "agent tooling",
        )
    ):
        return "Software"
    if any(word in domain_text for word in ("design", "web", "qa", "visual", "frontend", "sketch")):
        return "Design / QA"
    if any(
        word in domain_text
        for word in (
            "documentation",
            "documents",
            "presentation",
            "publishing",
            "template",
            "specification",
            "release",
            "communication",
            "career",
        )
    ):
        return "Docs / Publishing"

    # Use skill names only when a manifest has no useful domain label.
    text = f"{producer} {consumer}".lower()
    if any(word in text for word in ("wiki", "knowledge")):
        return "Knowledge"
    if any(word in text for word in ("marketing", "product", "strategy", "messaging")):
        return "Business"
    if any(
        word in text
        for word in ("analytics", "metric", "report", "experiment", "observability", "visualization", "sql", "data-quality")
    ):
        return "Data"
    if any(
        word in text
        for word in (
            "backend",
            "python",
            "javascript",
            "migration",
            "automation",
            "shell",
            "kubernetes",
            "agent",
            "api",
            "cqrs",
        )
    ):
        return "Software"
    if any(word in text for word in ("design", "web", "qa", "visual", "frontend", "sketch")):
        return "Design / QA"
    return "Docs / Publishing"


def choose_manifest(pair_id: str) -> tuple[dict[str, Any], Path]:
    pair_number = int(pair_id.removeprefix("pair_"))
    static_pairs = load_json(STATIC_CLASSIFICATION_PATH).get("pairs", [])
    static_by_id = {str(item.get("pair_id")): item for item in static_pairs}

    candidates: list[Path] = []
    if pair_number in REPLACEMENT_PAIR_NUMBERS:
        candidates.append(DIVERSE_MANIFEST_DIR / f"{pair_id}.json")
    candidates.extend(
        [
            FAST_MANIFEST_DIR / f"{pair_id}.json",
            LEGACY_FAST_MANIFEST_DIR / f"{pair_id}.json",
            DIVERSE_MANIFEST_DIR / f"{pair_id}.json",
        ]
    )
    for path in candidates:
        if path.is_file():
            manifest = load_json(path)
            domain = str(manifest.get("domain", ""))
            producer = str(manifest.get("producer_skill", ""))
            consumer = str(manifest.get("consumer_skill", ""))
            return (
                {
                    "pair_id": pair_id,
                    "domain": domain,
                    "broad_domain": category_from_domain(domain, producer, consumer),
                    "source_bundle": str(manifest.get("source_platform_bundle", "")),
                    "producer_skill": producer,
                    "consumer_skill": consumer,
                    "manifest_path": str(path),
                },
                path,
            )

    if pair_id in static_by_id:
        item = static_by_id[pair_id]
        domain = str(item.get("domain", ""))
        producer = str(item.get("producer_skill", ""))
        consumer = str(item.get("consumer_skill", ""))
        return (
            {
                "pair_id": pair_id,
                "domain": domain,
                "broad_domain": category_from_domain(domain, producer, consumer),
                "source_bundle": str(
                    item.get("source_bundle") or item.get("source_platform_bundle", "")
                ),
                "producer_skill": producer,
                "consumer_skill": consumer,
                "manifest_path": str(STATIC_CLASSIFICATION_PATH),
            },
            STATIC_CLASSIFICATION_PATH,
        )
    raise FileNotFoundError(f"no pair classification manifest found for {pair_id}")


def classify_pairs(pair_ids: list[str]) -> dict[str, dict[str, Any]]:
    classifications: dict[str, dict[str, Any]] = {}
    for pair_id in pair_ids:
        try:
            classification, _ = choose_manifest(pair_id)
        except (FileNotFoundError, ValueError) as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
            continue
        classifications[pair_id] = classification
    return classifications


def experiment_dir(pair_id: str, exp_id: str) -> Path:
    return RUNS_ROOT / pair_id / "experiments" / f"{pair_id}_{exp_id}"


def sink_only_result(variant: dict[str, Any], variant_dir: Path) -> str:
    status = str(variant.get("status") or "").strip()
    if status in {"coordinated_success", "sink_only_success"}:
        return status
    verdict = sink_only_verdict(variant, variant_dir)
    if verdict == "success":
        return "sink_only_success"
    return verdict


def sink_only_verdict(variant: dict[str, Any], variant_dir: Path) -> str:
    """Read the sink-only verdict independently of the top-level status."""
    explicit = str(variant.get("sink_only_verdict") or "").strip()
    if explicit:
        return explicit
    verdict_path = variant_dir / "sink_only" / "verdict.json"
    if verdict_path.is_file():
        try:
            verdict = load_json(verdict_path)
        except ValueError as exc:
            print(f"WARNING: {exc}", file=sys.stderr)
        else:
            return str(verdict.get("verdict") or "").strip()
    return ""


def collect_stats(
    pair_ids: list[str],
    exp_ids: list[str],
    classifications: dict[str, dict[str, Any]],
) -> tuple[dict[str, Any], list[dict[str, Any]], list[dict[str, Any]]]:
    category_counts: dict[str, Counter[str]] = defaultdict(Counter)
    pair_rows: list[dict[str, Any]] = []
    missing_experiments: list[dict[str, Any]] = []

    for pair_id in pair_ids:
        classification = classifications.get(pair_id)
        if classification is None:
            continue
        category = classification["broad_domain"]
        pair_total = Counter()
        pair_exp_count = 0
        for exp_id in exp_ids:
            root = experiment_dir(pair_id, exp_id)
            if not root.is_dir():
                missing_experiments.append({"pair": pair_id, "experiment": exp_id})
                continue
            pair_exp_count += 1
            variants_dir = root / "variants"
            if not variants_dir.is_dir():
                continue
            for variant_json in sorted(variants_dir.glob("*/variant.json")):
                try:
                    variant = load_json(variant_json)
                except ValueError as exc:
                    print(f"WARNING: {exc}", file=sys.stderr)
                    continue
                result = sink_only_result(variant, variant_json.parent)
                if result == "coordinated_success":
                    kind = "coordinated_success"
                elif result == "sink_only_success":
                    kind = "sink_only_success"
                else:
                    kind = "fail"
                sink_verdict = sink_only_verdict(variant, variant_json.parent)
                pair_total["all_variants"] += 1
                pair_total[kind] += 1
                category_counts[category]["all_variants"] += 1
                category_counts[category][kind] += 1
                if sink_verdict in {"failure", "inconclusive"}:
                    pair_total["sink_only_failed"] += 1
                    category_counts[category]["sink_only_failed"] += 1
                    if kind == "coordinated_success":
                        pair_total["coordinated_after_sink_failure"] += 1
                        category_counts[category]["coordinated_after_sink_failure"] += 1

        pair_rows.append(
            {
                "pair": pair_id,
                "category": category,
                "domain": classification["domain"],
                "source_bundle": classification["source_bundle"],
                "producer": classification["producer_skill"],
                "consumer": classification["consumer_skill"],
                "experiments_found": pair_exp_count,
                "experiments_requested": len(exp_ids),
                **{
                    key: pair_total[key]
                    for key in (
                        "all_variants",
                        "coordinated_success",
                        "sink_only_success",
                        "fail",
                        "sink_only_failed",
                        "coordinated_after_sink_failure",
                    )
                },
            }
        )

    category_rows: list[dict[str, Any]] = []
    for category in BROAD_CATEGORIES:
        counts = category_counts[category]
        total = counts["all_variants"]
        category_rows.append(
            {
                "category": category,
                "pair_count": sum(row["category"] == category for row in pair_rows),
                "all_variants": total,
                "coordinated_success": counts["coordinated_success"],
                "sink_only_success": counts["sink_only_success"],
                "fail": counts["fail"],
                "sink_only_failed": counts["sink_only_failed"],
                "coordinated_after_sink_failure": counts["coordinated_after_sink_failure"],
                "coordinated_rate": rate(counts["coordinated_success"], total),
                "sink_only_rate": rate(counts["sink_only_success"], total),
                "fail_rate": rate(counts["fail"], total),
                "conditional_rate": rate(
                    counts["coordinated_after_sink_failure"],
                    counts["sink_only_failed"],
                ),
            }
        )
    return (
        {
            "requested_pairs": len(pair_ids),
            "classified_pairs": len(classifications),
            "experiments": exp_ids,
            "categories": category_rows,
        },
        pair_rows,
        missing_experiments,
    )


def rate(numerator: int, denominator: int) -> str:
    return "NA" if denominator == 0 else f"{numerator / denominator:.4f}"


def available_experiment_count(pair_id: str, exp_ids: list[str]) -> int:
    return sum(experiment_dir(pair_id, exp_id).is_dir() for exp_id in exp_ids)


def recommend_pairs(
    selected: set[str],
    classifications: dict[str, dict[str, Any]],
    exp_ids: list[str],
    target_per_category: int,
) -> dict[str, list[dict[str, Any]]]:
    selected_counts = Counter(
        classifications[pair_id]["broad_domain"]
        for pair_id in selected
        if pair_id in classifications
    )
    all_known_ids = set(classifications)
    static_pairs = load_json(STATIC_CLASSIFICATION_PATH).get("pairs", [])
    all_known_ids.update(str(item.get("pair_id")) for item in static_pairs if item.get("pair_id"))
    for root in (FAST_MANIFEST_DIR, LEGACY_FAST_MANIFEST_DIR, DIVERSE_MANIFEST_DIR):
        for path in root.glob("pair_*.json"):
            all_known_ids.add(path.stem)
    all_classified = classify_pairs(sorted(all_known_ids))
    recommendations: dict[str, list[dict[str, Any]]] = {}
    for category in BROAD_CATEGORIES:
        needed = max(0, target_per_category - selected_counts[category])
        if needed == 0:
            continue
        candidates = []
        for pair_id, item in all_classified.items():
            if pair_id in selected or item["broad_domain"] != category:
                continue
            available = available_experiment_count(pair_id, exp_ids)
            candidates.append(
                {
                    "pair": pair_id,
                    "domain": item["domain"],
                    "source_bundle": item["source_bundle"],
                    "producer": item["producer_skill"],
                    "consumer": item["consumer_skill"],
                    "experiments_available": available,
                }
            )
        candidates.sort(key=lambda row: (-row["experiments_available"], row["pair"]))
        recommendations[category] = candidates[:needed]
    return recommendations


def print_classification_table(pair_rows: list[dict[str, Any]]) -> None:
    print("\nPair function classification")
    print("=" * 100)
    print(f"{'Pair':<10} {'Category':<42} {'Producer -> consumer':<43}")
    print("-" * 100)
    for row in pair_rows:
        edge = f"{row['producer']} -> {row['consumer']}"
        print(f"{row['pair']:<10} {row['category']:<42} {edge:<43}")


def print_markdown(
    summary: dict[str, Any],
    pair_rows: list[dict[str, Any]],
    missing: list[dict[str, Any]],
    recommendations: dict[str, list[dict[str, Any]]],
) -> None:
    print(f"# Pair Function Category Statistics\n")
    print(f"- Experiments: {', '.join(summary['experiments'])}")
    print(f"- Requested pairs: {summary['requested_pairs']}")
    print(f"- Classified pairs: {summary['classified_pairs']}\n")
    print(
        "| Category | Pairs | All variants | Coordinated success | "
        "Coordinated rate | Sink-only success | Sink-only rate | Fail | Fail rate | "
        "Sink-only failed | Coord. after sink failure | Conditional rate |"
    )
    print("|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|")
    for row in summary["categories"]:
        print(
            f"| {row['category']} | {row['pair_count']} | {row['all_variants']} | "
            f"{row['coordinated_success']} | {row['coordinated_rate']} | "
            f"{row['sink_only_success']} | {row['sink_only_rate']} | "
            f"{row['fail']} | {row['fail_rate']} | {row['sink_only_failed']} | "
            f"{row['coordinated_after_sink_failure']} | {row['conditional_rate']} |"
        )
    print("\n## Pair Details\n")
    print(
        "| Pair | Category | Domain | Producer -> consumer | Experiments | Variants | "
        "Coord. | Sink-only | Fail | Sink-only failed | Coord. after sink failure |"
    )
    print("|---|---|---|---|---:|---:|---:|---:|---:|---:|---:|")
    for row in pair_rows:
        print(
            f"| {row['pair']} | {row['category']} | {row['domain']} | "
            f"{row['producer']} -> {row['consumer']} | "
            f"{row['experiments_found']}/{row['experiments_requested']} | "
            f"{row['all_variants']} | {row['coordinated_success']} | "
            f"{row['sink_only_success']} | {row['fail']} | "
            f"{row['sink_only_failed']} | {row['coordinated_after_sink_failure']} |"
        )
    if missing:
        print("\n## Missing Experiments\n")
        for row in missing:
            print(f"- `{row['pair']}`: `{row['experiment']}`")
    print("\n## Recommended Additions\n")
    for category, rows in recommendations.items():
        print(f"### {category}")
        if not rows:
            print("- No classified candidate available.")
            continue
        for row in rows:
            print(
                f"- `{row['pair']}`: {row['producer']} -> {row['consumer']} "
                f"({row['domain']}; {row['experiments_available']} requested experiments available)"
            )


def write_tsv(path: Path, pair_rows: list[dict[str, Any]]) -> None:
    fields = (
        "pair",
        "category",
        "domain",
        "source_bundle",
        "producer",
        "consumer",
        "experiments_found",
        "experiments_requested",
        "all_variants",
        "coordinated_success",
        "sink_only_success",
        "fail",
        "sink_only_failed",
        "coordinated_after_sink_failure",
    )
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t")
        writer.writeheader()
        writer.writerows({field: row[field] for field in fields} for row in pair_rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Classify selected pairs and aggregate coordinated/sink-only success rates."
    )
    parser.add_argument(
        "--pairs",
        default=DEFAULT_PAIR_TEXT,
        help=(
            "Comma/space-separated pair IDs or ranges, or 'all-ran' for all pairs "
            "with requested experiment directories. Defaults to the requested 62 pairs."
        ),
    )
    parser.add_argument(
        "--exp",
        nargs="+",
        default=["001", "002", "003"],
        help="Experiment IDs, comma-separated values, or ranges such as 001..003.",
    )
    parser.add_argument(
        "--target-per-category",
        type=int,
        default=5,
        help="Recommend additions until sparse categories reach this pair count (default: 5).",
    )
    parser.add_argument(
        "--format",
        choices=("text", "markdown", "json", "tsv"),
        default="text",
    )
    parser.add_argument("--output", type=Path, help="Optional output file.")
    args = parser.parse_args()

    try:
        exp_ids = parse_experiments(args.exp)
        pair_ids = (
            ran_pairs_for_experiments(exp_ids)
            if args.pairs.strip().lower() in {"all", "all-ran", "all_run", "all-run", "ran"}
            else parse_pairs(args.pairs)
        )
        classifications = classify_pairs(pair_ids)
    except (ValueError, FileNotFoundError) as exc:
        parser.error(str(exc))

    summary, pair_rows, missing = collect_stats(pair_ids, exp_ids, classifications)
    recommendations = recommend_pairs(
        set(pair_ids),
        classifications,
        exp_ids,
        args.target_per_category,
    )

    if args.format == "text":
        print_classification_table(pair_rows)
        print("\nCategory statistics")
        print("=" * 100)
        for row in summary["categories"]:
            print(
                f"{row['category']}: pairs={row['pair_count']}, "
                f"variants={row['all_variants']}, "
                f"coordinated_success={row['coordinated_success']} "
                f"({row['coordinated_rate']}), "
                f"sink_only_success={row['sink_only_success']} "
                f"({row['sink_only_rate']}), fail={row['fail']} "
                f"({row['fail_rate']}), "
                f"conditional={row['coordinated_after_sink_failure']}/"
                f"{row['sink_only_failed']} ({row['conditional_rate']})"
            )
        if missing:
            print(f"\nMissing experiment directories: {len(missing)}")
            for row in missing:
                print(f"  {row['pair']} {row['experiment']}")
        print("\nRecommended additions")
        for category, rows in recommendations.items():
            print(f"{category}: " + (", ".join(row["pair"] for row in rows) or "none"))
    elif args.format == "markdown":
        from io import StringIO

        old_stdout = sys.stdout
        buffer = StringIO()
        sys.stdout = buffer
        try:
            print_markdown(summary, pair_rows, missing, recommendations)
        finally:
            sys.stdout = old_stdout
        rendered = buffer.getvalue()
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    elif args.format == "json":
        payload = {
            "summary": summary,
            "pairs": pair_rows,
            "missing_experiments": missing,
            "recommendations": recommendations,
        }
        rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
        if args.output:
            args.output.write_text(rendered, encoding="utf-8")
        else:
            print(rendered, end="")
        return 0
    else:
        if not args.output:
            parser.error("--format tsv requires --output")
        write_tsv(args.output, pair_rows)
        return 0

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
