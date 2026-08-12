#!/usr/bin/env python3
"""Portable, read-only Lark identity probe with safe compatibility fallback."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
from typing import Any


ENV_QUIET = {
    "LARKSUITE_CLI_NO_UPDATE_NOTIFIER": "1",
    "LARKSUITE_CLI_NO_SKILLS_NOTIFIER": "1",
}
SUBJECT_KEYS = ("open_id", "openId", "user_id", "userId", "union_id", "unionId")


def _run(cli: str, args: list[str], env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run([cli, *args], capture_output=True, text=True, timeout=25, env=env, check=False)


def _json(result: subprocess.CompletedProcess[str]) -> dict[str, Any] | None:
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _unsupported_auth(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode != 0 and "auth" in text and any(
        marker in text for marker in ("unknown command", "no such command", "unrecognized command")
    )


def _unsupported_profile(result: subprocess.CompletedProcess[str]) -> bool:
    text = f"{result.stdout}\n{result.stderr}".lower()
    return result.returncode != 0 and "profile" in text and any(
        marker in text for marker in ("unknown flag", "unknown option", "unrecognized option")
    )


def _args(base: list[str], profile: str | None) -> tuple[list[str], bool]:
    if profile:
        return [*base, "--profile", profile], True
    return base, False


def _run_profiled(cli: str, base: list[str], profile: str | None, env: dict[str, str]) -> tuple[subprocess.CompletedProcess[str], bool, bool]:
    args, profile_applied = _args(base, profile)
    result = _run(cli, args, env)
    if profile and _unsupported_profile(result):
        return _run(cli, base, env), False, True
    return result, profile_applied, False


def _subject_from_contact(payload: dict[str, Any]) -> str | None:
    data = payload.get("data")
    user = data.get("user") if isinstance(data, dict) and isinstance(data.get("user"), dict) else {}
    for key in SUBJECT_KEYS:
        value = user.get(key)
        if isinstance(value, str) and value:
            return value
    return None


def _result(*, ok: bool, method: str, assurance: str, subject_id: str | None = None,
            profile_requested: bool = False, profile_applied: bool = False, warnings: list[str] | None = None,
            auth_supported: bool | None = None) -> dict[str, Any]:
    return {
        "ok": ok,
        "method": method,
        "identity_assurance": assurance,
        "subject_id": subject_id,
        "subject_resolved": bool(subject_id),
        "profile_requested": profile_requested,
        "profile_applied": profile_applied,
        "auth_supported": auth_supported,
        "warnings": warnings or [],
    }


def probe_lark_identity(*, profile: str | None = None, require_subject: bool = False,
                        require_profile: bool = False, cli_path: str | None = None,
                        env: dict[str, str] | None = None) -> dict[str, Any]:
    """Return internal probe state. Callers must redact ``subject_id`` before logging."""
    cli = cli_path or shutil.which("lark-cli")
    requested = bool(profile)
    if not cli:
        return _result(ok=False, method="none", assurance="unavailable", profile_requested=requested,
                       warnings=["lark-cli is not installed"], auth_supported=None)
    run_env = dict(os.environ if env is None else env)
    run_env.update(ENV_QUIET)
    warnings: list[str] = []

    auth, profile_applied, profile_fallback = _run_profiled(
        cli, ["auth", "status", "--json", "--verify"], profile, run_env
    )
    if profile_fallback:
        warnings.append("requested profile is unsupported by this CLI build")
    auth_payload = _json(auth)
    if not _unsupported_auth(auth):
        if auth.returncode != 0 or not auth_payload:
            return _result(ok=False, method="auth_status", assurance="unavailable", profile_requested=requested,
                           profile_applied=profile_applied, warnings=warnings + ["authentication check failed"], auth_supported=True)
        identities = auth_payload.get("identities") if isinstance(auth_payload.get("identities"), dict) else {}
        user = identities.get("user") if isinstance(identities.get("user"), dict) else {}
        subject = next((user.get(key) for key in ("openId", "open_id", "userId", "user_id") if isinstance(user.get(key), str) and user.get(key)), None)
        verified = auth_payload.get("identity") == "user" and auth_payload.get("verified") is True
        if not verified:
            return _result(ok=False, method="auth_status", assurance="unavailable", profile_requested=requested,
                           profile_applied=profile_applied, warnings=warnings + ["authentication is not a verified user identity"], auth_supported=True)
        ok = (not require_subject or bool(subject)) and (not require_profile or profile_applied)
        return _result(ok=ok, method="auth_status", assurance="verified", subject_id=subject,
                       profile_requested=requested, profile_applied=profile_applied, warnings=warnings, auth_supported=True)

    warnings.append("auth status is unavailable in this CLI build; using read-only compatibility probes")
    contact, profile_applied, profile_fallback = _run_profiled(
        cli, ["contact", "+get-user", "--as", "user", "--json"], profile, run_env
    )
    if profile_fallback:
        warnings.append("requested profile is unsupported by this CLI build")
    contact_payload = _json(contact)
    if contact.returncode == 0 and contact_payload and contact_payload.get("ok") is True and contact_payload.get("identity") == "user":
        subject = _subject_from_contact(contact_payload)
        ok = bool(subject) and (not require_profile or profile_applied)
        return _result(ok=ok, method="contact_self", assurance="resolved", subject_id=subject,
                       profile_requested=requested, profile_applied=profile_applied, warnings=warnings, auth_supported=False)

    task, profile_applied, profile_fallback = _run_profiled(
        cli, ["task", "+get-my-tasks", "--as", "user", "--json"], profile, run_env
    )
    if profile_fallback:
        warnings.append("requested profile is unsupported by this CLI build")
    task_payload = _json(task)
    if task.returncode == 0 and task_payload and task_payload.get("ok") is True and task_payload.get("identity") == "user":
        warnings.append("task canary proves user-context access, not the user's stable subject identity")
        return _result(ok=not require_subject and (not require_profile or profile_applied), method="task_canary",
                       assurance="user_context", profile_requested=requested, profile_applied=profile_applied,
                       warnings=warnings, auth_supported=False)
    return _result(ok=False, method="none", assurance="unavailable", profile_requested=requested,
                   profile_applied=profile_applied, warnings=warnings + ["no read-only user identity probe succeeded"], auth_supported=False)


def public_probe(result: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in result.items() if key != "subject_id"}


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only, compatibility-safe Lark identity probe.")
    parser.add_argument("--profile")
    parser.add_argument("--require-subject", action="store_true")
    parser.add_argument("--require-profile", action="store_true")
    args = parser.parse_args()
    result = probe_lark_identity(profile=args.profile, require_subject=args.require_subject, require_profile=args.require_profile)
    print(json.dumps(public_probe(result), ensure_ascii=False))
    return 0 if result["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
