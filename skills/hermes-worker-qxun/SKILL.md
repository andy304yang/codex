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
- Deploys previews to an Nginx static site so HTML/CSS/JS can be opened as a real web page.
- Reports result status, summaries, commits, and preview URLs back to the Docs task Markdown.

Default Docs queue:

```text
https://cnb.cool/yztx_qxun/Docs
tasks/*.md
```

Feishu task messages should stay short. Users do not need to provide `项目` or `类型`; Hermes infers the default project from the Feishu/Hermes deployment context and infers task type from the request text. A normal task can be:

```text
新增任务
分配给：jerry
需求：把 html 的标题从 千寻求职者端 改成 千寻求职
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

If previews should be hosted on an Nginx server, configure only deploy metadata. Do not put server passwords in this config; SSH should use the user's key/agent or a key path:

```bash
python3 scripts/configure_preview.py \
  --provider nginx \
  --base-url http://43.136.77.201 \
  --prefix hermes-previews \
  --remote-host 43.136.77.201 \
  --remote-user ubuntu \
  --remote-root /var/www/html
```

## Start Automatic Worker

When the user says `Hermes worker start` or `启动 Hermes 自动 worker`:

1. Confirm the worker has been initialized.
2. Prefer a Codex App automation over a background LaunchAgent. The automation should run in the current thread every 2 minutes and only do claim/review:

1. Pulls the Docs queue repository.
2. Finds one `tasks/*.md` with `status: open` and `assignee: <worker_id>`.
3. Claims it by committing `status: claimed`, `claimed_by`, and `claimed_at`.
4. Displays the task id, requirement, project/type, and Docs path to the user.
5. Stops and asks whether the user agrees to start modifying local code.

Do not run `worker_tick.py --exec-codex` from the default automation. Code changes, builds, preview uploads, and result submission happen only after the user approves the claimed task.

The claim-only command is:

```bash
python3 scripts/worker_runner.py
```

The legacy macOS LaunchAgent scheduler still exists for fully unattended experiments, but do not use it unless the user explicitly asks for unattended execution:

```bash
python3 scripts/install_scheduler.py --interval 120 --exec-codex --install --load
```

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

For normal Codex App automation, use `scripts/worker_runner.py` only. Use `scripts/worker_tick.py --exec-codex` only after the user explicitly approves execution for a claimed task.

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

## Deploy Preview

Deploy the built `dist`/HTML to the configured Nginx static site:

```bash
python3 scripts/upload_preview.py \
  --manifest ~/.hermes-codex-worker/runs/<task_id>/preview_manifest.json \
  --nginx
```

The Nginx deploy flow:

- copies every file in `dist` to `<remote-root>/<prefix>/<task_id>/<build_id>/`;
- rewrites root-relative `src="/..."` and `href="/..."` in `index.html` to relative paths, so CSS/JS load under the preview subdirectory;
- returns `<base-url>/<prefix>/<task_id>/<build_id>/index.html` as `preview_url`.

For a dry run that shows the SSH/rsync commands without publishing:

```bash
python3 scripts/upload_preview.py \
  --manifest ~/.hermes-codex-worker/runs/<task_id>/preview_manifest.json \
  --nginx \
  --dry-run
```

The older Hermes/COS upload flow is still available when a Hermes preview API exists. It expects Hermes to provide:

- `POST /api/previews/create-upload`: receives file metadata and returns `build_id`, `preview_url`, and per-file presigned `PUT` URLs.
- `POST /api/previews/complete`: marks upload complete and returns the final `preview_url`.

Do not store COS permanent keys in local config. Hermes should issue short-lived, prefix-scoped upload URLs for the current `task_id/build_id`.

While the Hermes preview API is being brought up, `--fallback-cos` can upload directly to Tencent COS with the official `cos-python-sdk-v5` package:

```bash
python3 -m pip install cos-python-sdk-v5
```

Direct COS upload reads these environment variables:

```text
TENCENTCLOUD_SECRET_ID
TENCENTCLOUD_SECRET_KEY
HERMES_COS_BUCKET=xqunbot-1330713835
HERMES_COS_REGION=ap-guangzhou
HERMES_COS_PREFIX=hermes-previews
HERMES_COS_SIGNED_GET_EXPIRES=604800
```

The bucket may remain private. Direct COS upload writes the files and stores a temporary signed GET URL as `preview_url`.

Do not commit these credentials or write them into skill config. Put them in the automation environment, the local shell environment, or the Hermes server environment only.

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
  },
  "preview_provider": "nginx",
  "nginx_preview": {
    "public_base_url": "http://43.136.77.201",
    "prefix": "hermes-previews",
    "remote_host": "43.136.77.201",
    "remote_user": "ubuntu",
    "remote_root": "/var/www/html",
    "ssh_port": "22"
  }
}
```

Do not store CNB tokens or server SSH keys in this config. Git authentication should use the user's existing Git credential helper or `~/.netrc`.
Do not store server passwords or COS permanent keys in this config; use SSH keys/agent for Nginx and Hermes-issued temporary upload URLs for COS.
