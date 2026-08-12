#!/usr/bin/env python3
"""Resolve a date against an explicit official workday calendar."""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
from pathlib import Path


def default_config_path() -> Path:
    return Path(os.environ.get("EMOTION_TIDE_CONFIG", "~/.config/emotion-tide/config.json")).expanduser()


def classify(day: dt.date, config: dict) -> dict[str, object]:
    calendar = config.get("workday_calendar") or {}
    configured_year = calendar.get("year")
    iso = day.isoformat()
    result: dict[str, object] = {
        "date": iso,
        "calendar_year": configured_year,
        "source_url": calendar.get("source_url"),
    }
    if configured_year != day.year:
        return {**result, "status": "unknown", "reason": "calendar_year_missing"}
    workdays = set(calendar.get("workdays") or [])
    holidays = set(calendar.get("holidays") or [])
    if iso in workdays:
        return {**result, "status": "workday", "reason": "official_makeup_workday"}
    if iso in holidays:
        return {**result, "status": "non_workday", "reason": "official_holiday"}
    if day.weekday() >= 5:
        return {**result, "status": "non_workday", "reason": "weekend"}
    return {**result, "status": "workday", "reason": "weekday"}


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether a date is an official workday.")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--date", default=dt.date.today().isoformat(), help="YYYY-MM-DD")
    args = parser.parse_args()
    try:
        day = dt.date.fromisoformat(args.date)
        config = json.loads(args.config.expanduser().read_text(encoding="utf-8"))
    except (ValueError, OSError, json.JSONDecodeError) as exc:
        print(json.dumps({"status": "unknown", "reason": "invalid_input", "detail": str(exc)}, ensure_ascii=False))
        raise SystemExit(4) from exc
    result = classify(day, config)
    print(json.dumps(result, ensure_ascii=False))
    raise SystemExit({"workday": 0, "non_workday": 3, "unknown": 4}[str(result["status"])])


if __name__ == "__main__":
    main()
