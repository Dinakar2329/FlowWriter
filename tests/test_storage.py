from __future__ import annotations
from cryptography.fernet import Fernet
from flowwriter.storage import Store
from flowwriter.domain import Action, Provider


def test_encrypted_history_and_readback(tmp_path):
    store = Store(tmp_path / "a" / "app.sqlite", Fernet(Fernet.generate_key()))
    assert len(store.actions()) == 13  # 12 presets + Prompt
    assert store.active_profile().name == "Local Ollama"
    key_phrase = "internal private text 🚀"
    rid = store.log_action("Refine", source_app="Private Deal Room", input_text=key_phrase, output_text="Hello world", instruction="Be clear")
    assert rid
    raw = (tmp_path / "a" / "app.sqlite").read_bytes()
    assert key_phrase.encode() not in raw
    assert b"Hello world" not in raw
    assert b"Private Deal Room" not in raw
    records = store.recent(query="private")
    assert len(records) == 1
    assert records[0]["input_text"] == key_phrase
    assert records[0]["source_app"] == "Private Deal Room"
    store.update_history(rid, "replaced", output_text="Adjusted")
    assert store.recent()[0]["status"] == "replaced"
    assert store.stats()["applied"] == 1
    store.close()


def test_history_privacy_and_no_key(tmp_path):
    store = Store(tmp_path / "n.sqlite", None)
    assert store.log_action("Custom", input_text="secret") is None
    store.close()
    store = Store(tmp_path / "n.sqlite", Fernet(Fernet.generate_key()))
    store.set_pref("private_mode", "true")
    assert store.log_action("Custom", input_text="secret") is None
    store.set_pref("private_mode", "false")
    store.set_pref("save_history", "false")
    assert store.log_action("Custom", input_text="secret") is None
    assert store.stats()["total"] == 0
    store.close()


def test_actions_profiles_delete_and_reopen(tmp_path):
    path = tmp_path / "app.sqlite"
    cipher = Fernet(Fernet.generate_key())
    store = Store(path, cipher)
    store.save_action(Action("a2", "Translate", "Translate to Hindi.", 1, 3))
    store.save_profile(Provider("p2", "Remote", "https://example.org/v1", "any-id", False))
    store.set_pref("active_profile", "p2")
    store.log_action("Translate", input_text="hello", output_text="नमस्ते")
    store.close()
    store = Store(path, cipher)
    assert store.active_profile().model == "any-id"
    assert any(a.name == "Translate" for a in store.actions())
    assert store.recent()[0]["output_text"] == "नमस्ते"
    store.delete_profile("p2")
    assert store.active_profile().id == "local-default"
    store.clear_history()
    assert store.stats()["total"] == 0
    store.close()


def test_cannot_delete_last_provider(tmp_path):
    store = Store(tmp_path / "x.sqlite", Fernet(Fernet.generate_key()))
    import pytest
    with pytest.raises(ValueError, match="at least one"):
        store.delete_profile("local-default")
    store.close()


def test_history_pages_keep_ties_stable_and_have_no_search_cap(tmp_path):
    store = Store(tmp_path / "pages.sqlite", Fernet(Fernet.generate_key()))
    try:
        for i in range(815):
            store.log_action("Polish", input_text=f"Draft {i}", output_text=f"Result {i}")
        cursor, ids = None, []
        while True:
            page = store.history_page(cursor)
            if not page:
                break
            ids.extend(row["id"] for row in page)
            assert page[0]["output_text"].startswith("Result ")
            cursor = page[-1]["created_at"], page[-1]["id"]
        assert len(ids) == len(set(ids)) == 815
        assert ids == sorted(ids, reverse=True)
        store.clear_history()
        assert store.history_page(cursor) == []
    finally:
        store.close()


def test_history_page_offset_matches_cursor_paging_and_count(tmp_path):
    store = Store(tmp_path / "pages.sqlite", Fernet(Fernet.generate_key()))
    for i in range(23):
        store.log_action("Polish", input_text=f"in {i}", output_text=f"out {i}")
    assert store.history_count() == 23
    pages = [store.history_page(limit=10, offset=n * 10) for n in range(3)]
    assert [len(p) for p in pages] == [10, 10, 3]
    ids = [r["id"] for p in pages for r in p]
    assert ids == sorted(ids, reverse=True) and len(set(ids)) == 23
    assert store.history_page(limit=10, offset=30) == []
    assert store.history_page(limit=10, offset=-5)[0]["id"] == ids[0]
    store.close()


