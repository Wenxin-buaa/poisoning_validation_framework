#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
WORKSPACE="$(cd "$ROOT/.." && pwd)"
PYTHON_BIN="${PYTHON_BIN:-python3.11}"

PACKS_CSV=""
KEYS_FILE=""
BATCH_ID=""
PAYLOAD_POOL=""
D2_PROVIDER=""
D5_PROVIDER=""
LOCAL_PROVIDER=""
EXPERIMENT_ID_TEMPLATE=""
MAX_STEPS_PER_WORKER=""
PAYLOAD_IDS_CSV="1,2"
SHARDS_CSV="0,1,2"

usage() {
  cat <<'EOF'
Usage:
  run_exp002_payload_001_002_six_workers.sh \
    --packs pair_001,pair_002,... \
    --experiment-id-template '{pack}_exp_002' \
    --payload-pool skillject-obvious-general-no003 \
    --worker-api-keys-file /path/to/pvf_worker_keys.json \
    --d2-provider claude-code-sandbox \
    --d5-provider claude-code-sandbox \
    --local-provider openai-compatible \
    --batch-id pair_exp_002_payload_001_002_six_workers

Optional resume controls:
  --payload-ids 1          Run only payload 001.
  --payload-ids 2          Run only payload 002.
  --shards 0              Run only shard 00.
  --shards 1,2            Run shard 01 and shard 02.

This launches six controllers:
  payload_001 shard_00/01/02
  payload_002 shard_00/01/02

Each shard receives one API key from the first six keys in --worker-api-keys-file.
EOF
}

while [[ $# -gt 0 ]]; do
  case "$1" in
    --packs)
      PACKS_CSV="$2"
      shift 2
      ;;
    --experiment-id-template)
      EXPERIMENT_ID_TEMPLATE="$2"
      shift 2
      ;;
    --payload-pool)
      PAYLOAD_POOL="$2"
      shift 2
      ;;
    --worker-api-keys-file)
      KEYS_FILE="$2"
      shift 2
      ;;
    --d2-provider)
      D2_PROVIDER="$2"
      shift 2
      ;;
    --d5-provider)
      D5_PROVIDER="$2"
      shift 2
      ;;
    --local-provider)
      LOCAL_PROVIDER="$2"
      shift 2
      ;;
    --batch-id)
      BATCH_ID="$2"
      shift 2
      ;;
    --payload-ids)
      PAYLOAD_IDS_CSV="$2"
      shift 2
      ;;
    --shards)
      SHARDS_CSV="$2"
      shift 2
      ;;
    --max-steps-per-worker)
      MAX_STEPS_PER_WORKER="$2"
      shift 2
      ;;
    --help|-h)
      usage
      exit 0
      ;;
    *)
      echo "Unknown argument: $1" >&2
      usage >&2
      exit 2
      ;;
  esac
done

