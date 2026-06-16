#!/usr/bin/env python3
"""Shared helpers for Hermes Codex worker scripts."""

from __future__ import annotations

import json
import mimetypes
import os
import shlex
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


DEFAULT_API = "http://81.71.29.84:8787"
DEFAULT_DOCS_REPO_URL = "https://cnb.cool/yztx_qxun/Docs"
DEFAULT_DOCS_TASK_DIR = "tasks"
CONFIG_DIR = Path.home() / ".hermes-codex-worker"
CONFIG_PATH = CONFIG_DIR / "config.json"
TASK_DIR = CONFIG_DIR / "tasks"
RUNS_DIR = CONFIG_DIR / "runs"
LOG_DIR = CONFIG_DIR / "logs"
DOCS_CACHE_DIR = CONFIG_DIR / "docs-repo"


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


def docs_queue_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("docs_queue")
    docs_queue = raw if isinstance(raw, dict) else {}
    return {
        "repo_url": str(docs_queue.get("repo_url") or os.getenv("HERMES_DOCS_REPO_URL") or DEFAULT_DOCS_REPO_URL),
        "repo_dir": str(docs_queue.get("repo_dir") or os.getenv("HERMES_DOCS_REPO_DIR") or DOCS_CACHE_DIR),
        "task_dir": str(docs_queue.get("task_dir") or os.getenv("HERMES_DOCS_TASK_DIR") or DEFAULT_DOCS_TASK_DIR),
    }


def run_git(repo_dir: Path, args: list[str], *, check: bool = True) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(
        ["git", *args],
        cwd=str(repo_dir),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )
    if check and result.returncode != 0:
        details = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"git {' '.join(args)} failed: {details}")
    return result


def ensure_docs_repo(config: dict[str, Any]) -> Path:
    queue = docs_queue_config(config)
    repo_url = queue["repo_url"]
    repo_dir = Path(queue["repo_dir"]).expanduser()
    repo_dir.parent.mkdir(parents=True, exist_ok=True)
    if not (repo_dir / ".git").exists():
        subprocess.run(
            ["git", "clone", repo_url, str(repo_dir)],
            text=True,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=True,
        )
    else:
        run_git(repo_dir, ["pull", "--ff-only"])
    ensure_docs_git_identity(repo_dir, config)
    return repo_dir


def ensure_docs_git_identity(repo_dir: Path, config: dict[str, Any]) -> None:
    name = run_git(repo_dir, ["config", "--get", "user.name"], check=False).stdout.strip()
    email = run_git(repo_dir, ["config", "--get", "user.email"], check=False).stdout.strip()
    worker_id = str(config.get("worker_id") or "hermes-worker")
    if not name:
        run_git(repo_dir, ["config", "user.name", str(config.get("display_name") or worker_id)], check=False)
    if not email:
        run_git(repo_dir, ["config", "user.email", f"{worker_id}@hermes.local"], check=False)


def parse_frontmatter(text: str) -> tuple[dict[str, Any], str]:
    if not text.startswith("---\n"):
        return {}, text
    end = text.find("\n---\n", 4)
    if end == -1:
        return {}, text
    raw = text[4:end]
    body = text[end + 5 :]
    data: dict[str, Any] = {}
    for line in raw.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#") or ":" not in stripped:
            continue
        key, value = stripped.split(":", 1)
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {"'", '"'}:
            value = value[1:-1]
        elif value.lower() == "true":
            data[key.strip()] = True
            continue
        elif value.lower() == "false":
            data[key.strip()] = False
            continue
        data[key.strip()] = value
    return data, body


def render_frontmatter(data: dict[str, Any], body: str) -> str:
    lines = ["---"]
    for key, value in data.items():
        if isinstance(value, bool):
            rendered = "true" if value else "false"
        elif isinstance(value, (int, float)):
            rendered = str(value)
        else:
            rendered = json.dumps(str(value), ensure_ascii=False)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines) + "\n" + body.lstrip("\n")


def docs_task_to_task(doc_path: Path, repo_dir: Path, metadata: dict[str, Any], body: str) -> dict[str, Any]:
    task: dict[str, Any] = dict(metadata)
    task["id"] = str(metadata.get("id") or doc_path.stem)
    task["title"] = str(metadata.get("title") or first_markdown_heading(body) or task["id"])
    task["body"] = body.strip()
    task["doc_path"] = doc_path.relative_to(repo_dir).as_posix()
    task["docs_queue"] = {
        "repo_dir": str(repo_dir),
        "doc_path": doc_path.relative_to(repo_dir).as_posix(),
    }
    return task


def first_markdown_heading(body: str) -> str:
    for line in body.splitlines():
        stripped = line.strip()
        if stripped.startswith("#"):
            return stripped.lstrip("#").strip()
    return ""


def iter_docs_tasks(config: dict[str, Any]) -> list[tuple[Path, dict[str, Any], str]]:
    repo_dir = ensure_docs_repo(config)
    task_root = repo_dir / docs_queue_config(config)["task_dir"]
    if not task_root.exists():
        return []
    tasks: list[tuple[Path, dict[str, Any], str]] = []
    for path in sorted(task_root.glob("*.md")):
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        tasks.append((path, metadata, body))
    return tasks


