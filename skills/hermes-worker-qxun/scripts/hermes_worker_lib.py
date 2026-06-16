#!/usr/bin/env python3
"""Shared helpers for Hermes Codex worker scripts."""

from __future__ import annotations

import json
import mimetypes
import os
import shlex
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


DEFAULT_API = "http://81.71.29.84:8787"
CONFIG_DIR = Path.home() / ".hermes-codex-worker"
CONFIG_PATH = CONFIG_DIR / "config.json"
TASK_DIR = CONFIG_DIR / "tasks"
RUNS_DIR = CONFIG_DIR / "runs"
LOG_DIR = CONFIG_DIR / "logs"


@dataclass(frozen=True)
class ProjectContext:
    project_key: str
    project_path: Path
    build_command: str
    dist_dir: str


@dataclass(frozen=True)
class DistFile:
    absolute_path: Path
    relative_path: str
    content_type: str
    size: int


def load_config(path: Path = CONFIG_PATH) -> dict[str, Any]:
    if not path.exists():
        raise SystemExit(f"Missing config: {path}. Run Hermes worker init first.")
    return json.loads(path.read_text(encoding="utf-8"))


def save_config(config: dict[str, Any], path: Path = CONFIG_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    path.chmod(0o600)


def parse_mapping(values: Iterable[str]) -> dict[str, str]:
    parsed: dict[str, str] = {}
    for value in values:
        if "=" not in value:
            raise SystemExit(f"Expected name=value, got: {value}")
        key, raw = value.split("=", 1)
        key = key.strip()
        raw = raw.strip()
        if not key or not raw:
            raise SystemExit(f"Expected non-empty name=value, got: {value}")
        parsed[key] = raw
    return parsed


def task_id(task: dict[str, Any]) -> str:
    value = task.get("id") or task.get("task_id")
    if not value:
        raise SystemExit("Task is missing id/task_id")
    return str(value)


def task_project_key(task: dict[str, Any]) -> str:
    for key in ("project", "project_key", "repo", "repository"):
        value = task.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    metadata = task.get("metadata")
    if isinstance(metadata, dict):
        for key in ("project", "project_key", "repo", "repository"):
            value = metadata.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    return ""


def resolve_project_context(task: dict[str, Any], config: dict[str, Any]) -> ProjectContext:
    projects = config.get("local_projects")
    if not isinstance(projects, dict) or not projects:
        raise SystemExit("No local_projects configured. Run init with --project name=/path.")

    requested_key = task_project_key(task)
    if not requested_key and len(projects) == 1:
        requested_key = next(iter(projects))
    if not requested_key:
        available = ", ".join(sorted(projects))
        raise SystemExit(f"Task does not specify project. Available local_projects: {available}")
    if requested_key not in projects:
        available = ", ".join(sorted(projects))
        raise SystemExit(f"Project {requested_key!r} is not configured. Available: {available}")

    project_path = Path(str(projects[requested_key])).expanduser()
    if not project_path.exists():
        raise SystemExit(f"Configured project path does not exist: {project_path}")

    project_builds = config.get("project_builds")
    build_config = project_builds.get(requested_key, {}) if isinstance(project_builds, dict) else {}
    if not isinstance(build_config, dict):
        build_config = {}
    build_command = str(build_config.get("build_command") or "npm run build")
    dist_dir = str(build_config.get("dist_dir") or "dist")

    return ProjectContext(
        project_key=requested_key,
        project_path=project_path,
        build_command=build_command,
        dist_dir=dist_dir,
    )


def task_run_dir(task: dict[str, Any]) -> Path:
    safe_id = "".join(ch if ch.isalnum() or ch in ("-", "_", ".") else "_" for ch in task_id(task))
    return RUNS_DIR / safe_id


def content_type_for(path: str | Path) -> str:
    suffix = Path(path).suffix.lower()
    if suffix in {".html", ".htm"}:
        return "text/html; charset=utf-8"
    if suffix == ".css":
        return "text/css; charset=utf-8"
    if suffix == ".js":
        return "application/javascript"
    if suffix == ".mjs":
        return "application/javascript"
    if suffix == ".json":
        return "application/json; charset=utf-8"
    if suffix == ".svg":
        return "image/svg+xml"
    guessed, _ = mimetypes.guess_type(str(path))
    return guessed or "application/octet-stream"


def list_dist_files(dist_path: Path) -> list[DistFile]:
    dist_path = dist_path.expanduser().resolve()
    if not dist_path.exists() or not dist_path.is_dir():
        raise SystemExit(f"Dist directory does not exist: {dist_path}")
    files: list[DistFile] = []
    for absolute in sorted(path for path in dist_path.rglob("*") if path.is_file()):
        relative = absolute.relative_to(dist_path).as_posix()
        files.append(DistFile(
            absolute_path=absolute,
            relative_path=relative,
            content_type=content_type_for(relative),
            size=absolute.stat().st_size,
        ))
    if not files:
        raise SystemExit(f"Dist directory is empty: {dist_path}")
    return files


def git_value(project_path: Path, args: list[str]) -> str:
    try:
        result = subprocess.run(
            ["git", *args],
            cwd=str(project_path),
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    except FileNotFoundError:
        return ""
    if result.returncode != 0:
        return ""
    return result.stdout.strip()


def project_git_metadata(project_path: Path) -> dict[str, str]:
    return {
        "branch": git_value(project_path, ["rev-parse", "--abbrev-ref", "HEAD"]),
        "commit": git_value(project_path, ["rev-parse", "--short", "HEAD"]),
        "status": git_value(project_path, ["status", "--short"]),
    }


def shell_join(command: list[str]) -> str:
    return " ".join(shlex.quote(part) for part in command)


def render_codex_task_prompt(
    task: dict[str, Any],
    config: dict[str, Any],
    context: ProjectContext,
    scripts_dir: Path,
) -> str:
    task_json = json.dumps(task, ensure_ascii=False, indent=2)
    worker_id = config.get("worker_id", "")
    build_script = scripts_dir / "build_preview.py"
    upload_script = scripts_dir / "upload_preview.py"
    submit_script = scripts_dir / "submit_result.py"
    return f"""You are the local Hermes Codex worker `{worker_id}`.

Complete the Hermes task below in the local project.

Task:
```json
{task_json}
```

Project:
- key: {context.project_key}
- path: {context.project_path}
- build command: {context.build_command}
- dist dir: {context.dist_dir}

Workflow:
1. Inspect the task and the project.
2. Implement the requested change in a focused branch or local working tree.
3. Run the relevant checks for the project.
4. Build a preview with:

```bash
python3 {shell_join([str(build_script), "--task-file", str(task_run_dir(task) / "task.json")])}
```

5. Upload the preview artifact with:

```bash
python3 {shell_join([str(upload_script), "--manifest", str(task_run_dir(task) / "preview_manifest.json")])}
```

6. Submit the final Hermes result with `{submit_script}`. Include the preview_url if upload succeeds.

Keep the final response concise and include changed files, checks run, commit/branch if available, and the preview URL.
"""


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def env_with_overrides(overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = os.environ.copy()
    if overrides:
        env.update(overrides)
    return env
