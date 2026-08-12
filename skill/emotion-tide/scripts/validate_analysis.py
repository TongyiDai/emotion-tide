#!/usr/bin/env python3
"""Validate and normalize Emotion Tide model output before any external write."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from pathlib import Path


EMOTIONS = {
    "平稳", "愉悦", "充实", "焦虑", "疲惫", "低落", "烦躁", "受挫",
    "感激", "惊喜", "混合", "无法判断", "无本人消息",
}
COVERAGE = {"complete", "partial", "no_user_messages", "unreadable"}
DIMENSIONS = ("comfort", "energy", "calm", "agency", "connection", "clarity")
ATTENTION = {"none", "human_attention"}
ATTENTION_REASONS = {None, "explicit_immediate_risk"}
FORBIDDEN_DIAGNOSIS = ("抑郁症", "焦虑症", "躁郁症", "双相", "PTSD", "人格障碍", "确诊", "患者")


def fail(message: str) -> None:
    raise ValueError(message)


def bounded_number(name: str, value: object, *, nullable: bool = False) -> float | None:
    if value is None and nullable:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        fail(f"{name} must be a number between 0 and 1")
    result = float(value)
    if not 0 <= result <= 1:
        fail(f"{name} must be between 0 and 1")
    return round(result, 4)


def short_text(name: str, value: object, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    result = value.strip()
    if len(result) > max_chars:
        fail(f"{name} exceeds {max_chars} characters")
    if any(term.lower() in result.lower() for term in FORBIDDEN_DIAGNOSIS):
        fail(f"{name} contains diagnostic language")
    return result


def validate(raw: dict[str, object]) -> dict[str, object]:
    required = {
        "date", "primary_emotion", "secondary_emotions", "intensity", "confidence",
        "coverage", "message_count", "effective_text_count", "effective_char_count",
        "observed", "inference", "uncertainty", "summary", "warm_words",
        "reflection_prompt", "micro_action", "dimensions", "attention_flag",
        "attention_reason",
    }
    missing = sorted(required - raw.keys())
    if missing:
        fail(f"missing fields: {', '.join(missing)}")
    extra = sorted(raw.keys() - required)
    if extra:
        fail(f"unexpected fields: {', '.join(extra)}")
    try:
        dt.date.fromisoformat(str(raw["date"]))
    except ValueError:
        fail("date must use YYYY-MM-DD")

    primary = raw["primary_emotion"]
    if primary not in EMOTIONS:
        fail("primary_emotion is not allowed")
    secondary = raw["secondary_emotions"]
    if not isinstance(secondary, list) or len(secondary) > 3 or any(item not in EMOTIONS for item in secondary):
        fail("secondary_emotions must contain up to three allowed labels")
    coverage = raw["coverage"]
    if coverage not in COVERAGE:
        fail("coverage is not allowed")
    counts: dict[str, int] = {}
    for name in ("message_count", "effective_text_count", "effective_char_count"):
        value = raw[name]
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            fail(f"{name} must be a non-negative integer")
        counts[name] = value
    if counts["effective_text_count"] > counts["message_count"]:
        fail("effective_text_count cannot exceed message_count")

    observed = raw["observed"]
    if not isinstance(observed, list) or len(observed) > 3:
        fail("observed must contain up to three semantic summaries")
    observed = [short_text("observed item", item, 40) for item in observed]
    dimensions = raw["dimensions"]
    if not isinstance(dimensions, dict) or set(dimensions) != set(DIMENSIONS):
        fail("dimensions must contain exactly six named dimensions")
    normalized_dimensions = {name: bounded_number(f"dimensions.{name}", dimensions[name], nullable=True) for name in DIMENSIONS}

    intensity = bounded_number("intensity", raw["intensity"])
    confidence = bounded_number("confidence", raw["confidence"])
    weak_evidence = counts["message_count"] < 3 or counts["effective_char_count"] < 100 or confidence < 0.55
    no_evidence = coverage == "no_user_messages" or counts["message_count"] == 0
    if no_evidence:
        if coverage != "no_user_messages" or counts["message_count"] != 0:
            fail("zero messages and no_user_messages coverage must appear together")
        if primary != "无本人消息" or confidence != 0 or intensity != 0 or any(value is not None for value in normalized_dimensions.values()):
            fail("no-message output must use 无本人消息, zero intensity/confidence, and null dimensions")
    elif weak_evidence:
        if primary not in {"无法判断", "混合"}:
            fail("weak evidence requires 无法判断 or 混合")
        if any(value is not None for value in normalized_dimensions.values()):
            fail("weak evidence requires null dimensions")
    if coverage == "partial" and confidence > 0.65:
        fail("partial coverage confidence cannot exceed 0.65")

    attention_flag = raw["attention_flag"]
    attention_reason = raw["attention_reason"]
    if attention_flag not in ATTENTION or attention_reason not in ATTENTION_REASONS:
        fail("invalid attention fields")
    if attention_flag == "human_attention" and attention_reason != "explicit_immediate_risk":
        fail("human_attention requires explicit_immediate_risk")
    if attention_flag == "none" and attention_reason is not None:
        fail("attention_reason must be null when attention_flag is none")

    normalized = dict(raw)
    normalized.update({
        "primary_emotion": primary,
        "secondary_emotions": secondary,
        "intensity": intensity,
        "confidence": confidence,
        "observed": observed,
        "dimensions": normalized_dimensions,
        "inference": short_text("inference", raw["inference"], 160),
        "uncertainty": short_text("uncertainty", raw["uncertainty"], 160),
        "summary": short_text("summary", raw["summary"], 160),
        "warm_words": short_text("warm_words", raw["warm_words"], 120),
        "reflection_prompt": short_text("reflection_prompt", raw["reflection_prompt"], 80),
        "micro_action": short_text("micro_action", raw["micro_action"], 80),
        "evidence_level": "none" if no_evidence else "low" if weak_evidence else "medium" if confidence < 0.75 else "high",
    })
    return normalized


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Emotion Tide analysis JSON.")
    parser.add_argument("input", nargs="?", type=Path, help="JSON file; defaults to stdin")
    args = parser.parse_args()
    try:
        raw = json.loads(args.input.read_text(encoding="utf-8") if args.input else sys.stdin.read())
        if not isinstance(raw, dict):
            fail("root must be an object")
        print(json.dumps(validate(raw), ensure_ascii=False, indent=2))
    except (OSError, json.JSONDecodeError, ValueError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
