#!/usr/bin/env python3
"""Configure local project paths and preview build commands."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hermes_worker_lib import CONFIG_PATH, load_config, parse_mapping, save_config


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Configure Hermes worker local projects.")
    parser.add_argument("--project", action="append", default=[], help="Project mapping, e.g. qxun=/path/to/QXunPortal")
    parser.add_argument("--build", action="append", default=[], help="Build command mapping, e.g. qxun='pnpm build'")
    parser.add_argument("--dist", action="append", default=[], help="Dist directory mapping, e.g. qxun=dist")
    args = parser.parse_args(argv)

    config = load_config()
    local_projects = config.get("local_projects") if isinstance(config.get("local_projects"), dict) else {}
    project_builds = config.get("project_builds") if isinstance(config.get("project_builds"), dict) else {}

    for key, path in parse_mapping(args.project).items():
        local_projects[key] = str(Path(path).expanduser())

    for key, command in parse_mapping(args.build).items():
        project_builds.setdefault(key, {})
        project_builds[key]["build_command"] = command

    for key, dist_dir in parse_mapping(args.dist).items():
        project_builds.setdefault(key, {})
        project_builds[key]["dist_dir"] = dist_dir

    config["local_projects"] = local_projects
    config["project_builds"] = project_builds
    save_config(config)

    print(json.dumps({
        "ok": True,
        "config_path": str(CONFIG_PATH),
        "local_projects": local_projects,
        "project_builds": project_builds,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
