#!/usr/bin/env python3
"""Upload a built preview artifact to Hermes, Nginx, COS, or a local directory."""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import re
import shutil
import subprocess
import sys
import time
import urllib.parse
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from hermes_worker_lib import load_config, read_json, write_json


def safe_path_component(value: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", value.strip())
    return cleaned.strip(".-") or "preview"


def rewrite_index_html(body: bytes) -> bytes:
    html = body.decode("utf-8")
    html = re.sub(r'((?:src|href)=["\'])/', r"\1./", html)
    return html.encode("utf-8")


def preview_build_id(manifest: dict[str, Any]) -> str:
    build_id = manifest.get("build_id") or time.strftime("%Y%m%d-%H%M%S")
    return safe_path_component(str(build_id))


def preview_relative_root(manifest: dict[str, Any], prefix: str) -> Path:
    task_id = safe_path_component(str(manifest["task_id"]))
    build_id = preview_build_id(manifest)
    parts = [part for part in [prefix.strip("/"), task_id, build_id] if part]
    return Path(*parts)


def copy_preview_file(source: Path, destination: Path, relative_path: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    body = source.read_bytes()
    if relative_path == "index.html":
        body = rewrite_index_html(body)
    destination.write_bytes(body)


def stage_preview_files(manifest: dict[str, Any], target: Path) -> None:
    dist_path = Path(manifest["dist_path"])
    if target.exists():
        shutil.rmtree(target)
    for file_info in manifest["files"]:
        relative_path = str(file_info["path"]).lstrip("/")
        copy_preview_file(dist_path / relative_path, target / relative_path, relative_path)


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
    target = output_dir / preview_relative_root(manifest, "")
    stage_preview_files(manifest, target)
    return target.joinpath("index.html").as_uri()


def nginx_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("nginx_preview")
    nginx = raw if isinstance(raw, dict) else {}
    return {
        "public_base_url": str(os.getenv("HERMES_NGINX_PUBLIC_BASE_URL") or nginx.get("public_base_url") or ""),
        "prefix": str(os.getenv("HERMES_NGINX_PREFIX") or nginx.get("prefix") or "hermes-previews").strip("/"),
        "local_root": str(os.getenv("HERMES_NGINX_LOCAL_ROOT") or nginx.get("local_root") or ""),
        "remote_host": str(os.getenv("HERMES_NGINX_REMOTE_HOST") or nginx.get("remote_host") or ""),
        "remote_user": str(os.getenv("HERMES_NGINX_REMOTE_USER") or nginx.get("remote_user") or "ubuntu"),
        "remote_root": str(os.getenv("HERMES_NGINX_REMOTE_ROOT") or nginx.get("remote_root") or ""),
        "ssh_port": str(os.getenv("HERMES_NGINX_SSH_PORT") or nginx.get("ssh_port") or "22"),
        "ssh_key": str(os.getenv("HERMES_NGINX_SSH_KEY") or nginx.get("ssh_key") or ""),
    }


def ssh_base_command(nginx: dict[str, str]) -> list[str]:
    command = ["ssh", "-p", nginx["ssh_port"]]
    if nginx["ssh_key"]:
        command.extend(["-i", str(Path(nginx["ssh_key"]).expanduser())])
    return command


def rsync_command(nginx: dict[str, str], source: Path, remote_target: str) -> list[str]:
    ssh_command = " ".join(ssh_base_command(nginx))
    remote = f"{nginx['remote_user']}@{nginx['remote_host']}:{remote_target.rstrip('/')}/"
    return ["rsync", "-az", "--delete", "-e", ssh_command, f"{source}/", remote]


def upload_to_nginx(manifest: dict[str, Any], config: dict[str, Any], dry_run: bool = False) -> dict[str, Any]:
    nginx = nginx_config(config)
    if not nginx["public_base_url"]:
        raise SystemExit("Nginx preview requires HERMES_NGINX_PUBLIC_BASE_URL or nginx_preview.public_base_url.")
    if not nginx["local_root"] and not (nginx["remote_host"] and nginx["remote_root"]):
        raise SystemExit("Nginx preview requires local_root or remote_host + remote_root.")

    relative_root = preview_relative_root(manifest, nginx["prefix"])
    build_id = relative_root.name
    run_staging = Path(manifest_path_for_staging(manifest)).expanduser()
    stage_preview_files(manifest, run_staging)

    commands: list[list[str]] = []
    remote_target = ""
    if nginx["remote_host"]:
        remote_target = str(Path(nginx["remote_root"]) / relative_root)
        mkdir_command = ssh_base_command(nginx) + [
            f"{nginx['remote_user']}@{nginx['remote_host']}",
            f"mkdir -p {remote_target!r}",
        ]
        deploy_command = rsync_command(nginx, run_staging, remote_target)
        commands = [mkdir_command, deploy_command]
        if not dry_run:
            subprocess.run(mkdir_command, check=True)
            subprocess.run(deploy_command, check=True)
    else:
        target = Path(nginx["local_root"]).expanduser() / relative_root
        commands = [["copy", str(run_staging), str(target)]]
        if not dry_run:
            stage_preview_files(manifest, target)

    preview_path = "/".join(urllib.parse.quote(part, safe="-_.~") for part in relative_root.parts)
    preview_url = f"{nginx['public_base_url'].rstrip('/')}/{preview_path}/index.html"
    manifest["build_id"] = build_id
    manifest["preview_url"] = preview_url
    manifest["nginx"] = {
        "public_base_url": nginx["public_base_url"],
        "prefix": nginx["prefix"],
        "relative_root": str(relative_root),
        "remote_host": nginx["remote_host"],
        "remote_root": nginx["remote_root"],
        "local_root": nginx["local_root"],
        "remote_target": remote_target,
    }
    return {
        "preview_url": preview_url,
        "build_id": build_id,
        "uploaded_files": [item["path"] for item in manifest["files"]],
        "commands": commands,
        "staging_dir": str(run_staging),
    }


def manifest_path_for_staging(manifest: dict[str, Any]) -> str:
    task_id = safe_path_component(str(manifest["task_id"]))
    build_id = preview_build_id(manifest)
    return str(Path.home() / ".hermes-codex-worker" / "runs" / task_id / "nginx_staging" / build_id)


def cos_config(config: dict[str, Any]) -> dict[str, str]:
    raw = config.get("cos_upload")
    cos_upload = raw if isinstance(raw, dict) else {}
    return {
        "bucket": str(os.getenv("HERMES_COS_BUCKET") or cos_upload.get("bucket") or "xqunbot-1330713835"),
        "region": str(os.getenv("HERMES_COS_REGION") or cos_upload.get("region") or "ap-guangzhou"),
        "prefix": str(os.getenv("HERMES_COS_PREFIX") or cos_upload.get("prefix") or "hermes-previews").strip("/"),
        "secret_id": str(os.getenv("TENCENTCLOUD_SECRET_ID") or os.getenv("COS_SECRET_ID") or ""),
        "secret_key": str(os.getenv("TENCENTCLOUD_SECRET_KEY") or os.getenv("COS_SECRET_KEY") or ""),
        "public_base_url": str(os.getenv("HERMES_COS_PUBLIC_BASE_URL") or cos_upload.get("public_base_url") or ""),
        "signed_get_expires": str(os.getenv("HERMES_COS_SIGNED_GET_EXPIRES") or cos_upload.get("signed_get_expires") or "604800"),
        "acl": str(os.getenv("HERMES_COS_ACL") or cos_upload.get("acl") or "public-read"),
    }


def sha1_hex(value: str) -> str:
    return hashlib.sha1(value.encode("utf-8")).hexdigest()


def hmac_sha1_hex(key: str | bytes, value: str) -> str:
    raw_key = key.encode("utf-8") if isinstance(key, str) else key
    return hmac.new(raw_key, value.encode("utf-8"), hashlib.sha1).hexdigest()


def cos_authorization(
    *,
    method: str,
    key: str,
    host: str,
    secret_id: str,
    secret_key: str,
    now: int | None = None,
) -> str:
    start = int(now or time.time())
    end = start + 3600
    sign_time = f"{start};{end}"
    key_time = sign_time
    uri = "/" + urllib.parse.quote(key.lstrip("/"), safe="/-_.~")
    http_string = "\n".join([
        method.lower(),
        uri,
        "",
        f"host={host.lower()}",
        "",
    ])
    string_to_sign = "\n".join(["sha1", sign_time, sha1_hex(http_string), ""])
    sign_key = hmac_sha1_hex(secret_key, key_time)
    signature = hmac_sha1_hex(bytes.fromhex(sign_key), string_to_sign)
    return "&".join([
        "q-sign-algorithm=sha1",
        f"q-ak={secret_id}",
        f"q-sign-time={sign_time}",
        f"q-key-time={key_time}",
        "q-header-list=host",
        "q-url-param-list=",
        f"q-signature={signature}",
    ])


def cos_put_file(
    *,
    bucket: str,
    region: str,
    secret_id: str,
    secret_key: str,
    key: str,
    path: Path,
    content_type: str,
) -> str:
    host = f"{bucket}.cos.{region}.myqcloud.com"
    encoded_key = urllib.parse.quote(key.lstrip("/"), safe="/-_.~")
    url = f"https://{host}/{encoded_key}"
    authorization = cos_authorization(
        method="PUT",
        key=key,
        host=host,
        secret_id=secret_id,
        secret_key=secret_key,
    )
    req = urllib.request.Request(
        url,
        data=path.read_bytes(),
        headers={
            "Authorization": authorization,
            "Content-Type": content_type,
            "Host": host,
        },
        method="PUT",
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        if resp.status >= 400:
            raise RuntimeError(f"COS upload failed for {key}: HTTP {resp.status}")
    return url


def upload_to_cos(manifest: dict[str, Any], config: dict[str, Any]) -> dict[str, Any]:
    try:
        from qcloud_cos import CosConfig, CosS3Client  # type: ignore
    except ImportError:
        raise SystemExit("COS direct upload requires: python3 -m pip install cos-python-sdk-v5")

    cos = cos_config(config)
    if not cos["secret_id"] or not cos["secret_key"]:
        raise SystemExit("COS direct upload requires TENCENTCLOUD_SECRET_ID and TENCENTCLOUD_SECRET_KEY.")

    client = CosS3Client(CosConfig(
        Region=cos["region"],
        SecretId=cos["secret_id"],
        SecretKey=cos["secret_key"],
        Scheme="https",
    ))
    dist_path = Path(manifest["dist_path"])
    task_id = str(manifest["task_id"])
    build_id = str(manifest.get("build_id") or int(time.time()))
    prefix = "/".join(part for part in [cos["prefix"], task_id, build_id] if part)
    uploaded: list[str] = []
    for file_info in manifest["files"]:
        relative_path = str(file_info["path"]).lstrip("/")
        key = f"{prefix}/{relative_path}"
        body = (dist_path / relative_path).read_bytes()
        if relative_path == "index.html":
            html = body.decode("utf-8")
            html = re.sub(r'((?:src|href)=["\'])/', r"\1./", html)
            body = html.encode("utf-8")
        put_kwargs = {
            "Bucket": cos["bucket"],
            "Key": key,
            "Body": body,
            "ContentType": file_info.get("content_type") or "application/octet-stream",
        }
        if cos["acl"]:
            put_kwargs["ACL"] = cos["acl"]
        client.put_object(**put_kwargs)
        uploaded.append(key)

    base_url = cos["public_base_url"].rstrip("/") if cos["public_base_url"] else f"https://{cos['bucket']}.cos.{cos['region']}.myqcloud.com"
    index_key = f"{prefix}/index.html"
    object_url = f"{base_url}/{urllib.parse.quote(index_key, safe='/-_.~')}"
    if cos["acl"] == "public-read":
        preview_url = object_url
    else:
        preview_url = client.get_presigned_url(
            Method="GET",
            Bucket=cos["bucket"],
            Key=index_key,
            Expired=int(cos["signed_get_expires"]),
        )
    manifest["build_id"] = build_id
    manifest["preview_url"] = preview_url
    manifest["cos"] = {
        "bucket": cos["bucket"],
        "region": cos["region"],
        "prefix": prefix,
        "object_url": object_url,
        "acl": cos["acl"],
        "signed_get_expires": int(cos["signed_get_expires"]),
        "uploaded_files": uploaded,
    }
    return {"preview_url": preview_url, "build_id": build_id, "uploaded_files": uploaded}


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Upload Hermes preview artifact.")
    parser.add_argument("--manifest", required=True, help="Path from build_preview.py")
    parser.add_argument("--dry-run", action="store_true", help="Print upload request without uploading.")
    parser.add_argument("--local-dir", default="", help="Copy preview into local dir instead of calling Hermes.")
    parser.add_argument("--nginx", action="store_true", help="Deploy preview to an Nginx static site.")
    parser.add_argument("--cos-direct", action="store_true", help="Upload directly to Tencent COS using env credentials.")
    parser.add_argument("--fallback-cos", action="store_true", help="Use COS direct upload if Hermes upload API is unavailable.")
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

    if args.nginx:
        result = upload_to_nginx(manifest, config, dry_run=args.dry_run)
        if not args.dry_run:
            write_json(manifest_path, manifest)
        print(json.dumps({
            "ok": True,
            "dry_run": args.dry_run,
            "mode": "nginx",
            "build_id": result["build_id"],
            "preview_url": result["preview_url"],
            "uploaded_files": len(result["uploaded_files"]),
            "staging_dir": result["staging_dir"],
            "commands": result["commands"],
        }, ensure_ascii=False, indent=2))
        return 0

    if args.cos_direct:
        result = upload_to_cos(manifest, config)
        write_json(manifest_path, manifest)
        print(json.dumps({
            "ok": True,
            "mode": "cos-direct",
            "build_id": result["build_id"],
            "preview_url": result["preview_url"],
            "uploaded_files": len(result["uploaded_files"]),
        }, ensure_ascii=False, indent=2))
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

    try:
        upload_session = post_json(f"{server_api}/api/previews/create-upload", request_payload)
    except urllib.error.HTTPError as exc:
        if args.fallback_cos and exc.code == 404:
            result = upload_to_cos(manifest, config)
            write_json(manifest_path, manifest)
            print(json.dumps({
                "ok": True,
                "mode": "cos-direct",
                "fallback_from": "hermes-upload-404",
                "build_id": result["build_id"],
                "preview_url": result["preview_url"],
                "uploaded_files": len(result["uploaded_files"]),
            }, ensure_ascii=False, indent=2))
            return 0
        raise
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
