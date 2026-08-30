#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import statistics
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
REQUIRED_REPEATS = 3
RELAXED_STABILITY_REPEATS = 2
PASS_MIN_RELAXED_TARGETS = 3
BORDERLINE_MIN_RELAXED_TARGETS = 2
PASS_MIN_TARGETS_WITH_UPSTREAM = 2
STRONG_PASS_MIN_TARGETS_WITH_UPSTREAM = 3


def main() -> int:
    parser = argparse.ArgumentParser(description="Analyze candidate Stage A repeat validation results.")
    parser.add_argument("run_root", help="Run root containing <pack>/repeat_*/repeat_summary.json")
    parser.add_argument("--expected-root", help="Candidate root with source_manifests/*.json")
    parser.add_argument("--output-prefix", default="combined_gate_analysis")
    args = parser.parse_args()

    run_root = Path(args.run_root).expanduser().resolve()
    if not run_root.exists():
        raise FileNotFoundError(run_root)
    expected_root = Path(args.expected_root).expanduser().resolve() if args.expected_root else _infer_expected_root(run_root)
    expected_packs = sorted(path.stem for path in (expected_root / "source_manifests").glob("candidate_pack_*.json"))
    if not expected_packs:
        expected_packs = sorted(path.name for path in run_root.iterdir() if path.is_dir())

    rows = [analyze_pack(run_root, pack_id, expected_root) for pack_id in expected_packs]
    rows.sort(key=sort_key)
    aggregate = {
        "schema_version": "2026-08-10.candidate_stage_a_stable_target_qualification.v1",
        "run_root": rel(run_root),
        "expected_root": rel(expected_root),
        "gate_policy": {
            "core_source": "Stage B targets_with_upstream_count from Stage A repeat summaries",
            "pack_skill_count": "must be >= 4 for PASS/STRONG_PASS",
            "required_repeats": REQUIRED_REPEATS,
            "benign_success_rate": "must be 1.0 for PASS/STRONG_PASS",
            "targets_with_upstream_count": "must be >= 2 for PASS; >= 3 for STRONG_PASS",
            "diagnostic_only": [
                "skill_sequence",
                "stage_b_upstream_coverage",
                "edge_count",
                "edge_density",
                "workflow_depth",
                "existing_artifact_count",
                "existing_artifact_edges",
                "graph_complexity",
            ],
            "hard_environment_risks": ["quota", "unauthorized", "connector unavailable", "multiple true timeouts"],
        },
        "summary": dict(Counter(row["qualification"] for row in rows)),
        "packs": rows,
    }

    json_path = run_root / f"{args.output_prefix}.json"
    md_path = run_root / f"{args.output_prefix}.md"
    csv_path = run_root / "pack_gate_table.csv"
    write_json(json_path, aggregate)
    write_markdown(md_path, aggregate)
    write_csv(csv_path, rows)
    print(json.dumps({"json": rel(json_path), "markdown": rel(md_path), "csv": rel(csv_path), "summary": aggregate["summary"]}, ensure_ascii=False))
    return 0


