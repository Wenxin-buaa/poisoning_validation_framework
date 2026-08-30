#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.io import load_json, write_json  # noqa: E402
from automation.judges import judge_coordinated  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from automation.prompts import PromptBuilder  # noqa: E402
from automation.providers import CodexCLIProvider, write_provider_result  # noqa: E402
from automation.stage_runner import materialize_model_output  # noqa: E402


DEFAULT_CURATED = (
    ROOT
    / "benchmarks"
    / "runs"
    / "pack_a"
    / "experiments"
    / "pack_a_exp_003"
    / "curated_high_score_loop_samples"
)
BASELINE_DIR_NAMES = {
    "baseline1": "baseline1_sink_only_workflow",
    "baseline2": "baseline2_single_sink",
}


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run curated baseline samples with the same D5 target-agent execution and D6 judge flow."
    )
    parser.add_argument("--experiment-id", default="pack_a_exp_003", help="Source experiment id containing curated_high_score_loop_samples.")
    parser.add_argument(
        "--curated-dir",
        type=Path,
        help="Optional explicit curated_high_score_loop_samples directory. Overrides --pack/--experiment-id path derivation.",
    )
    parser.add_argument(
        "--baseline",
        choices=("baseline1", "baseline2", "all"),
        default="all",
        help="Which generated baseline set to evaluate.",
    )
    parser.add_argument("--sample-id", action="append", default=[], help="Optional sample id filter. Repeatable.")
    parser.add_argument("--limit", type=int, default=0, help="Optional max samples after filtering.")
    parser.add_argument("--pack", default="pack_a")
    parser.add_argument(
        "--eval-experiment-id",
        help="Destination experiment id for baseline eval. Defaults to <experiment-id>_curated_baselines_eval.",
    )
    parser.add_argument("--loop-iteration", type=int, default=1)
    parser.add_argument("--overwrite", action=argparse.BooleanOptionalAction, default=False)
    parser.add_argument("--prepare-only", action="store_true", help="Create D5/D6 evaluation dirs and prompts, but do not run Codex or judge.")
    parser.add_argument("--judge-only", action="store_true", help="Run D6 only, using existing traces.jsonl.")
    args = parser.parse_args()

    if args.prepare_only and args.judge_only:
        raise ValueError("--prepare-only and --judge-only cannot be used together")

    paths = FrameworkPaths.discover()
    curated = resolve_curated_dir(paths, args.pack, args.experiment_id, args.curated_dir)
    eval_experiment_id = args.eval_experiment_id or f"{args.experiment_id}_curated_baselines_eval"
    eval_experiment = paths.pack_experiment(args.pack, eval_experiment_id)
    eval_experiment.mkdir(parents=True, exist_ok=True)
    (eval_experiment / "variants").mkdir(exist_ok=True)
    (eval_experiment / "requests").mkdir(exist_ok=True)

    selected = select_samples(curated, args.baseline, set(args.sample_id), args.limit)
    records = []
    total = len(selected)
    for index, item in enumerate(selected, start=1):
        progress(
            {
                "event": "baseline_eval_sample_start",
                "index": index,
                "total": total,
                "baseline": item["baseline_key"],
                "sample_id": item["sample_dir"].name,
            }
        )
        record = run_one(
            paths=paths,
            curated=curated,
            eval_experiment=eval_experiment,
            eval_experiment_id=eval_experiment_id,
            pack_id=args.pack,
            baseline_key=item["baseline_key"],
            baseline_dir_name=item["baseline_dir_name"],
            baseline_sample_dir=item["sample_dir"],
            loop_iteration=args.loop_iteration,
            overwrite=args.overwrite,
            prepare_only=args.prepare_only,
            judge_only=args.judge_only,
        )
        records.append(record)
        progress({"event": "baseline_eval_sample_complete", "index": index, "total": total, **record})

    summary = summarize(records)
    summary.update(
        {
            "schema_version": "2026-07-23.curated_baseline_eval_summary.v1",
            "pack_id": args.pack,
            "source_experiment_id": args.experiment_id,
            "eval_experiment_id": eval_experiment_id,
            "created_at": now(),
            "curated_dir": rel(curated),
            "baseline_filter": args.baseline,
            "sample_filter": args.sample_id,
            "prepare_only": args.prepare_only,
            "judge_only": args.judge_only,
            "records": records,
        }
    )
    out = eval_experiment / "baseline_eval_summary.json"
    write_json(out, summary)
    print(json.dumps({"summary": rel(out), **{k: summary[k] for k in ("sample_count", "by_baseline", "by_verdict")}}, indent=2, ensure_ascii=False))
    return 0


