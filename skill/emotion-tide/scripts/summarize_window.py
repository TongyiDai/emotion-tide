#!/usr/bin/env python3
"""Aggregate the last N days of Emotion Tide Base summary fields for a rolling recap.

The daily dashboard shows charts and a six-dimension radar, but no plain-language
"what the last two weeks looked like". This deterministic aggregator reads back
the most recent Base rows (already de-identified summary fields the skill wrote
itself) and produces window-level counts, means, distributions, and a simple
first-half vs second-half trend direction. A structured model then turns this
aggregate into a short restrained narrative for the pinned dashboard text block.

Like `extract_reaction_signals.py`, this script only emits numbers and labels.
It never emits message text, chat names, record IDs, or person IDs, and it does
not read message content at all: its input is the skill's own Base readback.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys
from typing import Iterable, Iterator


EMOTIONS = {
    "平稳", "愉悦", "充实", "焦虑", "疲惫", "低落", "烦躁", "受挫",
    "感激", "惊喜", "混合", "无法判断", "无本人消息",
}
NON_EVIDENCE = {"无本人消息", "无法判断"}

DIMENSIONS = ("comfort", "energy", "calm", "agency", "connection", "clarity")
DIMENSION_FIELDS = {
    "comfort": "文本舒适度",
    "energy": "文本精力",
    "calm": "文本平静度",
    "agency": "文本掌控感",
    "connection": "文本连接感",
    "clarity": "文本清晰度",
}
DIMENSION_LABELS = {
    "comfort": "舒适度",
    "energy": "精力",
    "calm": "平静度",
    "agency": "掌控感",
    "connection": "连接感",
    "clarity": "清晰度",
}

COVERAGE_LABELS = {
    "complete": "覆盖完整", "覆盖完整": "覆盖完整",
    "partial": "部分覆盖", "部分覆盖": "部分覆盖",
    "no_user_messages": "无本人消息", "无本人消息": "无本人消息",
    "unreadable": "读取失败", "读取失败": "读取失败",
}
REACTION_LABELS = {
    "none": "无", "无": "无",
    "acknowledgement": "事务确认", "事务确认": "事务确认",
    "warmth": "温暖连接", "温暖连接": "温暖连接",
    "celebration": "庆祝认可", "庆祝认可": "庆祝认可",
    "tension": "可能张力", "可能张力": "可能张力",
    "mixed": "混合信号", "混合信号": "混合信号",
    "ambiguous": "语义不明", "语义不明": "语义不明",
}


def iter_records(payload: object) -> Iterator[dict]:
    """Yield each record's field map from a Base readback or a plain list.

    Accepts the `base +record-list` envelope (`data.items[].fields`), a bare
    list of records or field maps, or a single record/field map.
    """
    if isinstance(payload, dict):
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("items"), list):
            for item in data["items"]:
                if isinstance(item, dict):
                    yield item.get("fields") if isinstance(item.get("fields"), dict) else item
            return
        if isinstance(payload.get("items"), list):
            for item in payload["items"]:
                if isinstance(item, dict):
                    yield item.get("fields") if isinstance(item.get("fields"), dict) else item
            return
        if isinstance(payload.get("fields"), dict):
            yield payload["fields"]
            return
        yield payload
        return
    if isinstance(payload, list):
        for item in payload:
            if isinstance(item, dict):
                yield item.get("fields") if isinstance(item.get("fields"), dict) else item


def scalar(value: object) -> object:
    """Reduce a Base cell value to a scalar for text/select/date fields."""
    if isinstance(value, list):
        value = value[0] if value else None
    if isinstance(value, dict):
        for key in ("text", "value", "name"):
            if key in value:
                return value[key]
        return None
    return value


def field(record: dict, *names: str) -> object:
    for name in names:
        if name in record and record[name] not in (None, ""):
            return record[name]
    return None


def as_float(value: object) -> float | None:
    value = scalar(value)
    if isinstance(value, bool) or value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def as_text(value: object) -> str | None:
    value = scalar(value)
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def as_date(value: object) -> str | None:
    text = as_text(value)
    if not text:
        return None
    try:
        return dt.date.fromisoformat(text[:10]).isoformat()
    except ValueError:
        return None


def dimension_value(record: dict, dim: str) -> float | None:
    dims = record.get("dimensions")
    if isinstance(dims, dict) and dim in dims:
        return as_float(dims[dim])
    return as_float(field(record, DIMENSION_FIELDS[dim], dim))


def mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def trend(intensities: list[float]) -> str:
    if len(intensities) < 4:
        return "insufficient"
    half = len(intensities) // 2
    first = mean(intensities[:half])
    second = mean(intensities[len(intensities) - half:])
    if first is None or second is None:
        return "insufficient"
    delta = second - first
    if delta >= 0.08:
        return "rising"
    if delta <= -0.08:
        return "falling"
    return "stable"


def sorted_counts(counter: dict[str, int]) -> dict[str, int]:
    return dict(sorted(((k, v) for k, v in counter.items() if v), key=lambda kv: (-kv[1], kv[0])))


def aggregate(records: Iterable[dict], *, window_days: int) -> dict[str, object]:
    rows: list[dict] = []
    for record in records:
        if not isinstance(record, dict):
            continue
        date = as_date(field(record, "日期", "date"))
        if date is None:
            continue
        rows.append({
            "date": date,
            "primary": as_text(field(record, "主情绪", "primary_emotion")),
            "intensity": as_float(field(record, "情绪强度", "intensity")),
            "confidence": as_float(field(record, "置信度", "confidence")),
            "coverage": as_text(field(record, "覆盖状态", "coverage")),
            "reaction": as_text(field(record, "表情互动线索", "reaction_signal")),
            "helpfulness": as_float(field(record, "帮助程度", "helpfulness")),
            "dims": {dim: dimension_value(record, dim) for dim in DIMENSIONS},
        })

    # Deduplicate by date (date is the upsert key) keeping the last occurrence,
    # then take the most recent window_days rows in chronological order.
    by_date: dict[str, dict] = {}
    for row in rows:
        by_date[row["date"]] = row
    ordered = [by_date[key] for key in sorted(by_date)]
    if window_days > 0:
        ordered = ordered[-window_days:]

    total_days = len(ordered)
    if total_days == 0:
        return {
            "generated_from": "base_summary_fields",
            "window_days_requested": window_days,
            "total_days": 0,
            "evidence_days": 0,
            "no_message_days": 0,
            "undetermined_days": 0,
            "date_start": None,
            "date_end": None,
            "avg_intensity": None,
            "avg_confidence": None,
            "dominant_emotion": None,
            "emotion_distribution": {},
            "dimension_means": {dim: None for dim in DIMENSIONS},
            "dimension_high": None,
            "dimension_low": None,
            "coverage_distribution": {},
            "reaction_signal_distribution": {},
            "helpfulness_avg": None,
            "intensity_trend": "insufficient",
        }

    emotion_counts: dict[str, int] = {}
    coverage_counts: dict[str, int] = {}
    reaction_counts: dict[str, int] = {}
    evidence_intensities: list[float] = []
    evidence_confidences: list[float] = []
    dim_values: dict[str, list[float]] = {dim: [] for dim in DIMENSIONS}
    helpfulness_values: list[float] = []
    no_message_days = 0
    undetermined_days = 0
    evidence_days = 0

    for row in ordered:
        primary = row["primary"]
        if primary in EMOTIONS:
            emotion_counts[primary] = emotion_counts.get(primary, 0) + 1
        if primary == "无本人消息":
            no_message_days += 1
        elif primary == "无法判断":
            undetermined_days += 1
        coverage = COVERAGE_LABELS.get(str(row["coverage"]), row["coverage"]) if row["coverage"] else None
        if coverage:
            coverage_counts[coverage] = coverage_counts.get(coverage, 0) + 1
        reaction = REACTION_LABELS.get(str(row["reaction"]), row["reaction"]) if row["reaction"] else None
        if reaction:
            reaction_counts[reaction] = reaction_counts.get(reaction, 0) + 1
        if row["helpfulness"] is not None:
            helpfulness_values.append(row["helpfulness"])

        is_evidence = primary not in NON_EVIDENCE and primary is not None
        if is_evidence:
            evidence_days += 1
            if row["intensity"] is not None:
                evidence_intensities.append(row["intensity"])
            if row["confidence"] is not None:
                evidence_confidences.append(row["confidence"])
            for dim in DIMENSIONS:
                value = row["dims"][dim]
                if value is not None:
                    dim_values[dim].append(value)

    dimension_means = {dim: mean(values) for dim, values in dim_values.items()}
    present_dims = {dim: value for dim, value in dimension_means.items() if value is not None}
    dimension_high = None
    dimension_low = None
    if present_dims:
        high = max(present_dims.items(), key=lambda kv: kv[1])
        low = min(present_dims.items(), key=lambda kv: kv[1])
        dimension_high = {"name": DIMENSION_LABELS[high[0]], "value": high[1]}
        dimension_low = {"name": DIMENSION_LABELS[low[0]], "value": low[1]}

    evidence_emotions = {k: v for k, v in emotion_counts.items() if k not in NON_EVIDENCE}
    dominant_emotion = None
    if evidence_emotions:
        dominant_emotion = max(evidence_emotions.items(), key=lambda kv: (kv[1], kv[0]))[0]

    return {
        "generated_from": "base_summary_fields",
        "window_days_requested": window_days,
        "total_days": total_days,
        "evidence_days": evidence_days,
        "no_message_days": no_message_days,
        "undetermined_days": undetermined_days,
        "date_start": ordered[0]["date"],
        "date_end": ordered[-1]["date"],
        "avg_intensity": mean(evidence_intensities),
        "avg_confidence": mean(evidence_confidences),
        "dominant_emotion": dominant_emotion,
        "emotion_distribution": sorted_counts(emotion_counts),
        "dimension_means": dimension_means,
        "dimension_high": dimension_high,
        "dimension_low": dimension_low,
        "coverage_distribution": sorted_counts(coverage_counts),
        "reaction_signal_distribution": sorted_counts(reaction_counts),
        "helpfulness_avg": mean(helpfulness_values),
        "intensity_trend": trend([row["intensity"] for row in ordered
                                  if row["primary"] not in NON_EVIDENCE and row["intensity"] is not None]),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Aggregate the last N days of Emotion Tide Base summary fields from JSON on stdin.")
    parser.add_argument("--window-days", type=int, default=14, help="Keep the most recent N dated rows (default 14)")
    args = parser.parse_args()
    try:
        payload = json.load(sys.stdin)
        result = aggregate(iter_records(payload), window_days=args.window_days)
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
