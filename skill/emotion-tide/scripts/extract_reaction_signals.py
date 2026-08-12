#!/usr/bin/env python3
"""Aggregate the current user's Feishu reactions without emitting message text or IDs."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path
from typing import Iterator


ACKNOWLEDGEMENT = {"OK", "THUMBSUP", "DONE", "CHECKMARK", "LGTM", "ONIT", "YES", "JIAYI"}
WARMTH = {"HEART", "HUG", "COMFORT", "THANKS", "FINGERHEART", "LOVE", "ROSE", "KISS", "SMOOCH"}
CELEBRATION = {"APPLAUSE", "CLAP", "PARTY", "FIREWORKS", "PRAISE", "TROPHY", "FIRECRACKER", "YEAH"}
TENSION = {"ANGRY", "FROWN", "CRY", "SOB", "SIGH", "WAIL", "WHIMPER", "WRONGED", "SPEECHLESS"}
COVERAGE = {"complete", "partial", "unavailable"}


def milliseconds(value: object) -> int | None:
    try:
        result = int(str(value))
    except (TypeError, ValueError):
        return None
    return result * 1000 if result < 10_000_000_000 else result


def iso_milliseconds(value: str) -> int:
    parsed = dt.datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError("time boundary must include a timezone offset")
    return int(parsed.timestamp() * 1000)


def walk(value: object) -> Iterator[dict[str, object]]:
    if isinstance(value, dict):
        yield value
        for child in value.values():
            yield from walk(child)
    elif isinstance(value, list):
        for child in value:
            yield from walk(child)


def operator_id(item: dict[str, object]) -> str | None:
    operator = item.get("operator")
    if isinstance(operator, dict):
        value = operator.get("operator_id") or operator.get("id")
        return str(value) if value else None
    value = item.get("operator_id")
    return str(value) if value else None


def emoji_type(item: dict[str, object]) -> str | None:
    value = item.get("emoji_type")
    if value:
        return str(value)
    reaction_type = item.get("reaction_type")
    if isinstance(reaction_type, dict):
        value = reaction_type.get("emoji_type")
    else:
        value = reaction_type
    return str(value) if value else None


def sender_id(message: dict[str, object]) -> str | None:
    sender = message.get("sender")
    if isinstance(sender, dict):
        value = sender.get("id") or sender.get("sender_id")
        return str(value) if value else None
    return None


def classify(name: str) -> str:
    normalized = name.replace("_", "").upper()
    if normalized in ACKNOWLEDGEMENT:
        return "acknowledgement"
    if normalized in WARMTH:
        return "warmth"
    if normalized in CELEBRATION:
        return "celebration"
    if normalized in TENSION:
        return "tension"
    return "ambiguous"


def summarize(counts: dict[str, int], stickers: int) -> str:
    labels = {
        "acknowledgement": "事务确认",
        "warmth": "温暖连接",
        "celebration": "庆祝认可",
        "tension": "可能的张力",
        "ambiguous": "语义不明",
    }
    parts = [f"{labels[key]} {value} 次" for key, value in counts.items() if value]
    if stickers:
        parts.append(f"语义不明贴纸 {stickers} 次")
    return "当天未识别到本人主动添加的表情回应。" if not parts else "识别到本人主动表情：" + "，".join(parts) + "。"


def aggregate(payload: object, user_id: str, start_ms: int, end_ms: int, coverage: str) -> dict[str, object]:
    if coverage not in COVERAGE:
        raise ValueError("coverage must be complete, partial, or unavailable")
    counts = {key: 0 for key in ("acknowledgement", "warmth", "celebration", "tension", "ambiguous")}
    seen: set[str] = set()
    sticker_messages: set[str] = set()
    for item in walk(payload):
        reaction_id = item.get("reaction_id")
        action_time = milliseconds(item.get("action_time"))
        emoji = emoji_type(item)
        if reaction_id and action_time is not None and emoji and operator_id(item) == user_id and start_ms <= action_time < end_ms:
            stable_id = str(reaction_id)
            if stable_id not in seen:
                seen.add(stable_id)
                counts[classify(emoji)] += 1
        if str(item.get("msg_type", "")).lower() == "sticker" and sender_id(item) == user_id:
            created = milliseconds(item.get("create_time"))
            message_id = item.get("message_id")
            if created is not None and message_id and start_ms <= created < end_ms:
                sticker_messages.add(str(message_id))

    expressive = {key: counts[key] for key in ("warmth", "celebration", "tension") if counts[key]}
    if len(expressive) > 1:
        signal = "mixed"
    elif expressive:
        signal = next(iter(expressive))
    elif counts["acknowledgement"]:
        signal = "acknowledgement"
    elif counts["ambiguous"] or sticker_messages:
        signal = "ambiguous"
    else:
        signal = "none"
    effective = sum(expressive.values())
    return {
        "reaction_count": len(seen) + len(sticker_messages),
        "effective_reaction_count": effective,
        "reaction_coverage": coverage,
        "reaction_signal": signal,
        "reaction_summary": summarize(counts, len(sticker_messages)),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate self-authored Feishu reaction signals from message JSON on stdin.")
    parser.add_argument("--config", type=Path, required=True, help="Private Emotion Tide config containing recipient_user_id")
    parser.add_argument("--start", required=True, help="Inclusive ISO 8601 timestamp")
    parser.add_argument("--end", required=True, help="Exclusive ISO 8601 timestamp")
    parser.add_argument("--coverage", choices=sorted(COVERAGE), default="complete")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.expanduser().read_text(encoding="utf-8"))
        user_id = str(config["recipient_user_id"])
        payload = json.load(sys.stdin)
        result = aggregate(payload, user_id, iso_milliseconds(args.start), iso_milliseconds(args.end), args.coverage)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (OSError, KeyError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
