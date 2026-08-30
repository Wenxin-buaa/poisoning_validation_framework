# PVF Codex OpenSandbox Runtime

This optional target-agent provider follows SkillJect's sandbox pattern while
using Codex instead of Claude Code.

## Build Image

```bash
docker build -f pair_poisoning_validation_framework/Dockerfile.codex \
  -t pvf-codex-runtime:latest pair_poisoning_validation_framework
```

To pin another Codex CLI version:

```bash
docker build -f pair_poisoning_validation_framework/Dockerfile.codex \
  --build-arg CODEX_CLI_VERSION=0.145.0 \
  -t pvf-codex-runtime:latest pair_poisoning_validation_framework
```

## Local Python Dependency

Use a Python 3.10+ environment. The system Python 3.9 on this machine does
not resolve the sandbox SDK package.

```bash
python3 -m pip install -r pair_poisoning_validation_framework/requirements-sandbox.txt
```

## Runtime Environment

```bash
export PVF_SANDBOX_DOMAIN=localhost:8080
export PVF_SANDBOX_IMAGE=pvf-codex-runtime:latest
export OPENAI_API_KEY=...
```

`CODEX_API_KEY` is also accepted; the provider forwards it to Codex inside the
sandbox.

## Run With Sandbox Target Agent

For one variant slice:

```bash
python3 pair_poisoning_validation_framework/scripts/run_experiment_from_variant.py \
  --pack pack_a \
  --experiment-id pack_a_exp_XXX \
  --start-variant-id <variant_id> \
  --d2-provider codex-sandbox \
  --d5-provider codex-sandbox
```

For parallel runs:

```bash
python3 pair_poisoning_validation_framework/scripts/run_experiment_parallel.py \
  --pack pack_a \
  --experiment-id pack_a_exp_XXX \
  --workers 2 \
  --d2-provider codex-sandbox \
  --d5-provider codex-sandbox
```

## Container Layout

```text
/home/codex/project/
  artifacts/
  resources/                 # copied from the sink skill's resources/

/home/codex/.codex/skills/
  <skill_name>/
    SKILL.md
    resources/
```

`resources/` is copied into the project workspace, not symlinked, so instructions
such as `bash resources/helper.sh` resolve naturally from Codex's working
directory.