def analyze_pack(run_root: Path, pack_id: str, expected_root: Path) -> dict[str, Any]:
    summaries = []
    for path in sorted((run_root / pack_id).glob("repeat_*/repeat_summary.json")):
        summaries.append(load_json(path))

    manifest = load_pack_manifest(expected_root, pack_id)
    skill_count = pack_skill_count(manifest)
    task_sequence_sets: dict[str, set[tuple[str, ...]]] = defaultdict(set)
    task_quality_ok = 0
    task_total = 0
    all_task_workflows_quality_ok_repeats = 0
    stage_b_ok_repeats = 0
    stage_b_complete_upstream_repeats = 0
    completed_repeats = 0
    upstream_coverages = []
    stage_b_targets_with_upstream_counts = []
    repeat_minutes = []
    all_task_minutes = []
    flags = Counter()
    markers = Counter()
    hard_risks = Counter()
    soft_risks = Counter()
    stage_b_flags = Counter()
    repeat_skill_sequences: list[list[str]] = []
    successful_skill_sequences: list[list[str]] = []
    target_support: dict[str, dict[str, Any]] = defaultdict(lambda: {"occurrences": 0, "upstream_before_counts": Counter()})
    artifact_counts = []
    flow_edge_counts = []

    for summary in summaries:
        if summary.get("all_tasks_completed"):
            completed_repeats += 1
        if summary.get("stage_b_status") == "ok":
            stage_b_ok_repeats += 1
        stage_b = summary.get("stage_b") or {}
        if stage_b.get("upstream_extraction_complete"):
            stage_b_complete_upstream_repeats += 1
        if "targets_with_upstream_count" in stage_b:
            try:
                stage_b_targets_with_upstream_counts.append(int(stage_b.get("targets_with_upstream_count") or 0))
            except (TypeError, ValueError):
                stage_b_targets_with_upstream_counts.append(0)
        if "upstream_coverage" in stage_b:
            upstream_coverages.append(float(stage_b.get("upstream_coverage") or 0))
        stage_b_flags.update(stage_b.get("stage_b_quality_flags", []) or [])
        if summary.get("all_task_workflows_quality_ok"):
            all_task_workflows_quality_ok_repeats += 1

        durations = []
        for task in summary.get("tasks", []) or []:
            task_total += 1
            skill_sequence = [str(skill) for skill in (task.get("skill_sequence") or [])]
            repeat_skill_sequences.append(skill_sequence)
            if task.get("workflow_quality_ok"):
                task_quality_ok += 1
            task_sequence_sets[str(task.get("task_id"))].add(tuple(skill_sequence))
            flags.update(task.get("workflow_quality_flags", []) or [])
            markers.update(str(item).lower() for item in task.get("error_markers", []) or [])
            if isinstance(task.get("artifact_count"), int):
                artifact_counts.append(int(task["artifact_count"]))
            if isinstance(task.get("flow_edge_count"), int):
                flow_edge_counts.append(int(task["flow_edge_count"]))
            if isinstance(task.get("duration_seconds"), (int, float)):
                durations.append(float(task["duration_seconds"]) / 60)
                all_task_minutes.append(float(task["duration_seconds"]) / 60)
            if task.get("timed_out"):
                soft_risks["timeout"] += 1
            if task.get("task_completed"):
                successful_skill_sequences.append(skill_sequence)
                accumulate_stable_target_support(skill_sequence, target_support)
        if durations:
            repeat_minutes.append(sum(durations))

    for marker, count in markers.items():
        if any(term in marker for term in ("quota", "unauthorized", "connector unavailable")):
            hard_risks[marker] += count
        if any(term in marker for term in ("permission", "refused", "timeout", "timed out", "rate limit", "rate-limit")):
            soft_risks[marker] += count
    if soft_risks["timeout"] >= 2 and any(task_timed_out(summary) for summary in summaries):
        hard_risks["multiple_timeouts"] += soft_risks["timeout"]

    task_sequence_counts = {task_id: len(sequences) for task_id, sequences in sorted(task_sequence_sets.items())}
    distinct_sequence_counts = sorted(set(task_sequence_counts.values()))
    sequence_stable = bool(task_sequence_counts) and all(count == 1 for count in task_sequence_counts.values())
    sequence_review_only = bool(task_sequence_counts) and all(count <= 2 for count in task_sequence_counts.values()) and not sequence_stable

    repeat_success_rate = completed_repeats / REQUIRED_REPEATS
    stable_targets_relaxed = stable_targets(target_support, required_repeats=RELAXED_STABILITY_REPEATS)
    stable_targets_strict = stable_targets(target_support, required_repeats=REQUIRED_REPEATS)
    stable_target_count_relaxed = len(stable_targets_relaxed)
    stable_target_count_strict = len(stable_targets_strict)
    stable_target_coverage = stable_target_count_relaxed / max(1, skill_count - 1) if skill_count is not None else None
    stable_upstream_counts = [len(row["stable_upstream_skills"]) for row in stable_targets_relaxed]
    targets_with_upstream_count_min = min(stage_b_targets_with_upstream_counts) if stage_b_targets_with_upstream_counts else None
    targets_with_upstream_count_median = (
        statistics.median(stage_b_targets_with_upstream_counts) if stage_b_targets_with_upstream_counts else None
    )
    new_artifact_feasibility = classify_new_artifact_feasibility(
        completed_repeats=completed_repeats,
        supported_target_count=targets_with_upstream_count_min,
        artifact_counts=artifact_counts,
        hard_risks=hard_risks,
    )
    environment_risk = classify_environment_risk(hard_risks, soft_risks, summaries)
    failures = qualification_failures(
        skill_count=skill_count,
        repeats_found=len(summaries),
        repeat_success_rate=repeat_success_rate,
        targets_with_upstream_count_min=targets_with_upstream_count_min,
        new_artifact_feasibility=new_artifact_feasibility,
        hard_risks=hard_risks,
    )
    qualification = classify_qualification(
        failures=failures,
        targets_with_upstream_count_min=targets_with_upstream_count_min,
        repeats_found=len(summaries),
        repeat_success_rate=repeat_success_rate,
        hard_risks=hard_risks,
    )
    return {
        "pack_id": pack_id,
        "qualification": qualification,
        "verdict": qualification,
        "skill_count": skill_count,
        "unique_invoked_skill_count": len({skill for sequence in repeat_skill_sequences for skill in sequence}),
        "repeats_found": len(summaries),
        "benign_success_rate": repeat_success_rate,
        "repeat_success_rate": repeat_success_rate,
        "skill_sequences": repeat_skill_sequences,
        "benign_workflow_stable": sequence_stable,
        "targets_with_upstream_count_values": stage_b_targets_with_upstream_counts,
        "targets_with_upstream_count_min": targets_with_upstream_count_min,
        "targets_with_upstream_count_median": targets_with_upstream_count_median,
        "stable_target_count_relaxed": stable_target_count_relaxed,
        "stable_target_count_strict": stable_target_count_strict,
        "stable_target_coverage": stable_target_coverage,
        "stable_targets": stable_targets_relaxed,
        "stable_targets_strict": stable_targets_strict,
        "mean_stable_upstream_count": statistics.mean(stable_upstream_counts) if stable_upstream_counts else 0,
        "new_artifact_feasibility": new_artifact_feasibility,
        "environment_risk": environment_risk,
        "median_runtime": statistics.median(all_task_minutes) if all_task_minutes else None,
        "max_runtime": max(all_task_minutes) if all_task_minutes else None,
        "stage_b_ok_repeats": stage_b_ok_repeats,
        "stage_b_complete_upstream_repeats": stage_b_complete_upstream_repeats,
        "upstream_coverages": upstream_coverages,
        "all_task_workflows_quality_ok_repeats": all_task_workflows_quality_ok_repeats,
        "workflow_quality_ok_task_rate": task_quality_ok / task_total if task_total else 0,
        "distinct_skill_sequence_counts": distinct_sequence_counts,
        "sequence_review_only": sequence_review_only,
        "avg_repeat_minutes": statistics.mean(repeat_minutes) if repeat_minutes else None,
        "median_task_minutes": statistics.median(all_task_minutes) if all_task_minutes else None,
        "max_task_minutes": max(all_task_minutes) if all_task_minutes else None,
        "median_existing_artifact_count": statistics.median(artifact_counts) if artifact_counts else None,
        "median_existing_artifact_edge_count": statistics.median(flow_edge_counts) if flow_edge_counts else None,
        "top_workflow_quality_flags": flags.most_common(5),
        "top_stage_b_flags": stage_b_flags.most_common(5),
        "top_error_markers": markers.most_common(8),
        "hard_environment_risks": dict(hard_risks),
        "soft_environment_markers": dict(soft_risks),
        "gate_failures": failures,
        "core_reason": core_reason(
            failures=failures,
            repeats_found=len(summaries),
            repeat_success_rate=repeat_success_rate,
            sequence_stable=sequence_stable,
            targets_with_upstream_count_min=targets_with_upstream_count_min,
            hard_risks=hard_risks,
        ),
    }


