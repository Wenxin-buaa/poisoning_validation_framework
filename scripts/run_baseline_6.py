#!/usr/bin/env python3
"""Run and judge constructed baseline_6 downstream-only variants.

By default, source experiments are used only as an eligibility filter:
source variants with ``status == coordinated_success`` select the matching
already-constructed baseline_6 payload variant.  With ``--all-variants``, all
variants in the baseline_6 construction manifest are evaluated directly.
The coordinated source pack is never replayed and its upstream modifications
are never copied.
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
from automation.judges import judge_sink_only  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from automation.providers import create_provider, write_provider_result  # noqa: E402
from automation.prompts import PromptBuilder  # noqa: E402
from automation.stage_runner import materialize_model_output  # noqa: E402


PAYLOAD_IDS = {1, 2, 15, 39, 40, 41, 42}
PROVIDERS = ("codex-sandbox", "codex-cli", "claude-code-sandbox", "dry-run")


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run and D3-judge existing baseline_6 downstream-only variants. "
            "Use --all-variants to evaluate every constructed variant, or "
            "provide source experiment ids to select coordinated_success variants."
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
        action="append",
        default=[],
        help="Source experiment number/id, repeatable and/or comma-separated (001, 002, 003).",
    )
    parser.add_argument(
        "--all-variants",
        action="store_true",
        help="Evaluate every constructed baseline_6 variant; do not use source-experiment eligibility filtering.",
    )
    parser.add_argument(
        "--model",
        default="",
        help="Target-agent model. Sets PVF_CODEX_MODEL for codex providers.",
    )
    parser.add_argument(
        "--provider",
        default="codex-sandbox",
        choices=PROVIDERS,
        help="Target-agent provider used for D2 execution.",
    )
    parser.add_argument(
        "--variant-id",
        action="append",
        default=[],
        help="Optional baseline_6 variant id filter, repeatable and/or comma-separated.",
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Replace the selected baseline_6 evaluation output roots.",
    )
    parser.add_argument(
        "--resume",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Skip variants that already have a D3 verdict (default: true).",
    )
    parser.add_argument("--prepare-only", action="store_true", help="Prepare packs/prompts without D2 execution or D3 judge.")
    parser.add_argument("--judge-only", action="store_true", help="Judge existing D2 traces without executing D2.")
    args = parser.parse_args()

    if args.prepare_only and args.judge_only:
        parser.error("--prepare-only and --judge-only are mutually exclusive")

    packs = _csv_values(args.pack)
    experiment_tokens = _csv_values(args.experiment_id)
    variant_filter = set(_csv_values(args.variant_id))
    if not packs:
        parser.error("at least one pair is required")
    if args.all_variants and experiment_tokens:
        parser.error("--all-variants cannot be combined with --experiment-id/--exp")
    if not args.all_variants and not experiment_tokens:
        parser.error("provide --experiment-id/--exp or use --all-variants")

    paths = FrameworkPaths.discover()
    if args.model:
        os.environ["PVF_CODEX_MODEL"] = args.model
        if args.provider == "claude-code-sandbox":
            os.environ["PVF_CLAUDE_MODEL"] = args.model
    model_name = _selected_model(args.model, args.provider)
    model_slug = slug(model_name)
    source_experiments = {
        pack_id: (
            []
            if args.all_variants
            else [_resolve_experiment_id(pack_id, token) for token in experiment_tokens]
        )
        for pack_id in packs
    }
    exp_label = "all" if args.all_variants else "_".join(
        _experiment_short_id(exp_id) for exp_id in experiment_tokens
    )

    all_records: list[dict[str, Any]] = []
    for pack_id in packs:
        records = run_pack(
            paths=paths,
            pack_id=pack_id,
            source_experiment_ids=source_experiments[pack_id],
            source_experiment_tokens=experiment_tokens,
            exp_label=exp_label,
            model_name=model_name,
            model_slug=model_slug,
            provider_name=args.provider,
            variant_filter=variant_filter,
            overwrite=args.overwrite,
            resume=args.resume,
            prepare_only=args.prepare_only,
            judge_only=args.judge_only,
            all_variants=args.all_variants,
        )
        all_records.extend(records)

    print(
        {
            "baseline": "baseline_6",
            "provider": args.provider,
            "model": model_name,
            "pack_count": len(packs),
            "eligible_variant_count": len(all_records),
            "selection_mode": "all_variants" if args.all_variants else "coordinated_success",
        },
        flush=True,
    )
    return 0


def run_pack(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    source_experiment_ids: list[str],
    source_experiment_tokens: list[str],
    exp_label: str,
    model_name: str,
    model_slug: str,
    provider_name: str,
    variant_filter: set[str],
    overwrite: bool,
    resume: bool,
    prepare_only: bool,
    judge_only: bool,
    all_variants: bool,
) -> list[dict[str, Any]]:
    try:
        if all_variants:
            selected = select_all_baseline6_variants(
                paths=paths,
                pack_id=pack_id,
                variant_filter=variant_filter,
            )
        else:
            selected = select_eligible_baseline6_variants(
                paths=paths,
                pack_id=pack_id,
                source_experiment_ids=source_experiment_ids,
                variant_filter=variant_filter,
            )
    except ValueError as exc:
        if "No eligible coordinated_success baseline_6 variants" not in str(exc):
            raise
        print(
            {
                "event": "baseline_6_eval_skip_pack",
                "pack_id": pack_id,
                "source_experiments": source_experiment_ids,
                "reason": str(exc),
            },
            flush=True,
        )
        return []
    eval_experiment_id = f"{pack_id}_exp_{exp_label}_baseline_6_{model_slug}"
    baseline_root = paths.pack_experiment(pack_id, eval_experiment_id)
    if baseline_root.exists() and overwrite and not judge_only:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    print(
        {
            "event": "baseline_6_eval_start",
            "pack_id": pack_id,
            "source_experiments": source_experiment_tokens,
            "eval_experiment_id": eval_experiment_id,
            "eligible_variant_count": len(selected),
            "selection_mode": "all_variants" if all_variants else "coordinated_success",
            "provider": provider_name,
            "model": model_name,
            "prepare_only": prepare_only,
            "judge_only": judge_only,
        },
        flush=True,
    )
    records: list[dict[str, Any]] = []
    for item in selected:
        record = run_one(
            paths=paths,
            pack_id=pack_id,
            eval_experiment_id=eval_experiment_id,
            baseline_root=baseline_root,
            item=item,
            provider_name=provider_name,
            model_name=model_name,
            overwrite=overwrite,
            resume=resume,
            prepare_only=prepare_only,
            judge_only=judge_only,
            selection_mode="all_variants" if all_variants else "coordinated_success",
        )
        records.append(record)
        print(record, flush=True)

    summary = {
        "schema_version": "2026-09-16.baseline_6_eval_summary.v1",
        "baseline": "baseline_6",
        "pack_id": pack_id,
        "source_experiments": source_experiment_tokens,
        "eval_experiment_id": eval_experiment_id,
        "provider": provider_name,
        "model": model_name,
        "created_at": now(),
        "eligibility": (
            "all constructed baseline_6 variants"
            if all_variants
            else "source variant status == coordinated_success"
        ),
        "records": records,
    }
    summary_path = baseline_root / "summary.json"
    write_json(summary_path, summary)
    print(f"[baseline_6] summary={paths.rel(summary_path)}", flush=True)
    return records


def select_eligible_baseline6_variants(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    source_experiment_ids: list[str],
    variant_filter: set[str],
) -> list[dict[str, Any]]:
    selected: dict[str, dict[str, Any]] = {}
    skipped: list[tuple[str, str, str]] = []
    baseline_root = paths.pack_run(pack_id) / "baselines" / "baseline_6_skillinject"
    manifest_path = baseline_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)
    baseline_manifest = load_json(manifest_path)
    baseline_variants = {
        str(item["variant_id"]): item
        for item in baseline_manifest.get("variants", [])
        if isinstance(item, dict) and item.get("variant_id")
    }

    for source_experiment_id in source_experiment_ids:
        source_root = paths.pack_experiment(pack_id, source_experiment_id)
        variant_paths = sorted((source_root / "variants").glob("*/variant.json"))
        if not variant_paths:
            raise FileNotFoundError(f"No source variants found under {source_root / 'variants'}")
        for variant_path in variant_paths:
            source_variant = load_json(variant_path)
            source_variant_id = str(source_variant.get("variant_id") or variant_path.parent.name)
            if source_variant.get("status") != "coordinated_success":
                skipped.append((source_experiment_id, source_variant_id, str(source_variant.get("status"))))
                continue
            payload_id = int(source_variant.get("payload_id"))
            if payload_id not in PAYLOAD_IDS:
                skipped.append((source_experiment_id, source_variant_id, f"payload_{payload_id:03d}_not_in_baseline6"))
                continue
            sink_skill = str(source_variant.get("sink_skill") or source_variant.get("target_skill") or "").strip()
            if not sink_skill:
                raise ValueError(f"Source variant has no sink_skill: {variant_path}")
            baseline_variant_id = _find_baseline_variant_id(
                baseline_variants=baseline_variants,
                sink_skill=sink_skill,
                payload_id=payload_id,
            )
            item = selected.setdefault(
                baseline_variant_id,
                {
                    "baseline_variant_id": baseline_variant_id,
                    "source_variant_ids": [],
                    "source_experiment_ids": [],
                    "source_variants": [],
                },
            )
            if source_variant_id not in item["source_variant_ids"]:
                item["source_variant_ids"].append(source_variant_id)
            if source_experiment_id not in item["source_experiment_ids"]:
                item["source_experiment_ids"].append(source_experiment_id)
            item["source_variants"].append(
                {
                    "experiment_id": source_experiment_id,
                    "variant_id": source_variant_id,
                    "status": source_variant.get("status"),
                    "payload_id": payload_id,
                    "sink_skill": sink_skill,
                    "task_ids": list(source_variant.get("task_ids") or []),
                }
            )

    if variant_filter:
        selected = {
            key: value
            for key, value in selected.items()
            if key in variant_filter or any(v in variant_filter for v in value["source_variant_ids"])
        }
    if not selected:
        raise ValueError(
            f"No eligible coordinated_success baseline_6 variants for {pack_id}; "
            f"source experiments={source_experiment_ids}"
        )
    for item in selected.values():
        baseline_variant = baseline_variants[item["baseline_variant_id"]]
        item["baseline_variant"] = baseline_variant
        item["source_variant_path"] = str(
            paths.pack_experiment(pack_id, item["source_experiment_ids"][0])
            / "variants"
            / item["source_variant_ids"][0]
            / "variant.json"
        )
    print(
        {
            "event": "baseline_6_eligibility",
            "pack_id": pack_id,
            "source_experiments": source_experiment_ids,
            "selected_count": len(selected),
            "skipped_non_coordinated_count": len(skipped),
            "selected_payloads": sorted(
                (int(item["baseline_variant"]["payload_id"]), item["baseline_variant"]["sink_skill"])
                for item in selected.values()
            ),
        },
        flush=True,
    )
    return [selected[key] for key in sorted(selected)]


def select_all_baseline6_variants(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    variant_filter: set[str],
) -> list[dict[str, Any]]:
    """Select every already-constructed baseline_6 variant from its manifest."""
    baseline_root = paths.pack_run(pack_id) / "baselines" / "baseline_6_skillinject"
    manifest_path = baseline_root / "manifest.json"
    if not manifest_path.exists():
        raise FileNotFoundError(manifest_path)

    baseline_manifest = load_json(manifest_path)
    selected: dict[str, dict[str, Any]] = {}
    for raw_variant in baseline_manifest.get("variants", []):
        if not isinstance(raw_variant, dict) or not raw_variant.get("variant_id"):
            continue
        variant_id = str(raw_variant["variant_id"])
        if variant_filter and variant_id not in variant_filter:
            continue
        selected[variant_id] = {
            "baseline_variant_id": variant_id,
            "source_variant_ids": [],
            "source_experiment_ids": [],
            "source_variants": [],
            "baseline_variant": raw_variant,
            "source_variant_path": None,
        }

    if not selected:
        raise ValueError(
            f"No constructed baseline_6 variants for {pack_id}"
            + (f" matching filter={sorted(variant_filter)}" if variant_filter else "")
        )

    print(
        {
            "event": "baseline_6_all_variants",
            "pack_id": pack_id,
            "selected_count": len(selected),
            "selected_payloads": sorted(
                (int(item["baseline_variant"]["payload_id"]), item["baseline_variant"].get("sink_skill"))
                for item in selected.values()
            ),
        },
        flush=True,
    )
    return [selected[key] for key in sorted(selected)]


def run_one(
    *,
    paths: FrameworkPaths,
    pack_id: str,
    eval_experiment_id: str,
    baseline_root: Path,
    item: dict[str, Any],
    provider_name: str,
    model_name: str,
    overwrite: bool,
    resume: bool,
    prepare_only: bool,
    judge_only: bool,
    selection_mode: str,
) -> dict[str, Any]:
    baseline_variant_id = item["baseline_variant_id"]
    baseline_variant = item["baseline_variant"]
    baseline_variant_dir = Path(_absolute_path(paths, baseline_variant["variant_dir"]))
    source_pack = baseline_variant_dir / "variant_pack"
    if not source_pack.exists():
        raise FileNotFoundError(source_pack)
    payload_reference = load_json(baseline_variant_dir / "payload_reference.json")
    baseline_meta = load_json(baseline_variant_dir / "baseline_6_construction.json")
    sink_skill = str(baseline_variant.get("sink_skill") or baseline_meta["modified_skills"][0])
    task_ids = _task_ids_from_item(item, payload_reference)

    eval_dir = baseline_root / "variants" / baseline_variant_id
    sink_dir = eval_dir / "sink_only"
    eval_pack = sink_dir / "variant_pack"
    trace_path = sink_dir / "traces.jsonl"
    verdict_path = sink_dir / "verdict.json"
    if eval_dir.exists() and overwrite and not judge_only:
        shutil.rmtree(eval_dir)
    if eval_dir.exists() and resume and verdict_path.exists() and not prepare_only and not judge_only:
        verdict = load_json(verdict_path)
        return _record(item, baseline_variant_id, sink_skill, eval_experiment_id, paths, trace_path, verdict_path, "skipped_existing", verdict.get("verdict"))
    eval_dir.mkdir(parents=True, exist_ok=True)

    eval_variant = {
        "schema_version": "2026-09-16.baseline_6_eval_variant.v1",
        "baseline": "baseline_6",
        "variant_type": "skillinject_style_sink_only",
        "pack_id": pack_id,
        "experiment_id": eval_experiment_id,
        "variant_id": baseline_variant_id,
        "candidate_target_id": baseline_variant.get("candidate_target_id"),
        "upstream_skill": baseline_variant.get("upstream_skill"),
        "sink_skill": sink_skill,
        "downstream_skill": sink_skill,
        "payload_id": int(baseline_variant["payload_id"]),
        "payload_source": payload_reference.get("payload_source"),
        "task_ids": task_ids,
        "status": "baseline_6_pending",
        "baseline6_variant_source": paths.rel(baseline_variant_dir),
        "eligibility_source_experiments": item["source_experiment_ids"],
        "eligibility_source_variants": item["source_variant_ids"],
        "target_agent_payload_blind": True,
    }
    eval_variant_path = eval_dir / "variant.json"
    payload_path = eval_dir / "payload_reference.json"
    if not judge_only:
        if not eval_pack.exists():
            shutil.copytree(source_pack, eval_pack)
        write_json(eval_variant_path, eval_variant)
        write_json(payload_path, payload_reference)
        write_json(
            eval_dir / "baseline_6_eval_manifest.json",
            {
                "schema_version": "2026-09-16.baseline_6_eval_manifest.v1",
                "baseline": "baseline_6",
                "baseline6_variant_source": paths.rel(baseline_variant_dir),
                "source_experiment_ids": item["source_experiment_ids"],
                "source_variant_ids": item["source_variant_ids"],
                "eligibility": selection_mode,
                "provider": provider_name,
                "model": model_name,
            },
        )
    elif not eval_variant_path.exists() or not payload_path.exists():
        raise FileNotFoundError(f"Judge-only metadata missing under {eval_dir}")

    request = build_request(
        paths=paths,
        pack_id=pack_id,
        experiment_id=eval_experiment_id,
        variant=eval_variant,
        task_file=paths.benign_tasks / f"{pack_id}_tasks.json",
        pack_path=eval_pack,
        payload_reference_path=payload_path,
        trace_path=trace_path,
        task_ids=task_ids,
    )
    request_dir = eval_dir / "requests" / "D2"
    if not judge_only:
        write_stage_prompt(paths, request_dir, request)

    if prepare_only:
        return _record(item, baseline_variant_id, sink_skill, eval_experiment_id, paths, trace_path, verdict_path, "prepared", None)
    if not judge_only and not trace_path.exists():
        print(f"[baseline_6] {baseline_variant_id} D2 start provider={provider_name}", flush=True)
        execute_request(provider_name, request, request_dir)
    if not trace_path.exists():
        raise FileNotFoundError(trace_path)

    if not judge_only or verdict_path.exists():
        print(f"[baseline_6] {baseline_variant_id} D3 judge start", flush=True)
        judge_sink_only(
            paths=paths,
            pack_id=pack_id,
            experiment_id=eval_experiment_id,
            variant_id=baseline_variant_id,
        )
    verdict = load_json(verdict_path)
    print(
        f"[D3] sink_only={verdict.get('verdict')} "
        f"payload_observed={verdict.get('payload_observed')} "
        f"task_completed={verdict.get('task_completed')} "
        f"verdict_path={paths.rel(verdict_path)}",
        flush=True,
    )
    return _record(item, baseline_variant_id, sink_skill, eval_experiment_id, paths, trace_path, verdict_path, "executed", verdict.get("verdict"))


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
    task_ids: list[str],
) -> dict[str, Any]:
    return {
        "schema_version": "2026-09-16.baseline_6_stage_request.v1",
        "stage": "D2",
        "role": "target_agent",
        "created_at": now(),
        "pack_id": pack_id,
        "experiment_id": experiment_id,
        "loop_iteration": 0,
        "safety": {
            "baseline": "baseline_6",
            "payload_policy": "inert_payload_only",
            "target_agent_payload_blind": True,
        },
        "inputs": {
            "task_file": paths.rel(task_file),
            "clean_pack": paths.rel(paths.clean_packs / pack_id),
            "payload_reference": paths.rel(payload_reference_path),
            "sink_only_pack": paths.rel(pack_path),
        },
        "expected_output": paths.rel(trace_path),
        "contract": {"type": "jsonl", "rows": "RunTrace rows"},
        "variant": {**variant, "task_ids": task_ids},
    }


def write_stage_prompt(paths: FrameworkPaths, request_dir: Path, request: dict[str, Any]) -> None:
    request_dir.mkdir(parents=True, exist_ok=True)
    write_json(request_dir / "stage_request.json", request)
    prompt = PromptBuilder(paths).build(request)
    write_json(request_dir / "prompt_messages.json", prompt.messages())
    (request_dir / "resolved_prompt.md").write_text(prompt.to_debug_markdown(), encoding="utf-8")


def execute_request(provider_name: str, request: dict[str, Any], request_dir: Path) -> None:
    prompt = PromptBuilder().build(request)
    result = create_provider(provider_name).execute(prompt)
    write_provider_result(request_dir, result)
    materialized = materialize_model_output(
        request=request,
        raw_output=result.content,
        request_dir=request_dir,
    )
    if materialized is None:
        raise RuntimeError(f"D2 output could not be materialized; see {request_dir}")
    destination = Path(request["expected_output"])
    if not destination.is_absolute():
        destination = WORKSPACE / destination
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(materialized, destination)


def _find_baseline_variant_id(
    *,
    baseline_variants: dict[str, dict[str, Any]],
    sink_skill: str,
    payload_id: int,
) -> str:
    matches = [
        variant_id
        for variant_id, item in baseline_variants.items()
        if str(item.get("sink_skill") or item.get("downstream_skill") or "") == sink_skill
        and int(item.get("payload_id")) == payload_id
    ]
    if len(matches) != 1:
        raise ValueError(
            f"Expected one baseline_6 variant for sink_skill={sink_skill!r}, "
            f"payload_id={payload_id}; found {matches}"
        )
    return matches[0]


def _task_ids_from_item(item: dict[str, Any], payload_reference: dict[str, Any]) -> list[str]:
    task_ids: list[str] = []
    for source in item.get("source_variants", []):
        for task_id in source.get("task_ids") or []:
            if task_id not in task_ids:
                task_ids.append(str(task_id))
    if task_ids:
        return task_ids
    for task in payload_reference.get("example_tasks") or []:
        if isinstance(task, dict) and task.get("task_id"):
            task_ids.append(str(task["task_id"]))
    return task_ids


def _record(
    item: dict[str, Any],
    baseline_variant_id: str,
    sink_skill: str,
    eval_experiment_id: str,
    paths: FrameworkPaths,
    trace_path: Path,
    verdict_path: Path,
    status: str,
    verdict: Any,
) -> dict[str, Any]:
    return {
        "baseline_variant_id": baseline_variant_id,
        "sink_skill": sink_skill,
        "payload_id": int(item["baseline_variant"]["payload_id"]),
        "source_experiment_ids": item["source_experiment_ids"],
        "source_variant_ids": item["source_variant_ids"],
        "eval_experiment_id": eval_experiment_id,
        "status": status,
        "verdict": verdict,
        "trace": paths.rel(trace_path) if trace_path.exists() else None,
        "verdict_path": paths.rel(verdict_path) if verdict_path.exists() else None,
    }


def _resolve_experiment_id(pack_id: str, token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"\d{1,3}", token):
        return f"{pack_id}_exp_{int(token):03d}"
    if re.fullmatch(rf"{re.escape(pack_id)}_exp_\d{{3}}", token):
        return token
    raise ValueError(f"Invalid experiment id {token!r}; use 001, 002, 003 or {pack_id}_exp_001")


def _experiment_short_id(token: str) -> str:
    match = re.search(r"exp_(\d{3})$", token)
    return match.group(1) if match else token


def _selected_model(model: str, provider: str) -> str:
    if model:
        return model
    if provider == "codex-sandbox" or provider == "codex-cli":
        return os.environ.get("PVF_CODEX_MODEL", "") or "default"
    if provider == "claude-code-sandbox":
        return os.environ.get("PVF_CLAUDE_MODEL", "") or "default"
    return "dry-run"


def _csv_values(values: list[str]) -> list[str]:
    return list(dict.fromkeys(item.strip() for value in values for item in value.split(",") if item.strip()))


def _absolute_path(paths: FrameworkPaths, value: str) -> str:
    path = Path(value)
    return str(path if path.is_absolute() else paths.workspace_root / path)


def slug(value: str) -> str:
    value = value.strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    return value.strip("-") or "default"


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


if __name__ == "__main__":
    raise SystemExit(main())
