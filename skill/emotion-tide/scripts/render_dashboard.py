#!/usr/bin/env python3
"""Render one private Emotion Tide daily summary as a self-contained SVG card.

Reads a structured analysis JSON object from stdin and writes an SVG. The
caller may convert the SVG to PNG with the platform's image tool before it is
sent through Feishu. No message text is read or embedded by this renderer.
"""

from __future__ import annotations

import argparse
import html
import json
import sys
import unicodedata
from pathlib import Path


EMOTION_COLORS = {
    "平稳": "#5F7D73",
    "愉悦": "#D9963B",
    "充实": "#607D5A",
    "焦虑": "#B76A4A",
    "疲惫": "#8C6A5D",
    "低落": "#7C8395",
    "烦躁": "#B75B58",
    "受挫": "#9A6370",
    "感激": "#C48A42",
    "惊喜": "#C77B3B",
    "混合": "#7A728A",
    "无法判断": "#87909A",
    "无本人消息": "#87909A",
}


def text(value: object, default: str = "—") -> str:
    if value is None:
        return default
    value = str(value).strip()
    return value or default


def number(value: object) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return 0.0


def integer(value: object) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def compact_count(value: int) -> str:
    if value >= 100_000_000:
        return f"{value / 100_000_000:.1f}亿"
    if value >= 10_000:
        return f"{value / 10_000:.1f}万"
    return str(value)


def escape(value: object) -> str:
    return html.escape(text(value), quote=False)


def character_units(char: str) -> float:
    """Conservative display-width estimate for CJK and Latin text."""
    if char == "\t":
        return 2.0
    if unicodedata.east_asian_width(char) in {"F", "W", "A"}:
        return 1.15
    return 0.72


def display_units(value: str) -> float:
    return sum(character_units(char) for char in value)


def ellipsize(value: str, max_units: float) -> str:
    value = text(value, "")
    if display_units(value) <= max_units:
        return value
    suffix = "…"
    kept = ""
    for char in value:
        if display_units(kept + char + suffix) > max_units:
            break
        kept += char
    return (kept or suffix) + suffix


def wrap(value: str, max_width: int, font_size: int, max_lines: int) -> list[str]:
    value = text(value, "")
    if not value:
        return []
    max_units = max_width / (font_size * 1.12)
    lines: list[str] = []
    current = ""
    remaining = False
    for index, char in enumerate(value):
        if char == "\n":
            lines.append(current.strip())
            current = ""
            if len(lines) == max_lines and index < len(value) - 1:
                remaining = True
                break
            continue
        if current and display_units(current + char) > max_units:
            lines.append(current.strip())
            current = char
            if len(lines) == max_lines:
                remaining = True
                break
        else:
            current += char
    if current.strip():
        lines.append(current.strip())
    lines = [line for line in lines if line]
    if len(lines) > max_lines:
        lines = lines[:max_lines]
        remaining = True
    if remaining and lines:
        lines[-1] = ellipsize(lines[-1], max_units - character_units("…")) + "…"
    return lines


def label_for_coverage(coverage: str) -> str:
    return {
        "complete": "覆盖完整",
        "partial": "部分覆盖",
        "no_user_messages": "无本人消息",
        "unreadable": "读取失败",
    }.get(coverage, coverage or "覆盖待确认")


def line(
    x: int,
    y: int,
    content: str,
    size: int,
    color: str,
    weight: int = 400,
    max_width: int | None = None,
    clip_id: str | None = None,
) -> str:
    if max_width is not None:
        content = ellipsize(content, max_width / (size * 1.12))
    clip = f' clip-path="url(#{clip_id})"' if clip_id else ""
    return (
        f'<text x="{x}" y="{y}" font-family="PingFang SC, STHeiti, sans-serif" '
        f'font-size="{size}" font-weight="{weight}" fill="{color}"{clip}>{escape(content)}</text>'
    )


