#!/usr/bin/env python3
"""Atomically checkpoint a first-run Base creation without printing private coordinates.

This script intentionally does not call Lark APIs. The calling agent verifies the
current user before creation and verifies owner, collaborators and sharing before
marking the installation ready. Its only job is to make a successful create
response durable before later provisioning steps can fail.
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import sys
import tempfile
from pathlib import Path
from typing import Any


COORDINATE_KEYS = ("url", "base_token", "table_id", "dashboard_id")
PLACEHOLDER_PREFIXES = ("YOUR_", "REPLACE_", "EXAMPLE_")


def default_config_path() -> Path:
    return Path(os.environ.get("EMOTION_TIDE_CONFIG", "~/.config/emotion-tide/config.json")).expanduser()


def real_value(value: object) -> bool:
    return isinstance(value, str) and bool(value.strip()) and not value.strip().upper().startswith(PLACEHOLDER_PREFIXES)


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc).replace(microsecond=0)


def iso_utc(value: dt.datetime) -> str:
    return value.astimezone(dt.timezone.utc).isoformat().replace("+00:00", "Z")


def parse_utc(value: object) -> dt.datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(dt.timezone.utc)


def load_config(path: Path) -> dict[str, Any]:
    value = json.loads(path.expanduser().read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError("config root must be an object")
    return value


def atomic_write(path: Path, config: dict[str, Any]) -> None:
    directory = path.expanduser().parent
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, prefix=f".{path.name}.", delete=False) as handle:
        handle.write(json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        temporary = Path(handle.name)
    os.chmod(temporary, 0o600)
    temporary.replace(path.expanduser())


def base_name(installation_id: object) -> str:
    if not real_value(installation_id):
        raise ValueError("installation_id is required")
    digest = hashlib.sha256(str(installation_id).encode("utf-8")).hexdigest()[:12].upper()
    return f"情绪潮汐 · {digest}"


def empty_coordinates(base: object) -> bool:
    return isinstance(base, dict) and all(base.get(key) is None for key in COORDINATE_KEYS)


def valid_bound_user(config: dict[str, Any]) -> bool:
    return real_value(config.get("owner_user_id")) and config.get("owner_user_id") == config.get("recipient_user_id")


def prepare(config: dict[str, Any], *, now: dt.datetime) -> str:
    if config.get("provisioning_state") != "unprovisioned":
        raise ValueError("provisioning_state must be unprovisioned")
    if not valid_bound_user(config):
        raise ValueError("owner and recipient must be the same configured user")
    base = config.setdefault("base", {})
    if not isinstance(base, dict) or not empty_coordinates(base):
        raise ValueError("Base coordinates already exist; resume exact resource instead")
    expected = base_name(config.get("installation_id"))
    existing = base.get("recovery_label")
    started = parse_utc(base.get("provisioning_started_at"))
    if existing is not None and (existing != expected or started is None):
        raise ValueError("existing recovery checkpoint is invalid")
    base["recovery_label"] = expected
    base["provisioning_started_at"] = iso_utc(now)
    return expected


def response_data(payload: object) -> dict[str, Any]:
    if not isinstance(payload, dict) or payload.get("ok") is not True or payload.get("identity") != "user":
        raise ValueError("create response must be a successful user envelope")
    data = payload.get("data")
    if not isinstance(data, dict):
        raise ValueError("create response data is missing")
    return data


def created_coordinates(payload: object, *, expected_name: str) -> dict[str, str]:
    data = response_data(payload)
    base = data.get("base")
    table = data.get("table")
    if not isinstance(base, dict) or not isinstance(table, dict):
        raise ValueError("create response must include base and table")
    if base.get("name") is not None and base.get("name") != expected_name:
        raise ValueError("create response name does not match this installation checkpoint")
    token = base.get("base_token") or base.get("app_token")
    table_id = table.get("table_id") or table.get("id")
    url = base.get("url")
    if not all(real_value(value) for value in (token, table_id, url)):
        raise ValueError("create response lacks usable Base coordinates")
    return {"url": str(url), "base_token": str(token), "table_id": str(table_id)}


def bind(config: dict[str, Any], payload: object) -> None:
    if config.get("provisioning_state") != "unprovisioned" or not valid_bound_user(config):
        raise ValueError("config is not an eligible first-run installation")
    base = config.get("base")
    if not empty_coordinates(base) or not isinstance(base, dict):
        raise ValueError("Base coordinates already exist; refusing to overwrite")
    expected = base_name(config.get("installation_id"))
    if base.get("recovery_label") != expected or parse_utc(base.get("provisioning_started_at")) is None:
        raise ValueError("prepare checkpoint is required before binding")
    base.update(created_coordinates(payload, expected_name=expected))


def recovery_plan(config: dict[str, Any], *, now: dt.datetime, max_age_minutes: int) -> str:
    if config.get("provisioning_state") != "unprovisioned" or not valid_bound_user(config):
        raise ValueError("config is not an eligible first-run installation")
    base = config.get("base")
    if not empty_coordinates(base) or not isinstance(base, dict):
        raise ValueError("Base coordinates already exist; no discovery is allowed")
    expected = base_name(config.get("installation_id"))
    started = parse_utc(base.get("provisioning_started_at"))
    if base.get("recovery_label") != expected or started is None:
        raise ValueError("no valid recovery checkpoint exists")
    age = now - started
    if age < dt.timedelta(minutes=-5) or age > dt.timedelta(minutes=max_age_minutes):
        raise ValueError("recovery window is closed")
    return expected


def main() -> int:
    parser = argparse.ArgumentParser(description="Checkpoint first-run Base creation without exposing coordinates.")
    parser.add_argument("command", choices=("prepare", "bind", "recovery-plan"))
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--emit", choices=("json", "base-name"), default="json")
    parser.add_argument("--max-age-minutes", type=int, default=60)
    args = parser.parse_args()
    try:
        if args.max_age_minutes < 1:
            raise ValueError("max-age-minutes must be positive")
        config = load_config(args.config)
        now = utc_now()
        if args.command == "prepare":
            name = prepare(config, now=now)
            atomic_write(args.config, config)
            if args.emit == "base-name":
                print(name)
            else:
                print(json.dumps({"ok": True, "checkpoint_prepared": True, "base_name": name}, ensure_ascii=False))
        elif args.command == "bind":
            bind(config, json.load(sys.stdin))
            atomic_write(args.config, config)
            print(json.dumps({"ok": True, "coordinates_bound": True}, ensure_ascii=False))
        else:
            name = recovery_plan(config, now=now, max_age_minutes=args.max_age_minutes)
            if args.emit == "base-name":
                print(name)
            else:
                print(json.dumps({"ok": True, "recovery_allowed": True, "base_name": name}, ensure_ascii=False))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