missing=()
[[ -n "$PACKS_CSV" ]] || missing+=("--packs")
[[ -n "$EXPERIMENT_ID_TEMPLATE" ]] || missing+=("--experiment-id-template")
[[ -n "$PAYLOAD_POOL" ]] || missing+=("--payload-pool")
[[ -n "$KEYS_FILE" ]] || missing+=("--worker-api-keys-file")
[[ -n "$D2_PROVIDER" ]] || missing+=("--d2-provider")
[[ -n "$D5_PROVIDER" ]] || missing+=("--d5-provider")
[[ -n "$LOCAL_PROVIDER" ]] || missing+=("--local-provider")
[[ -n "$BATCH_ID" ]] || missing+=("--batch-id")
if (( ${#missing[@]} > 0 )); then
  echo "Missing required arguments: ${missing[*]}" >&2
  usage >&2
  exit 2
fi

IFS=',' read -r -a PACKS <<< "$PACKS_CSV"
if (( ${#PACKS[@]} == 0 )); then
  echo "--packs did not contain any pack ids" >&2
  exit 2
fi
IFS=',' read -r -a PAYLOAD_IDS <<< "$PAYLOAD_IDS_CSV"
IFS=',' read -r -a SHARDS <<< "$SHARDS_CSV"
if (( ${#PAYLOAD_IDS[@]} == 0 || ${#SHARDS[@]} == 0 )); then
  echo "--payload-ids and --shards must not be empty" >&2
  exit 2
fi

RUN_DIR="$ROOT/benchmarks/runs/batches/$BATCH_ID"
KEY_DIR="$RUN_DIR/worker_key_files"
PID_FILE="$RUN_DIR/controller_pids.txt"
mkdir -p "$KEY_DIR"
printf '# launch %s payload_ids=%s shards=%s batch_id=%s\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" "$PAYLOAD_IDS_CSV" "$SHARDS_CSV" "$BATCH_ID" >> "$PID_FILE"

"$PYTHON_BIN" - "$KEYS_FILE" "$KEY_DIR" <<'PY'
import json
import sys
from pathlib import Path

keys_file = Path(sys.argv[1])
key_dir = Path(sys.argv[2])
data = json.loads(keys_file.read_text(encoding="utf-8"))
keys = data.get("keys") if isinstance(data, dict) else data
if not isinstance(keys, list):
    raise SystemExit(f"{keys_file} must be a JSON list or an object with a 'keys' list")
keys = [str(key).strip() for key in keys if str(key).strip()]
if len(keys) < 6:
    raise SystemExit(f"{keys_file} must contain at least 6 non-empty API keys; got {len(keys)}")
for index, key in enumerate(keys[:6]):
    (key_dir / f"worker_key_{index:02d}.json").write_text(
        json.dumps({"keys": [key]}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
PY

pack_experiment_args_for_shard() {
  local shard="$1"
  local index=0
  local pack experiment
  for pack in "${PACKS[@]}"; do
    if (( index % 3 == shard )); then
      experiment="${EXPERIMENT_ID_TEMPLATE/\{pack\}/$pack}"
      printf '%s\n' "--pack-experiment" "$pack:$experiment"
    fi
    index=$((index + 1))
  done
}

echo "Starting $BATCH_ID under $RUN_DIR"
echo "Using keys from $KEYS_FILE"

for payload_id in "${PAYLOAD_IDS[@]}"; do
  payload_id="${payload_id//[[:space:]]/}"
  for shard in "${SHARDS[@]}"; do
    shard="${shard//[[:space:]]/}"
    if [[ "$payload_id" != "1" && "$payload_id" != "2" ]]; then
      echo "Unsupported payload id for this wrapper: $payload_id" >&2
      exit 2
    fi
    if [[ "$shard" != "0" && "$shard" != "1" && "$shard" != "2" ]]; then
      echo "Unsupported shard for this wrapper: $shard" >&2
      exit 2
    fi
    if [[ "$payload_id" == "1" ]]; then
      key_index="$shard"
    else
      key_index=$((3 + shard))
    fi
    worker_batch_id="${BATCH_ID}_payload_$(printf '%03d' "$payload_id")_shard_$(printf '%02d' "$shard")"
    log_path="$ROOT/benchmarks/runs/batches/${worker_batch_id}.nohup.log"
    key_file="$KEY_DIR/worker_key_$(printf '%02d' "$key_index").json"
    shard_args=()
    while IFS= read -r arg; do
      shard_args+=("$arg")
    done < <(pack_experiment_args_for_shard "$shard")
    extra_args=()
    if [[ -n "$MAX_STEPS_PER_WORKER" ]]; then
      extra_args+=(--max-steps-per-worker "$MAX_STEPS_PER_WORKER")
    fi

    cmd=(
      "$PYTHON_BIN" "$ROOT/scripts/run_payload_batch.py"
      --payload-pool "$PAYLOAD_POOL"
      --payload-id "$payload_id"
      --worker-api-keys-file "$key_file"
      --d2-provider "$D2_PROVIDER"
      --d5-provider "$D5_PROVIDER"
      --local-provider "$LOCAL_PROVIDER"
      --batch-id "$worker_batch_id"
    )
    if [[ -n "$MAX_STEPS_PER_WORKER" ]]; then
      cmd+=(--max-steps-per-worker "$MAX_STEPS_PER_WORKER")
    fi
    cmd+=("${shard_args[@]}")

    nohup "${cmd[@]}" > "$log_path" 2>&1 &

    pid="$!"
    printf '%s payload_%03d shard_%02d key_%02d %s\n' "$pid" "$payload_id" "$shard" "$key_index" "$worker_batch_id" | tee -a "$PID_FILE"
  done
done

echo "Launched 6 controllers. PID file: $PID_FILE"
echo "Logs:"
for payload_id in 1 2; do
  for shard in 0 1 2; do
    worker_batch_id="${BATCH_ID}_payload_$(printf '%03d' "$payload_id")_shard_$(printf '%02d' "$shard")"
    echo "  $ROOT/benchmarks/runs/batches/${worker_batch_id}.nohup.log"
  done
done
