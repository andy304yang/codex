# Codex Skills

This repository publishes Codex skills for the QXun workflow.

## Hermes Worker QXun

Install this skill from GitHub:

```text
https://github.com/andy304yang/codex/tree/main/skills/hermes-worker-qxun
```

After installation, restart Codex and initialize the worker:

```text
Hermes worker init <your_worker_id>
```

Then claim tasks with:

```text
领取 Hermes 任务
```

The skill talks to the Hermes Worker API and stores local worker config at:

```text
~/.hermes-codex-worker/config.json
```
