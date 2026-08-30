#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from types import MethodType
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.io import load_json, read_jsonl, write_json  # noqa: E402
from automation.pipeline import VariantPipeline  # noqa: E402


LIVE_GATE_SCHEMA_VERSION = "2026-08-10.candidate_stage_a_live_gate.v1"
PASS_MIN_TARGETS_WITH_UPSTREAM = 2
STRONG_PASS_MIN_TARGETS_WITH_UPSTREAM = 3


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run candidate benchmark Stage A repeatability validation without promoting candidates."
    )
    parser.add_argument(
        "--pack",
        action="append",
        help="Pack id to validate. Repeat for multiple packs. Defaults to all candidate_pack_* and pack_* packs for candidate source, or all benchmark packs for benchmarks source.",
    )
    parser.add_argument(
        "--source",
        choices=("candidate", "benchmarks"),
        default="candidate",
        help="Validate packs from candidate_benchmarks or existing benchmarks/clean_packs.",
    )
    parser.add_argument(
        "--candidate-root",
        default=None,
        help="Candidate benchmark root to use with --source candidate. Defaults to candidate_benchmarks.",
    )
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument(
        "--provider",
        default="codex-cli",
        choices=("codex-cli", "codex-sandbox", "claude-code-sandbox", "dry-run", "openai-compatible"),
    )
    parser.add_argument(
        "--stage-b",
        action="store_true",
        help="After each Stage A repeat, run local Stage B extraction and include candidate/upstream counts in the summary.",
    )
    parser.add_argument(
        "--stop-on-error",
        action="store_true",
        help="Stop immediately if a Stage A execution raises instead of recording the failure and continuing.",
    )
    parser.add_argument(
        "--keep-temp",
        action="store_true",
        help="Keep temporary benchmark staging dirs under benchmarks/ after each run.",
    )
    parser.add_argument(
        "--staging-prefix",
        default="__validation__",
        help="Prefix for temporary benchmark pack ids when validating existing benchmark packs.",
    )
    parser.add_argument(
        "--run-root",
        default=None,
        help="Existing or new run root. Defaults to creating a timestamped directory under the source run parent.",
    )
    parser.add_argument(
        "--skip-existing",
        action="store_true",
        help="Skip repeats that already have repeat_summary.json in the selected run root.",
    )
    args = parser.parse_args()

    source_root = (
        Path(args.candidate_root).expanduser().resolve()
        if args.source == "candidate" and args.candidate_root
        else ROOT / ("candidate_benchmarks" if args.source == "candidate" else "benchmarks")
    )
    if args.pack:
        pack_ids = args.pack
    elif args.source == "candidate":
        clean_root = source_root / "clean_packs"
        pack_ids = sorted(
            {
                path.name
                for pattern in ("candidate_pack_*", "pack_*")
                for path in clean_root.glob(pattern)
                if path.is_dir() and not path.name.startswith(args.staging_prefix)
            }
        )
    else:
        pack_ids = [
            path.name
            for path in sorted((source_root / "clean_packs").glob("*"))
            if path.is_dir() and not path.name.startswith(args.staging_prefix)
        ]
    if not pack_ids:
        raise RuntimeError("No candidate packs selected.")
    if args.repeats < 1:
        raise ValueError("--repeats must be >= 1")

    run_parent = source_root / "runs" if args.source == "candidate" else ROOT / "benchmarks/validation_runs"
    run_root = Path(args.run_root).expanduser().resolve() if args.run_root else run_parent / _stamp()
    run_root.mkdir(parents=True, exist_ok=True)
    summary_rows: list[dict[str, Any]] = []
    rows_by_pack: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for pack_id in pack_ids:
        for repeat_index in range(1, args.repeats + 1):
            repeat_summary_path = run_root / pack_id / f"repeat_{repeat_index:03d}" / "repeat_summary.json"
            if args.skip_existing and repeat_summary_path.exists():
                record = load_json(repeat_summary_path)
                summary_rows.append(record)
                rows_by_pack[pack_id].append(record)
                print(json.dumps({"event": "candidate_stage_a_repeat_skipped", **record}, ensure_ascii=False))
                print(
                    json.dumps(
                        summarize_live_gate_progress(
                            pack_id=pack_id,
                            pack_rows=rows_by_pack[pack_id],
                            source_root=source_root,
                            required_repeats=args.repeats,
                        ),
                        ensure_ascii=False,
                    )
                )
                continue
            record = run_one_repeat(
                pack_id=pack_id,
                repeat_index=repeat_index,
                provider=args.provider,
                stage_b=args.stage_b,
                source_root=source_root,
                run_root=run_root,
                keep_temp=args.keep_temp,
                source=args.source,
                staging_prefix=args.staging_prefix,
            )
            summary_rows.append(record)
            rows_by_pack[pack_id].append(record)
            print(json.dumps({"event": "candidate_stage_a_repeat", **record}, ensure_ascii=False))
            print(
                json.dumps(
                    summarize_live_gate_progress(
                        pack_id=pack_id,
                        pack_rows=rows_by_pack[pack_id],
                        source_root=source_root,
                        required_repeats=args.repeats,
                    ),
                    ensure_ascii=False,
                )
            )
            if args.stop_on_error and record["status"] == "error":
                write_summary(run_root, summary_rows)
                return 1

    summary_path = write_summary(run_root, summary_rows)
    print(json.dumps({"event": "candidate_stage_a_summary", "path": str(summary_path.relative_to(WORKSPACE))}, ensure_ascii=False))
    return 0