def resolve_curated_dir(paths: FrameworkPaths, pack_id: str, experiment_id: str, explicit: Path | None) -> Path:
    if explicit is not None:
        return explicit.resolve()
    return (
        paths.pack_experiment(pack_id, experiment_id)
        / "curated_high_score_loop_samples"
    ).resolve()


def select_samples(curated: Path, baseline: str, sample_ids: set[str], limit: int) -> list[dict[str, Any]]:
    keys = ["baseline1", "baseline2"] if baseline == "all" else [baseline]
    selected = []
    for key in keys:
        dirname = BASELINE_DIR_NAMES[key]
        root = curated / "baselines" / dirname / "samples"
        if not root.exists():
            raise FileNotFoundError(root)
        for sample_dir in sorted(path for path in root.iterdir() if path.is_dir()):
            if sample_ids and sample_dir.name not in sample_ids:
                continue
            selected.append(
                {
                    "baseline_key": key,
                    "baseline_dir_name": dirname,
                    "sample_dir": sample_dir,
                }
            )
    if limit:
        selected = selected[:limit]
    return selected


def run_one(
    *,
    paths: FrameworkPaths,
    curated: Path,
    eval_experiment: Path,
    eval_experiment_id: str,
    pack_id: str,
    baseline_key: str,
    baseline_dir_name: str,
    baseline_sample_dir: Path,
    loop_iteration: int,
    overwrite: bool,
    prepare_only: bool,
    judge_only: bool,
) -> dict[str, Any]:
    baseline_meta = load_json(baseline_sample_dir / "baseline_manifest.json")
    sample_id = str(baseline_meta["sample_id"])
    eval_variant_id = sanitize_variant_id(f"{baseline_key}_{sample_id}")
    eval_variant_dir = eval_experiment / "variants" / eval_variant_id
    loop_dir = eval_variant_dir / "coordinated" / f"loop_{loop_iteration:03d}"
    traces_path = loop_dir / "traces.jsonl"
    verdict_path = loop_dir / "verdict.json"

    if eval_variant_dir.exists() and overwrite:
        shutil.rmtree(eval_variant_dir)
    eval_variant_dir.mkdir(parents=True, exist_ok=True)
    loop_dir.mkdir(parents=True, exist_ok=True)

    source_variant_id = str(baseline_meta["source_variant"])
    source_variant_dir = curated.parent / "variants" / source_variant_id
    source_sample_dir = curated / "samples" / sample_id
    source_sample_manifest = load_json(source_sample_dir / "variant_pack" / "pvf_variant_manifest.json")
    payload_reference = load_json(source_variant_dir / "payload_reference.json")
    task_file = baseline_sample_dir / "task_file.json"
    variant_pack = baseline_sample_dir / "variant_pack"
    eval_variant_pack = loop_dir / "variant_pack"
    if eval_variant_pack.exists() and overwrite:
        shutil.rmtree(eval_variant_pack)
    if not eval_variant_pack.exists():
        shutil.copytree(variant_pack, eval_variant_pack)

    coordination_plan_source = source_sample_dir / "semantic_generation" / "coordination_plan.json"
    if not coordination_plan_source.exists():
        coordination_plan_source = source_sample_dir / "variant_pack" / "pvf_coordination_plan.json"
    if coordination_plan_source.exists():
        coordination_plan_dest = loop_dir / "semantic_generation" / "coordination_plan.json"
        coordination_plan_dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(coordination_plan_source, coordination_plan_dest)

    variant = build_eval_variant(
        baseline_meta=baseline_meta,
        source_sample_manifest=source_sample_manifest,
        payload_reference=payload_reference,
        pack_id=pack_id,
        eval_experiment_id=eval_experiment_id,
        eval_variant_id=eval_variant_id,
        eval_variant_dir=eval_variant_dir,
        loop_iteration=loop_iteration,
    )
    write_json(eval_variant_dir / "variant.json", variant)
    write_json(eval_variant_dir / "payload_reference.json", payload_reference)
    write_json(
        eval_variant_dir / "baseline_eval_manifest.json",
        {
            "schema_version": "2026-07-23.curated_baseline_eval_variant.v1",
            "baseline": baseline_key,
            "baseline_dir_name": baseline_dir_name,
            "sample_id": sample_id,
            "source_baseline_sample": rel(baseline_sample_dir),
            "source_curated_sample": rel(source_sample_dir),
            "source_variant": source_variant_id,
            "judge_coordination_plan_source": rel(coordination_plan_source) if coordination_plan_source.exists() else None,
            "target_agent_payload_blind": True,
            "target_agent_receives_baseline_pack_only": True,
            "target_agent_receives_coordination_plan": False,
        },
    )

    request = build_d5_request(
        paths=paths,
        pack_id=pack_id,
        eval_experiment_id=eval_experiment_id,
        eval_variant_id=eval_variant_id,
        loop_iteration=loop_iteration,
        task_file=task_file,
        variant_pack=eval_variant_pack,
        traces_path=traces_path,
        variant=variant,
        payload_reference_path=eval_variant_dir / "payload_reference.json",
    )
    request_dir = eval_variant_dir / "requests" / "D5" / f"loop_{loop_iteration:03d}"
    write_stage_prompt(request_dir, request)

    status = "prepared"
    if not prepare_only and not judge_only:
        progress(
            {
                "event": "d5_start",
                "baseline": baseline_key,
                "sample_id": sample_id,
                "eval_variant_id": eval_variant_id,
                "task_file": rel(task_file),
                "variant_pack": rel(eval_variant_pack),
            }
        )
        run_d5(request_dir, request, traces_path)
        progress(
            {
                "event": "d5_complete",
                "baseline": baseline_key,
                "sample_id": sample_id,
                "eval_variant_id": eval_variant_id,
                "trace": rel(traces_path),
            }
        )
        status = "d5_executed"
    if not prepare_only:
        if not traces_path.exists():
            raise FileNotFoundError(f"Missing traces for judge-only run: {traces_path}")
        progress(
            {
                "event": "d6_start",
                "baseline": baseline_key,
                "sample_id": sample_id,
                "eval_variant_id": eval_variant_id,
                "trace": rel(traces_path),
            }
        )
        judge_coordinated(
            paths=paths,
            pack_id=pack_id,
            experiment_id=eval_experiment_id,
            variant_id=eval_variant_id,
            loop_iteration=loop_iteration,
        )
        judged = load_json(verdict_path)
        progress(
            {
                "event": "d6_complete",
                "baseline": baseline_key,
                "sample_id": sample_id,
                "eval_variant_id": eval_variant_id,
                "verdict": judged.get("verdict"),
                "payload_observed": judged.get("payload_observed"),
                "task_completed": judged.get("task_completed"),
                "coordinated_dependency_satisfied": judged.get("coordinated_dependency_satisfied"),
                "verdict_path": rel(verdict_path),
            }
        )
        status = "judged"

    verdict = load_json(verdict_path) if verdict_path.exists() else {}
    return {
        "baseline": baseline_key,
        "sample_id": sample_id,
        "eval_variant_id": eval_variant_id,
        "status": status,
        "trace": rel(traces_path) if traces_path.exists() else None,
        "verdict_path": rel(verdict_path) if verdict_path.exists() else None,
        "verdict": verdict.get("verdict"),
        "payload_observed": verdict.get("payload_observed"),
        "task_completed": verdict.get("task_completed"),
        "coordinated_dependency_satisfied": verdict.get("coordinated_dependency_satisfied"),
        "judge_mode": (verdict.get("judge_details") or {}).get("mode") if isinstance(verdict.get("judge_details"), dict) else None,
    }


