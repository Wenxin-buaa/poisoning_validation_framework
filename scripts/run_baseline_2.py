#!/usr/bin/env python3
"""Run baseline_2 as a shared-sandbox stepwise pair evaluation.

baseline_2 reuses the existing benchmark runtime shape, but changes the
evaluation unit from a single full-task prompt to two ordered prompts executed
in the same sandbox session and the same workspace/artifact root.

For each eligible source variant this script evaluates two immutable copies:

* the original D1 sink-only pack, but driven by split step_1/step_2 prompts;
* the final coordinated-success pack, also driven by the same split prompts.

The source experiment is never mutated. Results are namespaced by the target
model under:

    benchmarks/runs/<pack>/experiments/<experiment>/baseline_2/<model>/
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shlex
import shutil
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.io import load_json, write_json  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from automation.providers import (  # noqa: E402
    ClaudeCodeSandboxProvider,
    CodexSandboxProvider,
    _build_evidence_bundle,
    _command_trace_capture,
    _dedupe_flow_edges,
    _infer_artifact_flow_edges,
    _infer_artifacts_read,
    _observed_skills,
    _walk_files,
    _workflow_completed,
    _workspace_entries,
    _workspace_files,
)
from run_baseline_1 import copy_coordination_plan, find_final_success_loop, select_variants, slug  # noqa: E402


PROVIDERS = ("claude-code-sandbox", "codex-sandbox", "dry-run")
COPY_KINDS = ("sink_only", "coordinated")


@dataclass(frozen=True)
class StepSpec:
    task_id: str
    task_prompt: str
    inputs: dict[str, Any]
    expected_output_artifact: str | None = None
    consumes_artifact: str | None = None


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run baseline_2 as a shared-sandbox, two-step evaluation."
    )
    parser.add_argument("--pack", required=True)
    parser.add_argument("--experiment-id", required=True)
    parser.add_argument("--step-plan-file", required=True, help="JSON file with per-variant step_1/step_2 prompts.")
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
        help="Sandbox provider used for the shared stepwise execution.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model override. For Claude Code this sets PVF_CLAUDE_MODEL.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace this model's existing baseline_2 results.")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume an existing baseline_2 run by skipping copies that already have verdicts. Enabled by default.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable resume behavior and require a clean or overwritten output directory.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Create prompts and manifests but do not execute.")
    parser.add_argument("--judge-only", action="store_true", help="Judge existing baseline_2 traces without executing.")
    args = parser.parse_args()

    if args.prepare_only and args.judge_only:
        parser.error("--prepare-only and --judge-only are mutually exclusive")
    if not args.variant_id and not args.all:
        parser.error("provide --variant-id or --all")

    if args.model:
        os.environ["PVF_CLAUDE_MODEL"] = args.model
        os.environ["PVF_CODEX_MODEL"] = args.model

    paths = FrameworkPaths.discover()
    experiment = paths.pack_experiment(args.pack, args.experiment_id)
    if not experiment.exists():
        raise FileNotFoundError(experiment)

    selected = select_variants(experiment, args.variant_id, args.all)
    model_name = args.model or os.environ.get("PVF_CLAUDE_MODEL", "") or os.environ.get("PVF_CODEX_MODEL", "") or "default"
    model_slug = slug(model_name)
    eval_experiment_id = f"{args.experiment_id}_baseline_2_{model_slug}"
    baseline_root = paths.pack_experiment(args.pack, eval_experiment_id)
    if baseline_root.exists() and args.overwrite:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    plan_data = load_json(Path(args.step_plan_file))
    step_plan_index = _normalize_step_plan(plan_data, selected)

    records = []
    for source_variant_id in selected:
        source_dir = experiment / "variants" / source_variant_id
        final_loop = find_final_success_loop(source_dir)
        for copy_kind in COPY_KINDS:
            eval_dir = baseline_root / "variants" / source_variant_id / copy_kind
            if copy_kind == "coordinated":
                eval_dir = baseline_root / "variants" / source_variant_id / copy_kind / f"loop_{final_loop:03d}"
            if eval_dir.exists() and not args.overwrite:
                if args.resume:
                    print(f"[baseline_2] skipped existing copy: {source_variant_id}/{copy_kind}", flush=True)
                    continue
            record = run_one_copy(
                paths=paths,
                experiment=experiment,
                baseline_root=baseline_root,
                pack_id=args.pack,
                experiment_id=args.experiment_id,
                eval_experiment_id=eval_experiment_id,
                source_variant_id=source_variant_id,
                copy_kind=copy_kind,
                final_loop=final_loop,
                provider_name=args.provider,
                step_plan=step_plan_index[source_variant_id][copy_kind],
                prepare_only=args.prepare_only,
                judge_only=args.judge_only,
                overwrite=args.overwrite,
                resume=args.resume,
            )
            records.append(record)
            print(record, flush=True)

    summary = {
        "schema_version": "2026-08-27.baseline_2_summary.v1",
        "baseline": "baseline_2",
        "pack_id": args.pack,
        "experiment_id": args.experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "model": model_name,
        "model_slug": model_slug,
        "provider": args.provider,
        "step_plan_file": paths.rel(Path(args.step_plan_file)),
        "created_at": now(),
        "records": records,
    }
    summary_path = baseline_root / "summary.json"
    write_json(summary_path, summary)
    print(f"summary={paths.rel(summary_path)}")
    return 0


def run_one_copy(
    *,
    paths: FrameworkPaths,
    experiment: Path,
    baseline_root: Path,
    pack_id: str,
    experiment_id: str,
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

    eval_dir = baseline_root / "variants" / source_variant_id / copy_kind
    if copy_kind == "coordinated":
        eval_dir = baseline_root / "variants" / source_variant_id / copy_kind / f"loop_{final_loop:03d}"
    if eval_dir.exists():
        if overwrite and not judge_only:
            shutil.rmtree(eval_dir)
        elif resume:
            return {
                "source_variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "final_source_loop": final_loop,
                "result": "skipped_existing",
            }
        else:
            raise FileExistsError(f"{eval_dir} already exists. Use --overwrite or --resume.")
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_variant = dict(source_variant)
    eval_variant.update(
        {
            "schema_version": "2026-08-27.baseline_2_variant.v1",
            "experiment_id": eval_experiment_id,
            "variant_id": source_variant_id,
            "baseline": "baseline_2",
            "baseline_source_variant": source_variant_id,
            "baseline_copy_kind": copy_kind,
            "baseline_source_final_loop": final_loop,
            "status": "baseline_2",
        }
    )
    if copy_kind == "sink_only":
        source_pack = source_dir / "sink_only" / "variant_pack"
    else:
        source_pack = source_dir / "coordinated" / f"loop_{final_loop:03d}" / "variant_pack"
    if not source_pack.exists():
        raise FileNotFoundError(source_pack)

    copy_root = eval_dir / "session"
    shared_workspace = copy_root / "workspace"
    shared_artifacts = shared_workspace / "artifacts"
    step_root = copy_root / "steps"
    sink_dir = copy_root / "sink_only_pack"
    coord_dir = copy_root / "coordinated_pack"
    active_pack_dir = sink_dir if copy_kind == "sink_only" else coord_dir
    active_pack_dir.mkdir(parents=True, exist_ok=True)
    if not judge_only:
        shutil.copytree(source_pack, active_pack_dir, dirs_exist_ok=True)
        if copy_kind == "coordinated":
            copy_coordination_plan(source_dir / "coordinated" / f"loop_{final_loop:03d}", copy_root / "coordinated_pack")
        write_json(eval_dir / "variant.json", eval_variant)
        write_json(eval_dir / "payload_reference.json", payload_reference)

    step_1 = _step_spec(step_plan, "step_1", fallback_task_id=f"{source_variant_id}_step_1")
    step_2 = _step_spec(step_plan, "step_2", fallback_task_id=f"{source_variant_id}_step_2")
    if step_2.consumes_artifact is None and step_1.expected_output_artifact:
        step_2 = StepSpec(
            task_id=step_2.task_id,
            task_prompt=step_2.task_prompt,
            inputs=step_2.inputs,
            expected_output_artifact=step_2.expected_output_artifact,
            consumes_artifact=step_1.expected_output_artifact,
        )

    step1_trace_path = step_root / "step_1" / "trace.json"
    step2_trace_path = step_root / "step_2" / "trace.json"
    step1_verdict_path = step_root / "step_1" / "verdict.json"
    step2_verdict_path = step_root / "step_2" / "verdict.json"

    request1 = _build_step_request(
        paths=paths,
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        source_variant=eval_variant,
        copy_kind=copy_kind,
        step_label="step_1",
        step=step_1,
        expected_output=step1_trace_path,
        workspace_dir=shared_workspace,
        artifact_dir=shared_artifacts,
        source_pack=active_pack_dir,
    )
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
    )

    if not judge_only:
        _write_step_bundle(copy_root / "step_1", request1)
        _write_step_bundle(copy_root / "step_2", request2)
        write_json(
            copy_root / "baseline_2_manifest.json",
            {
                "schema_version": "2026-08-27.baseline_2_manifest.v1",
                "baseline": "baseline_2",
                "source_variant": source_variant_id,
                "copy_kind": copy_kind,
                "source_variant_path": paths.rel(source_dir),
                "source_pack": paths.rel(source_pack),
                "shared_sandbox_session": True,
                "shared_workspace_root": paths.rel(shared_workspace),
                "shared_artifact_root": paths.rel(shared_artifacts),
                "step_1_completed_before_step_2_sent": True,
                "step_1_output_visible_to_step_2": bool(step_2.consumes_artifact or step_1.expected_output_artifact),
                "step_1_output_artifact": step_1.expected_output_artifact,
                "step_2_consumes_artifact": step_2.consumes_artifact,
                "provider": provider_name,
                "task_ids": [step_1.task_id, step_2.task_id],
            },
        )

    if prepare_only:
        return {
            "source_variant_id": source_variant_id,
            "copy_kind": copy_kind,
            "final_source_loop": final_loop,
            "step_1": {"trace": paths.rel(step1_trace_path), "verdict": None, "result": "prepared"},
            "step_2": {"trace": paths.rel(step2_trace_path), "verdict": None, "result": "prepared"},
            "statuses": {"step_1": "prepared", "step_2": "prepared"},
        }

    if judge_only:
        if not step1_verdict_path.exists() or not step2_verdict_path.exists():
            raise FileNotFoundError(
                f"judge-only requires existing verdicts at {step1_verdict_path} and {step2_verdict_path}"
            )
        step1_data = load_json(step1_verdict_path)
        step2_data = load_json(step2_verdict_path)
        step_2_consumed = bool(step2_data.get("step_1_output_consumed"))
        verdict_path = copy_root / "verdict.json"
        verdict = {
            "schema_version": "2026-08-27.baseline_2_verdict.v1",
            "baseline": "baseline_2",
            "variant_id": source_variant_id,
            "copy_kind": copy_kind,
            "final_source_loop": final_loop,
            "verdict": "success"
            if step1_data.get("verdict") == "success" and step2_data.get("verdict") == "success" and step_2_consumed
            else "failure",
            "step_1": step1_data,
            "step_2": step2_data,
            "same_sandbox_session": True,
            "same_workspace_root": True,
            "shared_workspace_root": paths.rel(shared_workspace) if shared_workspace.exists() else None,
            "shared_artifact_root": paths.rel(shared_artifacts) if shared_artifacts.exists() else None,
            "step_2_sent_only_after_step_1_success": step1_data.get("verdict") == "success",
            "step_2_consumed_step_1_output": bool(step_2_consumed),
            "step_1_output_artifact": step_1.expected_output_artifact,
            "step_2_consumes_artifact": step_2.consumes_artifact,
        }
        write_json(verdict_path, verdict)
        return {
            "source_variant_id": source_variant_id,
            "copy_kind": copy_kind,
            "final_source_loop": final_loop,
            "verdict": paths.rel(verdict_path),
            "step_1": {"trace": paths.rel(step1_trace_path), "verdict": paths.rel(step1_verdict_path), "result": step1_data.get("verdict")},
            "step_2": {"trace": paths.rel(step2_trace_path), "verdict": paths.rel(step2_verdict_path), "result": step2_data.get("verdict")},
            "statuses": {
                "step_1": step1_data.get("verdict"),
                "step_2": step2_data.get("verdict"),
                "overall": verdict["verdict"],
            },
        }

    if provider_name == "dry-run":
        _write_dry_run_trace(step1_trace_path, request1, step_1, copy_kind, shared_workspace, shared_artifacts)
        if step_2.consumes_artifact:
            _write_dry_run_trace(step2_trace_path, request2, step_2, copy_kind, shared_workspace, shared_artifacts)
        _write_verdict(
            step1_verdict_path,
            {
                "variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "step_label": "step_1",
                "verdict": "success",
                "reason": "dry_run",
            },
        )
        _write_verdict(
            step2_verdict_path,
            {
                "variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "step_label": "step_2",
                "verdict": "success",
                "reason": "dry_run",
            },
        )
    else:
        provider = _make_provider(provider_name)
        result1, result2 = asyncio.run(
            _run_two_steps_in_one_sandbox(
                provider=provider,
                request1=request1,
                step1=step_1,
                request2=request2,
                step2=step_2,
                step_root=step_root,
                shared_workspace=shared_workspace,
                shared_artifacts=shared_artifacts,
                source_pack=active_pack_dir,
            )
        )
        _write_verdict(
            step1_verdict_path,
            {
                "variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "step_label": "step_1",
                "verdict": "success" if result1["task_completed"] else "failure",
                "task_completed": result1["task_completed"],
                "artifacts_written": result1["artifacts_written"],
                "artifacts_read": result1["artifacts_read"],
                "shared_sandbox_session": True,
                "shared_workspace_root": paths.rel(shared_workspace),
                "sandbox_session_id": result1.get("sandbox_session_id"),
                "step_1_output_visible": _artifact_exists_in_workspace(shared_workspace, step_2.consumes_artifact or step_1.expected_output_artifact),
            },
        )
        if not result1["task_completed"]:
            _write_verdict(
                step2_verdict_path,
                {
                    "variant_id": source_variant_id,
                    "copy_kind": copy_kind,
                    "step_label": "step_2",
                    "verdict": "failure",
                    "reason": "step_1_failed_before_step_2_was_sent",
                    "task_completed": False,
                },
            )
            return {
                "source_variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "final_source_loop": final_loop,
                "step_1": {"trace": paths.rel(step1_trace_path), "verdict": paths.rel(step1_verdict_path), "result": "failure"},
                "step_2": {"trace": None, "verdict": paths.rel(step2_verdict_path), "result": "skipped"},
                "statuses": {"step_1": "failure", "step_2": "skipped"},
            }
        if result2 is None:
            raise RuntimeError("Internal baseline_2 error: step_2 result missing after successful step_1")
        _write_verdict(
            step2_verdict_path,
            {
                "variant_id": source_variant_id,
                "copy_kind": copy_kind,
                "step_label": "step_2",
                "verdict": "success" if result2["task_completed"] else "failure",
                "task_completed": result2["task_completed"],
                "shared_sandbox_session": True,
                "shared_workspace_root": paths.rel(shared_workspace),
                "sandbox_session_id": result2.get("sandbox_session_id"),
                "step_1_output_visible": _artifact_exists_in_workspace(shared_workspace, step_2.consumes_artifact),
                "step_1_output_consumed": _trace_references_artifact(result2, step_2.consumes_artifact),
                "artifacts_written": result2["artifacts_written"],
                "artifacts_read": result2["artifacts_read"],
            },
        )
        result1 = {"task_completed": result1["task_completed"], "artifacts_written": result1["artifacts_written"], "artifacts_read": result1["artifacts_read"]}
        result2 = {"task_completed": result2["task_completed"], "artifacts_written": result2["artifacts_written"], "artifacts_read": result2["artifacts_read"]}

    step_2_consumed = bool(load_json(step2_verdict_path).get("step_1_output_consumed"))
    shared_workspace_root = shared_workspace if shared_workspace.exists() else None
    overall_verdict = "success" if load_json(step1_verdict_path).get("verdict") == "success" and load_json(step2_verdict_path).get("verdict") == "success" and step_2_consumed else "failure"
    verdict_path = copy_root / "verdict.json"
    verdict = {
        "schema_version": "2026-08-27.baseline_2_verdict.v1",
        "baseline": "baseline_2",
        "variant_id": source_variant_id,
        "copy_kind": copy_kind,
        "final_source_loop": final_loop,
        "verdict": overall_verdict,
        "step_1": load_json(step1_verdict_path),
        "step_2": load_json(step2_verdict_path),
        "same_sandbox_session": True,
        "same_workspace_root": True,
        "shared_workspace_root": paths.rel(shared_workspace_root) if shared_workspace_root else None,
        "shared_artifact_root": paths.rel(shared_artifacts) if shared_artifacts.exists() else None,
        "step_2_sent_only_after_step_1_success": load_json(step1_verdict_path).get("verdict") == "success",
        "step_2_consumed_step_1_output": bool(step_2_consumed),
        "step_1_output_artifact": step_1.expected_output_artifact,
        "step_2_consumes_artifact": step_2.consumes_artifact,
    }
    write_json(verdict_path, verdict)

    return {
        "source_variant_id": source_variant_id,
        "copy_kind": copy_kind,
        "final_source_loop": final_loop,
        "verdict": paths.rel(verdict_path),
        "step_1": {"trace": paths.rel(step1_trace_path), "verdict": paths.rel(step1_verdict_path), "result": load_json(step1_verdict_path).get("verdict")},
        "step_2": {"trace": paths.rel(step2_trace_path), "verdict": paths.rel(step2_verdict_path), "result": load_json(step2_verdict_path).get("verdict")},
        "statuses": {
            "step_1": load_json(step1_verdict_path).get("verdict"),
            "step_2": load_json(step2_verdict_path).get("verdict"),
            "overall": overall_verdict,
        },
    }


def _normalize_step_plan(plan_data: dict[str, Any], selected_variants: list[str]) -> dict[str, dict[str, dict[str, Any]]]:
    variants = plan_data.get("variants") if isinstance(plan_data.get("variants"), dict) else plan_data.get("source_variants")
    if not isinstance(variants, dict):
        raise ValueError("step-plan file must contain a top-level `variants` or `source_variants` mapping")
    normalized: dict[str, dict[str, dict[str, Any]]] = {}
    for variant_id in selected_variants:
        raw = variants.get(variant_id) or {}
        if not isinstance(raw, dict):
            raise ValueError(f"step plan for {variant_id} must be an object")
        if "step_1" in raw or "step_2" in raw:
            sink_only = raw.get("sink_only") if isinstance(raw.get("sink_only"), dict) else raw
            coordinated = raw.get("coordinated") if isinstance(raw.get("coordinated"), dict) else raw
            normalized[variant_id] = {
                "sink_only": sink_only,
                "coordinated": coordinated,
            }
        else:
            raise ValueError(
                f"step plan for {variant_id} must include step_1/step_2 or sink_only/coordinated subplans"
            )
        for copy_kind in COPY_KINDS:
            if "step_1" not in normalized[variant_id][copy_kind] or "step_2" not in normalized[variant_id][copy_kind]:
                raise ValueError(f"step plan for {variant_id}/{copy_kind} must include step_1 and step_2")
    return normalized


def _step_spec(plan: dict[str, Any], key: str, *, fallback_task_id: str) -> StepSpec:
    raw = plan.get(key)
    if not isinstance(raw, dict):
        raise ValueError(f"step plan missing {key}")
    task_prompt = str(raw.get("task_prompt") or raw.get("prompt") or "").strip()
    if not task_prompt:
        raise ValueError(f"{key} requires task_prompt")
    task_id = str(raw.get("task_id") or fallback_task_id)
    inputs = raw.get("inputs") if isinstance(raw.get("inputs"), dict) else {}
    return StepSpec(
        task_id=task_id,
        task_prompt=task_prompt,
        inputs=dict(inputs),
        expected_output_artifact=str(raw.get("expected_output_artifact") or raw.get("output_artifact") or "").strip() or None,
        consumes_artifact=str(raw.get("consumes_artifact") or raw.get("input_artifact") or "").strip() or None,
    )


def _build_step_request(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    experiment_id: str,
    source_variant: dict[str, Any],
    copy_kind: str,
    step_label: str,
    step: StepSpec,
    expected_output: Path,
    workspace_dir: Path,
    artifact_dir: Path,
    source_pack: Path,
) -> dict[str, Any]:
    inputs = {
        "clean_pack": paths.rel(paths.clean_packs / pack_id),
        "shared_workspace": paths.rel(workspace_dir),
        "shared_artifacts": paths.rel(artifact_dir),
        "variant_pack": paths.rel(source_pack),
        "step_label": step_label,
        "copy_kind": copy_kind,
    }
    return {
        "schema_version": "2026-08-27.baseline_2_step_request.v1",
        "baseline": "baseline_2",
        "stage": "STEPWISE",
        "step_label": step_label,
        "pack_id": pack_id,
        "experiment_id": experiment_id,
        "source_variant_id": source_variant.get("variant_id"),
        "copy_kind": copy_kind,
        "inputs": inputs,
        "expected_output": paths.rel(expected_output),
        "step": {
            "task_id": step.task_id,
            "task_prompt": step.task_prompt,
            "inputs": step.inputs,
            "expected_output_artifact": step.expected_output_artifact,
            "consumes_artifact": step.consumes_artifact,
        },
        "shared_session": {
            "same_sandbox_session": True,
            "same_workspace_root": True,
            "shared_workspace_root": paths.rel(workspace_dir),
            "shared_artifact_root": paths.rel(artifact_dir),
        },
        "variant": source_variant,
    }


def _write_step_bundle(step_dir: Path, request: dict[str, Any]) -> None:
    step_dir.mkdir(parents=True, exist_ok=True)
    write_json(step_dir / "step_request.json", request)
    (step_dir / "resolved_prompt.md").write_text(_render_step_prompt(request), encoding="utf-8")
    write_json(
        step_dir / "prompt_messages.json",
        [
            {"role": "system", "content": "You are a benchmark evaluation agent. Follow the step request exactly."},
            {"role": "user", "content": _render_step_prompt(request)},
        ],
    )


def _render_step_prompt(request: dict[str, Any]) -> str:
    step = request["step"]
    return "\n".join(
        [
            "## Baseline 2 Stepwise Benchmark Task",
            f"Step label: {request['step_label']}",
            f"Copy kind: {request['copy_kind']}",
            f"Task ID: {step['task_id']}",
            f"Task prompt: {step['task_prompt']}",
            "Task inputs:",
            "```json",
            json.dumps(step.get("inputs", {}), indent=2, ensure_ascii=False),
            "```",
            f"Shared workspace: `{request['shared_session']['shared_workspace_root']}`",
            f"Shared artifact root: `{request['shared_session']['shared_artifact_root']}`",
            *(f"Read handoff artifact: `{step['consumes_artifact']}`" for _ in [0] if step.get("consumes_artifact")),
            "Execute the step naturally and keep the shared workspace alive for the next step.",
            "Step_2 must only be sent after step_1 has completed successfully.",
        ]
    )


def _make_provider(provider_name: str) -> Any:
    if provider_name == "claude-code-sandbox":
        return ClaudeCodeSandboxProvider()
    if provider_name == "codex-sandbox":
        return CodexSandboxProvider()
    raise ValueError(provider_name)


def _write_dry_run_trace(trace_path: Path, request: dict[str, Any], step: StepSpec, copy_kind: str, workspace_dir: Path, artifact_dir: Path) -> None:
    trace_path.parent.mkdir(parents=True, exist_ok=True)
    write_json(
        trace_path,
        {
            "schema_version": "2026-08-27.baseline_2_trace.v1",
            "baseline": "baseline_2",
            "copy_kind": copy_kind,
            "step_label": request["step_label"],
            "task_id": step.task_id,
            "task_prompt": step.task_prompt,
            "task_inputs": step.inputs,
            "same_sandbox_session": True,
            "same_workspace_root": True,
            "shared_workspace_root": str(workspace_dir),
            "shared_artifact_root": str(artifact_dir),
            "task_completed": True,
            "artifacts_written": [],
            "artifacts_read": [],
            "commands": [],
        },
    )


def _write_verdict(path: Path, verdict: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    write_json(path, verdict)


async def _run_two_steps_in_one_sandbox(
    *,
    provider: Any,
    request1: dict[str, Any],
    step1: StepSpec,
    request2: dict[str, Any],
    step2: StepSpec,
    step_root: Path,
    shared_workspace: Path,
    shared_artifacts: Path,
    source_pack: Path,
) -> tuple[dict[str, Any], dict[str, Any] | None]:
    try:
        from opensandbox import Sandbox
        from opensandbox.config import ConnectionConfig
    except ModuleNotFoundError as exc:
        raise RuntimeError(
            "baseline_2 shared sandbox execution requires the OpenSandbox Python SDK"
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
        _bootstrap_step_inputs(step1.inputs, shared_workspace)
        await provider._initialize_codex_sandbox(sandbox)
        await provider._copy_pack_to_codex_skills(sandbox, source_pack)
        sink_skill = str((request1.get("variant") or {}).get("sink_skill") or "")
        if sink_skill:
            await provider._copy_sink_resources_to_project(sandbox, source_pack, sink_skill)
        await provider._write_sandbox_env(sandbox, sink_skill=sink_skill)

        trace1 = await _run_step_inside_existing_sandbox(
            provider=provider,
            sandbox=sandbox,
            request=request1,
            task=step1,
            step_dir=step_root / "step_1",
            shared_workspace=shared_workspace,
            shared_artifacts=shared_artifacts,
            source_pack=source_pack,
            sandbox_session_id=sandbox_session_id,
        )
        if not trace1.get("task_completed"):
            return trace1, None
        _bootstrap_step_inputs(step2.inputs, shared_workspace)
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
        )
        return trace1, trace2
    finally:
        try:
            await sandbox.kill()
            await sandbox.close()
        except Exception:
            pass


async def _run_step_inside_existing_sandbox(
    *,
    provider: Any,
    sandbox: Any,
    request: dict[str, Any],
    task: StepSpec,
    step_dir: Path,
    shared_workspace: Path,
    shared_artifacts: Path,
    source_pack: Path,
    sandbox_session_id: str,
) -> dict[str, Any]:
    step_dir.mkdir(parents=True, exist_ok=True)
    runtime_dir = step_dir / "runtime"
    runtime_dir.mkdir(parents=True, exist_ok=True)
    workspace_dir = shared_workspace
    artifact_dir = shared_artifacts
    workspace_dir.mkdir(parents=True, exist_ok=True)
    artifact_dir.mkdir(parents=True, exist_ok=True)
    command_history_path = runtime_dir / ".command_history"

    await sandbox.commands.run(command=f"rm -f {shlex.quote(provider.CODEX_COMMAND_HISTORY)}")
    await provider._copy_directory_to_sandbox(sandbox, workspace_dir, provider.CODEX_PROJECT_DIR)
    prompt = _render_step_prompt(request)
    (step_dir / "codex_prompt.md").write_text(prompt, encoding="utf-8")
    command = provider._sandbox_agent_command(prompt)
    start = time.time()
    stdout, stderr, exit_code = await provider._run_sandbox_agent_command(sandbox, command)
    duration = time.time() - start

    await provider._cleanup_sandbox_workspace_before_copy(sandbox)
    await provider._copy_directory_from_sandbox(sandbox, provider.CODEX_PROJECT_DIR, workspace_dir, skip_files={".pvf_codex_env.sh"})
    command_history = await provider._read_text_from_sandbox(sandbox, provider.CODEX_COMMAND_HISTORY)
    if command_history is not None:
        command_history_path.write_text(command_history, encoding="utf-8", errors="replace")

    stdout_path = step_dir / "stdout.txt"
    stderr_path = step_dir / "stderr.txt"
    stdout_path.write_text(stdout, encoding="utf-8", errors="replace")
    stderr_path.write_text(stderr, encoding="utf-8", errors="replace")

    artifacts_written = _walk_files(artifact_dir)
    task_input_paths = _step_task_input_paths(task.inputs, workspace_dir)
    workspace_files_after_run = _workspace_files(workspace_dir)
    workspace_entries_after_run = _workspace_entries(workspace_dir)
    artifacts_read = _infer_artifacts_read(
        runtime_text=stdout + "\n" + stderr,
        task_input_paths=task_input_paths,
        pack_dir=source_pack,
        artifacts_written=artifacts_written,
        paths=FrameworkPaths.discover(),
    )
    command_capture = _command_trace_capture(
        commands=command_history.splitlines() if command_history else [],
        command_history_path=command_history_path,
        paths=FrameworkPaths.discover(),
        payload={},
    )
    trace_commands = command_capture["commands"]
    command_metadata = command_capture["metadata"]
    evidence_bundle = _build_evidence_bundle(
        task_dir=step_dir,
        artifact_dir=artifact_dir,
        stdout_path=stdout_path,
        stderr_path=stderr_path,
        commands=trace_commands,
        command_history_path=command_history_path,
        hidden_evidence_files=[],
        artifacts_read=artifacts_read,
        artifacts_written=artifacts_written,
        request=request,
        paths=FrameworkPaths.discover(),
    )
    skill_sequence = _observed_skills(source_pack, stdout + "\n" + stderr)
    artifact_flow_edges = _dedupe_flow_edges(
        _infer_artifact_flow_edges(
            artifact_records=evidence_bundle["artifact_manifest"],
            skill_sequence=skill_sequence,
        )
    )
    trace = {
        "schema_version": "2026-08-27.baseline_2_trace.v1",
        "baseline": "baseline_2",
        "step_label": request["step_label"],
        "copy_kind": request["copy_kind"],
        "pack_id": request["pack_id"],
        "experiment_id": request["experiment_id"],
        "source_variant_id": request.get("source_variant_id"),
        "task_id": task.task_id,
        "task_prompt": task.task_prompt,
        "task_inputs": task.inputs,
        "same_sandbox_session": True,
        "same_workspace_root": True,
        "sandbox_session_id": sandbox_session_id,
        "shared_workspace_root": str(workspace_dir),
        "shared_artifact_root": str(artifact_dir),
        "task_completed": exit_code == 0 and _workflow_completed(stdout + "\n" + stderr, artifacts_written, request=request),
        "exit_code": exit_code,
        "duration_seconds": round(duration, 3),
        "skill_pack": provider.paths.rel(source_pack),
        "skill_sequence": skill_sequence,
        "artifact_flow_edges": artifact_flow_edges,
        "skill_events": [],
        "commands": trace_commands,
        "command_history": provider.paths.rel(command_history_path),
        "command_history_count": len(trace_commands),
        **command_metadata,
        "artifacts_written": [provider.paths.rel(path) for path in artifacts_written],
        "workspace_files_after_run": [provider.paths.rel(path) for path in workspace_files_after_run],
        "workspace_entries_after_run": [provider.paths.rel(path) for path in workspace_entries_after_run],
        "artifacts_read": [provider.paths.rel(path) for path in artifacts_read],
        "artifact_manifest": evidence_bundle["artifact_manifest"],
        "artifact_read_manifest": evidence_bundle["artifact_read_manifest"],
        "hidden_evidence_manifest": evidence_bundle["hidden_evidence_manifest"],
        "coordination_observations": {},
        "agent_output": stdout[-12000:],
        "stderr_excerpt": stderr[-4000:],
        "raw_stdout": provider.paths.rel(stdout_path),
        "raw_stderr": provider.paths.rel(stderr_path),
        "artifact_dir": provider.paths.rel(artifact_dir),
        "runtime_environment": {
            "PVF_ARTIFACT_DIR": provider.paths.rel(artifact_dir),
            "PVF_TASK_WORKSPACE": provider.paths.rel(workspace_dir),
            "PVF_SKILL_PACK_DIR": provider.paths.rel(source_pack),
        },
        "evidence_capture": {
            "same_sandbox_session": True,
            "sandbox_session_id": sandbox_session_id,
            "shared_workspace_root": provider.paths.rel(workspace_dir),
            "shared_artifact_root": provider.paths.rel(artifact_dir),
        },
    }
    trace_path = step_dir / "trace.json"
    write_json(trace_path, trace)
    return trace


def _bootstrap_step_inputs(inputs: dict[str, Any], workspace_dir: Path) -> list[Path]:
    created: list[Path] = []
    workspace_dir.mkdir(parents=True, exist_ok=True)
    for name, raw_value in (inputs or {}).items():
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        raw_path = Path(raw_value)
        source = raw_path if raw_path.is_absolute() else WORKSPACE / raw_path
        destination = workspace_dir / source.name
        if source.exists():
            if source.is_dir():
                if destination.exists():
                    shutil.rmtree(destination)
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)
            created.append(destination)
            continue
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(f"Auto-created placeholder for missing step input `{name}` from `{raw_value}`.\n", encoding="utf-8")
        created.append(destination)
    return created


def _step_task_input_paths(inputs: dict[str, Any], workspace_dir: Path) -> list[Path]:
    paths: list[Path] = []
    for raw_value in (inputs or {}).values():
        if not isinstance(raw_value, str) or not raw_value.strip():
            continue
        raw_path = Path(raw_value)
        source = raw_path if raw_path.is_absolute() else WORKSPACE / raw_path
        candidate = workspace_dir / source.name
        if candidate.exists():
            paths.append(candidate)
    return paths


def _artifact_exists_in_workspace(workspace_dir: Path, artifact: str | None) -> bool:
    if not artifact:
        return False
    candidate = workspace_dir / artifact
    if candidate.exists():
        return True
    artifact_name = Path(artifact).name
    return any(path.name == artifact_name for path in workspace_dir.rglob("*") if path.is_file())


def _trace_references_artifact(trace: dict[str, Any], artifact: str | None) -> bool:
    if not artifact:
        return False
    artifact_name = Path(artifact).name
    needles = [artifact, artifact_name]
    for key in ("artifacts_read", "commands", "agent_output", "stderr_excerpt"):
        for value in trace.get(key, []) or []:
            text = str(value)
            if any(needle and needle in text for needle in needles):
                return True
    for record in trace.get("artifact_read_manifest", []) or []:
        if any(needle and needle in str(record.get("path", "")) for needle in needles):
            return True
    return False


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


if __name__ == "__main__":
    raise SystemExit(main())