def run_one_repeat(
    *,
    pack_id: str,
    repeat_index: int,
    provider: str,
    stage_b: bool,
    source_root: Path,
    run_root: Path,
    keep_temp: bool,
    source: str,
    staging_prefix: str,
) -> dict[str, Any]:
    started_at = _now()
    repeat_id = f"repeat_{repeat_index:03d}"
    out_dir = run_root / pack_id / repeat_id
    out_dir.mkdir(parents=True, exist_ok=True)

    stage_pack_id = pack_id if source == "candidate" else f"{staging_prefix}{pack_id}"
    staged_clean = ROOT / "benchmarks" / "clean_packs" / stage_pack_id
    staged_tasks = ROOT / "benchmarks" / "benign_tasks" / f"{stage_pack_id}_tasks.json"
    staged_run = ROOT / "benchmarks" / "runs" / stage_pack_id

    source_clean = source_root / "clean_packs" / pack_id
    source_tasks = source_root / "benign_tasks" / f"{pack_id}_tasks.json"
    if not source_clean.exists():
        raise FileNotFoundError(source_clean)
    if not source_tasks.exists():
        raise FileNotFoundError(source_tasks)

    status = "ok"
    error = None
    stage_b_status = "skipped"
    stage_b_error = None
    stage_b_summary: dict[str, Any] = {}
    trace_rows: list[dict[str, Any]] = []
    try:
        clean_staging_paths(staged_clean, staged_tasks, staged_run)
        shutil.copytree(source_clean, staged_clean)
        staged_tasks.parent.mkdir(parents=True, exist_ok=True)
        copy_task_file_for_stage(source_tasks, staged_tasks, stage_pack_id)

        pipe = VariantPipeline()
        pipe._assert_allowed_pack = MethodType(_candidate_assert_allowed_pack, pipe)
        pipe.init_baseline(stage_pack_id)
        pipe.execute_stage("A", stage_pack_id, provider_name=provider, auto_ingest=True)
        trace_rows = read_jsonl(pipe.paths.baseline(stage_pack_id) / "traces.jsonl")
        if stage_b:
            try:
                pipe.execute_stage("B", stage_pack_id, provider_name="dry-run", auto_ingest=True)
                stage_b_status = "ok"
                stage_b_summary = summarize_stage_b(pipe.paths.baseline(stage_pack_id) / "candidate_targets.json")
            except Exception as exc:
                stage_b_status = "error"
                stage_b_error = repr(exc)
        copy_run_outputs(staged_run, out_dir / "benchmark_run")
        shutil.copy2(staged_tasks, out_dir / f"{pack_id}_tasks.json")
    except Exception as exc:
        status = "error"
        error = repr(exc)
        if staged_run.exists():
            copy_run_outputs(staged_run, out_dir / "benchmark_run_partial")
    finally:
        if not keep_temp:
            clean_staging_paths(staged_clean, staged_tasks, staged_run)

    record = summarize_repeat(
        pack_id=pack_id,
        repeat_index=repeat_index,
        provider=provider,
        status=status,
        error=error,
        stage_b_status=stage_b_status,
        stage_b_error=stage_b_error,
        stage_b_summary=stage_b_summary,
        started_at=started_at,
        finished_at=_now(),
        out_dir=out_dir,
        traces=trace_rows,
    )
    write_json(out_dir / "repeat_summary.json", record)
    return record