def render(data: dict[str, object]) -> str:
    date = text(data.get("date") or data.get("日期"))
    primary = text(data.get("primary_emotion") or data.get("主情绪"), "无法判断")
    secondary_value = data.get("secondary_emotions") or data.get("辅助情绪") or []
    secondary = "、".join(map(str, secondary_value)) if isinstance(secondary_value, list) else text(secondary_value, "")
    intensity = number(data.get("intensity") if "intensity" in data else data.get("情绪强度"))
    confidence = number(data.get("confidence") if "confidence" in data else data.get("置信度"))
    messages = integer(data.get("message_count") if "message_count" in data else data.get("本人消息数"))
    effective = integer(data.get("effective_text_count") if "effective_text_count" in data else data.get("有效文本数"))
    coverage = text(data.get("coverage") or data.get("覆盖状态"), "partial")
    summary = text(data.get("summary") or data.get("情绪摘要"), "今天没有足够的本人文本，暂不做情绪判断。")
    warm_words = text(data.get("warm_words") or data.get("暖心话语"), "给自己留一点空白，也给今天一个收尾。")
    color = EMOTION_COLORS.get(primary, "#607D8B")
    secondary_line = f"辅助情绪：{secondary}" if secondary else "辅助情绪：未识别"

    parts = [
        '<svg xmlns="http://www.w3.org/2000/svg" width="1200" height="720" viewBox="0 0 1200 720">',
        '<defs>',
        '<clipPath id="date-clip"><rect x="920" y="64" width="198" height="42"/></clipPath>',
        '<clipPath id="emotion-clip"><rect x="106" y="248" width="360" height="114"/></clipPath>',
        '<clipPath id="state-clip"><rect x="106" y="502" width="360" height="112"/></clipPath>',
        '<clipPath id="summary-clip"><rect x="554" y="238" width="540" height="126"/></clipPath>',
        '<clipPath id="evidence-clip"><rect x="550" y="470" width="224" height="126"/></clipPath>',
        '<clipPath id="confidence-clip"><rect x="858" y="470" width="224" height="112"/></clipPath>',
        '<clipPath id="footer-clip"><rect x="82" y="634" width="1036" height="44"/></clipPath>',
        '</defs>',
        '<rect width="1200" height="720" fill="#F6EBD8"/>',
        '<rect x="40" y="36" width="1120" height="648" rx="28" fill="#FFFDF8" stroke="#0B0A09" stroke-width="2"/>',
        line(82, 96, "情绪潮汐", 34, "#0B0A09", 700),
        line(82, 130, "基于本人当天消息的克制回顾", 18, "#605B52"),
        line(934, 96, date, 20, "#0B0A09", 600, 170, "date-clip"),
        '<line x1="82" y1="154" x2="1118" y2="154" stroke="#0B0A09" stroke-opacity="0.18"/>',
        '<rect x="82" y="184" width="420" height="228" rx="22" fill="#F4EEE2"/>',
        line(116, 228, "当日主情绪", 17, "#605B52", 500),
        line(116, 304, primary, 54, color, 700, 352, "emotion-clip"),
        line(116, 340, secondary_line, 18, "#403B35", 400, 352, "emotion-clip"),
        '<rect x="82" y="442" width="420" height="184" rx="22" fill="#F4EEE2"/>',
        line(116, 486, "状态刻度", 17, "#605B52", 500),
        line(116, 530, f"情绪强度  {intensity:.0%}", 21, "#0B0A09", 600, 348, "state-clip"),
        '<rect x="116" y="548" width="348" height="14" rx="7" fill="#DDD5C7"/>',
        f'<rect x="116" y="548" width="{348 * intensity:.1f}" height="14" rx="7" fill="{color}"/>',
        line(116, 604, f"覆盖：{label_for_coverage(coverage)}", 17, "#403B35", 400, 348, "state-clip"),
        '<rect x="532" y="184" width="586" height="202" rx="22" fill="#F4EEE2"/>',
        line(568, 228, "今日观察", 17, "#605B52", 500),
    ]
    for index, item in enumerate(wrap(summary, 516, 25, 3)):
        parts.append(line(568, 278 + index * 35, item, 25, "#0B0A09", 500, 516, "summary-clip"))
    parts += [
        '<rect x="532" y="416" width="278" height="210" rx="22" fill="#F4EEE2"/>',
        line(566, 460, "消息与证据", 17, "#605B52", 500),
        line(566, 520, compact_count(messages), 46, "#0B0A09", 700, 208, "evidence-clip"),
        line(566, 550, "条本人消息", 17, "#403B35", 400, 210, "evidence-clip"),
        line(566, 588, f"有效文本：{compact_count(effective)}", 18, "#403B35", 400, 210, "evidence-clip"),
        '<rect x="840" y="416" width="278" height="210" rx="22" fill="#EEE4D4"/>',
        line(874, 460, "分析可信度", 17, "#605B52", 500),
        line(874, 520, f"{confidence:.0%}", 46, color, 700, 192, "confidence-clip"),
        line(874, 566, "仅代表文本线索强弱", 17, "#403B35", 400, 210, "confidence-clip"),
    ]
    for index, item in enumerate(wrap(warm_words, 1036, 16, 2)):
        parts.append(line(82, 654 + index * 21, item, 16, "#403B35", 500, 1036, "footer-clip"))
    parts += [
        '</svg>',
    ]
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description="Render an Emotion Tide daily dashboard SVG from JSON stdin.")
    parser.add_argument("--output", required=True, help="Output SVG path")
    args = parser.parse_args()
    try:
        data = json.load(sys.stdin)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid analysis JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise SystemExit("Analysis JSON must be an object.")
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render(data), encoding="utf-8")


if __name__ == "__main__":
    main()
