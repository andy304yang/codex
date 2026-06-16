---
name: hermes-worker-qxun
description: Initialize and run a local automatic Codex worker for the QXun Hermes workflow. Use when a user says "Hermes worker init", "Hermes worker start", "加入 Hermes worker", "领取 Hermes 任务", or needs Codex to pull Feishu-assigned Markdown tasks from the CNB Docs repository, claim tasks assigned to the local Feishu nickname, optionally execute local project work, build previews, and write task status back to Docs.
---

# Hermes Worker QXun

Use this skill when the user wants this local Codex to join the QXun Hermes workflow, run as an automatic local worker, or process a task assigned from Feishu.

## What This Skill Does

- Initializes local worker config at `~/.hermes-codex-worker/config.json`.
- Pulls the CNB Docs repository used as the shared Hermes task queue.
- Claims one `tasks/*.md` task assigned to this worker by changing `status: open` to `status: claimed` and pushing that commit.
- Runs Codex on the Docs repository for document/product tasks when no local code project is configured.
- Optionally resolves tasks to configured local project paths for frontend/backend code work.
- Optionally builds local `dist`/HTML previews before merge.
- Reports result status, summaries, commits, and preview URLs back to the Docs task Markdown.

Default Docs queue:

```text
https://cnb.cool/yztx_qxun/Docs
tasks/*.md
```

## Initialize

When the user says `Hermes worker init <worker_id>` or `使用 hermes-worker-qxun 初始化 Hermes worker`:

1. If no worker id is provided, ask: `请关联你的飞书昵称`.
2. Run:

```bash
python3 scripts/init_worker.py --worker jerry
```

This does not require a local product/code repository. It only stores the local worker id and the Docs queue configuration.

If this worker should also handle a local code project, configure it explicitly:

```bash
python3 scripts/configure_project.py \
  --project qxun=/path/to/QXunPortal \
  --build qxun="pnpm build:h5:candidate" \
  --dist qxun=apps/h5-candidate/dist
```

## Start Automatic Worker

When the user says `Hermes worker start` or `启动 Hermes 自动 worker`:

1. Confirm the worker has been initialized.
2. Install a timer that runs one automatic Docs queue tick every 2 minutes:

```bash
python3 scripts/install_scheduler.py --interval 120 --exec-codex --install --load
```

The scheduler runs `scripts/worker_tick.py --exec-codex`. Each tick:

1. Pulls the Docs queue repository.
2. Finds one `tasks/*.md` with `status: open` and `assignee: <worker_id>`.
3. Claims it by committing `status: claimed`, `claimed_by`, and `claimed_at`.
4. Writes the task and a Codex prompt under `~/.hermes-codex-worker/runs/<task_id>/`.
5. Runs `codex exec` in the configured local project when available, otherwise in the Docs repository.
6. The Codex run completes the task and reports the result back to the task Markdown.

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
   - `requirement`: update the Docs Markdown or the configured project.
   - `bug`: reproduce/fix if the relevant project is configured, or mark blocked with missing project details.
   - `preview`: modify/build/upload only when a local project build is configured; otherwise mark blocked.

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
  "docs_queue": {
    "repo_url": "https://cnb.cool/yztx_qxun/Docs",
    "repo_dir": "/Users/name/.hermes-codex-worker/docs-repo",
    "task_dir": "tasks"
  },
  "local_projects": {},
  "project_builds": {
    "qxun": {
      "build_command": "pnpm build",
      "dist_dir": "dist"
    }
  }
}
```

Do not store CNB tokens or server SSH keys in this config. Git authentication should use the user's existing Git credential helper or `~/.netrc`.
Do not store COS permanent keys in this config; use Hermes-issued temporary upload URLs.
