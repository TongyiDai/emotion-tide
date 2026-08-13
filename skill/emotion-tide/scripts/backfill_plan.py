#!/usr/bin/env python3
"""Plan a quarterly, workday-by-workday backfill for Emotion Tide.

The daily run analyses a single completed day. First-run provisioning creates an
empty Base, so the dashboard only becomes useful after weeks of daily runs. This
planner lets the agent seed the Base out of the box: it walks the past quarter,
reuses the exact official-calendar rules from `workday_gate.classify`, drops any
date already written to the Base (date-keyed upsert is idempotent, so this is
resumable across quota interruptions), and returns an ordered, oldest-first list
of workdays that still need analysis together with each day's message time
window.

The planner never touches the network and never reads message text. It only
turns configuration plus a list of already-present Base dates into a work plan.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from workday_gate import classify  # noqa: E402


def default_config_path() -> Path:
    return Path(os.environ.get("EMOTION_TIDE_CONFIG", "~/.config/emotion-tide/config.json")).expanduser()


def resolve_offset(config: dict, override: str | None) -> str:
    """Resolve a fixed UTC offset string like '+08:00'.

    Prefers an explicit override or a configured `workday_calendar.utc_offset`,
    then derives it from the IANA timezone via zoneinfo, and finally falls back
    to Asia/Shanghai's stable +08:00.
    """
    if override:
        return override
    calendar = config.get("workday_calendar") or {}
    if isinstance(calendar.get("utc_offset"), str) and calendar["utc_offset"].strip():
        return calendar["utc_offset"].strip()
    timezone = config.get("timezone") or "Asia/Shanghai"
    try:
        from zoneinfo import ZoneInfo

        offset = dt.datetime.now(ZoneInfo(str(timezone))).utcoffset()
        if offset is not None:
            total = int(offset.total_seconds())
            sign = "+" if total >= 0 else "-"
            total = abs(total)
            return f"{sign}{total // 3600:02d}:{(total % 3600) // 60:02d}"
    except Exception:
        pass
    return "+08:00"


def load_done_dates(path: Path | None) -> set[str]:
    """Load ISO dates already present in the Base from a JSON array or line list."""
    if path is None:
        return set()
    text = path.expanduser().read_text(encoding="utf-8").strip()
    if not text:
        return set()
    done: set[str] = set()
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = [line.strip() for line in text.splitlines()]
    if isinstance(parsed, dict):
        parsed = parsed.get("dates") or parsed.get("done") or []
    for item in parsed if isinstance(parsed, list) else []:
        value = str(item).strip()
        if not value:
            continue
        try:
            done.add(dt.date.fromisoformat(value).isoformat())
        except ValueError:
            continue
    return done


def daterange(start: dt.date, end: dt.date):
    day = start
    while day <= end:
        yield day
        day += dt.timedelta(days=1)


def plan(config: dict, *, as_of: dt.date, start: dt.date, end: dt.date, offset: str, done: set[str], limit: int | None) -> dict:
    counts = {"total_days": 0, "workdays": 0, "non_workdays": 0, "unknown": 0, "already_done": 0}
    pending: list[dict] = []
    unknown_dates: list[str] = []
    for day in daterange(start, end):
        counts["total_days"] += 1
        verdict = classify(day, config)
        status = str(verdict.get("status"))
        if status == "non_workday":
            counts["non_workdays"] += 1
            continue
        if status == "unknown":
            counts["unknown"] += 1
            unknown_dates.append(day.isoformat())
            continue
        counts["workdays"] += 1
        iso = day.isoformat()
        if iso in done:
            counts["already_done"] += 1
            continue
        next_day = (day + dt.timedelta(days=1)).isoformat()
        pending.append(
            {
                "date": iso,
                "start": f"{iso}T00:00:00{offset}",
                "end": f"{next_day}T00:00:00{offset}",
                "reason": str(verdict.get("reason")),
            }
        )
    total_pending = len(pending)
    remaining_after_limit = 0
    if limit is not None and limit >= 0 and total_pending > limit:
        remaining_after_limit = total_pending - limit
        pending = pending[:limit]
    counts["pending"] = total_pending
    return {
        "as_of": as_of.isoformat(),
        "window": {"start": start.isoformat(), "end": end.isoformat()},
        "timezone": config.get("timezone"),
        "utc_offset": offset,
        "calendar_complete": not unknown_dates,
        "counts": counts,
        "batch_size": limit,
        "batch_pending": len(pending),
        "remaining_after_limit": remaining_after_limit,
        "pending": pending,
        "unknown_dates": unknown_dates,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="Plan a quarterly workday backfill for Emotion Tide.")
    parser.add_argument("--config", type=Path, default=default_config_path())
    parser.add_argument("--as-of", default=dt.date.today().isoformat(), help="Reference date (YYYY-MM-DD); default today")
    parser.add_argument("--lookback-days", type=int, default=90, help="Days to look back from --as-of (default 90 ~ one quarter)")
    parser.add_argument("--start", help="Explicit inclusive window start (YYYY-MM-DD); overrides --lookback-days")
    parser.add_argument("--end", help="Explicit inclusive window end (YYYY-MM-DD); default is the day before --as-of")
    parser.add_argument("--done-dates-file", type=Path, help="JSON array or newline list of ISO dates already in the Base")
    parser.add_argument("--utc-offset", help="Fixed offset like +08:00; default derived from config timezone")
    parser.add_argument("--limit", type=int, help="Return at most N oldest pending workdays for batched processing")
    args = parser.parse_args()
    try:
        config = json.loads(args.config.expanduser().read_text(encoding="utf-8"))
        as_of = dt.date.fromisoformat(args.as_of)
        end = dt.date.fromisoformat(args.end) if args.end else as_of - dt.timedelta(days=1)
        if args.start:
            start = dt.date.fromisoformat(args.start)
        else:
            start = end - dt.timedelta(days=max(0, args.lookback_days) - 1)
        if start > end:
            raise ValueError("window start must not be after window end")
        offset = resolve_offset(config, args.utc_offset)
        done = load_done_dates(args.done_dates_file)
        result = plan(config, as_of=as_of, start=start, end=end, offset=offset, done=done, limit=args.limit)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(json.dumps({"ok": False, "error": str(exc)}, ensure_ascii=False), file=sys.stderr)
        raise SystemExit(2) from exc
    print(json.dumps(result, ensure_ascii=False, indent=2))
    raise SystemExit(0 if result["calendar_complete"] else 5)


if __name__ == "__main__":
    main()
