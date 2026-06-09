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
python scripts/python/agent_s/run_multienv.py `
  --provider_name vmware `
  --path_to_vm vmware_vm_data\Windows0\Windows0.vmx `
  --os_type Windows `
  --platform windows `
  --examples_dir evaluation_examples\examples_windows `
  --test_all_meta_path evaluation_examples\test_omnic_windows.json `
  --domain omnic `
  --result_dir results\vlaa_qwen `
  --model_dir_name qwen3.6-plus `
  --num_envs 1 `
  --observation_type screenshot `
  --max_steps 15 `
  --ground_provider <provider> `
  --ground_url <url> `
  --ground_model <model>
```

`run_multienv.py` uses the result directory directly, so this example writes task
outputs under `results/vlaa_qwen/pyautogui/screenshot/qwen3.6-plus/...`. A single
local VMware `.vmx` only supports `--num_envs 1`; use an independent environment
provider before increasing the worker count. Agent-S logs default to
`C:\Users\unter\Agent-S\logs\osworld\<run_id>\` when that directory is available, otherwise they fall back to `logs/agent_s/<run_id>/`.
For `qwen` providers, keep keys in the environment; the Agent-S runners accept
either `QWEN_API_KEY` or `DASHSCOPE_API_KEY` without writing secrets to config.
The older `run_local.py` entrypoint remains available and appends `<run_id>` under
its `--result_dir`.

### UIAgent Batch Evaluation

OSWorld owns the shared `DesktopEnv`, VM startup, snapshot restore, and per-task
`reset()`. UIAgent runs inline in the OSWorld process and only talks to the
prepared controller.

```powershell
python scripts/python/uiagent/eval_windows.py `
  --uiagent-root C:\Users\unter\UIAgent `
  --examples-dir evaluation_examples\examples_windows `
  --meta evaluation_examples\test_omnic_windows.json `
  --domain omnic `
  --result-dir results\uiagent
```

### UIAgent Multi-Environment Evaluation

Use this when you want a `run_multienv_vlaa.py`-style result layout and multiple
OSWorld environments. UIAgent's own repository logs stay in the UIAgent log
directory; each OSWorld task result records that path in `uiagent_log_dir.txt`.

```powershell
python scripts/python/run_multienv_uiagent.py `
  --uiagent-root C:\Users\unter\UIAgent `
  --provider_name vmware `
  --os_type Windows `
  --examples_subdir examples_windows `
  --test_all_meta_path evaluation_examples\test_omnic_windows.json `
  --domain omnic `
  --num_envs 1 `
  --max_steps 15 `
  --result_dir results\uiagent_qwen `
  --model_dir_name qwen
```

The result layout is
`results/uiagent_qwen/pyautogui/screenshot/qwen/<domain>/<task_id>/`. For local
VMware/VirtualBox runs, do not pass one `--path_to_vm` with `--num_envs > 1`;
omit `--path_to_vm` so OSWorld can allocate free registered Windows VMs, or keep
`--num_envs 1`. `--max_steps` maps to UIAgent controller turns; each turn may
contain one high-level UI action or a routine.

### UIAgent Single Task

```powershell
python scripts/python/uiagent/run_task.py `
  --uiagent-root C:\Users\unter\UIAgent `
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
