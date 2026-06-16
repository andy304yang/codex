#!/usr/bin/env python3
"""Submit a Hermes task result from local Codex."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.request
from pathlib import Path
from typing import Any

from hermes_worker_lib import update_docs_task_status

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
    parser.add_argument("--manifest", default="", help="Preview manifest path from build/upload scripts.")
    args = parser.parse_args(argv)

    config = load_config()
    manifest: dict[str, Any] = {}
    if args.manifest:
        manifest = json.loads(Path(args.manifest).expanduser().read_text(encoding="utf-8"))
    git = manifest.get("git") if isinstance(manifest.get("git"), dict) else {}
    payload = {
        "worker_id": config["worker_id"],
        "task_id": args.task_id,
        "status": args.status,
        "summary": args.summary,
        "preview_url": args.preview_url or str(manifest.get("preview_url") or ""),
        "doc_path": args.doc_path,
        "commit": args.commit or str(git.get("commit") or ""),
        "branch": str(git.get("branch") or ""),
        "preview_manifest": manifest,
    }
    api_result: dict[str, Any] = {}
    if config.get("server_api"):
        try:
            api_result = post_json(f"{config['server_api'].rstrip('/')}/api/results", payload)
        except Exception as exc:
            api_result = {"ok": False, "error": str(exc)}

    docs_result = update_docs_task_status(
        config,
        args.task_id,
        args.status,
        {
            "result_summary": "；".join(args.summary),
            "preview_url": payload["preview_url"],
            "commit": payload["commit"],
            "branch": payload["branch"],
            "completed_by": config["worker_id"],
        },
    )
    print(json.dumps({"ok": True, "api": api_result, "docs": docs_result}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
