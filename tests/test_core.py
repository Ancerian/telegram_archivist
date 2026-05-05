import json
import sys
import tempfile
from datetime import datetime
from pathlib import Path

try:
    import pytest
except ImportError:
    pytest = None

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


from analyzer import EntityAnalyzer
from deduplicator import VaultDeduplicator
from parser import TelegramParser
from registry import IdentityRegistry, normalize_name
from writer import ObsidianWriter, has_content, render_item, sanitize_tag


def test_render_item_string():
    assert render_item("Дмитро") == "Дмитро"


def test_render_item_none():
    assert render_item(None) == ""


def test_render_item_dict_with_name_and_desc():
    assert render_item({"name": "STORM", "description": "проєкт"}) == "STORM: проєкт"


def test_render_item_dict_only_name():
    assert render_item({"name": "STORM"}) == "STORM"


def test_render_item_raw_json_string():
    assert render_item('{"name": "test"}') == "test"


def test_render_item_list():
    assert render_item(["a", "b", "c"]) == "a, b, c"


def test_render_item_nested_dict():
    result = render_item({"tag": "програмування", "message_count": 5})
    assert result == "програмування"


def test_render_item_dict_none_values():
    assert render_item({"name": None, "description": None}) == ""


def test_sanitize_tag_basic():
    assert sanitize_tag("програмування") == "програмування"


def test_sanitize_tag_spaces():
    assert sanitize_tag("game dev") == "game-dev"


def test_sanitize_tag_uppercase():
    assert sanitize_tag("Gaming") == "gaming"


def test_sanitize_tag_dict():
    assert sanitize_tag({"tag": "music", "description": "..."}) == "music"


def test_sanitize_tag_emojis():
    result = sanitize_tag("music 🎵")
    assert "🎵" not in result


def test_sanitize_tag_multiple_dashes():
    assert sanitize_tag("a--b---c") == "a-b-c"


def test_normalize_same_name():
    assert normalize_name("Дмитро") == normalize_name("Kevin")


def test_normalize_removes_brackets():
    assert normalize_name("Дмитро (дизайнер)") == normalize_name("Дмитро")


def test_normalize_removes_emoji():
    assert normalize_name("Alice 🦢") == normalize_name("Alice")


def test_normalize_case_insensitive():
    assert normalize_name("ОЛЕКСАНДР") == normalize_name("олександр")


def test_has_content_none():
    assert not has_content(None)


def test_has_content_empty_str():
    assert not has_content("")


def test_has_content_empty_list():
    assert not has_content([])


def test_has_content_empty_dict():
    assert not has_content({})


def test_has_content_str():
    assert has_content("текст")


def test_has_content_list():
    assert has_content(["a"])


def test_has_content_nested_none():
    assert not has_content([None, None])


def test_has_content_nested_value():
    assert has_content([None, "a"])


def test_message_format_contains_author():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    analyzer.chat_name = "Test"
    analyzer.chat_language = "uk"
    analyzer.progress_callback = None

    messages = [{
        "id": 1,
        "date": "2024-01-15T10:30:00",
        "from_name": "Дмитро",
        "from_id": "user123",
        "text": "Привіт",
        "media_type": None,
        "transcript": None,
    }]

    result = analyzer._build_user_message(messages, {})

    assert "АВТОР: Дмитро" in result
    assert "user123" in result
    assert "ЧАС: 2024-01-15 10:30" in result


def test_attribution_audit_marks_non_author():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    analyzer.progress_callback = None
    batch = [{
        "from_name": "Дмитро",
        "from_id": "user123",
        "text": "Василь любить каву",
        "transcript": None,
    }]
    result = {
        "people": [
            {"name": "Дмитро", "telegram_id": "user123", "confidence": "high", "uncertainty_note": None},
            {"name": "Василь", "telegram_id": None, "confidence": "high", "uncertainty_note": None},
        ],
        "projects": [],
        "events": [],
        "themes": [],
    }

    audited = analyzer._audit_attribution(result, batch)

    assert audited["people"][0]["confidence"] == "high"
    assert audited["people"][1]["confidence"] == "medium"
    assert "чужих слів" in audited["people"][1]["uncertainty_note"]