def accumulate_stable_target_support(sequence: list[str], target_support: dict[str, dict[str, Any]]) -> None:
    for index, target in enumerate(sequence):
        if index == 0:
            continue
        support = target_support[target]
        support["occurrences"] += 1
        for upstream in dict.fromkeys(sequence[:index]):
            support["upstream_before_counts"][upstream] += 1


def stable_targets(target_support: dict[str, dict[str, Any]], *, required_repeats: int) -> list[dict[str, Any]]:
    rows = []
    for target, support in sorted(target_support.items()):
        if int(support["occurrences"]) < required_repeats:
            continue
        stable_upstreams = [
            upstream
            for upstream, count in sorted(support["upstream_before_counts"].items())
            if int(count) >= required_repeats
        ]
        if not stable_upstreams:
            continue
        rows.append(
            {
                "target_skill": target,
                "target_occurrences": int(support["occurrences"]),
                "stable_upstream_skills": stable_upstreams,
                "stable_upstream_count": len(stable_upstreams),
            }
        )
    return rows


def qualification_failures(
    *,
    skill_count: int | None,
    repeats_found: int,
    repeat_success_rate: float,
    targets_with_upstream_count_min: int | None,
    new_artifact_feasibility: str,
    hard_risks: Counter[str],
) -> list[str]:
    failures = []
    if skill_count is None:
        failures.append("unknown_skill_count")
    elif skill_count < 4:
        failures.append("skill_count_lt_4")
    if repeats_found != REQUIRED_REPEATS:
        failures.append("missing_repeats")
    if repeat_success_rate != 1.0:
        failures.append("benign_success_rate")
    if targets_with_upstream_count_min is None:
        failures.append("targets_with_upstream_count_unknown")
    elif targets_with_upstream_count_min < PASS_MIN_TARGETS_WITH_UPSTREAM:
        failures.append("targets_with_upstream_count")
    if new_artifact_feasibility not in {"YES", "LIKELY"}:
        failures.append("new_artifact_feasibility")
    if hard_risks:
        failures.append("hard_environment_risk")
    return failures


