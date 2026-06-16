---
name: hermes-worker-qxun
description: Initialize and run a local Codex worker for the QXun Hermes workflow. Use when a developer says "Hermes worker init", "加入 Hermes worker", "领取 Hermes 任务", or needs Codex to claim Feishu-assigned tasks, update Docs requirements/bugs, build previews, and report results back to the cloud Hermes Worker API.
---

# Hermes Worker QXun

Use this skill when the user wants this local Codex to join the QXun Hermes workflow or process a task assigned from Feishu.

## What This Skill Does

- Initializes local worker config at `~/.hermes-codex-worker/config.json`.
- Registers/heartbeats this Codex worker with the cloud Hermes Worker API.
- Claims tasks assigned to this worker.
- Guides Codex to complete the claimed task locally.
- Reports results back to the cloud.

Default API:

```text
http://81.71.29.84:8787
```

## Initialize

When the user says `Hermes worker init <worker_id>`:

1. Run `scripts/init_worker.py --worker <worker_id>`.
2. If the user knows local project paths, pass them with:

```bash
python3 scripts/init_worker.py \
  --worker jerry \
  --project docs=/path/to/Docs \
  --project qxun=/path/to/QXunPortal
```

3. If paths are missing, ask for them later only when a task needs that project.

## Claim A Task

When the user says `领取 Hermes 任务` or an automation runs this skill:

1. Run:

```bash
python3 scripts/worker_runner.py
```

2. If it returns `has_task: false`, stop.
3. If it returns a task, read the saved task file shown in the output.
4. Complete the task according to `task.type`:
   - `requirement`: update a Markdown requirement document.
   - `bug`: reproduce/fix if project code is available, or write a bug issue draft/result.
   - `preview`: modify/build the frontend and upload preview if configured.

## Report Result

After completing work, call:

```bash
python3 scripts/submit_result.py \
  --task-id <task_id> \
  --status done \
  --summary "short summary" \
  --doc-path "requirements/example.md" \
  --preview-url "https://..."
```

Include commit hash if available:

```bash
python3 scripts/submit_result.py --task-id <task_id> --commit abc1234
```

## Local Config

The config file is:

```text
~/.hermes-codex-worker/config.json
```

Minimum content:

```json
{
  "worker_id": "jerry",
  "server_api": "http://81.71.29.84:8787",
  "local_projects": {
    "docs": "/Users/name/Documents/app/Docs",
    "qxun": "/Users/name/Documents/app/QXunPortal"
  }
}
```

Do not store CNB tokens or server SSH keys in this config.