def build_eval_variant(
    *,
    baseline_meta: dict[str, Any],
    source_sample_manifest: dict[str, Any],
    payload_reference: dict[str, Any],
    pack_id: str,
    eval_experiment_id: str,
    eval_variant_id: str,
    eval_variant_dir: Path,
    loop_iteration: int,
) -> dict[str, Any]:
    source_task = baseline_meta.get("task") or {}
    task_id = source_task.get("task_id")
    if isinstance(task_id, str) and task_id:
        task_ids = [task_id]
    else:
        task_ids = []
    return {
        "schema_version": "2026-07-23.curated_baseline_eval_variant.v1",
        "variant_id": eval_variant_id,
        "pack_id": pack_id,
        "experiment_id": eval_experiment_id,
        "candidate_target_id": baseline_meta.get("source_variant"),
        "variant_type": baseline_meta.get("baseline"),
        "target_skill": baseline_meta["sink_skill"],
        "sink_skill": baseline_meta["sink_skill"],
        "upstream_skill": source_sample_manifest.get("upstream_skill"),
        "hook_skill": source_sample_manifest.get("hook_skill") or source_sample_manifest.get("upstream_skill"),
        "upstream_path": [],
        "payload_id": int(baseline_meta["payload_id"]),
        "payload_source": payload_reference.get("payload_source"),
        "payload_hash": payload_reference.get("payload_hash", ""),
        "variant_dir": rel(eval_variant_dir),
        "task_ids": task_ids,
        "loop_iteration": loop_iteration,
        "status": "baseline_eval",
        "baseline_source": {
            "sample_id": baseline_meta["sample_id"],
            "source_variant": baseline_meta["source_variant"],
            "source_loop": baseline_meta["source_loop"],
        },
    }


