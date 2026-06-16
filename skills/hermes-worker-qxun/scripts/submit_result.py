#!/usr/bin/env python3
"""Submit a Hermes task result from local Codex."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any


CONFIG_PATH = Path.home() / ".hermes-codex-worker" / "config.json"


def load_config() -> dict[str, Any]:
    if not CONFIG_PATH.exists():
        raise SystemExit(f"Missing config: {CONFIG_PATH}")
    return json.loads(CONFIG_PATH.read_text(encoding="utf-8"))


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
    parser = argparse.ArgumentParser(description="Submit Hermes task result.")
    parser.add_argument("--task-id", required=True)
    parser.add_argument("--status", default="done")
    parser.add_argument("--summary", action="append", default=[])
    parser.add_argument("--preview-url", default="")
    parser.add_argument("--doc-path", default="")
    parser.add_argument("--commit", default="")
    args = parser.parse_args(argv)

    config = load_config()
    payload = {
        "worker_id": config["worker_id"],
        "task_id": args.task_id,
        "status": args.status,
        "summary": args.summary,
        "preview_url": args.preview_url,
        "doc_path": args.doc_path,
        "commit": args.commit,
    }
    result = post_json(f"{config['server_api'].rstrip('/')}/api/results", payload)
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
