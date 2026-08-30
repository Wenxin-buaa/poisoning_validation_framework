#!/usr/bin/env python3
"""Re-run completed PVF variants as baseline_1 evaluations.

For every selected source variant this script evaluates two immutable copies:

* the original D1 sink-only pack with D2 -> D3;
* the last coordinated loop whose source verdict is successful with D5 -> D6.

The source experiment is never mutated. Results are namespaced by the target
model under:

    benchmarks/runs/<pack>/experiments/<experiment>/baseline_1/<model>/
"""
from __future__ import annotations

import argparse
import os
import re
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
from automation.judges import judge_coordinated, judge_sink_only  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from automation.prompts import PromptBuilder  # noqa: E402
from automation.providers import create_provider, write_provider_result  # noqa: E402
from automation.stage_runner import materialize_model_output  # noqa: E402


PROVIDERS = ("claude-code-sandbox", "codex-sandbox", "codex-cli", "dry-run")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Re-run D1 and final coordinated-success packs as baseline_1."
    )
    parser.add_argument("--pack", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument(
        "--variant-id",
        action="append",
        default=[],
        help="Source variant id. Repeatable; omit only with --all.",
    )
    parser.add_argument("--all", action="store_true", help="Evaluate every eligible coordinated_success variant.")
    parser.add_argument(
        "--provider",
        default="claude-code-sandbox",
        choices=PROVIDERS,
        help="Target-agent provider used for both D2 and D5.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model override. For Claude Code this sets PVF_CLAUDE_MODEL.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace this model's existing baseline_1 results.")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume an existing baseline_1 run by skipping variants that already have D3/D6 verdicts. Enabled by default.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable resume behavior and require a clean or overwritten output directory.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Create packs/prompts but do not execute or judge.")
    parser.add_argument("--judge-only", action="store_true", help="Judge existing baseline_1 traces without executing.")
    args = parser.parse_args()

    if args.prepare_only and args.judge_only:
        parser.error("--prepare-only and --judge-only are mutually exclusive")
    if not args.variant_id and not args.all:
        parser.error("provide --variant-id or --all")

    if args.model:
        os.environ["PVF_CLAUDE_MODEL"] = args.model
        if args.provider == "codex-sandbox":
            os.environ["PVF_CODEX_MODEL"] = args.model

    paths = FrameworkPaths.discover()
    experiment = paths.pack_experiment(args.pack, args.experiment_id)
    if not experiment.exists():
        raise FileNotFoundError(experiment)

    selected = select_variants(experiment, args.variant_id, args.all)
    model_name = args.model or os.environ.get("PVF_CLAUDE_MODEL", "") or os.environ.get("PVF_CODEX_MODEL", "") or "default"
    model_slug = slug(model_name)
    eval_experiment_id = f"{args.experiment_id}_baseline_1_{model_slug}"
    baseline_root = paths.pack_experiment(args.pack, eval_experiment_id)
    if baseline_root.exists() and args.overwrite:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    records = []
    for source_variant_id in selected:
        eval_dir = baseline_root / "variants" / source_variant_id
        if eval_dir.exists() and not args.overwrite:
            if args.resume:
                print(
                    f"[baseline_1] skipped existing variant: {source_variant_id}",
                    flush=True,
                )
                continue
        record = run_one(
            paths=paths,
            experiment=experiment,
            baseline_root=baseline_root,
            pack_id=args.pack,
            experiment_id=args.experiment_id,
            eval_experiment_id=eval_experiment_id,
            source_variant_id=source_variant_id,
            provider_name=args.provider,
            prepare_only=args.prepare_only,
            judge_only=args.judge_only,
            overwrite=args.overwrite,
            resume=args.resume,
        )
        records.append(record)
        print(record, flush=True)

    summary = {
        "schema_version": "2026-08-24.baseline_1_summary.v1",
        "baseline": "baseline_1",
        "pack_id": args.pack,
        "experiment_id": args.experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "model": model_name,
        "model_slug": model_slug,
        "provider": args.provider,
        "created_at": now(),
        "records": records,
    }
    summary_path = baseline_root / "summary.json"
    write_json(summary_path, summary)
    print(f"summary={paths.rel(summary_path)}")
    return 0


def select_variants(experiment: Path, requested: list[str], all_variants: bool) -> list[str]:
    if all_variants:
        candidates = sorted(path.parent.name for path in (experiment / "variants").glob("*/variant.json"))
    else:
        candidates = list(dict.fromkeys(requested))
    selected = []
    skipped = []
    for variant_id in candidates:
        path = experiment / "variants" / variant_id / "variant.json"
        if not path.exists():
            raise FileNotFoundError(path)
        variant = load_json(path)
        if variant.get("status") != "coordinated_success":
            skipped.append((variant_id, variant.get("status")))
            continue
        selected.append(variant_id)
    if not selected:
        raise ValueError("No eligible coordinated_success variants found.")
    if skipped:
        print(
            "[baseline_1] skipped non-coordinated variants: "
            + ", ".join(f"{vid}:{status}" for vid, status in skipped[:20]),
            flush=True,
        )
    return selected


def run_one(
    *,
    paths: FrameworkPaths,
    experiment: Path,
    baseline_root: Path,
    pack_id: str,
    experiment_id: str,
    eval_experiment_id: str,
    source_variant_id: str,
    provider_name: str,
    prepare_only: bool,
    judge_only: bool,
    overwrite: bool,
    resume: bool,
) -> dict[str, Any]:
    source_dir = experiment / "variants" / source_variant_id
    source_variant = load_json(source_dir / "variant.json")
    payload_reference = load_json(source_dir / "payload_reference.json")
    final_loop = find_final_success_loop(source_dir)
    task_ids = list(source_variant.get("task_ids") or [])

    eval_dir = baseline_root / "variants" / source_variant_id
    if eval_dir.exists():
        if overwrite and not judge_only:
            shutil.rmtree(eval_dir)
        elif resume:
            return {
                "source_variant_id": source_variant_id,
                "final_source_loop": final_loop,
                "sink_only": {"trace": None, "verdict": None, "result": "skipped_existing"},
                "coordinated": {"trace": None, "verdict": None, "result": "skipped_existing"},
                "statuses": {"skip": "existing_variant"},
            }
        else:
            raise FileExistsError(
                f"{eval_dir} already exists. Use --overwrite to replace it or --resume to skip it."
            )
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_variant = dict(source_variant)
    eval_variant.update(
        {
            "schema_version": "2026-08-24.baseline_1_variant.v1",
            "experiment_id": eval_experiment_id,
            "variant_id": source_variant_id,
            "status": "baseline_1",
            "baseline": "baseline_1",
            "baseline_source_variant": source_variant_id,
            "baseline_source_final_loop": final_loop,
            "task_ids": task_ids,
        }
    )
    if not judge_only:
        write_json(eval_dir / "variant.json", eval_variant)
        write_json(eval_dir / "payload_reference.json", payload_reference)
    else:
        eval_variant_path = eval_dir / "variant.json"
        payload_path = eval_dir / "payload_reference.json"
        if eval_variant_path.exists():
            eval_variant = load_json(eval_variant_path)
        if payload_path.exists():
            payload_reference = load_json(payload_path)

    sink_source_pack = source_dir / "sink_only" / "variant_pack"
    coordinated_source_dir = source_dir / "coordinated" / f"loop_{final_loop:03d}"
    coordinated_source_pack = coordinated_source_dir / "variant_pack"
    if not sink_source_pack.exists():
        raise FileNotFoundError(sink_source_pack)
    if not coordinated_source_pack.exists():
        raise FileNotFoundError(coordinated_source_pack)

    sink_dir = eval_dir / "sink_only"
    coord_dir = eval_dir / "coordinated" / f"loop_{final_loop:03d}"
    if not judge_only:
        shutil.copytree(sink_source_pack, sink_dir / "variant_pack")
        shutil.copytree(coordinated_source_pack, coord_dir / "variant_pack")
        copy_coordination_plan(coordinated_source_dir, coord_dir)

    task_file = paths.benign_tasks / f"{pack_id}_tasks.json"
    sink_trace = sink_dir / "traces.jsonl"
    sink_verdict = sink_dir / "verdict.json"
    coord_trace = coord_dir / "traces.jsonl"
    coord_verdict = coord_dir / "verdict.json"

    sink_request = build_request(
        paths=paths,
        stage="D2",
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        variant=eval_variant,
        task_file=task_file,
        pack_path=sink_dir / "variant_pack",
        payload_reference_path=eval_dir / "payload_reference.json",
        trace_path=sink_trace,
        loop_iteration=None,
    )
    coord_request = build_request(
        paths=paths,
        stage="D5",
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        variant=eval_variant,
        task_file=task_file,
        pack_path=coord_dir / "variant_pack",
        payload_reference_path=eval_dir / "payload_reference.json",
        trace_path=coord_trace,
        loop_iteration=final_loop,
    )
    sink_request_dir = sink_dir / "requests"
    coord_request_dir = coord_dir / "requests"
    if not judge_only:
        write_stage_prompt(paths, sink_request_dir, sink_request)
        write_stage_prompt(paths, coord_request_dir, coord_request)
        write_json(
            eval_dir / "baseline_1_manifest.json",
            {
                "schema_version": "2026-08-24.baseline_1_manifest.v1",
                "baseline": "baseline_1",
                "source_variant": source_variant_id,
                "source_variant_path": paths.rel(source_dir),
                "d1_pack": paths.rel(sink_source_pack),
                "final_coordinated_loop": final_loop,
                "final_coordinated_pack": paths.rel(coordinated_source_pack),
                "task_ids": task_ids,
                "target_agent_payload_blind": True,
                "provider": provider_name,
            },
        )

    statuses: dict[str, Any] = {}
    sink_has_verdict = sink_verdict.exists()
    coord_has_verdict = coord_verdict.exists()
    if resume and sink_has_verdict:
        sink_status = load_json(sink_verdict)
        statuses["d2"] = "skipped_existing"
        statuses["d3"] = sink_status.get("verdict")
        print(
            f"[SKIP] variant {source_variant_id} already has D3",
            flush=True,
        )
        print(
            f"[D3] sink_only={sink_status.get('verdict')} "
            f"payload_observed={sink_status.get('payload_observed')} "
            f"task_completed={sink_status.get('task_completed')} "
            f"(resume)",
            flush=True,
        )
    if not sink_has_verdict or not resume:
        if not judge_only:
            if not prepare_only:
                print(
                    f"[baseline_1] {source_variant_id} D2 start provider={provider_name}",
                    flush=True,
                )
                execute_request(provider_name, sink_request, sink_request_dir)
                statuses["d2"] = "executed"
            else:
                statuses["d2"] = "prepared"
        if not prepare_only:
            if not sink_trace.exists():
                raise FileNotFoundError(sink_trace)
            print(f"[baseline_1] {source_variant_id} D3 judge start", flush=True)
            judge_sink_only(
                paths=paths,
                pack_id=pack_id,
                experiment_id=eval_experiment_id,
                variant_id=source_variant_id,
            )
            sink_verdict_data = load_json(sink_verdict)
            statuses["d3"] = sink_verdict_data.get("verdict")
            print(
                f"[D3] sink_only={sink_verdict_data.get('verdict')} "
                f"payload_observed={sink_verdict_data.get('payload_observed')} "
                f"task_completed={sink_verdict_data.get('task_completed')} "
                f"verdict_path={paths.rel(sink_verdict)}",
                flush=True,
            )
    if resume and coord_has_verdict:
        coord_status = load_json(coord_verdict)
        statuses["d5"] = "skipped_existing"
        statuses["d6"] = coord_status.get("verdict")
        print(
            f"[SKIP] variant {source_variant_id} already has D6",
            flush=True,
        )
        print(
            f"[D6] coordinated={coord_status.get('verdict')} "
            f"payload_observed={coord_status.get('payload_observed')} "
            f"task_completed={coord_status.get('task_completed')} "
            f"coordinated_dependency_satisfied={coord_status.get('coordinated_dependency_satisfied')} "
            f"(resume)",
            flush=True,
        )
    if not coord_has_verdict or not resume:
        if not judge_only:
            if not prepare_only:
                print(
                    f"[baseline_1] {source_variant_id} D5 start provider={provider_name} loop={final_loop}",
                    flush=True,
                )
                execute_request(provider_name, coord_request, coord_request_dir)
                statuses["d5"] = "executed"
            else:
                statuses["d5"] = "prepared"
        if not prepare_only:
            if not coord_trace.exists():
                raise FileNotFoundError(coord_trace)
            print(f"[baseline_1] {source_variant_id} D6 judge start loop={final_loop}", flush=True)
            judge_coordinated(
                paths=paths,
                pack_id=pack_id,
                experiment_id=eval_experiment_id,
                variant_id=source_variant_id,
                loop_iteration=final_loop,
            )
            coord_verdict_data = load_json(coord_verdict)
            statuses["d6"] = coord_verdict_data.get("verdict")
            print(
                f"[D6] coordinated={coord_verdict_data.get('verdict')} "
                f"payload_observed={coord_verdict_data.get('payload_observed')} "
                f"task_completed={coord_verdict_data.get('task_completed')} "
                f"coordinated_dependency_satisfied={coord_verdict_data.get('coordinated_dependency_satisfied')} "
                f"verdict_path={paths.rel(coord_verdict)}",
                flush=True,
            )

    return {
        "source_variant_id": source_variant_id,
        "final_source_loop": final_loop,
        "sink_only": {
            "trace": paths.rel(sink_trace) if sink_trace.exists() else None,
            "verdict": paths.rel(sink_verdict) if sink_verdict.exists() else None,
            "result": statuses.get("d3"),
        },
        "coordinated": {
            "trace": paths.rel(coord_trace) if coord_trace.exists() else None,
            "verdict": paths.rel(coord_verdict) if coord_verdict.exists() else None,
            "result": statuses.get("d6"),
        },
        "statuses": statuses,
    }


def find_final_success_loop(source_dir: Path) -> int:
    successful = []
    for verdict_path in source_dir.glob("coordinated/loop_*/verdict.json"):
        verdict = load_json(verdict_path)
        if verdict.get("verdict") == "success":
            match = re.fullmatch(r"loop_(\d+)", verdict_path.parent.name)
            if match:
                successful.append(int(match.group(1)))
    if not successful:
        raise ValueError(f"No coordinated success loop found under {source_dir / 'coordinated'}")
    return max(successful)


def copy_coordination_plan(source_loop: Path, destination_loop: Path) -> None:
    for relative in (
        Path("semantic_generation/coordination_plan.json"),
        Path("variant_pack/pvf_coordination_plan.json"),
    ):
        source = source_loop / relative
        if source.exists():
            destination = destination_loop / relative
            destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source, destination)


