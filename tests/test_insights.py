"""Metric requirements over saved history, without Qt or a model endpoint."""
from collections import Counter
from datetime import date, datetime, time, timedelta

from cryptography.fernet import Fernet

from flowwriter.insights import InsightRecord, UsageSummary, ranked_counts
from flowwriter.storage import Store


TODAY = date(2026, 11, 14)


def record(day=TODAY, status="generated", words=4, source="Scratchpad", action="Polish"):
    timestamp = datetime.combine(day, time(10)).astimezone().isoformat()
    return InsightRecord(1, timestamp, action, status, source, words)


def test_completed_words_used_results_and_outcomes_have_separate_denominators():
    summary = UsageSummary(TODAY)
    for status in ("generated", "replaced", "copied", "rejected", "failed", "cancelled"):
        summary.add(record(status=status))
    assert summary.completed == 4
    assert summary.words == 16  # Includes discarded generated output, not failed attempts.
    assert summary.used == 2
    assert summary.used_percent == 50
    assert sum(summary.outcomes.values()) == 6
    assert summary.sources == {"Scratchpad": 4}
    assert summary.actions == {"Polish": 4}
    assert summary.days == {TODAY: 4}


def test_empty_and_unreadable_content_never_count_placeholder_words():
    empty = UsageSummary(TODAY)
    assert empty.used_percent == 0
    assert empty.current_streak == empty.longest_streak == 0
    empty.add(record(source=None, words=None))
    empty.add(record(source="Readable source", words=3))
    assert empty.completed == 2
    assert empty.unreadable == 1
    assert empty.words == 3
    assert empty.sources == {"Readable source": 1}


def test_streaks_use_distinct_local_days_and_allow_yesterday():
    summary = UsageSummary(TODAY)
    for ago in (1, 2, 2, 3, 8, 9, 10, 11, 12):
        summary.add(record(TODAY - timedelta(days=ago)))
    assert summary.current_streak == 3
    assert summary.longest_streak == 5
    summary.add(record(TODAY))
    assert summary.current_streak == 4
    assert summary.longest_streak == 5
    stale = UsageSummary(TODAY + timedelta(days=3))
    stale.add(record(TODAY))
    assert stale.current_streak == 0


def test_dates_handle_local_midnight_future_rows_and_invalid_dates():
    from datetime import timezone
    local_midnight = datetime.combine(TODAY, time(0, 15)).astimezone()
    utc_timestamp = local_midnight.astimezone(timezone.utc).isoformat()
    summary = UsageSummary(TODAY)
    summary.add(InsightRecord(1, utc_timestamp, "Polish", "copied", "Notes", 4))
    summary.add(record(TODAY + timedelta(days=1)))
    summary.add(InsightRecord(3, "invalid", "Polish", "generated", "Notes", 2))
    assert summary.days == {TODAY: 1}
    assert summary.current_streak == 1


def test_ranking_preserves_tail_counts_and_uses_stable_ties():
    counts = Counter({"Zulu": 10, "Alpha": 10, "Gamma": 4, "Delta": 3, "Epsilon": 2, "Eta": 1, "Theta": 1})
    ranked = ranked_counts(counts)
    assert ranked[:2] == [("Alpha", 10), ("Zulu", 10)]
    assert ranked[-1] == ("Other", 2)
    assert sum(value for _, value in ranked) == sum(counts.values())


def test_storage_batches_cover_old_history_without_search_limit(tmp_path):
    store = Store(tmp_path / "history.db", Fernet(Fernet.generate_key()))
    try:
        for _ in range(805):
            store.log_action("Polish", source_app="Notes", output_text="one two three", status="copied")
        boundary = store.insight_boundary()
        store.log_action("Polish", output_text="Newer than the snapshot", status="copied")
        after = 0
        summary = UsageSummary(date.today())
        batch_sizes = []
        while after < boundary:
            rows = store.insight_batch(after, boundary)
            assert rows
            batch_sizes.append(len(rows))
            for row in rows:
                summary.add(row)
            after = rows[-1].id
        assert max(batch_sizes) <= 128
        assert summary.completed == 805
        assert summary.words == 805 * 3
        assert summary.sources == {"Notes": 805}
        store.clear_history()
        assert store.insight_boundary() == 0
        assert store.insight_batch(0, boundary) == []
    finally:
        store.close()


def test_storage_does_not_count_locked_or_corrupt_content(tmp_path):
    store = Store(tmp_path / "locked.db", Fernet(Fernet.generate_key()))
    try:
        store.log_action("Polish", source_app="Notes", output_text="Private output", status="copied")
        boundary = store.insight_boundary()
        for cipher in (None, Fernet(Fernet.generate_key())):
            store.cipher = cipher
            row = store.insight_batch(0, boundary)[0]
            assert row.source is None
            assert row.words is None
            assert row.status == "copied"
    finally:
        store.close()


def test_window_titles_are_grouped_by_app_with_the_document_kept_for_details():
    from flowwriter.insights import split_source
    assert split_source("Budget.xlsx - Excel") == ("Excel", "Budget.xlsx")
    assert split_source("Chat | Sam Rivera | Microsoft Teams") == ("Microsoft Teams", "Chat | Sam Rivera")
    assert split_source("Inbox - Alex - Outlook") == ("Outlook", "Inbox - Alex")
    assert split_source("Scratchpad") == ("Scratchpad", "")
    assert split_source("a - b - Microsoft\u200b Edge") == ("Microsoft Edge", "a - b")   # invisible characters ignored
    assert split_source("") == ("Untitled selection", "")


def test_several_windows_of_one_app_are_one_row_with_per_app_details():
    summary = UsageSummary(TODAY)
    summary.add(record(source="Q3.xlsx - Excel", action="Polish", words=10))
    summary.add(record(source="Budget.xlsx - Excel", action="Shorten", words=5, status="copied"))
    summary.add(record(source="Inbox - Alex - Outlook", words=7))
    assert summary.sources == {"Excel": 2, "Outlook": 1}
    excel = summary.apps["excel"]
    assert (excel.count, excel.words, excel.used) == (2, 15, 1)
    assert excel.documents == {"Q3.xlsx": 1, "Budget.xlsx": 1}
    assert excel.actions == {"Polish": 1, "Shorten": 1} and excel.last_day == TODAY


def test_apps_beyond_the_limit_are_combined_without_losing_counts():
    summary = UsageSummary(TODAY)
    for number in range(9):
        for _ in range(9 - number):
            summary.add(record(source=f"Doc - App{number}"))
    shown, other = summary.app_ranking(limit=6)
    assert len(shown) == 6 and other.name == "Other apps (3)"
    assert other.count == sum(a.count for a in summary.apps.values()) - sum(a.count for a in shown)
    assert [m.name for m in other.members] == ["App6", "App7", "App8"]
    assert summary.app_ranking(limit=20)[1] is None