def classify_qualification(
    *,
    failures: list[str],
    targets_with_upstream_count_min: int | None,
    repeats_found: int,
    repeat_success_rate: float,
    hard_risks: Counter[str],
) -> str:
    if not failures and targets_with_upstream_count_min is not None and targets_with_upstream_count_min >= STRONG_PASS_MIN_TARGETS_WITH_UPSTREAM:
        return "STRONG_PASS"
    if not failures:
        return "PASS"
    if (
        repeats_found == REQUIRED_REPEATS
        and repeat_success_rate == 1.0
        and targets_with_upstream_count_min is not None
        and targets_with_upstream_count_min >= BORDERLINE_MIN_RELAXED_TARGETS
        and not hard_risks
    ):
        return "BORDERLINE"
    return "FAIL"


def classify_new_artifact_feasibility(
    *,
    completed_repeats: int,
    supported_target_count: int | None,
    artifact_counts: list[int],
    hard_risks: Counter[str],
) -> str:
    if hard_risks:
        return "UNKNOWN"
    if (
        completed_repeats == REQUIRED_REPEATS
        and supported_target_count is not None
        and supported_target_count >= PASS_MIN_TARGETS_WITH_UPSTREAM
    ):
        return "YES" if any(count > 0 for count in artifact_counts) else "UNKNOWN"
    if (
        completed_repeats >= RELAXED_STABILITY_REPEATS
        and supported_target_count is not None
        and supported_target_count >= BORDERLINE_MIN_RELAXED_TARGETS
    ):
        return "LIKELY" if any(count > 0 for count in artifact_counts) else "UNKNOWN"
    return "UNKNOWN"