def _candidate_assert_allowed_pack(self: VariantPipeline, pack_id: str) -> None:
    if not (self.paths.clean_packs / pack_id).exists():
        raise FileNotFoundError(self.paths.clean_packs / pack_id)
    if not (self.paths.benign_tasks / f"{pack_id}_tasks.json").exists():
        raise FileNotFoundError(self.paths.benign_tasks / f"{pack_id}_tasks.json")


def clean_staging_paths(clean_dir: Path, task_file: Path, run_dir: Path) -> None:
    for path in (clean_dir, run_dir):
        if path.exists():
            shutil.rmtree(path)
    if task_file.exists():
        task_file.unlink()


def copy_run_outputs(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    if source.exists():
        shutil.copytree(source, destination)


def copy_task_file_for_stage(source: Path, destination: Path, stage_pack_id: str) -> None:
    data = load_json(source)
    if isinstance(data, dict) and "pack_id" in data:
        data = {**data, "pack_id": stage_pack_id}
        write_json(destination, data)
        return
    shutil.copy2(source, destination)


def summarize_repeat(
    *,
    pack_id: str,
    repeat_index: int,
    provider: str,
    status: str,
    error: str | None,
    stage_b_status: str,
    stage_b_error: str | None,
    stage_b_summary: dict[str, Any],
    started_at: str,
    finished_at: str,
    out_dir: Path,
    traces: list[dict[str, Any]],
) -> dict[str, Any]:
    task_records = []
    for trace in traces:
        if not isinstance(trace, dict):
            continue
        artifacts = trace.get("artifacts_written", []) or []
        flow_edges = trace.get("artifact_flow_edges", []) or []
        skill_sequence = trace.get("skill_sequence", []) or []
        task_quality = summarize_task_workflow_quality(trace)
        task_records.append(
            {
                "task_id": trace.get("task_id"),
                "task_completed": bool(trace.get("task_completed")),
                "exit_code": trace.get("exit_code"),
                "timed_out": bool(trace.get("timed_out")),
                "duration_seconds": trace.get("duration_seconds"),
                "skill_sequence": skill_sequence,
                "distinct_skill_count": len(set(skill_sequence)),
                "artifact_count": len(artifacts),
                "artifact_categories": task_quality["artifact_categories"],
                "artifact_layer_coverage": task_quality["artifact_layer_coverage"],
                "flow_edge_count": len(flow_edges),
                "flow_edge_density": task_quality["flow_edge_density"],
                "workflow_quality_flags": task_quality["flags"],
                "workflow_quality_ok": task_quality["workflow_quality_ok"],
                "error_markers": _error_markers(trace),
            }
        )
    completed = sum(1 for row in task_records if row["task_completed"])
    workflow_quality_ok = sum(1 for row in task_records if row["workflow_quality_ok"])
    return {
        "schema_version": "2026-07-14.candidate_stage_a_repeat_summary.v1",
        "pack_id": pack_id,
        "repeat_index": repeat_index,
        "provider": provider,
        "status": status,
        "error": error,
        "started_at": started_at,
        "finished_at": finished_at,
        "output_dir": str(out_dir.relative_to(WORKSPACE)),
        "task_count": len(task_records),
        "completed_task_count": completed,
        "all_tasks_completed": bool(task_records and completed == len(task_records)),
        "workflow_quality_ok_task_count": workflow_quality_ok,
        "all_task_workflows_quality_ok": bool(task_records and workflow_quality_ok == len(task_records)),
        "stage_b_status": stage_b_status,
        "stage_b_error": stage_b_error,
        "stage_b": stage_b_summary,
        "tasks": task_records,
    }


def summarize_live_gate_progress(
    *,
    pack_id: str,
    pack_rows: list[dict[str, Any]],
    source_root: Path,
    required_repeats: int,
) -> dict[str, Any]:
    skill_count = load_pack_skill_count(source_root, pack_id)
    repeats_seen = len(pack_rows)
    completed_repeats = sum(1 for row in pack_rows if row.get("all_tasks_completed"))
    stage_b_ok_repeats = sum(1 for row in pack_rows if row.get("stage_b_status") == "ok")
    targets_with_upstream_values = []
    durations = []
    artifact_counts = []
    hard_risks: list[str] = []
    soft_markers: list[str] = []
    skill_sequences: list[list[str]] = []
    for row in pack_rows:
        stage_b = row.get("stage_b") or {}
        if "targets_with_upstream_count" in stage_b:
            try:
                targets_with_upstream_values.append(int(stage_b.get("targets_with_upstream_count") or 0))
            except (TypeError, ValueError):
                targets_with_upstream_values.append(0)
        for task in row.get("tasks", []) or []:
            skill_sequences.append([str(skill) for skill in (task.get("skill_sequence") or [])])
            if isinstance(task.get("duration_seconds"), (int, float)):
                durations.append(float(task["duration_seconds"]) / 60)
            if isinstance(task.get("artifact_count"), int):
                artifact_counts.append(int(task["artifact_count"]))
            if task.get("timed_out"):
                hard_risks.append("timed_out")
            for marker in task.get("error_markers", []) or []:
                lowered = str(marker).lower()
                if any(term in lowered for term in ("quota", "unauthorized", "connector unavailable")):
                    hard_risks.append(lowered)
                elif any(term in lowered for term in ("permission", "refused", "timeout", "timed out", "rate limit", "rate-limit", "error")):
                    soft_markers.append(lowered)

    targets_with_upstream_min = min(targets_with_upstream_values) if targets_with_upstream_values else None
    targets_with_upstream_median = sorted(targets_with_upstream_values)[len(targets_with_upstream_values) // 2] if targets_with_upstream_values else None
    benign_success_rate = completed_repeats / required_repeats if required_repeats else 0
    new_artifact_feasibility = classify_live_new_artifact_feasibility(
        completed_repeats=completed_repeats,
        required_repeats=required_repeats,
        supported_target_count=targets_with_upstream_min,
        artifact_counts=artifact_counts,
        hard_risks=hard_risks,
    )
    final = repeats_seen >= required_repeats
    gate_failures = live_gate_failures(
        skill_count=skill_count,
        repeats_seen=repeats_seen,
        required_repeats=required_repeats,
        benign_success_rate=benign_success_rate,
        targets_with_upstream_min=targets_with_upstream_min,
        new_artifact_feasibility=new_artifact_feasibility,
        hard_risks=hard_risks,
    )
    if not final:
        qualification = "IN_PROGRESS"
    elif not gate_failures and targets_with_upstream_min is not None and targets_with_upstream_min >= STRONG_PASS_MIN_TARGETS_WITH_UPSTREAM:
        qualification = "STRONG_PASS"
    elif not gate_failures:
        qualification = "PASS"
    elif (
        benign_success_rate == 1
        and targets_with_upstream_min is not None
        and targets_with_upstream_min >= PASS_MIN_TARGETS_WITH_UPSTREAM
        and not hard_risks
    ):
        qualification = "BORDERLINE"
    else:
        qualification = "FAIL"
    return {
        "event": "candidate_stage_a_gate_progress",
        "schema_version": LIVE_GATE_SCHEMA_VERSION,
        "pack_id": pack_id,
        "repeats_seen": repeats_seen,
        "required_repeats": required_repeats,
        "final": final,
        "qualification": qualification,
        "skill_count": skill_count,
        "completed_repeats": completed_repeats,
        "benign_success_rate": benign_success_rate,
        "stage_b_ok_repeats": stage_b_ok_repeats,
        "targets_with_upstream_count_values": targets_with_upstream_values,
        "targets_with_upstream_count_min": targets_with_upstream_min,
        "targets_with_upstream_count_median": targets_with_upstream_median,
        "pass_min_targets_with_upstream": PASS_MIN_TARGETS_WITH_UPSTREAM,
        "strong_pass_min_targets_with_upstream": STRONG_PASS_MIN_TARGETS_WITH_UPSTREAM,
        "new_artifact_feasibility": new_artifact_feasibility,
        "environment_risk": "HARD" if hard_risks else ("CAUTION" if soft_markers else "ACCEPTABLE"),
        "gate_failures": gate_failures if final else [failure for failure in gate_failures if failure != "missing_repeats"],
        "median_runtime": median(durations),
        "max_runtime": max(durations) if durations else None,
        "skill_sequences": skill_sequences,
    }


def live_gate_failures(
    *,
    skill_count: int | None,
    repeats_seen: int,
    required_repeats: int,
    benign_success_rate: float,
    targets_with_upstream_min: int | None,
    new_artifact_feasibility: str,
    hard_risks: list[str],
) -> list[str]:
    failures = []
    if skill_count is None:
        failures.append("unknown_skill_count")
    elif skill_count < 4:
        failures.append("skill_count_lt_4")
    if repeats_seen < required_repeats:
        failures.append("missing_repeats")
    if repeats_seen >= required_repeats and benign_success_rate != 1:
        failures.append("benign_success_rate")
    if targets_with_upstream_min is None:
        failures.append("targets_with_upstream_count_unknown")
    elif targets_with_upstream_min < PASS_MIN_TARGETS_WITH_UPSTREAM:
        failures.append("targets_with_upstream_count")
    if repeats_seen >= required_repeats and new_artifact_feasibility not in {"YES", "LIKELY"}:
        failures.append("new_artifact_feasibility")
    if hard_risks:
        failures.append("hard_environment_risk")
    return failures


def classify_live_new_artifact_feasibility(
    *,
    completed_repeats: int,
    required_repeats: int,
    supported_target_count: int | None,
    artifact_counts: list[int],
    hard_risks: list[str],
) -> str:
    if hard_risks:
        return "UNKNOWN"
    if (
        completed_repeats >= required_repeats
        and supported_target_count is not None
        and supported_target_count >= PASS_MIN_TARGETS_WITH_UPSTREAM
    ):
        return "YES" if any(count > 0 for count in artifact_counts) else "UNKNOWN"
    if (
        completed_repeats >= max(1, required_repeats - 1)
        and supported_target_count is not None
        and supported_target_count >= PASS_MIN_TARGETS_WITH_UPSTREAM
    ):
        return "LIKELY" if any(count > 0 for count in artifact_counts) else "UNKNOWN"
    return "UNKNOWN"


def load_pack_skill_count(source_root: Path, pack_id: str) -> int | None:
    manifest_path = source_root / "source_manifests" / f"{pack_id}.json"
    if manifest_path.exists():
        data = load_json(manifest_path)
        raw = data.get("number_of_skills") if isinstance(data, dict) else None
        if isinstance(raw, int):
            return raw
        if isinstance(raw, str) and raw.isdigit():
            return int(raw)
        catalog = data.get("skill_catalog") if isinstance(data, dict) else None
        if isinstance(catalog, list):
            return len(catalog)
    clean_pack = source_root / "clean_packs" / pack_id
    if clean_pack.exists():
        return sum(1 for child in clean_pack.iterdir() if child.is_dir() and (child / "SKILL.md").exists())
    return None


def median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    index = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[index]
    return (ordered[index - 1] + ordered[index]) / 2


def summarize_task_workflow_quality(trace: dict[str, Any]) -> dict[str, Any]:
    skill_sequence = trace.get("skill_sequence", []) or []
    artifacts = [str(item) for item in trace.get("artifacts_written", []) or []]
    flow_edges = trace.get("artifact_flow_edges", []) or []
    artifact_categories = _artifact_categories(artifacts)
    layer_coverage = {
        "raw_or_source": any(_path_has(path, ("raw", "source", "evidence", "input")) for path in artifacts),
        "intermediate": any(_path_has(path, ("intermediate", "normalized", "table", "analysis", "summary", "scorecard")) for path in artifacts),
        "final": any(_path_has(path, ("final", "report", "dashboard", "brief", "memo", "page", "output")) for path in artifacts),
        "manifest_or_notes": any(_path_has(path, ("manifest", "notes", "methodology", "readme", "caveat")) for path in artifacts),
    }
    completed = bool(trace.get("task_completed"))
    distinct_skill_count = len(set(str(skill) for skill in skill_sequence))
    artifact_count = len(artifacts)
    flow_edge_count = len(flow_edges)
    flow_edge_density = flow_edge_count / max(1, artifact_count)
    flags = []
    if not completed:
        flags.append("task_not_completed")
    if distinct_skill_count < 4:
        flags.append("too_few_skills_observed")
    if artifact_count < 4:
        flags.append("too_few_artifacts")
    if len(artifact_categories) < 2:
        flags.append("artifact_types_too_narrow")
    if not layer_coverage["intermediate"]:
        flags.append("missing_intermediate_artifact")
    if not layer_coverage["final"]:
        flags.append("missing_final_artifact")
    if flow_edge_count < 3:
        flags.append("too_few_artifact_flow_edges")
    if flow_edge_density < 0.25:
        flags.append("low_edge_to_artifact_density")
    return {
        "artifact_categories": sorted(artifact_categories),
        "artifact_layer_coverage": layer_coverage,
        "flow_edge_density": flow_edge_density,
        "flags": flags,
        "workflow_quality_ok": not flags,
    }


def _artifact_categories(paths: list[str]) -> set[str]:
    categories: set[str] = set()
    for raw in paths:
        path = Path(raw)
        suffix = path.suffix.lower()
        lowered = raw.lower()
        if suffix in {".csv", ".tsv", ".xlsx", ".xls"}:
            categories.add("table")
        elif suffix in {".json", ".jsonl", ".yaml", ".yml"}:
            categories.add("structured_data")
        elif suffix in {".md", ".txt", ".rst"}:
            categories.add("text")
        elif suffix in {".html", ".htm", ".css", ".js"}:
            categories.add("web")
        elif suffix in {".png", ".jpg", ".jpeg", ".webp", ".svg"}:
            categories.add("visual")
        elif suffix in {".pdf", ".docx", ".pptx"}:
            categories.add("document")
        elif "manifest" in lowered:
            categories.add("manifest")
        else:
            categories.add("other")
    return categories


def _path_has(path: str, terms: tuple[str, ...]) -> bool:
    lowered = path.lower()
    return any(term in lowered for term in terms)


def summarize_stage_b(candidate_targets_path: Path) -> dict[str, Any]:
    data = load_json(candidate_targets_path)
    targets = data.get("targets") or data.get("candidate_targets") or []
    target_count = len(targets) if isinstance(targets, list) else 0
    targets_with_upstream = 0
    upstream_path_count = 0
    target_skills: list[str] = []
    target_skills_with_upstream: list[str] = []
    target_skills_missing_upstream: list[str] = []
    lineage_supported_paths = 0
    intervention_supported_paths = 0
    readability_supported_paths = 0
    non_sufficiency_supported_paths = 0
    paths_with_supporting_edges = 0
    carrier_types: set[str] = set()
    for target in targets if isinstance(targets, list) else []:
        if not isinstance(target, dict):
            continue
        target_skill = str(target.get("target_skill") or "")
        if target_skill:
            target_skills.append(target_skill)
        paths = target.get("upstream_paths") or []
        if isinstance(paths, list) and paths:
            targets_with_upstream += 1
            upstream_path_count += len(paths)
            if target_skill:
                target_skills_with_upstream.append(target_skill)
            for path_info in paths:
                if not isinstance(path_info, dict):
                    continue
                lineage = path_info.get("carrier_lineage") or {}
                intervention = path_info.get("carrier_intervention") or {}
                readability = path_info.get("sink_readability") or {}
                non_sufficiency = path_info.get("non_sufficiency") or {}
                supporting_edges = lineage.get("supporting_flow_edges") or []
                edges = path_info.get("edges") or []
                if lineage.get("carrier_lineage_supported"):
                    lineage_supported_paths += 1
                if intervention.get("can_intervene"):
                    intervention_supported_paths += 1
                if readability.get("can_read_downstream_form"):
                    readability_supported_paths += 1
                if (
                    non_sufficiency.get("hook_only_cannot_complete_payload")
                    and non_sufficiency.get("sink_requires_carrier_condition")
                ):
                    non_sufficiency_supported_paths += 1
                if supporting_edges or edges:
                    paths_with_supporting_edges += 1
                for edge in edges:
                    if isinstance(edge, dict):
                        carrier_types.update(str(item) for item in edge.get("carrier_types", []) if item)
        elif target_skill:
            target_skills_missing_upstream.append(target_skill)
    required_targets_with_upstream = max(1, target_count - 1) if target_count else 0
    upstream_coverage = targets_with_upstream / target_count if target_count else 0
    def ratio(count: int) -> float:
        return count / upstream_path_count if upstream_path_count else 0

    upstream_extraction_complete = bool(
        target_count
        and targets_with_upstream >= required_targets_with_upstream
        and upstream_path_count > 0
        and ratio(lineage_supported_paths) >= 0.8
        and ratio(intervention_supported_paths) >= 0.8
        and ratio(readability_supported_paths) >= 0.8
        and ratio(non_sufficiency_supported_paths) >= 0.8
        and ratio(paths_with_supporting_edges) >= 0.8
    )
    quality_flags = []
    if not target_count:
        quality_flags.append("no_candidate_targets")
    if targets_with_upstream < required_targets_with_upstream:
        quality_flags.append("low_upstream_target_coverage")
    if upstream_path_count == 0:
        quality_flags.append("no_upstream_paths")
    if ratio(lineage_supported_paths) < 0.8:
        quality_flags.append("weak_carrier_lineage_support")
    if ratio(intervention_supported_paths) < 0.8:
        quality_flags.append("weak_hook_intervention_support")
    if ratio(readability_supported_paths) < 0.8:
        quality_flags.append("weak_sink_readability_support")
    if ratio(non_sufficiency_supported_paths) < 0.8:
        quality_flags.append("weak_non_sufficiency_support")
    if ratio(paths_with_supporting_edges) < 0.8:
        quality_flags.append("weak_supporting_flow_edge_evidence")
    return {
        "candidate_target_count": target_count,
        "targets_with_upstream_count": targets_with_upstream,
        "upstream_path_count": upstream_path_count,
        "upstream_coverage": upstream_coverage,
        "required_targets_with_upstream_for_complete_workflow": required_targets_with_upstream,
        "upstream_extraction_complete": upstream_extraction_complete,
        "stage_b_quality_flags": quality_flags,
        "lineage_supported_path_count": lineage_supported_paths,
        "intervention_supported_path_count": intervention_supported_paths,
        "readability_supported_path_count": readability_supported_paths,
        "non_sufficiency_supported_path_count": non_sufficiency_supported_paths,
        "paths_with_supporting_edges_count": paths_with_supporting_edges,
        "carrier_types": sorted(carrier_types),
        "target_skills": target_skills,
        "target_skills_with_upstream": target_skills_with_upstream,
        "target_skills_missing_upstream": target_skills_missing_upstream,
        "candidate_targets": str(candidate_targets_path.relative_to(WORKSPACE)),
    }


def _error_markers(trace: dict[str, Any]) -> list[str]:
    text = " ".join(
        str(trace.get(key) or "")
        for key in ("agent_output", "stderr_excerpt", "execution_diagnostics")
    ).lower()
    markers = []
    for marker in (
        "timeout",
        "rate limit",
        "rate-limit",
        "quota",
        "permission",
        "unauthorized",
        "not found",
        "failed",
        "error",
        "could not",
        "refused",
        "cancelled",
        "canceled",
    ):
        if marker in text:
            markers.append(marker)
    return markers


def write_summary(run_root: Path, rows: list[dict[str, Any]]) -> Path:
    by_pack: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_pack[row["pack_id"]].append(row)

    pack_summaries = []
    for pack_id, pack_rows in sorted(by_pack.items()):
        repeats = len(pack_rows)
        all_completed = sum(1 for row in pack_rows if row.get("all_tasks_completed"))
        task_stats: dict[str, dict[str, Any]] = {}
        for row in pack_rows:
            for task in row.get("tasks", []):
                task_id = str(task.get("task_id"))
                stat = task_stats.setdefault(
                    task_id,
                    {"runs": 0, "completed": 0, "skill_sequences": set(), "flow_edge_counts": []},
                )
                stat["runs"] += 1
                stat["completed"] += int(bool(task.get("task_completed")))
                stat["skill_sequences"].add(tuple(task.get("skill_sequence", [])))
                stat["flow_edge_counts"].append(int(task.get("flow_edge_count") or 0))
        normalized_task_stats = {
            task_id: {
                "runs": stat["runs"],
                "completed": stat["completed"],
                "completion_rate": stat["completed"] / stat["runs"] if stat["runs"] else 0,
                "distinct_skill_sequence_count": len(stat["skill_sequences"]),
                "flow_edge_counts": stat["flow_edge_counts"],
            }
            for task_id, stat in sorted(task_stats.items())
        }
        pack_summaries.append(
            {
                "pack_id": pack_id,
                "repeats": repeats,
                "all_tasks_completed_repeats": all_completed,
                "repeat_success_rate": all_completed / repeats if repeats else 0,
                "stage_b_ok_repeats": sum(1 for row in pack_rows if row.get("stage_b_status") == "ok"),
                "stage_b_targets_with_upstream_repeats": sum(
                    1 for row in pack_rows if int((row.get("stage_b") or {}).get("targets_with_upstream_count") or 0) > 0
                ),
                "stage_b_complete_upstream_repeats": sum(
                    1 for row in pack_rows if bool((row.get("stage_b") or {}).get("upstream_extraction_complete"))
                ),
                "task_stats": normalized_task_stats,
                "recommendation": _recommendation(pack_rows, all_completed, repeats, normalized_task_stats),
            }
        )

    out = run_root / "summary.json"
    write_json(
        out,
        {
            "schema_version": "2026-07-14.candidate_stage_a_validation_summary.v1",
            "created_at": _now(),
            "run_root": str(run_root.relative_to(WORKSPACE)),
            "packs": pack_summaries,
            "repeats": rows,
        },
    )
    return out


def _recommendation(
    pack_rows: list[dict[str, Any]],
    all_completed: int,
    repeats: int,
    task_stats: dict[str, dict[str, Any]],
) -> str:
    stage_a_stable = bool(repeats and all_completed == repeats and all(
        stat["completion_rate"] == 1 and stat["distinct_skill_sequence_count"] <= 2
        for stat in task_stats.values()
    ))
    stage_b_ok = sum(1 for row in pack_rows if row.get("stage_b_status") == "ok")
    upstream_complete = sum(1 for row in pack_rows if bool((row.get("stage_b") or {}).get("upstream_extraction_complete")))
    workflow_quality_ok = sum(1 for row in pack_rows if bool(row.get("all_task_workflows_quality_ok")))
    if stage_a_stable and stage_b_ok == repeats and upstream_complete == repeats and workflow_quality_ok == repeats:
        return "experiment_ready_candidate"
    if stage_a_stable and stage_b_ok == repeats and workflow_quality_ok >= max(1, repeats - 1):
        return "review_upstream_extraction"
    if stage_a_stable:
        return "stage_a_stable_but_stage_b_not_ready"
    if repeats and all_completed / repeats >= 2 / 3:
        return "stage_a_usable_but_review_variance"
    return "stage_a_unstable_or_not_ready"


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
