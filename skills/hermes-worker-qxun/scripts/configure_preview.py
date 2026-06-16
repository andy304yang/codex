#!/usr/bin/env python3
"""Configure preview deployment for the Hermes worker."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from hermes_worker_lib import CONFIG_PATH, load_config, save_config


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description="Configure Hermes preview deployment.")
    parser.add_argument("--provider", choices=["nginx", "hermes", "cos"], default="nginx")
    parser.add_argument("--base-url", default="", help="Public base URL, e.g. http://host or https://preview.example.com")
    parser.add_argument("--prefix", default="hermes-previews", help="URL/path prefix under the preview site.")
    parser.add_argument("--local-root", default="", help="Local Nginx document root when running on the Nginx host.")
    parser.add_argument("--remote-host", default="", help="Remote Nginx host for SSH/rsync deployment.")
    parser.add_argument("--remote-user", default="ubuntu")
    parser.add_argument("--remote-root", default="", help="Remote Nginx document root, e.g. /var/www/html")
    parser.add_argument("--ssh-port", default="22")
    parser.add_argument("--ssh-key", default="", help="Optional SSH private key path. Do not put passwords here.")
    args = parser.parse_args(argv)

    config = load_config()
    config["preview_provider"] = args.provider
    if args.provider == "nginx":
        existing = config.get("nginx_preview") if isinstance(config.get("nginx_preview"), dict) else {}
        nginx = {
            "public_base_url": args.base_url or existing.get("public_base_url", ""),
            "prefix": args.prefix if args.prefix is not None else existing.get("prefix", "hermes-previews"),
            "local_root": args.local_root or existing.get("local_root", ""),
            "remote_host": args.remote_host or existing.get("remote_host", ""),
            "remote_user": args.remote_user or existing.get("remote_user", "ubuntu"),
            "remote_root": args.remote_root or existing.get("remote_root", ""),
            "ssh_port": args.ssh_port or existing.get("ssh_port", "22"),
            "ssh_key": str(Path(args.ssh_key).expanduser()) if args.ssh_key else existing.get("ssh_key", ""),
        }
        config["nginx_preview"] = nginx

    save_config(config)
    print(json.dumps({
        "ok": True,
        "config_path": str(CONFIG_PATH),
        "preview_provider": config.get("preview_provider"),
        "nginx_preview": config.get("nginx_preview", {}),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
