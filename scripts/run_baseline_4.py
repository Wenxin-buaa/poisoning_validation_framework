#!/usr/bin/env python3
"""Run baseline_4 as a coordinated-loop ablation evaluation.

baseline_4 keeps the coordinated-success source selection shape from
baseline_1, but changes the replay surface:

1. it skips sink-only D2 -> D3 entirely;
2. it reuses the final successful coordinated loop as the runtime source;
3. it replaces the upstream skill directory in that loop with the matching
   clean_pack upstream skill directory;
4. it replays only D5 -> D6 on the modified coordinated pack.

The source experiment is never mutated. Results are namespaced by the target
model under:

    benchmarks/runs/<pack>/experiments/<experiment>/baseline_4/<model>/
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
from automation.judges import judge_coordinated  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from automation.prompts import PromptBuilder  # noqa: E402
from automation.providers import create_provider, write_provider_result  # noqa: E402
from automation.stage_runner import materialize_model_output  # noqa: E402
from run_baseline_2 import _apply_baseline_2_step_2_execution_verdict  # noqa: E402
from run_baseline_1 import copy_coordination_plan, find_final_success_loop, now, slug  # noqa: E402


PROVIDERS = ("claude-code-sandbox", "codex-sandbox", "codex-cli", "dry-run")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run baseline_4 as a coordinated-success replay with a clean upstream ablation."
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
        help="Target-agent provider used for D5.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Model override. For Claude Code this sets PVF_CLAUDE_MODEL.",
    )
    parser.add_argument("--overwrite", action="store_true", help="Replace this model's existing baseline_4 results.")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Resume an existing baseline_4 run by skipping variants that already have D6 verdicts. Enabled by default.",
    )
    parser.add_argument(
        "--no-resume",
        action="store_false",
        dest="resume",
        help="Disable resume behavior and require a clean or overwritten output directory.",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Create packs/prompts but do not execute or judge.")
    parser.add_argument("--judge-only", action="store_true", help="Judge existing baseline_4 traces without executing.")
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
    eval_experiment_id = f"{args.experiment_id}_baseline_4_{model_slug}"
    baseline_root = paths.pack_experiment(args.pack, eval_experiment_id)
    if baseline_root.exists() and args.overwrite:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    records = []
    for source_variant_id in selected:
        eval_dir = baseline_root / "variants" / source_variant_id
        if eval_dir.exists() and not args.overwrite:
            if args.resume:
                print(f"[baseline_4] skipped existing variant: {source_variant_id}", flush=True)
                continue
            if not args.judge_only:
                raise FileExistsError(
                    f"{eval_dir} already exists. Use --overwrite to replace it or --resume to skip it."
                )
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
        "schema_version": "2026-09-02.baseline_4_summary.v1",
        "baseline": "baseline_4",
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
            "[baseline_4] skipped non-coordinated variants: "
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
    final_loop_dir = source_dir / "coordinated" / f"loop_{final_loop:03d}"
    source_pack = final_loop_dir / "variant_pack"
    if not source_pack.exists():
        raise FileNotFoundError(source_pack)

    upstream_skill = _variant_upstream_skill(source_variant)
    clean_upstream_source = paths.clean_packs / pack_id / upstream_skill
    if not clean_upstream_source.exists():
        raise FileNotFoundError(clean_upstream_source)

    eval_dir = baseline_root / "variants" / source_variant_id / "coordinated" / f"loop_{final_loop:03d}"
    if eval_dir.exists():
        if overwrite and not judge_only:
            shutil.rmtree(baseline_root / "variants" / source_variant_id)
        elif resume and not judge_only:
            return {
                "source_variant_id": source_variant_id,
                "final_source_loop": final_loop,
                "upstream_skill": upstream_skill,
                "clean_upstream_pack": paths.rel(clean_upstream_source),
                "coordinated": {"trace": None, "verdict": None, "result": "skipped_existing"},
                "statuses": {"skip": "existing_variant"},
            }
        elif not judge_only:
            raise FileExistsError(f"{eval_dir} already exists. Use --overwrite or --resume to skip it.")
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_variant = dict(source_variant)
    eval_variant.update(
        {
            "schema_version": "2026-09-02.baseline_4_variant.v1",
            "experiment_id": eval_experiment_id,
            "variant_id": source_variant_id,
            "baseline": "baseline_4",
            "baseline_source_variant": source_variant_id,
            "baseline_source_final_loop": final_loop,
            "baseline_upstream_source": "clean_pack",
            "baseline_upstream_pack": paths.rel(clean_upstream_source),
            "status": "baseline_4",
        }
    )

    downstream_pack = eval_dir / "variant_pack"
    if not judge_only:
        shutil.copytree(source_pack, downstream_pack)
        _replace_upstream_skill(downstream_pack, upstream_skill, clean_upstream_source)
        copy_coordination_plan(final_loop_dir, eval_dir)
        variant_root = baseline_root / "variants" / source_variant_id
        variant_root.mkdir(parents=True, exist_ok=True)
        write_json(variant_root / "variant.json", eval_variant)
        write_json(variant_root / "payload_reference.json", payload_reference)

    task_file = paths.benign_tasks / f"{pack_id}_tasks.json"
    coord_trace = eval_dir / "traces.jsonl"
    coord_verdict = eval_dir / "verdict.json"
    coord_request = build_request(
        paths=paths,
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        variant=eval_variant,
        task_file=task_file,
        pack_path=downstream_pack,
        payload_reference_path=eval_dir / "payload_reference.json",
        trace_path=coord_trace,
        loop_iteration=final_loop,
    )
    coord_request_dir = eval_dir / "requests"
    if not judge_only:
        variant_root = baseline_root / "variants" / source_variant_id
        write_stage_prompt(paths, coord_request_dir, coord_request)
        write_json(
            variant_root / "baseline_4_manifest.json",
            {
                "schema_version": "2026-09-02.baseline_4_manifest.v1",
                "baseline": "baseline_4",
                "source_variant": source_variant_id,
                "source_variant_path": paths.rel(source_dir),
                "coordinated_source_pack": paths.rel(source_pack),
                "clean_upstream_pack": paths.rel(clean_upstream_source),
                "upstream_skill": upstream_skill,
                "final_coordinated_loop": final_loop,
                "task_ids": list(source_variant.get("task_ids") or []),
                "target_agent_payload_blind": True,
                "provider": provider_name,
                "ablation": "swap coordinated upstream skill with clean_pack upstream and skip sink-only replay",
            },
        )

    statuses: dict[str, Any] = {}
    coord_has_verdict = coord_verdict.exists()
    if resume and coord_has_verdict:
        coord_status = load_json(coord_verdict)
        statuses["d5"] = "skipped_existing"
        statuses["d6"] = coord_status.get("verdict")
        print(f"[SKIP] variant {source_variant_id} already has D6", flush=True)
        print(
            f"[D6] verdict={coord_status.get('verdict')} "
            f"reason={_baseline_4_verdict_reason(coord_status)} "
            f"(resume)",
            flush=True,
        )
    if not coord_has_verdict or not resume:
        if not judge_only:
            if not prepare_only:
                print(
                    f"[baseline_4] {source_variant_id} D5 start provider={provider_name} loop={final_loop}",
                    flush=True,
                )
                execute_request(provider_name, coord_request, coord_request_dir)
                statuses["d5"] = "executed"
            else:
                statuses["d5"] = "prepared"
        if not prepare_only:
            if not coord_trace.exists():
                raise FileNotFoundError(coord_trace)
            print(f"[baseline_4] {source_variant_id} D6 judge start loop={final_loop}", flush=True)
            judge_coordinated(
                paths=paths,
                pack_id=pack_id,
                experiment_id=eval_experiment_id,
                variant_id=source_variant_id,
                loop_iteration=final_loop,
            )
            _apply_baseline_2_step_2_execution_verdict(coord_verdict)
            coord_verdict_data = load_json(coord_verdict)
            execution_observed = bool(coord_verdict_data.get("payload_execution_observed"))
            coord_verdict_data["baseline"] = "baseline_4"
            coord_verdict_data["baseline_4_judge_mode"] = "payload_execution_only"
            coord_verdict_data["coordinated_dependency_satisfied"] = execution_observed
            coord_verdict_data["judge_prompt_satisfied"] = execution_observed
            coord_verdict_data["payload_observed"] = execution_observed
            if not execution_observed:
                coord_verdict_data["reason"] = _baseline_4_failure_reason(coord_verdict_data)
                write_json(coord_verdict, coord_verdict_data)
            else:
                coord_verdict_data["reason"] = None
                write_json(coord_verdict, coord_verdict_data)
            statuses["d6"] = coord_verdict_data.get("verdict")
            print(
                f"[D6] verdict={coord_verdict_data.get('verdict')} "
                f"reason={_baseline_4_verdict_reason(coord_verdict_data)} "
                f"verdict_path={paths.rel(coord_verdict)}",
                flush=True,
            )

    return {
        "source_variant_id": source_variant_id,
        "final_source_loop": final_loop,
        "upstream_skill": upstream_skill,
        "clean_upstream_pack": paths.rel(clean_upstream_source),
        "coordinated": {
            "trace": paths.rel(coord_trace) if coord_trace.exists() else None,
            "verdict": paths.rel(coord_verdict) if coord_verdict.exists() else None,
            "result": statuses.get("d6"),
        },
        "statuses": statuses,
    }


def build_request(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    experiment_id: str,
    variant: dict[str, Any],
    task_file: Path,
    pack_path: Path,
    payload_reference_path: Path,
    trace_path: Path,
    loop_iteration: int,
) -> dict[str, Any]:
    inputs = {
        "task_file": paths.rel(task_file),
        "clean_pack": paths.rel(paths.clean_packs / pack_id),
        "payload_reference": paths.rel(payload_reference_path),
        "sink_only_pack": paths.rel(pack_path),
        "coordinated_pack": paths.rel(pack_path),
    }
    inputs["loop_iteration"] = loop_iteration
    return {
        "schema_version": "2026-09-02.baseline_4_stage_request.v1",
        "stage": "D5",
        "role": "target_agent",
        "created_at": now(),
        "pack_id": pack_id,
        "experiment_id": f"{experiment_id}_baseline_4",
        "loop_iteration": loop_iteration,
        "safety": {
            "payload_policy": "inert_payload_only",
            "target_agent_payload_blind": True,
            "baseline": "baseline_4",
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
        f"[baseline_4] provider={provider_name} stage={request['stage']} "
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
        f"[baseline_4] provider={provider_name} stage={request['stage']} "
        f"trace_written={destination}",
        flush=True,
    )


def _replace_upstream_skill(pack_dir: Path, upstream_skill: str, clean_upstream_source: Path) -> None:
    destination = pack_dir / upstream_skill
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(clean_upstream_source, destination)


def _variant_upstream_skill(variant: dict[str, Any]) -> str:
    return str(variant.get("upstream_skill") or variant.get("hook_skill") or "").strip()


def _baseline_4_failure_reason(verdict_data: dict[str, Any]) -> str:
    diagnostics = verdict_data.get("failure_diagnostics") if isinstance(verdict_data.get("failure_diagnostics"), dict) else {}
    if isinstance(diagnostics, dict):
        reason = str(diagnostics.get("reason") or "").strip()
        if reason:
            return reason
    feedback = verdict_data.get("feedback") if isinstance(verdict_data.get("feedback"), dict) else {}
    if isinstance(feedback, dict):
        reason = str(feedback.get("reason") or "").strip()
        if reason:
            return reason
    failure_analysis = verdict_data.get("failure_analysis") if isinstance(verdict_data.get("failure_analysis"), dict) else {}
    if isinstance(failure_analysis, dict):
        reason = str(failure_analysis.get("reason") or failure_analysis.get("summary") or "").strip()
        if reason:
            return reason
    return "D6 execution-only judge did not observe payload execution evidence in runtime traces."


def _baseline_4_verdict_reason(verdict_data: dict[str, Any]) -> str:
    reason = str(verdict_data.get("reason") or "").strip()
    if reason:
        return reason
    if str(verdict_data.get("verdict") or "").strip() == "success":
        return "ok"
    return _baseline_4_failure_reason(verdict_data)


def _normalized_artifact_path(value: Any) -> str:
    text = str(value or "").strip().strip("`'\"")
    if not text:
        return ""
    text = text.replace("\\", "/")
    if "/artifacts/" in text:
        text = text.split("/artifacts/", 1)[1]
    if text.startswith("artifacts/"):
        text = text[len("artifacts/") :]
    return text.lstrip("/")


def slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "default"


if __name__ == "__main__":
    raise SystemExit(main())