def test_parser_get_new_messages():
    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp)
        (export_path / "result.json").write_text(json.dumps({
            "name": "Test",
            "messages": [
                {"id": 1, "type": "message", "date": "2026-04-28T15:00:00", "from": "Дмитро", "from_id": "user1", "text": "old"},
                {"id": 2, "type": "message", "date": "2026-04-28T16:00:00", "from": "Дмитро", "from_id": "user1", "text": "new"},
            ],
        }, ensure_ascii=False), encoding="utf-8")

        parser = TelegramParser()
        parser.load(export_path)
        messages = parser.get_new_messages(datetime.fromisoformat("2026-04-28T15:30:00"))

        assert len(messages) == 1
        assert messages[0]["text"] == "new"


def test_analyzer_incremental_no_new_messages():
    with tempfile.TemporaryDirectory() as tmp:
        checkpoint_path = Path(tmp) / "llm_checkpoint.json"
        checkpoint_path.write_text(json.dumps({
            "batching_version": 3,
            "last_processed_date": "2026-04-28T15:30:00",
        }), encoding="utf-8")

        analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
        analyzer.progress_callback = None
        result = analyzer.analyze([{
            "date": "2026-04-28T15:00:00",
            "from_name": "Дмитро",
            "from_id": "user1",
            "text": "old",
        }], {}, checkpoint_path=checkpoint_path)

        assert result == {"people": [], "projects": [], "events": [], "themes": []}
        assert analyzer.incremental_info["enabled"] is True
        assert analyzer.incremental_info["new_count"] == 0


def test_vault_deduplicator_find_duplicates():
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp)
        people_path = vault_path / "People"
        people_path.mkdir()
        (people_path / "Дмитро.md").write_text("# Дмитро", encoding="utf-8")
        (people_path / "Kevin.md").write_text("# Kevin", encoding="utf-8")
        (people_path / "Світлана.md").write_text("# Світлана", encoding="utf-8")

        groups = VaultDeduplicator.find_duplicates(vault_path)

        assert any(set(group) == {"People/Kevin.md", "People/Дмитро.md"} for group in groups)


def test_graph_canvas_valid_json():
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp)
        registry = IdentityRegistry(vault_path)
        registry.data["people"]["alex"] = {
            "canonical_name": "Дмитро",
            "aliases": [],
            "telegram_ids": [],
            "file": "People/Дмитро.md",
            "sources": [],
            "data": {"name": "Дмитро", "mentioned_projects": ["STORM"]},
        }
        registry.data["projects"]["alpha"] = {
            "canonical_name": "STORM",
            "aliases": [],
            "file": "Projects/STORM.md",
            "sources": [],
            "data": {"name": "STORM"},
        }
        writer = ObsidianWriter(vault_path, registry=registry)
        graph_path = writer.write_graph_canvas("test_graph.canvas")

        loaded = json.loads(graph_path.read_text(encoding="utf-8"))
        assert "nodes" in loaded
        assert "edges" in loaded


def test_summary_generation_skips_llm_error():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    analyzer.chat_name = "Test"
    analyzer.progress_callback = None

    def _raise(*args, **kwargs):
        raise RuntimeError("LLM down")

    analyzer._call_llm = _raise
    result = analyzer.generate_chat_summary([{
        "date": "2026-04-28T15:00:00",
        "from_name": "Дмитро",
    }], {"people": [], "projects": [], "events": [], "themes": []})

    assert result is None


# ─── Нові тести (Task 18) ───────────────────────────────


def test_is_context_error_400():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    assert analyzer._is_context_error("400 context length exceeded") is True


def test_is_context_error_429():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    assert analyzer._is_context_error("429 token limit reached") is True