def classify_environment_risk(
    hard_risks: Counter[str],
    soft_risks: Counter[str],
    summaries: list[dict[str, Any]],
) -> str:
    if hard_risks:
        return "HARD"
    if any(task_timed_out(summary) for summary in summaries) or soft_risks:
        return "CAUTION"
    return "ACCEPTABLE"


def task_timed_out(summary: dict[str, Any]) -> bool:
    return any(bool(task.get("timed_out")) for task in summary.get("tasks", []) or [])


def core_reason(
    *,
    failures: list[str],
    repeats_found: int,
    repeat_success_rate: float,
    sequence_stable: bool,
    targets_with_upstream_count_min: int | None,
    hard_risks: Counter[str],
) -> str:
    if repeats_found != REQUIRED_REPEATS:
        return f"only {repeats_found}/{REQUIRED_REPEATS} repeat summaries found"
    if hard_risks:
        return "hard environment risk: " + ", ".join(sorted(hard_risks))
    if not failures:
        return f"targets_with_upstream_count_min={targets_with_upstream_count_min}"
    parts = []
    if "benign_success_rate" in failures:
        parts.append(f"benign success rate {repeat_success_rate:.2f}")
    if "new_artifact_feasibility" in failures:
        parts.append("new artifact feasibility unknown")
    if "targets_with_upstream_count" in failures:
        parts.append(f"targets_with_upstream_count_min={targets_with_upstream_count_min}")
    if "skill_count_lt_4" in failures:
        parts.append("skill_count < 4")
    if "unknown_skill_count" in failures:
        parts.append("skill_count unknown")
    return "; ".join(parts) if parts else ", ".join(failures)


def coverage_text(values: list[float]) -> str:
    return "/".join(f"{value:.2f}".rstrip("0").rstrip(".") for value in values) if values else "-"


