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


VALID_MODES = {"agent_runtime", "local_only"}
PLACEHOLDER_PREFIXES = ("YOUR_", "REPLACE_", "EXAMPLE_")


def default_config_path() -> Path:
    return Path(os.environ.get("EMOTION_TIDE_CONFIG", "~/.config/emotion-tide/config.json")).expanduser()


def real_value(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not value.strip().upper().startswith(PLACEHOLDER_PREFIXES)


def derived_state(config: dict[str, object]) -> str:
    explicit = config.get("provisioning_state")
    if isinstance(explicit, str):
        return explicit
    base = config.get("base")
    return "ready" if isinstance(base, dict) and all(real_value(base.get(key)) for key in ("url", "base_token", "table_id", "dashboard_id")) else "unprovisioned"


def config_checks(config: dict[str, object], *, allow_unprovisioned: bool) -> dict[str, bool]:
    base = config.get("base")
    base_ready = isinstance(base, dict) and all(real_value(base.get(key)) for key in ("url", "base_token", "table_id", "dashboard_id"))
    state = derived_state(config)
    owner = config.get("owner_user_id") or config.get("recipient_user_id")
    recipient = config.get("recipient_user_id")
    ready = state == "ready"
    return {
        "config_structure": all(key in config for key in ("timezone", "lark_profile", "recipient_user_id", "base", "workday_calendar")),
        "profile_configured": real_value(config.get("lark_profile")),
        "processing_mode_valid": config.get("text_processing_mode") in VALID_MODES,
        "processing_consent": config.get("text_processing_consent") is True,
        "provisioning_state_valid": state in ({"unprovisioned", "ready"} if allow_unprovisioned else {"ready"}),
        "base_configured": (not ready and allow_unprovisioned) or base_ready,
        "owner_binding_configured": (not ready and allow_unprovisioned) or (real_value(owner) and real_value(recipient) and owner == recipient),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Emotion Tide installation doctor.")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--live", action="store_true", help="Also verify the configured Lark user profile")
    parser.add_argument("--allow-unprovisioned", action="store_true", help="Allow first-run config before its private Base exists")
    args = parser.parse_args()
    checks: dict[str, object] = {
        "python": sys.version_info >= (3, 9),
        "lark_cli": shutil.which("lark-cli") is not None,
        "svg_to_png": shutil.which("sips") is not None or shutil.which("rsvg-convert") is not None,
        "config_exists": args.config.expanduser().is_file(),
        "config_private": args.config.expanduser().is_file() and (args.config.expanduser().stat().st_mode & 0o077) == 0,
    }
    config: dict[str, object] = {}
    if checks["config_exists"]:
        try:
            config = json.loads(args.config.expanduser().read_text(encoding="utf-8"))
            checks.update(config_checks(config, allow_unprovisioned=args.allow_unprovisioned))
        except (OSError, json.JSONDecodeError):
            checks["config_structure"] = False
    else:
        checks["config_structure"] = False
    if args.live and checks["lark_cli"] and checks.get("config_structure") and checks.get("profile_configured"):
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
            verified = result.returncode == 0 and payload.get("identity") == "user" and payload.get("verified") is True
            checks["lark_user_verified"] = verified
            live_user = (((payload.get("identities") or {}).get("user") or {}).get("openId"))
            owner = config.get("owner_user_id") or config.get("recipient_user_id")
            recipient = config.get("recipient_user_id")
            state = derived_state(config)
            if state == "ready":
                checks["live_user_matches_owner"] = verified and real_value(live_user) and owner == recipient == live_user
            else:
                checks["live_user_matches_owner"] = verified and (owner is None or owner == live_user) and (recipient is None or recipient == live_user)
        except json.JSONDecodeError:
            checks["lark_user_verified"] = False
            checks["live_user_matches_owner"] = False
    ok = all(value is True for value in checks.values())
    print(json.dumps({"ok": ok, "checks": checks}, ensure_ascii=False, indent=2))
    raise SystemExit(0 if ok else 1)


if __name__ == "__main__":
    main()
