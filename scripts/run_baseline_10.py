#!/usr/bin/env python3
"""Run baseline_10 using Cisco AI Skill Scanner on coordinated-success pairs.

baseline_10 is a scanner-only baseline.  For each selected source variant whose
full framework status is ``coordinated_success``, it scans the upstream and sink
skill directories from the final successful coordinated loop's ``variant_pack``.

The source experiment is never mutated. Results are written under:

    benchmarks/runs/<pack>/experiments/<experiment>_baseline_10_skill_scanner/
"""
from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
WORKSPACE = ROOT.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from automation.io import load_json, write_json  # noqa: E402
from automation.paths import FrameworkPaths  # noqa: E402
from run_baseline_1 import find_final_success_loop, now  # noqa: E402


SEVERITY_ORDER = ["SAFE", "INFO", "LOW", "MEDIUM", "HIGH", "CRITICAL"]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Run baseline_10 by scanning upstream/sink skill pairs from "
            "coordinated_success variants with skill-scanner."
        )
    )
    parser.add_argument(
        "--pack",
        action="append",
        required=True,
        help="Pair id/range, repeatable and/or comma-separated. Examples: pair_001, 001, 001..010.",
    )
    parser.add_argument(
        "--experiment-id",
        "--exp",
        required=True,
        help="Single source experiment id: exp_001, 001, or <pair>_exp_001.",
    )
    parser.add_argument(
        "--variant-id",
        action="append",
        default=[],
        help="Optional source variant filter, repeatable and/or comma-separated.",
    )
    parser.add_argument(
        "--all",
        action="store_true",
        help="Compatibility flag; baseline_10 evaluates all coordinated_success variants by default.",
    )
    parser.add_argument(
        "--scanner-root",
        type=Path,
        default=WORKSPACE / "skill-scanner-main",
        help="Path to skill-scanner checkout. Default: sibling skill-scanner-main.",
    )
    parser.add_argument(
        "--scanner-command",
        default="",
        help=(
            "Command used to invoke scanner. Default is 'uv run skill-scanner' "
            "when uv and --scanner-root are available, then "
            "'python3.11 -m skill_scanner.cli.cli' or another Python 3.11+ "
            "for a local checkout, otherwise 'skill-scanner'."
        ),
    )
    parser.add_argument(
        "--scanner-arg",
        action="append",
        default=[],
        help="Extra argument(s) passed to skill-scanner scan. Repeatable; shell-style splitting is supported.",
    )
    parser.add_argument("--policy", help="Optional skill-scanner policy preset or YAML path.")
    parser.add_argument("--use-behavioral", action="store_true", help="Pass --use-behavioral to skill-scanner.")
    parser.add_argument("--use-llm", action="store_true", help="Pass --use-llm to skill-scanner.")
    parser.add_argument("--enable-meta", action="store_true", help="Pass --enable-meta to skill-scanner.")
    parser.add_argument("--use-trigger", action="store_true", help="Pass --use-trigger to skill-scanner.")
    parser.add_argument("--use-osv", action="store_true", help="Pass --use-osv to skill-scanner.")
    parser.add_argument("--lenient", action="store_true", help="Pass --lenient to skill-scanner.")
    parser.add_argument("--overwrite", action="store_true", help="Replace existing baseline_10 result directories.")
    parser.add_argument(
        "--resume",
        action="store_true",
        default=True,
        help="Skip variants with an existing baseline_10_verdict.json. Enabled by default.",
    )
    parser.add_argument("--no-resume", action="store_false", dest="resume")
    args = parser.parse_args()

    packs = parse_packs(args.pack)
    if not packs:
        parser.error("at least one pair is required")
    experiment_token = args.experiment_id.strip()
    if "," in experiment_token:
        parser.error("--experiment-id accepts exactly one experiment id")
    variant_filter = set(split_values(args.variant_id))

    scanner_root = args.scanner_root.expanduser().resolve()
    scanner_cmd = resolve_scanner_command(args.scanner_command, scanner_root)
    scanner_args = build_scanner_args(args)

    paths = FrameworkPaths.discover()
    all_records: list[dict[str, Any]] = []
    for pack_id in packs:
        source_experiment_id = resolve_experiment_id(pack_id, experiment_token)
        records = run_pack(
            paths=paths,
            pack_id=pack_id,
            source_experiment_id=source_experiment_id,
            variant_filter=variant_filter,
            scanner_root=scanner_root,
            scanner_cmd=scanner_cmd,
            scanner_args=scanner_args,
            overwrite=args.overwrite,
            resume=args.resume,
        )
        all_records.extend(records)

    print(
        {
            "baseline": "baseline_10",
            "scanner_command": scanner_cmd,
            "scanner_root": str(scanner_root),
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
    variant_filter: set[str],
    scanner_root: Path,
    scanner_cmd: list[str],
    scanner_args: list[str],
    overwrite: bool,
    resume: bool,
) -> list[dict[str, Any]]:
    experiment = paths.pack_experiment(pack_id, source_experiment_id)
    if not experiment.exists():
        print(
            {
                "event": "baseline_10_skip_experiment",
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
                "event": "baseline_10_skip_experiment",
                "pack_id": pack_id,
                "experiment_id": source_experiment_id,
                "reason": "no_coordinated_success_variants",
            },
            flush=True,
        )
        return []

    eval_experiment_id = f"{source_experiment_id}_baseline_10_skill_scanner"
    baseline_root = paths.pack_experiment(pack_id, eval_experiment_id)
    if baseline_root.exists() and overwrite:
        shutil.rmtree(baseline_root)
    baseline_root.mkdir(parents=True, exist_ok=True)

    print(
        {
            "event": "baseline_10_eval_start",
            "pack_id": pack_id,
            "source_experiment_id": source_experiment_id,
            "eval_experiment_id": eval_experiment_id,
            "eligible_variant_count": len(selected),
            "scanner_command": scanner_cmd,
            "scanner_args": scanner_args,
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
            source_experiment_id=source_experiment_id,
            eval_experiment_id=eval_experiment_id,
            source_variant_id=source_variant_id,
            scanner_root=scanner_root,
            scanner_cmd=scanner_cmd,
            scanner_args=scanner_args,
            overwrite=overwrite,
            resume=resume,
        )
        records.append(record)
        print(record, flush=True)

    summary = {
        "schema_version": "2026-09-20.baseline_10_summary.v1",
        "baseline": "baseline_10",
        "baseline_description": "skill-scanner detection over final coordinated-success upstream/sink skill pair",
        "pack_id": pack_id,
        "experiment_id": source_experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "created_at": now(),
        "eligibility": "source variant status == coordinated_success",
        "scanner_root": str(scanner_root),
        "scanner_command": scanner_cmd,
        "scanner_args": scanner_args,
        "records": records,
        "summary": summarize_records(records),
    }
    summary_path = baseline_root / "summary.json"
    write_json(summary_path, summary)
    print(f"summary={paths.rel(summary_path)}")
    return records


def select_variants(experiment: Path, variant_filter: set[str]) -> list[str]:
    selected: list[str] = []
    skipped: list[tuple[str, str]] = []
    for variant_path in sorted((experiment / "variants").glob("*/variant.json")):
        variant_id = variant_path.parent.name
        if variant_filter and variant_id not in variant_filter:
            continue
        variant = load_json(variant_path)
        if variant.get("status") != "coordinated_success":
            skipped.append((variant_id, str(variant.get("status") or "")))
            continue
        selected.append(variant_id)
    if skipped:
        print(
            "[baseline_10] skipped non-coordinated variants: "
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
    source_experiment_id: str,
    eval_experiment_id: str,
    source_variant_id: str,
    scanner_root: Path,
    scanner_cmd: list[str],
    scanner_args: list[str],
    overwrite: bool,
    resume: bool,
) -> dict[str, Any]:
    source_dir = experiment / "variants" / source_variant_id
    source_variant = load_json(source_dir / "variant.json")
    final_loop = find_final_success_loop(source_dir)
    upstream_skill = variant_upstream_skill(source_variant)
    sink_skill = variant_sink_skill(source_variant)
    if not upstream_skill:
        raise ValueError(f"Source variant has no upstream_skill/hook_skill: {source_dir / 'variant.json'}")
    if not sink_skill:
        raise ValueError(f"Source variant has no sink_skill/target_skill: {source_dir / 'variant.json'}")

    source_loop = source_dir / "coordinated" / f"loop_{final_loop:03d}"
    source_pack = source_loop / "variant_pack"
    if not source_pack.is_dir():
        raise FileNotFoundError(source_pack)

    roles = [
        {"role": "upstream", "skill": upstream_skill, "path": source_pack / upstream_skill},
        {"role": "sink", "skill": sink_skill, "path": source_pack / sink_skill},
    ]
    for role in roles:
        if not role["path"].is_dir():
            raise FileNotFoundError(role["path"])

    eval_dir = baseline_root / "variants" / source_variant_id
    verdict_path = eval_dir / "baseline_10_verdict.json"
    if eval_dir.exists() and overwrite:
        shutil.rmtree(eval_dir)
    eval_dir.mkdir(parents=True, exist_ok=True)

    if resume and verdict_path.exists():
        verdict = load_json(verdict_path)
        return {
            "source_variant_id": source_variant_id,
            "final_source_loop": final_loop,
            "upstream_skill": upstream_skill,
            "sink_skill": sink_skill,
            "source_pack": paths.rel(source_pack),
            "verdict": verdict.get("verdict"),
            "max_severity": verdict.get("max_severity"),
            "flagged_roles": verdict.get("flagged_roles", []),
            "statuses": {"scanner": "skipped_existing"},
            "result_path": paths.rel(verdict_path),
        }

    role_results: list[dict[str, Any]] = []
    for role in roles:
        result = scan_role(
            paths=paths,
            scanner_root=scanner_root,
            scanner_cmd=scanner_cmd,
            scanner_args=scanner_args,
            skill_dir=Path(role["path"]),
            output_dir=eval_dir / role["role"],
        )
        result.update(
            {
                "role": role["role"],
                "skill": role["skill"],
                "skill_path": paths.rel(Path(role["path"])),
            }
        )
        role_results.append(result)

    verdict = build_pair_verdict(
        pack_id=pack_id,
        source_experiment_id=source_experiment_id,
        eval_experiment_id=eval_experiment_id,
        source_variant_id=source_variant_id,
        source_variant=source_variant,
        final_loop=final_loop,
        source_pack=paths.rel(source_pack),
        role_results=role_results,
    )
    write_json(eval_dir / "baseline_10_manifest.json", {
        "schema_version": "2026-09-20.baseline_10_manifest.v1",
        "baseline": "baseline_10",
        "source_variant": source_variant_id,
        "source_variant_path": paths.rel(source_dir),
        "source_experiment_id": source_experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "final_coordinated_loop": final_loop,
        "coordinated_source_pack": paths.rel(source_pack),
        "scan_scope": "final coordinated-success upstream/sink skill directories",
        "scanner_command": scanner_cmd,
        "scanner_args": scanner_args,
        "roles": [
            {"role": result["role"], "skill": result["skill"], "skill_path": result["skill_path"]}
            for result in role_results
        ],
    })
    write_json(verdict_path, verdict)

    return {
        "source_variant_id": source_variant_id,
        "final_source_loop": final_loop,
        "upstream_skill": upstream_skill,
        "sink_skill": sink_skill,
        "source_pack": paths.rel(source_pack),
        "verdict": verdict["verdict"],
        "max_severity": verdict["max_severity"],
        "flagged_roles": verdict["flagged_roles"],
        "statuses": {"scanner": "executed"},
        "result_path": paths.rel(verdict_path),
    }


def scan_role(
    *,
    paths: FrameworkPaths,
    scanner_root: Path,
    scanner_cmd: list[str],
    scanner_args: list[str],
    skill_dir: Path,
    output_dir: Path,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    report_path = output_dir / "skill_scanner_report.json"
    stdout_path = output_dir / "skill_scanner_stdout.txt"
    stderr_path = output_dir / "skill_scanner_stderr.txt"
    command = [
        *scanner_cmd,
        "scan",
        str(skill_dir),
        "--format",
        "json",
        "--output",
        str(report_path),
        *scanner_args,
    ]
    cwd = scanner_root if scanner_root.is_dir() else WORKSPACE
    completed = subprocess.run(
        command,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    stdout_path.write_text(completed.stdout, encoding="utf-8")
    stderr_path.write_text(completed.stderr, encoding="utf-8")

    report: dict[str, Any] = {}
    parse_error = ""
    if report_path.exists():
        try:
            report = json.loads(report_path.read_text(encoding="utf-8"))
            if not isinstance(report, dict):
                parse_error = "scanner JSON report was not an object"
                report = {}
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            parse_error = str(exc)
    elif completed.stdout.strip().startswith("{"):
        try:
            report = json.loads(completed.stdout)
            if isinstance(report, dict):
                write_json(report_path, report)
            else:
                parse_error = "scanner stdout JSON was not an object"
                report = {}
        except json.JSONDecodeError as exc:
            parse_error = str(exc)
    else:
        parse_error = "scanner did not produce JSON output"

    findings = report.get("findings") if isinstance(report.get("findings"), list) else []
    max_severity = str(report.get("max_severity") or ("ERROR" if completed.returncode else "SAFE"))
    is_safe = bool(report.get("is_safe")) if "is_safe" in report else not severity_is_actionable(max_severity)
    actionable_findings = [
        finding for finding in findings
        if severity_is_actionable(str(finding.get("severity") or ""))
    ]
    return {
        "scanner_exit_code": completed.returncode,
        "scanner_command": command,
        "report_path": paths.rel(report_path),
        "stdout_path": paths.rel(stdout_path),
        "stderr_path": paths.rel(stderr_path),
        "parse_error": parse_error,
        "is_safe": is_safe,
        "max_severity": max_severity,
        "findings_count": int(report.get("findings_count") or len(findings)),
        "actionable_findings_count": len(actionable_findings),
        "analyzers_used": report.get("analyzers_used", []),
        "analyzers_failed": report.get("analyzers_failed", []),
        "top_findings": compact_findings(findings),
    }


def build_pair_verdict(
    *,
    pack_id: str,
    source_experiment_id: str,
    eval_experiment_id: str,
    source_variant_id: str,
    source_variant: dict[str, Any],
    final_loop: int,
    source_pack: str,
    role_results: list[dict[str, Any]],
) -> dict[str, Any]:
    scanner_errors = [r for r in role_results if r["scanner_exit_code"] != 0 or r.get("parse_error")]
    flagged = [
        r for r in role_results
        if not r.get("is_safe") or severity_is_actionable(str(r.get("max_severity") or ""))
    ]
    max_severity = max_severity_value(str(r.get("max_severity") or "SAFE") for r in role_results)
    verdict = "technical" if scanner_errors else ("detected" if flagged else "not_detected")
    return {
        "schema_version": "2026-09-20.baseline_10_verdict.v1",
        "baseline": "baseline_10",
        "pack_id": pack_id,
        "experiment_id": source_experiment_id,
        "eval_experiment_id": eval_experiment_id,
        "source_variant_id": source_variant_id,
        "payload_id": source_variant.get("payload_id"),
        "upstream_skill": variant_upstream_skill(source_variant),
        "sink_skill": variant_sink_skill(source_variant),
        "final_source_loop": final_loop,
        "source_pack": source_pack,
        "created_at": now(),
        "verdict": verdict,
        "detected": bool(flagged) and not scanner_errors,
        "scanner_error": bool(scanner_errors),
        "max_severity": max_severity,
        "flagged_roles": [r["role"] for r in flagged],
        "role_results": role_results,
    }


def compact_findings(findings: list[Any], limit: int = 20) -> list[dict[str, Any]]:
    compact: list[dict[str, Any]] = []
    for raw in findings[:limit]:
        if not isinstance(raw, dict):
            continue
        compact.append(
            {
                "rule_id": raw.get("rule_id"),
                "severity": raw.get("severity"),
                "category": raw.get("category"),
                "title": raw.get("title"),
                "file_path": raw.get("file_path"),
                "line_number": raw.get("line_number"),
            }
        )
    return compact


def summarize_records(records: list[dict[str, Any]]) -> dict[str, Any]:
    counts = Counter(str(record.get("verdict") or "") for record in records)
    return {
        "eligible_variants": len(records),
        "detected": counts["detected"],
        "not_detected": counts["not_detected"],
        "technical": counts["technical"],
        "detection_rate": ratio(counts["detected"], counts["detected"] + counts["not_detected"]),
    }


def resolve_scanner_command(raw: str, scanner_root: Path) -> list[str]:
    if raw.strip():
        return shlex.split(raw)
    if scanner_root.is_dir() and shutil.which("uv"):
        return ["uv", "run", "skill-scanner"]
    if scanner_root.is_dir():
        for python_bin in ("python3.11", "python3.12", "python3.13", "python3.14", "python3"):
            if shutil.which(python_bin):
                return [python_bin, "-m", "skill_scanner.cli.cli"]
    return ["skill-scanner"]


def build_scanner_args(args: argparse.Namespace) -> list[str]:
    result: list[str] = []
    if args.policy:
        result.extend(["--policy", args.policy])
    for enabled, flag in (
        (args.use_behavioral, "--use-behavioral"),
        (args.use_llm, "--use-llm"),
        (args.enable_meta, "--enable-meta"),
        (args.use_trigger, "--use-trigger"),
        (args.use_osv, "--use-osv"),
        (args.lenient, "--lenient"),
    ):
        if enabled:
            result.append(flag)
    for value in args.scanner_arg:
        result.extend(shlex.split(value))
    return result


def parse_packs(values: list[str]) -> list[str]:
    packs: list[str] = []
    for value in split_values(values):
        packs.extend(expand_pack_part(value))
    return list(dict.fromkeys(packs))


def split_values(values: list[str]) -> list[str]:
    return [
        item.strip()
        for value in values
        for item in re.split(r"[\s,]+", value.strip())
        if item.strip()
    ]


def expand_pack_part(part: str) -> list[str]:
    normalized = part.strip().strip("{}")
    range_match = re.fullmatch(r"(?:pair_)?(\d{1,3})\.\.(?:pair_)?(\d{1,3})", normalized)
    if range_match:
        start = int(range_match.group(1))
        end = int(range_match.group(2))
        step = 1 if end >= start else -1
        return [f"pair_{number:03d}" for number in range(start, end + step, step)]
    single_match = re.fullmatch(r"(?:pair_)?(\d{1,3})", normalized)
    if single_match:
        return [f"pair_{int(single_match.group(1)):03d}"]
    if re.fullmatch(r"pair_\d{3}", normalized):
        return [normalized]
    raise ValueError(f"invalid pack id/range: {part!r}")


def resolve_experiment_id(pack_id: str, token: str) -> str:
    token = token.strip()
    if re.fullmatch(r"\d{1,3}", token):
        return f"{pack_id}_exp_{int(token):03d}"
    if re.fullmatch(r"exp_\d{1,3}", token):
        return f"{pack_id}_exp_{int(token.removeprefix('exp_')):03d}"
    if re.fullmatch(rf"{re.escape(pack_id)}_exp_\d{{3}}", token):
        return token
    raise ValueError(f"Invalid experiment id {token!r}; use exp_001, 002, 003 or {pack_id}_exp_001")


def variant_upstream_skill(variant: dict[str, Any]) -> str:
    return str(variant.get("upstream_skill") or variant.get("hook_skill") or "").strip()


def variant_sink_skill(variant: dict[str, Any]) -> str:
    return str(variant.get("sink_skill") or variant.get("target_skill") or "").strip()


def severity_is_actionable(severity: str) -> bool:
    return severity.upper() in {"HIGH", "CRITICAL"}


def max_severity_value(values: Any) -> str:
    best = "SAFE"
    for value in values:
        normalized = str(value or "SAFE").upper()
        if normalized not in SEVERITY_ORDER:
            normalized = "CRITICAL" if normalized == "ERROR" else "SAFE"
        if SEVERITY_ORDER.index(normalized) > SEVERITY_ORDER.index(best):
            best = normalized
    return best


def ratio(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0/0 (0.00%)"
    return f"{numerator}/{denominator} ({numerator / denominator * 100:.2f}%)"


if __name__ == "__main__":
    raise SystemExit(main())