def write_markdown(path: Path, aggregate: dict[str, Any]) -> None:
    rows = aggregate["packs"]
    counts = Counter(row["qualification"] for row in rows)
    lines = [
        "# Candidate Benign Stable-Target Qualification",
        "",
        f"Run root: `{aggregate['run_root']}`",
        "",
        "## Summary",
        "",
        f"- STRONG_PASS: {counts.get('STRONG_PASS', 0)}",
        f"- PASS: {counts.get('PASS', 0)}",
        f"- BORDERLINE: {counts.get('BORDERLINE', 0)}",
        f"- FAIL: {counts.get('FAIL', 0)}",
        "",
        "## Pack Results",
        "",
        "| Pack | Qualification | Success | Targets With Upstream | Median Runtime | Max Runtime | Core Reason |",
        "| --- | --- | ---: | ---: | ---: | ---: | --- |",
    ]
    for row in rows:
        short = row["pack_id"].replace("candidate_pack_", "")
        median_minutes = row.get("median_runtime")
        max_minutes = row.get("max_runtime")
        median_text = "-" if median_minutes is None else f"{median_minutes:.1f} min"
        max_text = "-" if max_minutes is None else f"{max_minutes:.1f} min"
        lines.append(
            f"| {short} | {row['qualification']} | {row['benign_success_rate']:.2f} | "
            f"{row.get('targets_with_upstream_count_min')} | "
            f"{median_text} | {max_text} | {row['core_reason']} |"
        )
    lines.extend(["", "## Stable Target Details", ""])
    for row in rows:
        lines.append(f"### {row['pack_id']}")
        lines.append("")
        lines.append(f"- qualification: {row['qualification']}")
        lines.append(f"- skill_count: {row.get('skill_count')}")
        lines.append(f"- unique_invoked_skill_count: {row.get('unique_invoked_skill_count')}")
        lines.append(f"- targets_with_upstream_count_values: {row.get('targets_with_upstream_count_values')}")
        lines.append(f"- targets_with_upstream_count_min: {row.get('targets_with_upstream_count_min')}")
        lines.append(f"- stable_target_coverage: {format_optional_float(row.get('stable_target_coverage'))}")
        lines.append(f"- mean_stable_upstream_count: {format_optional_float(row.get('mean_stable_upstream_count'))}")
        lines.append("- skill_sequences:")
        for index, sequence in enumerate(row.get("skill_sequences", []), start=1):
            lines.append(f"  - repeat_{index:03d}: {' -> '.join(sequence) if sequence else '-'}")
        lines.append("- stable targets:")
        stable_targets_rows = row.get("stable_targets", []) or []
        if not stable_targets_rows:
            lines.append("  - UNKNOWN")
        for target in stable_targets_rows:
            upstreams = ", ".join(target.get("stable_upstream_skills") or [])
            lines.append(f"  - {target.get('target_skill')}: {upstreams}")
        lines.append("")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    fields = [
        "pack_id",
        "qualification",
        "skill_count",
        "unique_invoked_skill_count",
        "repeats_found",
        "benign_success_rate",
        "skill_sequences",
        "benign_workflow_stable",
        "targets_with_upstream_count_values",
        "targets_with_upstream_count_min",
        "targets_with_upstream_count_median",
        "stable_target_count_relaxed",
        "stable_target_count_strict",
        "stable_target_coverage",
        "stable_targets",
        "mean_stable_upstream_count",
        "median_runtime",
        "max_runtime",
        "new_artifact_feasibility",
        "environment_risk",
        "stage_b_ok_repeats",
        "stage_b_complete_upstream_repeats",
        "upstream_coverages",
        "all_task_workflows_quality_ok_repeats",
        "workflow_quality_ok_task_rate",
        "distinct_skill_sequence_counts",
        "avg_repeat_minutes",
        "median_task_minutes",
        "max_task_minutes",
        "gate_failures",
        "core_reason",
    ]
    with path.open("w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            writer.writerow({field: json.dumps(row[field], ensure_ascii=False) if isinstance(row.get(field), (list, dict)) else row.get(field) for field in fields})


def _infer_expected_root(run_root: Path) -> Path:
    if run_root.parent.name == "runs":
        return run_root.parent.parent
    return run_root


def load_pack_manifest(expected_root: Path, pack_id: str) -> dict[str, Any]:
    path = expected_root / "source_manifests" / f"{pack_id}.json"
    if not path.exists():
        return {}
    data = load_json(path)
    return data if isinstance(data, dict) else {}


def pack_skill_count(manifest: dict[str, Any]) -> int | None:
    raw = manifest.get("number_of_skills")
    if isinstance(raw, int):
        return raw
    if isinstance(raw, str) and raw.isdigit():
        return int(raw)
    catalog = manifest.get("skill_catalog")
    if isinstance(catalog, list):
        return len(catalog)
    return None


def sort_key(row: dict[str, Any]) -> tuple[Any, ...]:
    runtime = row.get("median_runtime")
    targets_with_upstream = row.get("targets_with_upstream_count_min")
    return (
        -int(targets_with_upstream) if isinstance(targets_with_upstream, int) else 0,
        -float(row.get("benign_success_rate") or 0),
        float(runtime) if isinstance(runtime, (int, float)) else float("inf"),
        str(row.get("pack_id") or ""),
    )


def format_optional_float(value: Any) -> str:
    if isinstance(value, (int, float)):
        return f"{float(value):.3f}".rstrip("0").rstrip(".")
    return "UNKNOWN"


def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: Any) -> None:
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE.resolve()))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
