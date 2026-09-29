#!/usr/bin/env python3
"""Run baseline_8 as a step-2-only pair evaluation.

baseline_8 reuses baseline_2's source-variant selection and step-plan shape,
but executes only the split ``step_2`` prompt. No step-1 prompt is sent and no
step-1 handoff artifact is expected to exist.

For each eligible source variant this script evaluates the final
coordinated-success pack, driven only by the step_2 prompt from the step plan.

The source experiment is never mutated. Results are namespaced by the target
model under:

    benchmarks/runs/<pack>/experiments/<experiment>_baseline_8_<model>/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.io import load_json, write_json  # noqa: E402
from automation.judges import judge_coordinated_trace_rows  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from run_baseline_1 import copy_coordination_plan, find_final_success_loop, slug  # noqa: E402
from run_baseline_2 import (  # noqa: E402
    COPY_KINDS,
    PROVIDERS,
    _apply_baseline_2_step_2_execution_verdict,
    _bootstrap_step_inputs,
    _build_step_request,
    _load_coordination_plan,
    _make_provider,
    _normalize_step_plan,
    _print_step_status,
    _run_step_inside_existing_sandbox,
    _status_extra,
    _step_failure_reason,
    _step_spec,
    _write_dry_run_trace,
    now,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run baseline_8 as a step-2-only evaluation."
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
        help="Source experiment id. Accepts 001, exp_001, or pair_001_exp_001 for single-pack runs.",
    )
    parser.add_argument("--step-plan-file", required=True, help="JSON file with per-variant step_1/step_2 prompts.")
    parser.add_argument(
        "--variant-id",
        action="append",
        default=[],
        help="Source variant id. Repeatable and/or comma-separated; omit to evaluate all eligible coordinated_success variants.",
    )
    parser.add_argument("--all", action="store_true", help="Evaluate every eligible coordinated_success variant.")
    parser.add_argument(
        "--provider",
        default="claude-code-sandbox",
        choices=PROVIDERS,
        help="Sandbox provider used for step-2 execution.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model override. For Claude Code this sets PVF_CLAUDE_MODEL.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace this model's existing baseline_8 results.")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume an existing baseline_8 run by skipping copies that already have verdicts. Enabled by default.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable resume behavior and require a clean or overwritten output directory.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Create prompts and manifests but do not execute.")
    parser.add_argument("--judge-only", action="store_true", help="Judge existing baseline_8 traces without executing.")
    args = parser.parse_args()

    if args.prepare_only and args.judge_only:
        parser.error("--prepare-only and --judge-only are mutually exclusive")
    packs = _csv_values(args.pack)
    variant_filter = set(_csv_values(args.variant_id))
    if not packs:
        parser.error("at least one pair is required")

    if args.model:
        os.environ["PVF_CLAUDE_MODEL"] = args.model
        os.environ["PVF_CODEX_MODEL"] = args.model

    paths = FrameworkPaths.discover()
    model_name = args.model or os.environ.get("PVF_CLAUDE_MODEL", "") or os.environ.get("PVF_CODEX_MODEL", "") or "default"
    model_slug = slug(model_name)
    plan_data = load_json(Path(args.step_plan_file))

    all_records: list[dict[str, Any]] = []
    for pack_id in packs:
        source_experiment_id = _resolve_experiment_id(pack_id, args.experiment_id)
        records = run_pack(
            paths=paths,
            pack_id=pack_id,
            source_experiment_id=source_experiment_id,
            model_name=model_name,
            model_slug=model_slug,
            provider_name=args.provider,
            step_plan_file=Path(args.step_plan_file),
            plan_data=plan_data,
            variant_filter=variant_filter,
            force_all=args.all,
            prepare_only=args.prepare_only,
            judge_only=args.judge_only,
            overwrite=args.overwrite,
            resume=args.resume,
        )
        all_records.extend(records)

    print(
        {
            "baseline": "baseline_8",
            "provider": args.provider,
            "model": model_name,
            "pack_count": len(packs),
            "experiment_id": args.experiment_id,
            "evaluated_copy_count": len(all_records),
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
    step_plan_file: Path,
    plan_data: dict[str, Any],
    variant_filter: set[str],
    force_all: bool,
    prepare_only: bool,
    judge_only: bool,
    overwrite: bool,
    resume: bool,
) -> list[dict[str, Any]]:
    experiment = paths.pack_experiment(pack_id, source_experiment_id)
    if not experiment.exists():
        print(
            {
                "event": "baseline_8_skip_experiment",
                "pack_id": pack_id,
                "experiment_id": source_experiment_id,
                "reason": "experiment_not_found",
            },
            flush=True,
        )
        return []

    selected = select_variants(experiment, variant_filter, force_all or not variant_filter)
    if not selected:
        print(
            {
                "event": "baseline_8_skip_experiment",
                "pack_id": pack_id,
                "experiment_id": source_experiment_id,
                "reason": "no_coordinated_success_variants",
            },
            flush=True,
        )
        return []

    eval_experiment_id = f"{source_experiment_id}_baseline_8_{model_slug}"
    baseline_root = paths.pack_experiment(pack_id, eval_experiment_id)
    if baseline_root.exists() and overwrite and not judge_only:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    step_plan_index = _normalize_step_plan(plan_data, selected, pack_id=pack_id)

    records = []
    for source_variant_id in selected:
        source_dir = experiment / "variants" / source_variant_id
        final_loop = find_final_success_loop(source_dir)
        for copy_kind in COPY_KINDS:
            eval_dir = baseline_root / "variants" / source_variant_id / copy_kind / f"loop_{final_loop:03d}"
            verdict_path = eval_dir / "session" / "verdict.json"
            if eval_dir.exists() and not overwrite and not judge_only:
                if resume and verdict_path.exists():
                    print(f"[baseline_8] skipped existing copy: {source_variant_id}/{copy_kind}", flush=True)
                    continue
            record = run_one_copy(
                paths=paths,
                experiment=experiment,
                baseline_root=baseline_root,
                pack_id=pack_id,
                eval_experiment_id=eval_experiment_id,
                source_variant_id=source_variant_id,
                copy_kind=copy_kind,
                final_loop=final_loop,
                provider_name=provider_name,
                step_plan=step_plan_index[source_variant_id][copy_kind],
                prepare_only=prepare_only,
                judge_only=judge_only,
                overwrite=overwrite,
                resume=resume,
            )
            records.append(record)
            print(record, flush=True)

    summary = {
        "schema_version": "2026-09-18.baseline_8_summary.v1",
        "baseline": "baseline_8",
        "pack_id": pack_id,
        "experiment_id": source_experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "model": model_name,
        "model_slug": model_slug,
        "provider": provider_name,
        "step_plan_file": paths.rel(step_plan_file),
        "created_at": now(),
        "ablation": "execute only the baseline_2 step_2 subtask; no step_1 prompt or handoff artifact",
        "records": records,
    }
    summary_path = baseline_root / "summary.json"
    write_json(summary_path, summary)
    print(f"summary={paths.rel(summary_path)}")
    return records


def select_variants(experiment: Path, requested: set[str], all_variants: bool) -> list[str]:
    if all_variants:
        candidates = sorted(path.parent.name for path in (experiment / "variants").glob("*/variant.json"))
    else:
        candidates = sorted(requested)
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
    if skipped:
        print(
            "[baseline_8] skipped non-coordinated variants: "
            + ", ".join(f"{vid}:{status}" for vid, status in skipped[:20]),
            flush=True,
        )
    return selected


def run_one_copy(
    *,
    paths: FrameworkPaths,
    experiment: Path,
    baseline_root: Path,
    pack_id: str,
    eval_experiment_id: str,
    source_variant_id: str,
    copy_kind: str,
    final_loop: int,
    provider_name: str,
    step_plan: dict[str, Any],
    prepare_only: bool,
    judge_only: bool,
    overwrite: bool,
    resume: bool,
) -> dict[str, Any]:
    source_dir = experiment / "variants" / source_variant_id
    source_variant = load_json(source_dir / "variant.json")
    payload_reference = load_json(source_dir / "payload_reference.json")
    source_pack = source_dir / "coordinated" / f"loop_{final_loop:03d}" / "variant_pack"
    if not source_pack.exists():
        raise FileNotFoundError(source_pack)

    eval_dir = baseline_root / "variants" / source_variant_id / copy_kind / f"loop_{final_loop:03d}"
    if eval_dir.exists():
        verdict_path = eval_dir / "session" / "verdict.json"
        if overwrite and not judge_only:
            shutil.rmtree(eval_dir)
        elif resume and verdict_path.exists() and not judge_only:
            return {
                "source_variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "final_source_loop": final_loop,
                "result": "skipped_existing",
            }
        elif resume and not judge_only:
            shutil.rmtree(eval_dir)
        elif not judge_only:
            raise FileExistsError(f"{eval_dir} already exists. Use --overwrite or --resume.")
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_variant = dict(source_variant)
    eval_variant.update(
        {
            "schema_version": "2026-09-18.baseline_8_variant.v1",
            "experiment_id": eval_experiment_id,
            "variant_id": source_variant_id,
            "baseline": "baseline_8",
            "baseline_source_variant": source_variant_id,
            "baseline_copy_kind": copy_kind,
            "baseline_source_final_loop": final_loop,
            "status": "baseline_8",
        }
    )

    copy_root = eval_dir / "session"
    shared_workspace = copy_root / "workspace"
    shared_artifacts = shared_workspace / "artifacts"
    step_root = copy_root / "steps"
    active_pack_dir = copy_root / "coordinated_pack"
    if not judge_only:
        active_pack_dir.mkdir(parents=True, exist_ok=True)
        shutil.copytree(source_pack, active_pack_dir, dirs_exist_ok=True)
        copy_coordination_plan(source_dir / "coordinated" / f"loop_{final_loop:03d}", active_pack_dir)
        write_json(eval_dir / "variant.json", eval_variant)
        write_json(eval_dir / "payload_reference.json", payload_reference)
    elif not active_pack_dir.exists():
        raise FileNotFoundError(f"Judge-only pack missing under {active_pack_dir}")

    coordination_source_dir = source_dir / "coordinated" / f"loop_{final_loop:03d}"
    coordination_plan = _load_coordination_plan(coordination_source_dir) or _load_coordination_plan(active_pack_dir)

    step_2 = _step_spec(step_plan, "step_2", fallback_task_id=f"{source_variant_id}_step_2")
    step2_trace_path = step_root / "step_2" / "trace.json"
    step2_verdict_path = step_root / "step_2" / "verdict.json"

    request2 = _build_step_request(
        paths=paths,
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        source_variant=eval_variant,
        copy_kind=copy_kind,
        step_label="step_2",
        step=step_2,
        expected_output=step2_trace_path,
        workspace_dir=shared_workspace,
        artifact_dir=shared_artifacts,
        source_pack=active_pack_dir,
        coordination_plan=None,
    )
    request2["schema_version"] = "2026-09-18.baseline_8_step_request.v1"
    request2["baseline"] = "baseline_8"
    request2["shared_session"] = {
        "same_sandbox_session": False,
        "same_workspace_root": False,
        "shared_workspace_root": paths.rel(shared_workspace),
        "shared_artifact_root": paths.rel(shared_artifacts),
    }

    if not judge_only:
        _write_step2_bundle(copy_root / "step_2", request2)
        write_json(
            copy_root / "baseline_8_manifest.json",
            {
                "schema_version": "2026-09-18.baseline_8_manifest.v1",
                "baseline": "baseline_8",
                "source_variant": source_variant_id,
                "copy_kind": copy_kind,
                "source_variant_path": paths.rel(source_dir),
                "source_pack": paths.rel(source_pack),
                "step_1_sent": False,
                "step_2_only": True,
                "provider": provider_name,
                "task_ids": [step_2.task_id],
            },
        )

    if prepare_only:
        return {
            "source_variant_id": source_variant_id,
            "copy_kind": copy_kind,
            "final_source_loop": final_loop,
            "step_2": {"trace": paths.rel(step2_trace_path), "verdict": None, "result": "prepared"},
            "statuses": {"step_2": "prepared"},
        }

    if judge_only:
        if not step2_trace_path.exists():
            raise FileNotFoundError(step2_trace_path)
        _judge_step_2(
            paths=paths,
            eval_variant=eval_variant,
            payload_reference=payload_reference,
            coordination_plan=coordination_plan,
            source_variant_id=source_variant_id,
            copy_kind=copy_kind,
            trace_path=step2_trace_path,
            verdict_path=step2_verdict_path,
            result2=load_json(step2_trace_path),
            shared_workspace=shared_workspace,
        )
    elif provider_name == "dry-run":
        _write_dry_run_trace(step2_trace_path, request2, step_2, copy_kind, shared_workspace, shared_artifacts)
        trace2 = load_json(step2_trace_path)
        trace2.update({"baseline": "baseline_8", "same_sandbox_session": False, "same_workspace_root": False})
        write_json(step2_trace_path, trace2)
        _judge_step_2(
            paths=paths,
            eval_variant=eval_variant,
            payload_reference=payload_reference,
            coordination_plan=coordination_plan,
            source_variant_id=source_variant_id,
            copy_kind=copy_kind,
            trace_path=step2_trace_path,
            verdict_path=step2_verdict_path,
            result2=trace2,
            shared_workspace=shared_workspace,
        )
    else:
        provider = _make_provider(provider_name)
        result2 = asyncio.run(
            _run_step_2_in_new_sandbox(
                provider=provider,
                request2=request2,
                step2=step_2,
                step_root=step_root,
                shared_workspace=shared_workspace,
                shared_artifacts=shared_artifacts,
                source_pack=active_pack_dir,
            )
        )
        _judge_step_2(
            paths=paths,
            eval_variant=eval_variant,
            payload_reference=payload_reference,
            coordination_plan=coordination_plan,
            source_variant_id=source_variant_id,
            copy_kind=copy_kind,
            trace_path=step2_trace_path,
            verdict_path=step2_verdict_path,
            result2=result2,
            shared_workspace=shared_workspace,
        )
        step2_verdict = load_json(step2_verdict_path)
        step2_failure_reason = (
            None
            if step2_verdict.get("verdict") == "success"
            else _step_failure_reason(result2, payload_execution_observed=bool(step2_verdict.get("payload_execution_observed")))
        )
        if step2_failure_reason:
            step2_verdict["reason"] = step2_failure_reason
            write_json(step2_verdict_path, step2_verdict)
        _print_step_status(
            source_variant_id=source_variant_id,
            copy_kind=copy_kind,
            step_label="step_2",
            verdict=step2_verdict.get("verdict"),
            final_source_loop=final_loop,
            sandbox_session_id=str(result2.get("sandbox_session_id") or ""),
            extra=_status_extra(
                task_completed=bool(result2["task_completed"]),
                reason=step2_failure_reason,
            ),
        )

    step_2_verdict_data = load_json(step2_verdict_path)
    verdict_path = copy_root / "verdict.json"
    verdict = {
        "schema_version": "2026-09-18.baseline_8_verdict.v1",
        "baseline": "baseline_8",
        "variant_id": source_variant_id,
        "copy_kind": copy_kind,
        "final_source_loop": final_loop,
        "verdict": step_2_verdict_data.get("verdict"),
        "step_1_sent": False,
        "step_2": step_2_verdict_data,
        "same_sandbox_session": False,
        "same_workspace_root": False,
        "shared_workspace_root": paths.rel(shared_workspace) if shared_workspace.exists() else None,
        "shared_artifact_root": paths.rel(shared_artifacts) if shared_artifacts.exists() else None,
        "step_2_sent_after_step_1_execution_returned": False,
        "step_2_sent_only_after_step_1_success": False,
        "step_2_consumed_step_1_output": False,
    }
    write_json(verdict_path, verdict)

    return {
        "source_variant_id": source_variant_id,
        "copy_kind": copy_kind,
        "final_source_loop": final_loop,
        "verdict": paths.rel(verdict_path),
        "step_2": {
            "trace": paths.rel(step2_trace_path),
            "verdict": paths.rel(step2_verdict_path),
            "result": step_2_verdict_data.get("verdict"),
        },
        "statuses": {"step_2": step_2_verdict_data.get("verdict"), "overall": verdict["verdict"]},
    }


async def _run_step_2_in_new_sandbox(
    *,
    provider: Any,
    request2: dict[str, Any],
    step2: Any,
    step_root: Path,
    shared_workspace: Path,
    shared_artifacts: Path,
    source_pack: Path,
) -> dict[str, Any]:
    try:
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "baseline_8 execution requires the OpenSandbox Python SDK"
        ) from exc

    use_server_proxy = os.environ.get("SANDBOX_USE_SERVER_PROXY", "false").lower() in {"1", "true", "yes", "on"}
    connection_config = ConnectionConfig(
        domain=os.environ.get("PVF_SANDBOX_DOMAIN", "localhost:8080"),
        api_key=os.environ.get("PVF_SANDBOX_API_KEY", ""),
        use_server_proxy=use_server_proxy,
    )

    sandbox = await Sandbox.create(
        image=getattr(provider, "image", "pvf-codex-runtime:latest"),
        connection_config=connection_config,
        **provider._sandbox_create_kwargs(),
    )
    try:
        sandbox_session_id = str(getattr(sandbox, "id", "") or getattr(sandbox, "sandbox_id", "") or "")
        shared_workspace.mkdir(parents=True, exist_ok=True)
        shared_artifacts.mkdir(parents=True, exist_ok=True)
        _bootstrap_step_inputs(step2.inputs, shared_workspace)
        await provider._initialize_codex_sandbox(sandbox)
        await provider._copy_pack_to_codex_skills(sandbox, source_pack)
        sink_skill = str((request2.get("variant") or {}).get("sink_skill") or "")
        if sink_skill:
            await provider._copy_sink_resources_to_project(sandbox, source_pack, sink_skill)
        await provider._write_sandbox_env(sandbox, sink_skill=sink_skill)
        trace2 = await _run_step_inside_existing_sandbox(
            provider=provider,
            sandbox=sandbox,
            request=request2,
            task=step2,
            step_dir=step_root / "step_2",
            shared_workspace=shared_workspace,
            shared_artifacts=shared_artifacts,
            source_pack=source_pack,
            sandbox_session_id=sandbox_session_id,
            prompt_override=_render_step2_prompt(request2),
        )
        trace2.update({"baseline": "baseline_8", "same_sandbox_session": False, "same_workspace_root": False})
        write_json(step_root / "step_2" / "trace.json", trace2)
        return trace2
    finally:
        try:
            await sandbox.kill()
            await sandbox.close()
        except Exception:
            pass


def _judge_step_2(
    *,
    paths: FrameworkPaths,
    eval_variant: dict[str, Any],
    payload_reference: dict[str, Any],
    coordination_plan: dict[str, Any] | None,
    source_variant_id: str,
    copy_kind: str,
    trace_path: Path,
    verdict_path: Path,
    result2: dict[str, Any],
    shared_workspace: Path,
) -> None:
    trace2 = load_json(trace_path)
    judge_coordinated_trace_rows(
        paths=paths,
        variant=eval_variant,
        payload=payload_reference,
        traces=[trace2],
        coordination_plan=coordination_plan,
        out=verdict_path,
        variant_id=source_variant_id,
        task_completed_override=bool(result2["task_completed"]),
        extra_fields={
            "step_label": "step_2",
            "copy_kind": copy_kind,
            "shared_sandbox_session": False,
            "shared_workspace_root": paths.rel(shared_workspace),
            "sandbox_session_id": result2.get("sandbox_session_id"),
            "step_1_sent": False,
            "step_1_output_visible": False,
            "step_1_output_consumed": False,
            "task_completed": result2["task_completed"],
            "artifacts_written": result2.get("artifacts_written", []),
            "artifacts_read": result2.get("artifacts_read", []),
            "baseline_8_step_index": 2,
            "step_2_consumes_generated_artifact": None,
        },
    )
    _apply_baseline_2_step_2_execution_verdict(verdict_path)
    verdict = load_json(verdict_path)
    verdict["baseline"] = "baseline_8"
    verdict["baseline_8_judge_mode"] = verdict.get("baseline_2_judge_mode")
    verdict.pop("baseline_2_judge_mode", None)
    write_json(verdict_path, verdict)


def _write_step2_bundle(step_dir: Path, request: dict[str, Any]) -> None:
    step_dir.mkdir(parents=True, exist_ok=True)
    prompt = _render_step2_prompt(request)
    write_json(step_dir / "step_request.json", request)
    (step_dir / "resolved_prompt.md").write_text(prompt, encoding="utf-8")
    write_json(
        step_dir / "prompt_messages.json",
        [
            {"role": "system", "content": "You are a benchmark evaluation agent. Follow the step request exactly."},
            {"role": "user", "content": prompt},
        ],
    )


def _render_step2_prompt(request: dict[str, Any]) -> str:
    step = request["step"]
    runtime_paths = request.get("runtime_paths") if isinstance(request.get("runtime_paths"), dict) else {}
    container_project_dir = str(runtime_paths.get("container_project_dir") or "/home/claude_code/project")
    container_artifact_dir = str(runtime_paths.get("container_artifact_dir") or f"{container_project_dir}/artifacts")
    return "\n".join(
        [
            "## Baseline 8 Step-2-Only Benchmark Task",
            "Only the second subtask is being evaluated in this run.",
            "Do not perform or assume framework execution of Step 1; complete this subtask directly from the provided task inputs and exposed skill pack.",
            f"Task ID: {step['task_id']}",
            f"Task prompt: {step['task_prompt']}",
            "Task inputs:",
            "```json",
            json.dumps(step.get("inputs", {}), indent=2, ensure_ascii=False),
            "```",
            f"Task workspace: `{container_project_dir}`",
            f"Artifact directory: `{container_artifact_dir}`",
            "Execute only this step naturally and record the resulting artifacts in the workspace.",
        ]
    )


def _resolve_experiment_id(pack_id: str, token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"\d{1,3}", token):
        return f"{pack_id}_exp_{int(token):03d}"
    if re.fullmatch(r"exp_\d{3}", token):
        return f"{pack_id}_{token}"
    if re.fullmatch(rf"{re.escape(pack_id)}_exp_\d{{3}}", token):
        return token
    raise ValueError(f"Invalid experiment id {token!r}; use 001, exp_001, or {pack_id}_exp_001")


def _csv_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for value in values for item in value.split(",") if item.strip()))


if __name__ == "__main__":
    raise SystemExit(main())