def build_request(
    *,
    paths: FrameworkPaths,
    stage: str,
    pack_id: str,
    experiment_id: str,
    variant: dict[str, Any],
    task_file: Path,
    pack_path: Path,
    payload_reference_path: Path,
    trace_path: Path,
    loop_iteration: int | None,
) -> dict[str, Any]:
    inputs = {
        "task_file": paths.rel(task_file),
        "clean_pack": paths.rel(paths.clean_packs / pack_id),
        "payload_reference": paths.rel(payload_reference_path),
        "sink_only_pack": paths.rel(pack_path),
        "coordinated_pack": paths.rel(pack_path),
    }
    if loop_iteration is not None:
        inputs["loop_iteration"] = loop_iteration
    return {
        "schema_version": "2026-08-24.baseline_1_stage_request.v1",
        "stage": stage,
        "role": "target_agent",
        "created_at": now(),
        "pack_id": pack_id,
        "experiment_id": f"{experiment_id}_baseline_1",
        "loop_iteration": loop_iteration,
        "safety": {
            "payload_policy": "inert_payload_only",
            "target_agent_payload_blind": True,
            "baseline": "baseline_1",
        },
        "inputs": inputs,
        "expected_output": paths.rel(trace_path),
        "contract": {"type": "jsonl", "rows": "RunTrace rows"},
        "variant": variant,
    }


