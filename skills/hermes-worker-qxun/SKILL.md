---
name: hermes-worker-qxun
description: Initialize and run a local automatic Codex worker for the QXun Hermes workflow. Use when a developer says "Hermes worker init", "Hermes worker start", "加入 Hermes worker", "领取 Hermes 任务", or needs Codex to claim Feishu-assigned tasks, edit local projects, build dist/html previews, upload previews to COS through Hermes-issued URLs, and report results back to the cloud Hermes Worker API.
---

# Hermes Worker QXun

Use this skill when the user wants this local Codex to join the QXun Hermes workflow, run as an automatic local worker, or process a task assigned from Feishu.

## What This Skill Does

- Initializes local worker config at `~/.hermes-codex-worker/config.json`.
- Registers/heartbeats this Codex worker with the cloud Hermes Worker API.
- Claims tasks assigned to this worker, either manually or on a timer.
- Resolves tasks to configured local project paths.
- Runs Codex in the target project for automatic task execution.
- Builds local `dist`/HTML previews before merge.
- Uploads preview files through Hermes-issued presigned COS upload URLs.
- Reports results, commits, and preview URLs back to Hermes.

Default API:

```text
http://81.71.29.84:8787
```

## Initialize

When the user says `Hermes worker init`, `加入 Hermes worker`, or wants to connect local Codex to Feishu:

1. If the user did not provide a Feishu nickname / worker id, ask exactly:

```text
请关联你的飞书昵称
```

2. Use that Feishu nickname as the worker id. Run `scripts/init_worker.py --worker <飞书昵称>`.
3. If the user knows local project paths and build settings, pass them with:

```bash
python3 scripts/init_worker.py \
  --worker <飞书昵称> \
  --project docs=/path/to/Docs \
  --project qxun=/path/to/QXunPortal \
  --build qxun="pnpm build" \
  --dist qxun=dist
```

4. If paths are missing, ask for them later only when a task needs that project.

The init script also supports interactive setup from a terminal:

```bash
python3 scripts/init_worker.py
```

It will prompt:

```text
请关联你的飞书昵称，用于 Hermes 将 Feishu 任务分配给这台本地 Codex worker。
飞书昵称:
```

To update project config after initialization, run:

```bash
python3 scripts/configure_project.py \
  --project qxun=/path/to/QXunPortal \
  --build qxun="pnpm build" \
  --dist qxun=dist
```

## Start Automatic Worker

When the user says `Hermes worker start` or `启动 Hermes 自动 worker`:

1. Confirm the worker has been initialized and local project config exists.
2. Install a timer that runs one automatic worker tick every 2 minutes:

```bash
python3 scripts/install_scheduler.py --interval 120 --exec-codex --install --load
```

The scheduler runs `scripts/worker_tick.py --exec-codex`. Each tick:

1. Sends heartbeat to Hermes.
2. Claims one task assigned to this worker.
3. Resolves `task.project` to `local_projects[project]`.
4. Writes the task and a Codex prompt under `~/.hermes-codex-worker/runs/<task_id>/`.
5. Runs `codex exec` inside the target local project.
6. The Codex run completes the task, builds preview, uploads it, and reports the result.

To run one tick manually:

```bash
python3 scripts/worker_tick.py --exec-codex
```

To stop the macOS timer:

```bash
python3 scripts/install_scheduler.py --uninstall
```

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

For automatic execution, prefer `scripts/worker_tick.py --exec-codex` over manually running `worker_runner.py`.

## Build Preview

After implementing a frontend change locally, build the preview from the saved task:

```bash
python3 scripts/build_preview.py \
  --task-file ~/.hermes-codex-worker/runs/<task_id>/task.json
```

This writes:

```text
~/.hermes-codex-worker/runs/<task_id>/preview_manifest.json
```

The manifest includes `task_id`, `worker_id`, project path, build command, dist path, git branch/commit, and the list of static files with content types.

## Upload Preview

Upload the built `dist`/HTML through Hermes-issued presigned COS upload URLs:

```bash
python3 scripts/upload_preview.py \
  --manifest ~/.hermes-codex-worker/runs/<task_id>/preview_manifest.json
```

The upload flow expects Hermes to provide:

- `POST /api/previews/create-upload`: receives file metadata and returns `build_id`, `preview_url`, and per-file presigned `PUT` URLs.
- `POST /api/previews/complete`: marks upload complete and returns the final `preview_url`.

Do not store COS permanent keys in local config. Hermes should issue short-lived, prefix-scoped upload URLs for the current `task_id/build_id`.

## Report Result

After completing work, call:

```bash
python3 scripts/submit_result.py \
  --task-id <task_id> \
  --status done \
  --summary "short summary" \
  --manifest ~/.hermes-codex-worker/runs/<task_id>/preview_manifest.json \
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
  },
  "project_builds": {
    "qxun": {
      "build_command": "pnpm build",
      "dist_dir": "dist"
    }
  }
}
```

Do not store CNB tokens or server SSH keys in this config.
Do not store COS permanent keys in this config; use Hermes-issued temporary upload URLs.
