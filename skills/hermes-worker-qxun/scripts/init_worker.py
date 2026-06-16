#!/usr/bin/env python3
"""Initialize a local Codex worker for the QXun Hermes workflow."""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from typing import Any

from hermes_worker_lib import (
    DEFAULT_API,
    DEFAULT_DOCS_REPO_URL,
    DEFAULT_DOCS_TASK_DIR,
    DOCS_CACHE_DIR,
    parse_mapping,
)


CONFIG_DIR = Path.home() / ".hermes-codex-worker"
CONFIG_PATH = CONFIG_DIR / "config.json"


def parse_project(values: list[str]) -> dict[str, str]:
    return {key: str(Path(path).expanduser()) for key, path in parse_mapping(values).items()}


def guess_projects() -> dict[str, str]:
    candidates = {
        "docs": [
            Path.home() / "Documents/app/Docs",
            Path.home() / "Documents/Docs",
        ],
        "qxun": [
            Path.home() / "Documents/app/QXunPortal",
            Path.home() / "Documents/app/QXunPortalH5C",
            Path.home() / "Documents/app",
        ],
    }
    found: dict[str, str] = {}
    for key, paths in candidates.items():
        for path in paths:
            if path.exists():
                found[key] = str(path)
                break
    return found


def load_existing() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        return {}
    try:
        return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Initialize Hermes Worker config.")
    parser.add_argument("--worker", required=True, help="Worker id, e.g. jerry or andy.")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--server-api", default=os.getenv("HERMES_WORKER_API", DEFAULT_API))
    parser.add_argument("--docs-repo", default=os.getenv("HERMES_DOCS_REPO_URL", DEFAULT_DOCS_REPO_URL))
    parser.add_argument("--docs-dir", default=os.getenv("HERMES_DOCS_REPO_DIR", str(DOCS_CACHE_DIR)))
    parser.add_argument("--docs-task-dir", default=os.getenv("HERMES_DOCS_TASK_DIR", DEFAULT_DOCS_TASK_DIR))
    parser.add_argument("--project", action="append", default=[], help="Project mapping, e.g. docs=/path/to/Docs")
    parser.add_argument("--build", action="append", default=[], help="Build command mapping, e.g. qxun='pnpm build'")
    parser.add_argument("--dist", action="append", default=[], help="Dist directory mapping, e.g. qxun=dist")
    parser.add_argument("--guess-local-projects", action="store_true", help="Guess known local project paths.")
    args = parser.parse_args(argv)

    worker_id = args.worker.strip().lower()
    if not worker_id:
        raise SystemExit("worker id is required")

    existing = load_existing()
    local_projects = existing.get("local_projects") if isinstance(existing.get("local_projects"), dict) else {}
    if args.guess_local_projects:
        local_projects = {**guess_projects(), **local_projects}
    local_projects.update(parse_project(args.project))

    project_builds = existing.get("project_builds") if isinstance(existing.get("project_builds"), dict) else {}
    for key, command in parse_mapping(args.build).items():
        project_builds.setdefault(key, {})
        project_builds[key]["build_command"] = command
    for key, dist_dir in parse_mapping(args.dist).items():
        project_builds.setdefault(key, {})
        project_builds[key]["dist_dir"] = dist_dir

    config = {
        "worker_id": worker_id,
        "display_name": args.display_name or existing.get("display_name") or worker_id,
        "server_api": args.server_api.rstrip("/"),
        "docs_queue": {
            "repo_url": args.docs_repo,
            "repo_dir": str(Path(args.docs_dir).expanduser()),
            "task_dir": args.docs_task_dir,
        },
        "cos_upload": existing.get("cos_upload") if isinstance(existing.get("cos_upload"), dict) else {
            "bucket": "xqunbot-1330713835",
            "region": "ap-guangzhou",
            "prefix": "hermes-previews",
        },
        "local_projects": local_projects,
        "project_builds": project_builds,
    }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)

    print(json.dumps({
        "ok": True,
        "config_path": str(CONFIG_PATH),
        "worker_id": worker_id,
        "docs_queue": config["docs_queue"],
        "local_projects": local_projects,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