def _filled(tmp_path, count=45):
    store = Store(tmp_path / "f.db", Fernet(Fernet.generate_key()))
    for i in range(count):
        store.log_action(
            "Polish" if i % 2 else "Summarize", source_app=f"App {i}", model="m1",
            input_text=f"input number {i}", output_text="needle text" if i == 3 else f"output {i}",
            instruction="Do it.", status="copied" if i % 5 == 0 else "generated",
        )
    return store


def test_search_finds_old_entries_beyond_any_record_limit(tmp_path):
    store = _filled(tmp_path)
    ids = store.search_history_ids("needle")
    assert len(ids) == 1
    # The oldest rows are reachable: the old screen only looked at the latest 800.
    oldest = store.search_history_ids("input number 0")
    assert store.history_rows(oldest)[0]["input_text"] == "input number 0"
    assert len(store.search_history_ids("")) == 45
    assert len(store.search_history_ids("", status="copied")) == 9
    assert store.search_history_ids("needle", status="copied") == []   # entry 3 is "generated"
    store.close()


def test_search_reports_progress_and_can_be_cancelled(tmp_path):
    import threading
    store = _filled(tmp_path, 250)
    steps = []
    assert len(store.search_history_ids("output", progress=lambda done, total: steps.append((done, total)))) == 249
    assert steps[-1] == (250, 250) and len(steps) == 3
    stop = threading.Event()
    stop.set()
    assert store.search_history_ids("output", cancel=stop) is None
    store.close()


def test_status_filter_counts_and_pages(tmp_path):
    store = _filled(tmp_path)
    assert store.history_count("copied") == 9 and store.history_count() == 45
    page = store.history_page(limit=5, offset=5, status="copied")
    assert len(page) == 4 and all(r["status"] == "copied" for r in page)
    assert store.history_rows([]) == []
    ids = [r["id"] for r in store.history_page(limit=3)]
    assert [r["id"] for r in store.history_rows(list(reversed(ids)))] == list(reversed(ids))
    store.close()


def test_daily_counts_read_only_timestamps(tmp_path, monkeypatch):
    store = _filled(tmp_path, 12)
    decrypted = []
    monkeypatch.setattr(store, "_decrypt", lambda data: decrypted.append(1) or "")
    counts = store.daily_counts(7)
    assert sum(counts.values()) == 12 and not decrypted      # nothing was decrypted for the chart
    store.close()


def test_a_page_decrypts_only_its_own_rows(tmp_path, monkeypatch):
    store = _filled(tmp_path, 60)
    decrypted = []
    real = store._decrypt
    monkeypatch.setattr(store, "_decrypt", lambda data: decrypted.append(1) or real(data))
    store.history_page(limit=10)
    assert len(decrypted) <= 40                               # 10 rows x 4 encrypted fields
    store.close()


def _old_v1_db(path, cipher):
    """A database as the previous release left it: 12 presets, user_version 1, no Prompt."""
    store = Store(path, cipher)
    with store.conn:
        store.conn.execute("DELETE FROM actions WHERE id='built-in-prompt'")
        store.conn.execute("PRAGMA user_version=1")
    store.close()


def test_prompt_action_is_added_to_the_front_of_an_existing_database_once(tmp_path):
    cipher = Fernet(Fernet.generate_key())
    path = tmp_path / "old.sqlite"
    _old_v1_db(path, cipher)
    store = Store(path, cipher)
    prompts = [a for a in store.actions() if a.name == "Prompt"]
    assert len(prompts) == 1 and prompts[0].face == 0 and prompts[0].position == 6
    assert "do NOT answer it" in prompts[0].prompt and "## Output format" in prompts[0].prompt
    store.delete_action(prompts[0].id)       # the user removes it: it must stay removed
    store.close()
    store = Store(path, cipher)
    assert not any(a.name == "Prompt" for a in store.actions())
    store.close()


def test_migration_does_not_duplicate_or_overwrite_the_users_own_prompt_action(tmp_path):
    cipher = Fernet(Fernet.generate_key())
    path = tmp_path / "mine.sqlite"
    _old_v1_db(path, cipher)
    store = Store(path, cipher)
    store.delete_action("built-in-prompt")
    store.save_action(Action("mine", "prompt", "My own wording", 1, 0))
    with store.conn:
        store.conn.execute("PRAGMA user_version=1")
    store.close()
    store = Store(path, cipher)
    found = [a for a in store.actions() if a.name.casefold() == "prompt"]
    assert [(a.id, a.prompt, a.face) for a in found] == [("mine", "My own wording", 1)]
    store.close()
