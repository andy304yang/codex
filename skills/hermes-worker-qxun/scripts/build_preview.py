#!/usr/bin/env python3
"""Build a local frontend preview artifact for a Hermes task."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from hermes_worker_lib import (
    load_config,
    list_dist_files,
    project_git_metadata,
    read_json,
    resolve_project_context,
    task_run_dir,
    write_json,
)


def load_task(args: argparse.Namespace) -> dict[str, Any]:
    if args.task_file:
        return read_json(Path(args.task_file).expanduser())
    if args.task_json:
        return json.loads(args.task_json)
    raise SystemExit("Provide --task-file or --task-json")


def run_build(project_path: Path, build_command: str) -> dict[str, Any]:
    result = subprocess.run(
        build_command,
        cwd=str(project_path),
        shell=True,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        check=False,
    )
    return {
        "command": build_command,
        "returncode": result.returncode,
        "output": result.stdout,
    }


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Build a Hermes preview artifact.")
    parser.add_argument("--task-file", default="")
    parser.add_argument("--task-json", default="")
    parser.add_argument("--project", default="", help="Override project key.")
    parser.add_argument("--build-command", default="", help="Override build command.")
    parser.add_argument("--dist-dir", default="", help="Override dist directory.")
    parser.add_argument("--no-build", action="store_true", help="Skip running the build command and only inspect dist.")
    args = parser.parse_args(argv)

    config = load_config()
    task = load_task(args)
    if args.project:
        task = {**task, "project": args.project}

    context = resolve_project_context(task, config)
    build_command = args.build_command or context.build_command
    dist_dir = args.dist_dir or context.dist_dir
    dist_path = (context.project_path / dist_dir).resolve()

    build = {"command": build_command, "returncode": 0, "output": ""}
    if not args.no_build:
        build = run_build(context.project_path, build_command)
        if build["returncode"] != 0:
            print(json.dumps({
                "ok": False,
                "stage": "build",
                "project_path": str(context.project_path),
                "build": build,
            }, ensure_ascii=False, indent=2))
            return int(build["returncode"]) or 1

    files = list_dist_files(dist_path)
    run_dir = task_run_dir(task)
    task_file = run_dir / "task.json"
    manifest_path = run_dir / "preview_manifest.json"
    write_json(task_file, task)

    git = project_git_metadata(context.project_path)
    manifest = {
        "task_id": task.get("id") or task.get("task_id"),
        "worker_id": config.get("worker_id"),
        "server_api": config.get("server_api"),
        "project": context.project_key,
        "project_path": str(context.project_path),
        "build_command": build_command,
        "dist_dir": dist_dir,
        "dist_path": str(dist_path),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "git": git,
        "build": {
            "command": build["command"],
            "returncode": build["returncode"],
        },
        "files": [
            {
                "path": item.relative_path,
                "content_type": item.content_type,
                "size": item.size,
            }
            for item in files
        ],
    }
    write_json(manifest_path, manifest)

    print(json.dumps({
        "ok": True,
        "task_file": str(task_file),
        "manifest": str(manifest_path),
        "dist_path": str(dist_path),
        "file_count": len(files),
        "git": git,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
