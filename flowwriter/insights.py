"""Pure aggregation of saved transformations, independent of storage and Qt."""
from __future__ import annotations

from collections import Counter
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
import re


COMPLETED_STATUSES = frozenset({"generated", "replaced", "copied", "rejected"})

_INVISIBLE = re.compile("[​-‏⁠﻿­]")
_SEPARATORS = (" - ", " – ", " — ", " | ")


def split_source(source: str) -> tuple[str, str]:
    """Window title -> (app, document). 'Budget.xlsx - Excel' -> ('Excel', 'Budget.xlsx').

    Windows apps put their own name at the end of the title ("Inbox - Name - Outlook",
    "Chat | Name | Microsoft Teams"), so the last segment is the app. A title with no
    separator, such as "Scratchpad" or "Calculator", is its own app.
    """
    text = " ".join(_INVISIBLE.sub("", source or "").split())
    if not text:
        return "Untitled selection", ""
    cut = max(((text.rfind(sep), sep) for sep in _SEPARATORS), key=lambda pair: pair[0])
    if cut[0] > 0:
        app, document = text[cut[0] + len(cut[1]):].strip(), text[:cut[0]].strip()
        if app and len(app) <= 40:
            return app, document
    return (text if len(text) <= 40 else text[:39] + "…"), ""


@dataclass(frozen=True)
class InsightRecord:
    id: int
    created_at: str
    action: str
    status: str
    source: str | None
    words: int | None


@dataclass
class AppStats:
    """Everything saved about writing in one app, for the detail view."""
    name: str
    count: int = 0
    words: int = 0
    used: int = 0
    last_day: date | None = None
    actions: Counter[str] = field(default_factory=Counter)
    documents: Counter[str] = field(default_factory=Counter)
    days: Counter[date] = field(default_factory=Counter)
    members: list["AppStats"] = field(default_factory=list)   # only for the combined "Other apps" entry

    @property
    def used_percent(self) -> float:
        return self.used / self.count * 100 if self.count else 0.0

    def add(self, record: InsightRecord, document: str, day: date | None) -> None:
        self.count += 1
        self.words += record.words or 0
        self.used += record.status in {"replaced", "copied"}
        self.actions[record.action] += 1
        if document:
            self.documents[document] += 1
        if day is not None:
            self.days[day] += 1
            if self.last_day is None or day > self.last_day:
                self.last_day = day


def combine_apps(name: str, apps: list[AppStats]) -> AppStats:
    total = AppStats(name, members=list(apps))
    for app in apps:
        total.count += app.count
        total.words += app.words
        total.used += app.used
        total.actions.update(app.actions)
        total.days.update(app.days)
        if app.last_day and (total.last_day is None or app.last_day > total.last_day):
            total.last_day = app.last_day
    return total


@dataclass
class UsageSummary:
    today: date
    completed: int = 0
    words: int = 0
    used: int = 0
    unreadable: int = 0
    days: Counter[date] = field(default_factory=Counter)
    sources: Counter[str] = field(default_factory=Counter)    # per app, not per window title
    apps: dict[str, AppStats] = field(default_factory=dict)   # keyed by lower-case app name
    actions: Counter[str] = field(default_factory=Counter)
    outcomes: Counter[str] = field(default_factory=Counter)

    def add(self, record: InsightRecord) -> None:
        self.outcomes[record.status] += 1
        if record.status not in COMPLETED_STATUSES:
            return
        self.completed += 1
        self.used += record.status in {"replaced", "copied"}
        self.actions[record.action] += 1
        try:
            day = datetime.fromisoformat(record.created_at).astimezone().date()
        except ValueError:
            day = None
        if day is not None and day > self.today:
            day = None
        if record.words is None or record.source is None:
            self.unreadable += 1
        else:
            self.words += record.words
            app, document = split_source(record.source)
            stats = self.apps.setdefault(app.casefold(), AppStats(app))
            stats.add(record, document, day)
            self.sources[stats.name] += 1
        if day is not None:
            self.days[day] += 1

    def app_ranking(self, limit: int = 6) -> tuple[list[AppStats], AppStats | None]:
        """The busiest apps, plus one combined entry for the rest (None when everything fits)."""
        ranked = sorted(self.apps.values(), key=lambda a: (-a.count, a.name.casefold()))
        if len(ranked) <= limit:
            return ranked, None
        return ranked[:limit], combine_apps(f"Other apps ({len(ranked) - limit})", ranked[limit:])

    @property
    def used_percent(self) -> float:
        return self.used / self.completed * 100 if self.completed else 0.0

    @property
    def current_streak(self) -> int:
        day = self.today
        if day not in self.days:
            day -= timedelta(days=1)
        count = 0
        while day in self.days:
            count += 1
            day -= timedelta(days=1)
        return count

    @property
    def longest_streak(self) -> int:
        longest = run = 0
        previous = None
        for day in sorted(self.days):
            run = run + 1 if previous == day - timedelta(days=1) else 1
            longest = max(longest, run)
            previous = day
        return longest


def ranked_counts(counts: Mapping[str, int], limit: int = 5) -> list[tuple[str, int]]:
    """Keep the comparison compact without losing counts in the denominator."""
    items = sorted(counts.items(), key=lambda pair: (-pair[1], pair[0].casefold()))
    if len(items) <= limit:
        return items
    return items[:limit] + [("Other", sum(value for _, value in items[limit:]))]
