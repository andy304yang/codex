#!/usr/bin/env python3
"""Run one automatic Hermes worker tick.

This script is timer-friendly: heartbeat, claim one task, prepare the Codex
task prompt, and optionally invoke `codex exec` in the target project.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import shutil
import socket
import subprocess
import sys
import urllib.request
from pathlib import Path
from typing import Any

from hermes_worker_lib import (
    CONFIG_DIR,
    LOG_DIR,
    ProjectContext,
    claim_docs_task,
    docs_queue_config,
    ensure_docs_repo,
    load_config,
    render_codex_task_prompt,
    resolve_project_context,
    task_run_dir,
    write_json,
)


def post_json(url: str, payload: dict[str, Any], timeout: int = 30) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def acquire_lock() -> Any:
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    lock_file = (CONFIG_DIR / "worker.lock").open("w")
    try:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        print(json.dumps({"ok": True, "skipped": True, "reason": "worker already running"}, ensure_ascii=False))
        raise SystemExit(0)
    return lock_file


def claim_task(config: dict[str, Any], include_unassigned: bool) -> dict[str, Any]:
    server_api = str(config["server_api"]).rstrip("/")
    worker_id = config["worker_id"]
    heartbeat = {
        "worker_id": worker_id,
        "hostname": socket.gethostname(),
        "projects": config.get("local_projects", {}),
        "codex": {"skill": "hermes-worker-qxun", "mode": "automatic"},
    }
    post_json(f"{server_api}/api/heartbeat", heartbeat)
    return post_json(
        f"{server_api}/api/tasks/claim",
        {"worker_id": worker_id, "include_unassigned": bool(include_unassigned)},
    )


def docs_context(config: dict[str, Any]) -> ProjectContext:
    repo_dir = ensure_docs_repo(config)
    queue = docs_queue_config(config)
    return ProjectContext(
        project_key="docs",
        project_path=repo_dir,
        build_command="",
        dist_dir=queue["task_dir"],
    )


def run_codex(
    codex_bin: str,
    project_path: Path,
    prompt: str,
    log_path: Path,
    sandbox: str,
    model: str,
) -> int:
    command = [
        codex_bin,
        "exec",
        "--cd",
        str(project_path),
        "--add-dir",
        str(CONFIG_DIR),
        "--sandbox",
        sandbox,
        "--ask-for-approval",
        "never",
    ]
    if model:
        command.extend(["--model", model])
    command.append("-")

    result = subprocess.run(
        command,
        input=prompt,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    log_path.parent.mkdir(parents=True, exist_ok=True)
    log_path.write_text(result.stdout, encoding="utf-8")
    return result.returncode


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Run one automatic Hermes worker tick.")
    parser.add_argument("--include-unassigned", action="store_true")
    parser.add_argument("--source", choices=["docs", "api"], default="docs")
    parser.add_argument("--exec-codex", action="store_true", help="Run codex exec for the claimed task.")
    parser.add_argument("--codex-bin", default=shutil.which("codex") or "codex")
    parser.add_argument("--sandbox", default="workspace-write", choices=["read-only", "workspace-write", "danger-full-access"])
    parser.add_argument("--model", default="")
    args = parser.parse_args(argv)

    lock_file = acquire_lock()
    _ = lock_file

    config = load_config()
    scripts_dir = Path(__file__).resolve().parent
    if args.source == "docs":
        result = claim_docs_task(config, args.include_unassigned)
    else:
        result = claim_task(config, args.include_unassigned)
    if not result.get("has_task"):
        print(json.dumps({"ok": True, "has_task": False}, ensure_ascii=False, indent=2))
        return 0

    task = result["task"]
    try:
        context = resolve_project_context(task, config)
    except SystemExit:
        context = docs_context(config)
    run_dir = task_run_dir(task)
    task_file = run_dir / "task.json"
    prompt_file = run_dir / "codex_prompt.md"
    write_json(task_file, task)
    prompt = render_codex_task_prompt(task, config, context, scripts_dir)
    prompt_file.parent.mkdir(parents=True, exist_ok=True)
    prompt_file.write_text(prompt, encoding="utf-8")

    output = {
        "ok": True,
        "has_task": True,
        "task_id": task.get("id") or task.get("task_id"),
        "task_file": str(task_file),
        "prompt_file": str(prompt_file),
        "project_key": context.project_key,
        "project_path": str(context.project_path),
    }

    if args.exec_codex:
        log_path = LOG_DIR / f"{output['task_id']}.codex.log"
        code = run_codex(args.codex_bin, context.project_path, prompt, log_path, args.sandbox, args.model)
        output["codex_exit_code"] = code
        output["codex_log"] = str(log_path)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return code

    print(json.dumps(output, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
