#!/usr/bin/env python3
"""Validate the rolling-recap narrative and assemble the dashboard text block.

The model turns `summarize_window.py` output into a short restrained recap for
the pinned dashboard text block. This validator enforces the same discipline as
`validate_analysis.py`: fixed schema, bounded lengths, no diagnostic language,
and no free-form fields. It then assembles a Markdown string using only the
Feishu Base text-block subset (headings, bold, ordered/unordered lists) and
appends the mandatory "文本信号，非心理测评" disclaimer.

The narrative must not contain message text, chat names, or IDs; the model is
only ever given the de-identified aggregate, and this validator additionally
rejects diagnostic terms and over-long fields.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import sys


FORBIDDEN_DIAGNOSIS = ("抑郁症", "焦虑症", "躁郁症", "双相", "PTSD", "人格障碍", "确诊", "患者")
DISCLAIMER = "文本信号，非心理测评。可忽略、修改或暂停。"
MAX_NARRATIVE_ITEMS = 4


def fail(message: str) -> None:
    raise ValueError(message)


def short_text(name: str, value: object, max_chars: int) -> str:
    if not isinstance(value, str) or not value.strip():
        fail(f"{name} must be a non-empty string")
    result = " ".join(value.split())
    if len(result) > max_chars:
        fail(f"{name} exceeds {max_chars} characters")
    if any(term.lower() in result.lower() for term in FORBIDDEN_DIAGNOSIS):
        fail(f"{name} contains diagnostic language")
    return result


def validate(raw: dict[str, object]) -> dict[str, object]:
    required = {"window_label", "headline", "narrative", "gentle_note", "as_of"}
    missing = sorted(required - raw.keys())
    if missing:
        fail(f"missing fields: {', '.join(missing)}")
    extra = sorted(raw.keys() - required)
    if extra:
        fail(f"unexpected fields: {', '.join(extra)}")

    try:
        dt.date.fromisoformat(str(raw["as_of"]))
    except ValueError:
        fail("as_of must use YYYY-MM-DD")

    narrative = raw["narrative"]
    if not isinstance(narrative, list) or not 1 <= len(narrative) <= MAX_NARRATIVE_ITEMS:
        fail(f"narrative must contain 1 to {MAX_NARRATIVE_ITEMS} items")

    return {
        "window_label": short_text("window_label", raw["window_label"], 40),
        "headline": short_text("headline", raw["headline"], 40),
        "narrative": [short_text("narrative item", item, 60) for item in narrative],
        "gentle_note": short_text("gentle_note", raw["gentle_note"], 60),
        "as_of": str(raw["as_of"]),
    }


def to_markdown(data: dict[str, object]) -> str:
    lines = [
        f"# 最近总结 · {data['window_label']}",
        "",
        f"**{data['headline']}**",
        "",
    ]
    for index, item in enumerate(data["narrative"], start=1):
        lines.append(f"{index}. {item}")
    lines += [
        "",
        f"*{data['gentle_note']}*",
        "",
        f"### {DISCLAIMER}",
        f"更新于 {data['as_of']}",
    ]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Validate Emotion Tide recap JSON and emit the dashboard text-block data_config.")
    parser.add_argument("--emit", choices=("data-config", "markdown", "json"), default="data-config",
                        help="data-config: {\"text\": markdown} for +dashboard-block-update; markdown: raw text; json: normalized fields")
    args = parser.parse_args()
    try:
        raw = json.loads(sys.stdin.read())
        if not isinstance(raw, dict):
            fail("root must be an object")
        normalized = validate(raw)
        markdown = to_markdown(normalized)
        if args.emit == "markdown":
            print(markdown)
        elif args.emit == "json":
            print(json.dumps(normalized, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"text": markdown}, ensure_ascii=False))
    except (ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc


if __name__ == "__main__":
    main()
