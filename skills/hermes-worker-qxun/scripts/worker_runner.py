#!/usr/bin/env python3
"""Claim one Hermes task for this local Codex worker."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

from hermes_worker_lib import claim_docs_task, load_config

CONFIG_DIR = Path.home() / ".hermes-codex-worker"
CONFIG_PATH = CONFIG_DIR / "config.json"
TASK_DIR = CONFIG_DIR / "tasks"
CURRENT_TASK = TASK_DIR / "current_task.json"


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=20) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Claim one Hermes task.")
    parser.add_argument("--include-unassigned", action="store_true")
    parser.add_argument("--source", choices=["docs", "api"], default="docs")
    args = parser.parse_args(argv)

    config = load_config()
    if args.source == "docs":
        result = claim_docs_task(config, include_unassigned=bool(args.include_unassigned))
    else:
        server_api = config["server_api"].rstrip("/")
        result = post_json(
            f"{server_api}/api/tasks/claim",
            {"worker_id": config["worker_id"], "include_unassigned": bool(args.include_unassigned)},
        )
    TASK_DIR.mkdir(parents=True, exist_ok=True)
    if result.get("has_task"):
        CURRENT_TASK.write_text(json.dumps(result["task"], ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(json.dumps({
            "ok": True,
            "has_task": True,
            "task_id": result["task"].get("id"),
            "task_file": str(CURRENT_TASK),
            "task": result["task"],
        }, ensure_ascii=False, indent=2))
    else:
        print(json.dumps({"ok": True, "has_task": False}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
