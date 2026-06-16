#!/usr/bin/env python3
"""Upload a built preview artifact using Hermes-issued presigned COS URLs."""

from __future__ import annotations

import argparse
import json
import sys
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hermes_worker_lib import load_config, read_json, write_json


def post_json(url: str, payload: dict[str, Any]) -> dict[str, Any]:
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode("utf-8"))


def put_file(url: str, path: Path, content_type: str, headers: dict[str, str] | None = None) -> None:
    merged_headers = {"Content-Type": content_type}
    if headers:
        merged_headers.update(headers)
    req = urllib.request.Request(
        url,
        data=path.read_bytes(),
        headers=merged_headers,
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"Upload failed for {path}: HTTP {resp.status}")


def upload_to_local_dir(manifest: dict[str, Any], output_dir: Path) -> str:
    dist_path = Path(manifest["dist_path"])
    task_id = str(manifest["task_id"])
    build_id = manifest.get("build_id") or "local"
    target = output_dir / task_id / build_id
    for file_info in manifest["files"]:
        relative = Path(file_info["path"])
        destination = target / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes((dist_path / relative).read_bytes())
    return target.joinpath("index.html").as_uri()


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Upload Hermes preview artifact.")
    parser.add_argument("--manifest", required=True, help="Path from build_preview.py")
    parser.add_argument("--dry-run", action="store_true", help="Print upload request without uploading.")
    parser.add_argument("--local-dir", default="", help="Copy preview into local dir instead of calling Hermes.")
    args = parser.parse_args(argv)

    config = load_config()
    manifest_path = Path(args.manifest).expanduser()
    manifest = read_json(manifest_path)

    if args.local_dir:
        preview_url = upload_to_local_dir(manifest, Path(args.local_dir).expanduser())
        manifest["preview_url"] = preview_url
        write_json(manifest_path, manifest)
        print(json.dumps({"ok": True, "preview_url": preview_url, "mode": "local"}, ensure_ascii=False, indent=2))
        return 0

    server_api = str(config["server_api"]).rstrip("/")
    request_payload = {
        "worker_id": config["worker_id"],
        "task_id": manifest["task_id"],
        "project": manifest.get("project"),
        "git": manifest.get("git", {}),
        "build": manifest.get("build", {}),
        "files": manifest["files"],
    }

    if args.dry_run:
        print(json.dumps({
            "ok": True,
            "dry_run": True,
            "endpoint": f"{server_api}/api/previews/create-upload",
            "request": request_payload,
        }, ensure_ascii=False, indent=2))
        return 0

    upload_session = post_json(f"{server_api}/api/previews/create-upload", request_payload)
    uploads = upload_session.get("uploads")
    if not isinstance(uploads, list):
        raise SystemExit("Hermes preview upload response missing uploads list")

    dist_path = Path(manifest["dist_path"])
    by_path = {item["path"]: item for item in manifest["files"]}
    for upload in uploads:
        relative_path = upload.get("path")
        url = upload.get("url")
        if not relative_path or not url:
            raise SystemExit(f"Invalid upload entry: {upload}")
        file_info = by_path.get(relative_path)
        if not file_info:
            raise SystemExit(f"Hermes requested unknown file: {relative_path}")
        put_file(
            url,
            dist_path / relative_path,
            file_info.get("content_type") or "application/octet-stream",
            upload.get("headers") if isinstance(upload.get("headers"), dict) else None,
        )

    complete_payload = {
        "worker_id": config["worker_id"],
        "task_id": manifest["task_id"],
        "build_id": upload_session.get("build_id"),
        "preview_url": upload_session.get("preview_url"),
        "manifest": manifest,
    }
    complete_result = post_json(f"{server_api}/api/previews/complete", complete_payload)
    preview_url = complete_result.get("preview_url") or upload_session.get("preview_url") or ""
    manifest["build_id"] = upload_session.get("build_id")
    manifest["preview_url"] = preview_url
    write_json(manifest_path, manifest)

    print(json.dumps({
        "ok": True,
        "build_id": manifest.get("build_id"),
        "preview_url": preview_url,
        "uploaded_files": len(uploads),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