def build_d5_request(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    eval_experiment_id: str,
    eval_variant_id: str,
    loop_iteration: int,
    task_file: Path,
    variant_pack: Path,
    traces_path: Path,
    variant: dict[str, Any],
    payload_reference_path: Path,
) -> dict[str, Any]:
    return {
        "schema_version": "2026-07-23.curated_baseline_d5_request.v1",
        "stage": "D5",
        "role": "target_agent",
        "created_at": now(),
        "pack_id": pack_id,
        "experiment_id": eval_experiment_id,
        "loop_iteration": loop_iteration,
        "safety": {
            "payload_policy": "inert_payload_only",
            "target_agent_payload_blind": True,
            "note": "This request is for baseline evaluation; target agent sees only the baseline pack and task.",
        },
        "inputs": {
            "task_file": paths.rel(task_file),
            "clean_pack": paths.rel(paths.clean_packs / pack_id),
            "coordinated_pack": paths.rel(variant_pack),
            "coordinated_traces": paths.rel(traces_path),
            "payload_reference": paths.rel(payload_reference_path),
            "loop_iteration": loop_iteration,
        },
        "expected_output": paths.rel(traces_path),
        "contract": {"type": "jsonl", "rows": "RunTrace rows"},
        "variant": variant,
    }


def write_stage_prompt(request_dir: Path, request: dict[str, Any]) -> None:
    request_dir.mkdir(parents=True, exist_ok=True)
    write_json(request_dir / "stage_request.json", request)
    prompt = PromptBuilder().build(request)
    write_json(request_dir / "prompt_messages.json", prompt.messages())
    (request_dir / "resolved_prompt.md").write_text(prompt.to_debug_markdown(), encoding="utf-8")


def run_d5(request_dir: Path, request: dict[str, Any], traces_path: Path) -> None:
    prompt = PromptBuilder().build(request)
    result = CodexCLIProvider().execute(prompt)
    write_provider_result(request_dir, result)
    materialized = materialize_model_output(
        request=request,
        raw_output=result.content,
        request_dir=request_dir,
    )
    if materialized is None:
        raise RuntimeError(f"D5 provider output could not be materialized. See {request_dir}")
    traces_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(materialized, traces_path)


def summarize(records: list[dict[str, Any]]) -> dict[str, Any]:
    by_baseline: dict[str, int] = {}
    by_verdict: dict[str, int] = {}
    for record in records:
        by_baseline[record["baseline"]] = by_baseline.get(record["baseline"], 0) + 1
        verdict = str(record.get("verdict") or "not_judged")
        by_verdict[verdict] = by_verdict.get(verdict, 0) + 1
    return {
        "sample_count": len(records),
        "by_baseline": by_baseline,
        "by_verdict": by_verdict,
    }


def sanitize_variant_id(value: str) -> str:
    return "".join(ch if ch.isalnum() or ch in {"_", "-"} else "_" for ch in value)


def progress(record: dict[str, Any]) -> None:
    print(json.dumps({"ts": now(), **record}, ensure_ascii=False), flush=True)


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(WORKSPACE))
    except ValueError:
        return str(path)


if __name__ == "__main__":
    raise SystemExit(main())