def write_stage_prompt(paths: FrameworkPaths, request_dir: Path, request: dict[str, Any]) -> None:
    request_dir.mkdir(parents=True, exist_ok=True)
    write_json(request_dir / "stage_request.json", request)
    prompt = PromptBuilder(paths).build(request)
    write_json(request_dir / "prompt_messages.json", prompt.messages())
    (request_dir / "resolved_prompt.md").write_text(prompt.to_debug_markdown(), encoding="utf-8")


def execute_request(provider_name: str, request: dict[str, Any], request_dir: Path) -> None:
    prompt = PromptBuilder().build(request)
    print(
        f"[baseline_1] provider={provider_name} stage={request['stage']} "
        f"tasks={request.get('variant', {}).get('task_ids') or 'all'}",
        flush=True,
    )
    result = create_provider(provider_name).execute(prompt)
    write_provider_result(request_dir, result)
    materialized = materialize_model_output(
        request=request,
        raw_output=result.content,
        request_dir=request_dir,
    )
    if materialized is None:
        raise RuntimeError(f"{request['stage']} output could not be materialized; see {request_dir}")
    destination = Path(request["expected_output"])
    if not destination.is_absolute():
        destination = WORKSPACE / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(materialized, destination)
    print(
        f"[baseline_1] provider={provider_name} stage={request['stage']} "
        f"trace_written={destination}",
        flush=True,
    )


def slug(value: str) -> str:
    result = re.sub(r"[^A-Za-z0-9_.-]+", "_", value).strip("._-")
    return result or "default"


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
