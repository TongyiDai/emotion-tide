#!/usr/bin/env python3
"""Check local prerequisites without exposing private configuration values."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path


def default_config_path() -> Path:
    return Path(os.environ.get("EMOTION_TIDE_CONFIG", "~/.config/emotion-tide/config.json")).expanduser()


def main() -> None:
    parser = argparse.ArgumentParser(description="Emotion Tide installation doctor.")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--live", action="store_true", help="Also verify the configured Lark user profile")
    args = parser.parse_args()
    checks: dict[str, object] = {
        "python": sys.version_info >= (3, 9),
        "lark_cli": shutil.which("lark-cli") is not None,
        "svg_to_png": shutil.which("sips") is not None or shutil.which("rsvg-convert") is not None,
        "config_exists": args.config.expanduser().is_file(),
    }
    config: dict[str, object] = {}
    if checks["config_exists"]:
        try:
            config = json.loads(args.config.expanduser().read_text(encoding="utf-8"))
            checks["config_valid"] = all(key in config for key in ("timezone", "lark_profile", "recipient_user_id", "base", "workday_calendar"))
        except (OSError, json.JSONDecodeError):
            checks["config_valid"] = False
    else:
        checks["config_valid"] = False
    if args.live and checks["lark_cli"] and checks["config_valid"]:
        env = dict(os.environ)
        env.update({"LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1", "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1"})
        result = subprocess.run(
            ["lark-cli", "auth", "status", "--profile", str(config["lark_profile"]), "--json", "--verify"],
            capture_output=True,
            text=True,
            env=env,
            check=False,
        )
        try:
            payload = json.loads(result.stdout)
            checks["lark_user_verified"] = result.returncode == 0 and payload.get("identity") == "user" and payload.get("verified") is True
        except json.JSONDecodeError:
            checks["lark_user_verified"] = False
    ok = all(value is True for value in checks.values())
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
