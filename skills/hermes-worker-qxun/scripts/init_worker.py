#!/usr/bin/env python3
"""Initialize a local Codex worker for the QXun Hermes workflow."""

from __future__ import annotations

import argparse
import json
import os
import socket
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hermes_worker_lib import parse_mapping


DEFAULT_API = "http://81.71.29.84:8787"
CONFIG_DIR = Path.home() / ".hermes-codex-worker"
CONFIG_PATH = CONFIG_DIR / "config.json"


def normalize_worker_id(value: str) -> str:
    return value.strip().lower()


def prompt_worker_id() -> str:
    print("请关联你的飞书昵称，用于 Hermes 将 Feishu 任务分配给这台本地 Codex worker。")
    return normalize_worker_id(input("飞书昵称: "))


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return json.loads(resp.read().decode("utf-8"))


def parse_project(values: list[str]) -> dict[str, str]:
    return {key: str(Path(path).expanduser()) for key, path in parse_mapping(values).items()}


def infer_qxun_project(cwd: Path | None = None) -> tuple[dict[str, str], dict[str, dict[str, str]]]:
    project_path = (cwd or Path.cwd()).resolve()
    package_json = project_path / "package.json"
    candidate_app = project_path / "apps" / "h5-candidate"
    if not package_json.exists() or not candidate_app.exists():
        return {}, {}
    try:
        package = json.loads(package_json.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}, {}
    if package.get("name") != "qianxun-monorepo":
        return {}, {}
    return (
        {"qxun": str(project_path)},
        {"qxun": {
            "build_command": "pnpm build:h5:candidate",
            "dist_dir": "apps/h5-candidate/dist",
        }},
    )


def guess_projects() -> dict[str, str]:
    candidates = {
        "qxun": [
            Path.home() / "Documents/app/QXunPortal",
            Path.home() / "Documents/app/QXunPortalH5C",
            Path.home() / "QXunPortal",
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
    parser.add_argument("--worker", default="", help="Feishu nickname / worker id, e.g. jerry or andy.")
    parser.add_argument("--feishu-nickname", default="", help="Alias for --worker.")
    parser.add_argument("--display-name", default="")
    parser.add_argument("--server-api", default=os.getenv("HERMES_WORKER_API", DEFAULT_API))
    parser.add_argument("--project", action="append", default=[], help="Project mapping, e.g. docs=/path/to/Docs")
    parser.add_argument("--build", action="append", default=[], help="Build command mapping, e.g. qxun='pnpm build'")
    parser.add_argument("--dist", action="append", default=[], help="Dist directory mapping, e.g. qxun=dist")
    parser.add_argument("--no-guess", action="store_true", help="Do not guess local project paths.")
    args = parser.parse_args(argv)

    worker_id = normalize_worker_id(args.worker or args.feishu_nickname)
    if not worker_id and sys.stdin.isatty():
        worker_id = prompt_worker_id()
    if not worker_id:
        raise SystemExit("请关联你的飞书昵称：重新运行并传入 --worker <飞书昵称>，或在交互式终端中按提示输入。")

    existing = load_existing()
    inferred_projects: dict[str, str] = {}
    inferred_builds: dict[str, dict[str, str]] = {}
    if not args.no_guess:
        inferred_projects, inferred_builds = infer_qxun_project()

    local_projects = existing.get("local_projects") if isinstance(existing.get("local_projects"), dict) else {}
    if not args.no_guess:
        local_projects = {**guess_projects(), **inferred_projects, **local_projects}
    local_projects.update(parse_project(args.project))

    project_builds = existing.get("project_builds") if isinstance(existing.get("project_builds"), dict) else {}
    project_builds = {**inferred_builds, **project_builds}
    for key, command in parse_mapping(args.build).items():
        project_builds.setdefault(key, {})
        project_builds[key]["build_command"] = command
    for key, dist_dir in parse_mapping(args.dist).items():
        project_builds.setdefault(key, {})
        project_builds[key]["dist_dir"] = dist_dir

    config = {
        "worker_id": worker_id,
        "display_name": args.display_name or worker_id,
        "server_api": args.server_api.rstrip("/"),
        "local_projects": local_projects,
        "project_builds": project_builds,
    }

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_PATH.write_text(json.dumps(config, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    CONFIG_PATH.chmod(0o600)

    payload = {
        "worker_id": worker_id,
        "display_name": config["display_name"],
        "hostname": socket.gethostname(),
        "projects": local_projects,
    }

    init_result = post_json(f"{config['server_api']}/api/workers/init", payload)
    heartbeat_result = post_json(f"{config['server_api']}/api/heartbeat", payload)
    print(json.dumps({
        "ok": True,
        "config_path": str(CONFIG_PATH),
        "worker": init_result.get("worker"),
        "heartbeat": heartbeat_result.get("heartbeat"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