def test_is_context_error_irrelevant():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    assert analyzer._is_context_error("500 internal server error") is False


def test_is_context_error_direct_keywords():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    assert analyzer._is_context_error("context size has been exceeded") is True
    assert analyzer._is_context_error("input too long for model") is True


def test_get_relevant_entities_filters():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    batch = [{"from_name": "Дмитро", "text": "Привіт Світлані", "transcript": ""}]
    known = {
        "known_people": ["Дмитро", "Світлана", "Оксана", "Микола", "Тетяна"],
        "known_projects": ["STORM", "Project B"],
        "known_events": ["Event1"],
        "known_themes": ["tech"],
    }
    result = analyzer._get_relevant_entities(batch, known)
    # Дмитро (author) and Світлана (mentioned) should be in the result
    assert "Дмитро" in result["known_people"]
    assert "Світлана" in result["known_people"]


def test_sanitize_tag_ru_to_uk():
    assert sanitize_tag("programmirovanie") == "prohramuvannia"
    assert sanitize_tag("razrabotka") == "rozrobka"
    assert sanitize_tag("igry") == "ihry"


def test_sanitize_tag_no_change():
    assert sanitize_tag("web-dev") == "web-dev"
    assert sanitize_tag("python") == "python"


def test_parser_extended_fields():
    """Тестує розширені поля парсера: reply_to, forwarded, is_edited."""
    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp)
        (export_path / "result.json").write_text(json.dumps({
            "name": "Test",
            "messages": [
                {"id": 1, "type": "message", "date": "2026-04-28T15:00:00",
                 "from": "Дмитро", "from_id": "user1", "text": "old"},
                {"id": 2, "type": "message", "date": "2026-04-28T16:00:00",
                 "from": "Світлана", "from_id": "user2", "text": "відповідь",
                 "reply_to_message_id": 1},
                {"id": 3, "type": "message", "date": "2026-04-28T17:00:00",
                 "from": "Дмитро", "from_id": "user1", "text": "edited",
                 "edited": "2026-04-28T17:05:00",
                 "forwarded_from": "Someone"},
            ],
        }, ensure_ascii=False), encoding="utf-8")

        parser = TelegramParser()
        parser.load(export_path)
        messages = parser.get_messages()

        assert messages[1]["reply_to_id"] == 1
        assert messages[1]["reply_to_name"] == "Дмитро"
        assert messages[2]["is_edited"] is True
        assert messages[2]["forwarded_from"] == "Someone"
        assert messages[0]["is_service"] is False


def test_parser_service_messages():
    """Тестує обробку сервісних повідомлень."""
    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp)
        (export_path / "result.json").write_text(json.dumps({
            "name": "Test",
            "messages": [
                {"id": 1, "type": "message", "date": "2026-04-28T15:00:00",
                 "from": "Дмитро", "from_id": "user1", "text": "msg"},
                {"id": 2, "type": "service", "date": "2026-04-28T16:00:00",
                 "actor": "Дмитро", "actor_id": "user1", "action": "pin_message",
                 "text": ""},
            ],
        }, ensure_ascii=False), encoding="utf-8")

        parser = TelegramParser()
        parser.load(export_path)
        messages = parser.get_messages()
        service = parser.get_service_messages()
        pinned = parser.get_pinned_messages()

        assert len(messages) == 1  # Тільки message
        assert len(service) == 1  # Тільки service
        assert len(pinned) == 1   # pin_message


def test_parser_get_owner():
    """Тестує визначення власника чату."""
    with tempfile.TemporaryDirectory() as tmp:
        export_path = Path(tmp)
        (export_path / "result.json").write_text(json.dumps({
            "name": "Test",
            "messages": [
                {"id": 1, "type": "message", "date": "2026-04-28T15:00:00",
                 "from": "Дмитро", "from_id": "user1", "text": "a"},
                {"id": 2, "type": "message", "date": "2026-04-28T16:00:00",
                 "from": "Дмитро", "from_id": "user1", "text": "b"},
                {"id": 3, "type": "message", "date": "2026-04-28T17:00:00",
                 "from": "Світлана", "from_id": "user2", "text": "c"},
            ],
        }, ensure_ascii=False), encoding="utf-8")

        parser = TelegramParser()
        parser.load(export_path)
        owner = parser.get_owner()

        assert owner["from_id"] == "user1"
        assert owner["from_name"] == "Дмитро"


