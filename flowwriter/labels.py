"""One place for the words and date format the interface shows.

Status values are stored in the database as lowercase keys. Every screen shows
them through STATUS_LABELS, so the same state never has two names.
"""
from __future__ import annotations
from datetime import datetime

STATUS_LABELS = {
    "generated": "Generated",
    "replaced": "Replaced",
    "copied": "Copied",
    "rejected": "Discarded",
    "cancelled": "Cancelled",
    "failed": "Failed",
}
STATUS_ORDER = list(STATUS_LABELS)

# Overview counters: stored key -> short caption shown next to the number.
METRIC_CAPTIONS = {
    "total": "transformations",
    "applied": "replaced in source",
    "copied": "copied to clipboard",
    "rejected": "discarded",
}


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, (status or "").title())


def _clock(dt: datetime) -> str:
    return dt.strftime("%I:%M %p").lstrip("0")


def day_text(iso: str, now: datetime | None = None) -> str:
    """'Today', 'Yesterday', 'Nov 12' (or 'Nov 12, 2025' for another year)."""
    try:
        dt = datetime.fromisoformat(iso).astimezone()
    except ValueError:
        return iso
    today = (now or datetime.now().astimezone()).astimezone().date()
    days = (today - dt.date()).days
    if days == 0:
        return "Today"
    if days == 1:
        return "Yesterday"
    stamp = dt.strftime("%b %d").replace(" 0", " ")
    return stamp if dt.year == today.year else f"{stamp}, {dt.year}"


def clock_text(iso: str) -> str:
    try:
        return _clock(datetime.fromisoformat(iso).astimezone())
    except ValueError:
        return ""


def when(iso: str, now: datetime | None = None) -> str:
    """One format everywhere: 'Today 12:54 PM', 'Yesterday 9:05 AM', 'Nov 12 · 12:54 PM'."""
    day = day_text(iso, now)
    clock = clock_text(iso)
    if not clock:
        return iso
    return f"{day} {clock}" if day in ("Today", "Yesterday") else f"{day} · {clock}"
