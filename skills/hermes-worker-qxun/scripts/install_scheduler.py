#!/usr/bin/env python3
"""Install a macOS LaunchAgent for automatic Hermes Codex worker ticks."""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import shutil
import subprocess
import sys
from pathlib import Path

from hermes_worker_lib import CONFIG_DIR, LOG_DIR, load_config


LABEL = "com.qxun.hermes-codex-worker"


def plist_payload(
    python_bin: str,
    worker_tick: Path,
    interval_seconds: int,
    exec_codex: bool,
    codex_bin: str,
    sandbox: str,
) -> dict:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    args = [python_bin, str(worker_tick)]
    if exec_codex:
        args.append("--exec-codex")
    args.extend(["--codex-bin", codex_bin, "--sandbox", sandbox])
    return {
        "Label": LABEL,
        "ProgramArguments": args,
        "StartInterval": interval_seconds,
        "RunAtLoad": True,
        "StandardOutPath": str(LOG_DIR / "scheduler.out.log"),
        "StandardErrorPath": str(LOG_DIR / "scheduler.err.log"),
        "WorkingDirectory": str(Path.home()),
        "EnvironmentVariables": {
            "PATH": os.environ.get("PATH", ""),
        },
    }


def write_plist(payload: dict, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(plistlib.dumps(payload, sort_keys=False))


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Install Hermes worker scheduler.")
    parser.add_argument("--interval", type=int, default=120, help="Seconds between worker ticks.")
    parser.add_argument("--exec-codex", action="store_true", help="Let each claimed task run codex exec.")
    parser.add_argument("--codex-bin", default=shutil.which("codex") or "codex")
    parser.add_argument("--sandbox", default="danger-full-access", choices=["read-only", "workspace-write", "danger-full-access"])
    parser.add_argument("--install", action="store_true", help="Write LaunchAgent plist.")
    parser.add_argument("--load", action="store_true", help="Load/start the LaunchAgent after writing.")
    parser.add_argument("--uninstall", action="store_true", help="Unload and remove the LaunchAgent.")
    args = parser.parse_args(argv)

    plist_path = Path.home() / "Library" / "LaunchAgents" / f"{LABEL}.plist"
    worker_tick = Path(__file__).resolve().parent / "worker_tick.py"

    if args.uninstall:
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        if plist_path.exists():
            plist_path.unlink()
        print(json.dumps({"ok": True, "removed": str(plist_path)}, ensure_ascii=False, indent=2))
        return 0

    load_config()
    payload = plist_payload(
        python_bin=sys.executable,
        worker_tick=worker_tick,
        interval_seconds=args.interval,
        exec_codex=args.exec_codex,
        codex_bin=args.codex_bin,
        sandbox=args.sandbox,
    )

    if not args.install:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "plist_path": str(plist_path),
            "plist": payload,
        }, ensure_ascii=False, indent=2))
        return 0

    write_plist(payload, plist_path)
    loaded = False
    if args.load:
        subprocess.run(["launchctl", "unload", str(plist_path)], check=False)
        result = subprocess.run(["launchctl", "load", "-w", str(plist_path)], check=False)
        loaded = result.returncode == 0

    print(json.dumps({
        "ok": True,
        "plist_path": str(plist_path),
        "loaded": loaded,
        "interval_seconds": args.interval,
        "exec_codex": args.exec_codex,
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
