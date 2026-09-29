#!/usr/bin/env python3
"""Run baseline_7 as a sink-only replay with coordinated upstream ablation.

baseline_7 mirrors baseline_4 in the opposite direction:

1. it selects source variants whose full framework status is coordinated_success;
2. it starts from the final successful coordinated loop pack, keeping that
   loop's upstream skill;
3. it replaces the downstream/sink skill directory with the original D1
   sink-only downstream skill directory;
4. it replays D2 -> D3 on the resulting pack.

The source experiment is never mutated. Results are namespaced by the target
model under:

    benchmarks/runs/<pack>/experiments/<experiment>_baseline_7_<model>/
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.io import load_json, write_json  # noqa: E402
from automation.judges import judge_sink_only  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from automation.prompts import PromptBuilder  # noqa: E402
from automation.providers import create_provider, write_provider_result  # noqa: E402
from automation.stage_runner import materialize_model_output  # noqa: E402
from run_baseline_1 import (  # noqa: E402
    ensure_eval_metadata,
    find_final_success_loop,
    now,
    slug,
)


PROVIDERS = ("claude-code-sandbox", "codex-sandbox", "codex-cli", "dry-run")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run baseline_7 by combining the coordinated-success upstream with "
            "the original D1 sink-only downstream, then replaying D2 -> D3."
        )
    )
    parser.add_argument(
        "--pack",
        action="append",
        required=True,
        help="Pair id, repeatable and/or comma-separated.",
    )
    parser.add_argument(
        "--experiment-id",
        "--exp",
        required=True,
        help="Single source experiment id (exp_001, 002, 003, or <pair>_exp_001).",
    )
    parser.add_argument(
        "--variant-id",
        action="append",
        default=[],
        help="Source variant id. Repeatable; omit only with --all.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compatibility flag; baseline_7 evaluates all eligible coordinated_success variants by default.",
    )
    parser.add_argument(
        "--provider",
        default="claude-code-sandbox",
        choices=PROVIDERS,
        help="Target-agent provider used for D2.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model override. For Claude Code this sets PVF_CLAUDE_MODEL.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace this model's existing baseline_7 results.")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume an existing baseline_7 run by skipping variants that already have D3 verdicts. Enabled by default.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable resume behavior and require a clean or overwritten output directory.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Create packs/prompts but do not execute or judge.")
    parser.add_argument("--judge-only", action="store_true", help="Judge existing baseline_7 traces without executing.")
    args = parser.parse_args()

    if args.prepare_only and args.judge_only:
        parser.error("--prepare-only and --judge-only are mutually exclusive")
    packs = _csv_values(args.pack)
    experiment_token = args.experiment_id.strip()
    variant_filter = set(_csv_values(args.variant_id))
    if not packs:
        parser.error("at least one pair is required")
    if not experiment_token:
        parser.error("at least one experiment id is required")
    if "," in experiment_token:
        parser.error("--experiment-id accepts exactly one experiment id; pass exp_001, 002, or 003")

    if args.model:
        os.environ["PVF_CLAUDE_MODEL"] = args.model
        if args.provider == "codex-sandbox":
            os.environ["PVF_CODEX_MODEL"] = args.model

    paths = FrameworkPaths.discover()
    model_name = _selected_model(args.model, args.provider)
    model_slug = slug(model_name)
    all_records: list[dict[str, Any]] = []
    for pack_id in packs:
        source_experiment_id = _resolve_experiment_id(pack_id, experiment_token)
        records = run_pack(
            paths=paths,
            pack_id=pack_id,
            source_experiment_id=source_experiment_id,
            model_name=model_name,
            model_slug=model_slug,
            provider_name=args.provider,
            variant_filter=variant_filter,
            prepare_only=args.prepare_only,
            judge_only=args.judge_only,
            overwrite=args.overwrite,
            resume=args.resume,
        )
        all_records.extend(records)

    print(
        {
            "baseline": "baseline_7",
            "provider": args.provider,
            "model": model_name,
            "pack_count": len(packs),
            "experiment_id": experiment_token,
            "eligible_variant_count": len(all_records),
            "selection_mode": "source variant status == coordinated_success",
        },
        flush=True,
    )
    return 0


def run_pack(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    source_experiment_id: str,
    model_name: str,
    model_slug: str,
    provider_name: str,
    variant_filter: set[str],
    prepare_only: bool,
    judge_only: bool,
    overwrite: bool,
    resume: bool,
) -> list[dict[str, Any]]:
    experiment = paths.pack_experiment(pack_id, source_experiment_id)
    if not experiment.exists():
        print(
            {
                "event": "baseline_7_skip_experiment",
                "pack_id": pack_id,
                "experiment_id": source_experiment_id,
                "reason": "experiment_not_found",
            },
            flush=True,
        )
        return []

    selected = select_variants(experiment, variant_filter)
    if not selected:
        print(
            {
                "event": "baseline_7_skip_experiment",
                "pack_id": pack_id,
                "experiment_id": source_experiment_id,
                "reason": "no_coordinated_success_variants",
            },
            flush=True,
        )
        return []

    eval_experiment_id = f"{source_experiment_id}_baseline_7_{model_slug}"
    baseline_root = paths.pack_experiment(pack_id, eval_experiment_id)
    if baseline_root.exists() and overwrite and not judge_only:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    print(
        {
            "event": "baseline_7_eval_start",
            "pack_id": pack_id,
            "source_experiment_id": source_experiment_id,
            "eval_experiment_id": eval_experiment_id,
            "eligible_variant_count": len(selected),
            "provider": provider_name,
            "model": model_name,
            "prepare_only": prepare_only,
            "judge_only": judge_only,
        },
        flush=True,
    )

    records: list[dict[str, Any]] = []
    for source_variant_id in selected:
        record = run_one(
            paths=paths,
            experiment=experiment,
            baseline_root=baseline_root,
            pack_id=pack_id,
            eval_experiment_id=eval_experiment_id,
            source_variant_id=source_variant_id,
            provider_name=provider_name,
            prepare_only=prepare_only,
            judge_only=judge_only,
            overwrite=overwrite,
            resume=resume,
        )
        records.append(record)
        print(record, flush=True)

    summary = {
        "schema_version": "2026-09-16.baseline_7_summary.v1",
        "baseline": "baseline_7",
        "pack_id": pack_id,
        "experiment_id": source_experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "model": model_name,
        "model_slug": model_slug,
        "provider": provider_name,
        "created_at": now(),
        "eligibility": "source variant status == coordinated_success",
        "ablation": (
            "reuse final coordinated-success upstream; replace downstream/sink "
            "with original D1 sink-only downstream; replay D2/D3"
        ),
        "records": records,
    }
    summary_path = baseline_root / "summary.json"
    write_json(summary_path, summary)
    print(f"summary={paths.rel(summary_path)}")
    return records


def select_variants(experiment: Path, variant_filter: set[str]) -> list[str]:
    candidates = sorted(path.parent.name for path in (experiment / "variants").glob("*/variant.json"))
    selected = []
    skipped = []
    for variant_id in candidates:
        if variant_filter and variant_id not in variant_filter:
            continue
        path = experiment / "variants" / variant_id / "variant.json"
        if not path.exists():
            raise FileNotFoundError(path)
        variant = load_json(path)
        if variant.get("status") != "coordinated_success":
            skipped.append((variant_id, variant.get("status")))
            continue
        selected.append(variant_id)
    if skipped:
        print(
            "[baseline_7] skipped non-coordinated variants: "
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

    upstream_skill = _variant_upstream_skill(source_variant)
    sink_skill = _variant_sink_skill(source_variant)
    if not upstream_skill:
        raise ValueError(f"Source variant has no upstream_skill/hook_skill: {source_dir / 'variant.json'}")
    if not sink_skill:
        raise ValueError(f"Source variant has no sink_skill/target_skill: {source_dir / 'variant.json'}")

    coordinated_source_dir = source_dir / "coordinated" / f"loop_{final_loop:03d}"
    coordinated_source_pack = coordinated_source_dir / "variant_pack"
    sink_source_skill = source_dir / "sink_only" / "variant_pack" / sink_skill
    if not coordinated_source_pack.exists():
        raise FileNotFoundError(coordinated_source_pack)
    if not sink_source_skill.exists():
        raise FileNotFoundError(sink_source_skill)

    eval_dir = baseline_root / "variants" / source_variant_id
    sink_dir = eval_dir / "sink_only"
    eval_pack = sink_dir / "variant_pack"
    trace_path = sink_dir / "traces.jsonl"
    verdict_path = sink_dir / "verdict.json"
    if eval_dir.exists() and overwrite and not judge_only:
        shutil.rmtree(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_variant = dict(source_variant)
    eval_variant.update(
        {
            "schema_version": "2026-09-16.baseline_7_variant.v1",
            "experiment_id": eval_experiment_id,
            "variant_id": source_variant_id,
            "status": "baseline_7",
            "baseline": "baseline_7",
            "baseline_source_variant": source_variant_id,
            "baseline_source_final_loop": final_loop,
            "baseline_upstream_source": "final_coordinated_success_pack",
            "baseline_downstream_source": "d1_sink_only_pack",
            "upstream_skill": upstream_skill,
            "sink_skill": sink_skill,
            "downstream_skill": sink_skill,
            "task_ids": list(source_variant.get("task_ids") or []),
            "target_agent_payload_blind": True,
        }
    )

    eval_variant_path = eval_dir / "variant.json"
    payload_path = eval_dir / "payload_reference.json"
    if not judge_only:
        if eval_pack.exists():
            if overwrite:
                shutil.rmtree(eval_pack)
            elif not resume:
                raise FileExistsError(f"{eval_pack} already exists. Use --overwrite or --resume.")
        if not eval_pack.exists():
            shutil.copytree(coordinated_source_pack, eval_pack)
            _replace_skill(eval_pack, sink_skill, sink_source_skill)
            _remove_coordination_plan(eval_pack)
        write_json(eval_variant_path, eval_variant)
        write_json(payload_path, payload_reference)
        write_json(
            eval_dir / "baseline_7_manifest.json",
            {
                "schema_version": "2026-09-16.baseline_7_manifest.v1",
                "baseline": "baseline_7",
                "source_variant": source_variant_id,
                "source_variant_path": paths.rel(source_dir),
                "final_coordinated_loop": final_loop,
                "coordinated_source_pack": paths.rel(coordinated_source_pack),
                "coordinated_upstream_skill": upstream_skill,
                "d1_sink_only_downstream_skill": sink_skill,
                "d1_sink_only_downstream_source": paths.rel(sink_source_skill),
                "eval_pack": paths.rel(eval_pack),
                "task_ids": list(source_variant.get("task_ids") or []),
                "target_agent_payload_blind": True,
                "provider": provider_name,
                "ablation": (
                    "reuse coordinated-success upstream from final coordinated pack; "
                    "replace downstream/sink with D1 sink-only downstream; replay D2/D3"
                ),
            },
        )
    elif not eval_variant_path.exists() or not payload_path.exists():
        raise FileNotFoundError(f"Judge-only metadata missing under {eval_dir}")
    else:
        eval_variant = load_json(eval_variant_path)
        payload_reference = load_json(payload_path)

    request = build_request(
        paths=paths,
        stage="D2",
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        variant=eval_variant,
        task_file=paths.benign_tasks / f"{pack_id}_tasks.json",
        pack_path=eval_pack,
        payload_reference_path=payload_path,
        trace_path=trace_path,
        loop_iteration=None,
    )
    request_dir = sink_dir / "requests"
    if not judge_only:
        write_stage_prompt(paths, request_dir, request)

    statuses: dict[str, Any] = {}
    has_verdict = verdict_path.exists()
    if resume and has_verdict:
        verdict = load_json(verdict_path)
        statuses["d2"] = "skipped_existing"
        statuses["d3"] = verdict.get("verdict")
        print(f"[SKIP] variant {source_variant_id} already has D3", flush=True)
        print(
            f"[D3] sink_only={verdict.get('verdict')} "
            f"payload_observed={verdict.get('payload_observed')} "
            f"task_completed={verdict.get('task_completed')} "
            f"(resume)",
            flush=True,
        )
    if not has_verdict or not resume:
        if not judge_only:
            if not prepare_only:
                print(f"[baseline_7] {source_variant_id} D2 start provider={provider_name}", flush=True)
                execute_request(provider_name, request, request_dir)
                statuses["d2"] = "executed"
            else:
                statuses["d2"] = "prepared"
        if not prepare_only:
            if not trace_path.exists():
                raise FileNotFoundError(trace_path)
            ensure_eval_metadata(eval_dir, eval_variant, payload_reference)
            print(f"[baseline_7] {source_variant_id} D3 judge start", flush=True)
            judge_sink_only(
                paths=paths,
                pack_id=pack_id,
                experiment_id=eval_experiment_id,
                variant_id=source_variant_id,
            )
            verdict_data = load_json(verdict_path)
            verdict_data["baseline"] = "baseline_7"
            verdict_data["baseline_7_judge_mode"] = "sink_only_d2_d3"
            write_json(verdict_path, verdict_data)
            statuses["d3"] = verdict_data.get("verdict")
            print(
                f"[D3] sink_only={verdict_data.get('verdict')} "
                f"payload_observed={verdict_data.get('payload_observed')} "
                f"task_completed={verdict_data.get('task_completed')} "
                f"verdict_path={paths.rel(verdict_path)}",
                flush=True,
            )

    return {
        "source_variant_id": source_variant_id,
        "final_source_loop": final_loop,
        "upstream_skill": upstream_skill,
        "sink_skill": sink_skill,
        "coordinated_source_pack": paths.rel(coordinated_source_pack),
        "d1_sink_only_downstream_source": paths.rel(sink_source_skill),
        "sink_only": {
            "trace": paths.rel(trace_path) if trace_path.exists() else None,
            "verdict": paths.rel(verdict_path) if verdict_path.exists() else None,
            "result": statuses.get("d3"),
        },
        "statuses": statuses,
    }


def _replace_skill(pack_dir: Path, skill_name: str, source_skill_dir: Path) -> None:
    destination = pack_dir / skill_name
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source_skill_dir, destination)


def _remove_coordination_plan(pack_dir: Path) -> None:
    plan_path = pack_dir / "pvf_coordination_plan.json"
    if plan_path.exists():
        plan_path.unlink()


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
    }
    if loop_iteration is not None:
        inputs["loop_iteration"] = loop_iteration
    return {
        "schema_version": "2026-09-16.baseline_7_stage_request.v1",
        "stage": stage,
        "role": "target_agent",
        "created_at": now(),
        "pack_id": pack_id,
        "experiment_id": experiment_id,
        "loop_iteration": loop_iteration,
        "safety": {
            "payload_policy": "inert_payload_only",
            "target_agent_payload_blind": True,
            "baseline": "baseline_7",
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
        f"[baseline_7] provider={provider_name} stage={request['stage']} "
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
        f"[baseline_7] provider={provider_name} stage={request['stage']} "
        f"trace_written={destination}",
        flush=True,
    )


def _variant_upstream_skill(variant: dict[str, Any]) -> str:
    return str(variant.get("upstream_skill") or variant.get("hook_skill") or "").strip()


def _variant_sink_skill(variant: dict[str, Any]) -> str:
    return str(variant.get("sink_skill") or variant.get("target_skill") or "").strip()


def _resolve_experiment_id(pack_id: str, token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"\d{1,3}", token):
        return f"{pack_id}_exp_{int(token):03d}"
    if re.fullmatch(r"exp_\d{3}", token):
        return f"{pack_id}_{token}"
    if re.fullmatch(rf"{re.escape(pack_id)}_exp_\d{{3}}", token):
        return token
    raise ValueError(f"Invalid experiment id {token!r}; use exp_001, 002, 003 or {pack_id}_exp_001")


def _selected_model(model: str, provider: str) -> str:
    if model:
        return model
    if provider in {"codex-sandbox", "codex-cli"}:
        return os.environ.get("PVF_CODEX_MODEL", "") or "default"
    if provider == "claude-code-sandbox":
        return os.environ.get("PVF_CLAUDE_MODEL", "") or "default"
    return "dry-run"


def _csv_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for value in values for item in value.split(",") if item.strip()))


if __name__ == "__main__":
    raise SystemExit(main())