def claim_docs_task(config: dict[str, Any], include_unassigned: bool = False) -> dict[str, Any]:
    worker_id = str(config.get("worker_id") or "").strip()
    if not worker_id:
        raise SystemExit("Config is missing worker_id")

    repo_dir = ensure_docs_repo(config)
    run_git(repo_dir, ["status", "--short"], check=True)
    task_root = repo_dir / docs_queue_config(config)["task_dir"]
    if not task_root.exists():
        return {"ok": True, "has_task": False, "source": "docs"}

    for path in sorted(task_root.glob("*.md")):
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        status = str(metadata.get("status") or "open").strip().lower()
        assignee = str(metadata.get("assignee") or metadata.get("assigned_to") or "").strip().lower()
        if status != "open":
            continue
        if assignee and assignee != worker_id.lower():
            continue
        if not assignee and not include_unassigned:
            continue

        metadata["status"] = "claimed"
        metadata["assignee"] = assignee or worker_id
        metadata["claimed_by"] = worker_id
        metadata["claimed_at"] = datetime.now(timezone.utc).isoformat()
        path.write_text(render_frontmatter(metadata, body), encoding="utf-8")
        run_git(repo_dir, ["add", path.relative_to(repo_dir).as_posix()])
        task = docs_task_to_task(path, repo_dir, metadata, body)
        message = f"docs: claim Hermes task {task['id']} by {worker_id}"
        commit = run_git(repo_dir, ["commit", "-m", message], check=False)
        if commit.returncode != 0:
            run_git(repo_dir, ["reset", "--hard", "HEAD"], check=False)
            continue
        push = run_git(repo_dir, ["push"], check=False)
        if push.returncode == 0:
            task["claim_commit"] = git_value(repo_dir, ["rev-parse", "--short", "HEAD"])
            return {"ok": True, "has_task": True, "source": "docs", "task": task}
        run_git(repo_dir, ["reset", "--hard", "HEAD~1"], check=False)
        run_git(repo_dir, ["pull", "--ff-only"], check=False)

    return {"ok": True, "has_task": False, "source": "docs"}


def update_docs_task_status(
    config: dict[str, Any],
    task_id_value: str,
    status: str,
    updates: dict[str, Any] | None = None,
) -> dict[str, Any]:
    repo_dir = ensure_docs_repo(config)
    task_root = repo_dir / docs_queue_config(config)["task_dir"]
    if not task_root.exists():
        return {"ok": False, "reason": "task dir missing"}
    candidates = sorted(task_root.glob(f"{task_id_value}.md")) + sorted(task_root.glob("*.md"))
    seen: set[Path] = set()
    for path in candidates:
        if path in seen or not path.exists():
            continue
        seen.add(path)
        metadata, body = parse_frontmatter(path.read_text(encoding="utf-8"))
        current_id = str(metadata.get("id") or path.stem)
        if current_id != task_id_value and path.stem != task_id_value:
            continue
        metadata["status"] = status
        metadata["updated_at"] = datetime.now(timezone.utc).isoformat()
        if updates:
            for key, value in updates.items():
                if value not in ("", None, [], {}):
                    metadata[key] = value
        path.write_text(render_frontmatter(metadata, body), encoding="utf-8")
        run_git(repo_dir, ["add", path.relative_to(repo_dir).as_posix()])
        commit = run_git(repo_dir, ["commit", "-m", f"docs: mark Hermes task {task_id_value} {status}"], check=False)
        if commit.returncode != 0:
            return {"ok": True, "changed": False, "doc_path": path.relative_to(repo_dir).as_posix()}
        push = run_git(repo_dir, ["push"], check=False)
        if push.returncode != 0:
            raise RuntimeError((push.stderr or push.stdout).strip())
        return {"ok": True, "changed": True, "doc_path": path.relative_to(repo_dir).as_posix()}
    return {"ok": False, "reason": "task not found"}


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
    has_local_build = bool(context.build_command)
    if has_local_build:
        workflow = f"""1. Inspect the task and the project.
2. Implement the requested change in a focused branch or local working tree.
3. Run the relevant checks for the project.
4. Build a preview with:

```bash
python3 {shell_join([str(build_script), "--task-file", str(task_run_dir(task) / "task.json")])}
```

5. Deploy the preview artifact to the configured Nginx preview site with:

```bash
python3 {shell_join([str(upload_script), "--manifest", str(task_run_dir(task) / "preview_manifest.json"), "--nginx"])}
```

6. Submit the final Hermes result with `{submit_script}`. Include the preview_url if upload succeeds."""
    else:
        workflow = f"""1. Inspect the task and the Docs repository.
2. Make the requested document/product change in the Docs repository if the task asks for a document update.
3. Commit and push any Docs repository changes.
4. Submit the final Hermes result with:

```bash
python3 {shell_join([str(submit_script), "--task-id", task_id(task), "--status", "done", "--summary", "completed"])}
```

If the task needs a code repository that is not configured locally, submit status `blocked` and summarize the missing project mapping."""
    return f"""You are the local Hermes Codex worker `{worker_id}`.

Complete the Hermes task below in the local project.

Task:
```json
{task_json}
```

Project:
- key: {context.project_key}
- path: {context.project_path}
- build command: {context.build_command or "(none; Docs-only task)"}
- dist dir: {context.dist_dir}

Workflow:
{workflow}

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
