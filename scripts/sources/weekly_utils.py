from __future__ import annotations

from datetime import date, timedelta


def latest_completed_week_ending(today: date | None = None, week_ending_weekday: int = 5) -> date:
    """Return the latest completed week-ending date.

    Python weekdays use Monday=0. The Weekly Scorecard currently uses Saturday
    week-ending dates, so the default is 5.
    """

    current = today or date.today()
    days_since_week_end = (current.weekday() - week_ending_weekday) % 7
    candidate = current - timedelta(days=days_since_week_end)
    if candidate == current:
        return candidate
    return candidate


def weekly_date_range(
    today: date | None = None,
    week_ending_weekday: int = 5,
) -> dict[str, str]:
    end = latest_completed_week_ending(today, week_ending_weekday)
    start = end - timedelta(days=6)
    return {
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "scorecard_date": end.isoformat(),
    }
