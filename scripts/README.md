# Scripts Directory

This directory contains OSWorld run scripts, helper CLIs, and agent-specific integrations.
Run all commands from the OSWorld project root, not from inside `scripts/`.

## Structure

```text
scripts/
  python/
    run_*.py              # Historical single-file runners for models/agents
    run_multienv_*.py     # Historical multi-environment runners
    agent_s/              # Agent-S integration and Agent-S-only helpers
    uiagent/              # UIAgent integration and Windows evaluation helpers
  bash/
    run_*.sh              # Shell wrappers for selected runners
```

## Python Scripts

The `python/` directory has two styles:

- Single-file runners such as `run_multienv.py`, `run_multienv_claude.py`, `run_multienv_vlaa.py`, and `run_maestro.py`.
- Directory-based integrations for agents that need multiple files or helper tools:
  - `agent_s/` contains the Agent-S OSWorld runner, its single-task loop, logging setup, and BBON utilities.
  - `uiagent/` contains the UIAgent OSWorld bridge and Windows batch-evaluation runner.

This keeps newer agent-specific code grouped by agent without changing the existing OSWorld runner layout.

## Bash Scripts

The `bash/` directory contains shell wrappers for specific workflows, including:

- `run_dart_gui.sh`
- `run_gpt54.sh`
- `run_manual_examine.sh`
- `run_os_symphony.sh`
- `run_vlaa_gui.sh`

## Usage

### Existing OSWorld Runner

```bash
python scripts/python/run_multienv.py \
  --provider_name docker \
  --headless \
  --observation_type screenshot \
  --model gpt-4o \
  --max_steps 15 \
  --num_envs 10 \
  --client_password password
```

### Agent-S On Windows OMNIC

```powershell
python scripts/python/agent_s/run_local.py `
  --provider_name vmware `
  --path_to_vm vmware_vm_data\Windows0\Windows0.vmx `
  --os_type Windows `
  --agent_platform windows `
  --examples_dir evaluation_examples\examples_windows `
  --test_all_meta_path evaluation_examples\test_omnic_windows.json `
  --domain omnic `
  --result_dir results\agent_s `
  --observation_type screenshot `
  --max_steps 15 `
  --ground_provider <provider> `
  --ground_url <url> `
  --ground_model <model>
```

Agent-S results are written under `results/agent_s/<run_id>/...`. Agent-S logs default to
`C:\Users\unter\Agent-S\logs\osworld\<run_id>\` when that directory is available, otherwise they fall back to `logs/agent_s/<run_id>/`.

### UIAgent Batch Evaluation

```powershell
python scripts/python/uiagent/eval_windows.py `
  --examples-dir evaluation_examples\examples_windows `
  --meta evaluation_examples\test_omnic_windows.json `
  --domain omnic `
  --result-dir results\uiagent
```

### UIAgent Single Task

```powershell
python scripts/python/uiagent/run_task.py `
  --task-config evaluation_examples\examples_windows\omnic\ec69d8d4-68d4-4ec2-99f0-3282132924e6.json `
  --vmx vmware_vm_data\Windows0\Windows0.vmx `
  --os-type Windows
```

## Adding New Agent Integrations

For a simple runner, adding `scripts/python/run_<agent>.py` is still acceptable. For an integration that needs multiple entrypoints, logging code, or helper utilities, prefer:

```text
scripts/python/<agent_name>/
  __init__.py
  run_local.py
  run_single.py
  logging_config.py
```

Each script should add the project root to `sys.path` before importing OSWorld modules when it is intended to be run directly.