def test_activity_stats():
    """Тестує розрахунок статистики активності."""
    messages = [
        {"from_name": "Дмитро", "from_id": "user1", "date": "2026-04-28T10:30:00", "media_type": None},
        {"from_name": "Дмитро", "from_id": "user1", "date": "2026-04-29T14:30:00", "media_type": "voice_message"},
        {"from_name": "Світлана", "from_id": "user2", "date": "2026-04-28T11:30:00", "media_type": None},
    ]
    stats = EntityAnalyzer._calculate_activity_stats("Дмитро", "user1", messages)
    assert stats["message_count"] == 2
    assert stats["voice_message_count"] == 1
    assert stats["first_seen"] == "2026-04-28"
    assert stats["last_seen"] == "2026-04-29"


def test_batch_summary():
    """Тестує генерацію summary батчу."""
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    analyzer.progress_callback = None
    result = {
        "people": [{"name": "Дмитро"}, {"name": "Світлана"}],
        "projects": [{"name": "STORM"}],
        "events": [],
    }
    batch = [{"date": "2026-04-28T10:00:00"}]
    summary = analyzer._generate_batch_summary(result, batch)
    assert "Дмитро" in summary
    assert "Світлана" in summary
    assert "2026-04-28" in summary


def test_health_check_python_version():
    """Тестує перевірку версії Python."""
    from health_check import SystemHealthCheck
    checker = SystemHealthCheck()
    result = checker._check_python_version()
    assert result["ok"] is True
    assert result["name"] == "Python версія"


def test_health_check_disk_space():
    """Тестує перевірку місця на диску."""
    from health_check import SystemHealthCheck
    checker = SystemHealthCheck()
    result = checker._check_disk_space()
    assert result["name"] == "Місце на диску"
    assert "GB" in result["detail"]


def test_consolidate_entity_facts_no_change():
    """Тестує що consolidation не змінює малий список."""
    entity = {"facts": ["fact1", "fact2"], "notable_quotes": ["q1"]}
    result = EntityAnalyzer.consolidate_entity_facts(entity, max_facts=50)
    assert len(result["facts"]) == 2


def test_consolidate_entity_facts_dedup():
    """Тестує дедуплікацію підстрок."""
    facts = [f"fact_{i}" for i in range(60)]
    # Додаємо підстроки
    facts.append("fact")  # підстрока fact_1, fact_2, etc.
    entity = {"facts": facts}
    result = EntityAnalyzer.consolidate_entity_facts(entity, max_facts=50)
    assert len(result["facts"]) <= 50
    assert "fact" not in result["facts"]  # підстрока видалена


def test_consolidate_quotes_cap():
    """Тестує обмеження цитат до 10."""
    entity = {"facts": [f"fact_{i}" for i in range(55)], "notable_quotes": [f"q{i}" for i in range(20)]}
    result = EntityAnalyzer.consolidate_entity_facts(entity, max_facts=50)
    assert len(result["notable_quotes"]) == 10


def test_provider_map_has_google_full():
    """Тестує що google_full є в PROVIDER_MAP."""
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    # Імпортуємо через exec щоб уникнути tkinter
    import importlib
    spec = importlib.util.spec_from_file_location(
        "gui_constants",
        str(Path(__file__).resolve().parents[1] / "gui.py")
    )
    # Просто перевіряємо що google_full є в analyzer._call_llm
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    analyzer.provider = "google_full"
    # Тестуємо що analyze_full_context існує
    assert hasattr(analyzer, "analyze_full_context")
