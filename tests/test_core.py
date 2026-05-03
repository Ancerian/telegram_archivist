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
    assert render_item("Антон") == "Антон"


def test_render_item_none():
    assert render_item(None) == ""


def test_render_item_dict_with_name_and_desc():
    assert render_item({"name": "ORIA", "description": "проєкт"}) == "ORIA: проєкт"


def test_render_item_dict_only_name():
    assert render_item({"name": "ORIA"}) == "ORIA"


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
    assert normalize_name("Антон") == normalize_name("Anton")


def test_normalize_removes_brackets():
    assert normalize_name("Антон (дизайнер)") == normalize_name("Антон")


def test_normalize_removes_emoji():
    assert normalize_name("Nady 🦢") == normalize_name("Nady")


def test_normalize_case_insensitive():
    assert normalize_name("АНТОН") == normalize_name("антон")


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

    messages = [{
        "id": 1,
        "date": "2024-01-15T10:30:00",
        "from_name": "Антон",
        "from_id": "user123",
        "text": "Привіт",
        "media_type": None,
        "transcript": None,
    }]

    result = analyzer._build_user_message(messages, {})

    assert "АВТОР: Антон" in result
    assert "user123" in result
    assert "ЧАС: 2024-01-15 10:30" in result


def test_attribution_audit_marks_non_author():
    analyzer = EntityAnalyzer.__new__(EntityAnalyzer)
    analyzer.progress_callback = None
    batch = [{
        "from_name": "Антон",
        "from_id": "user123",
        "text": "Аня любить каву",
        "transcript": None,
    }]
    result = {
        "people": [
            {"name": "Антон", "telegram_id": "user123", "confidence": "high", "uncertainty_note": None},
            {"name": "Аня", "telegram_id": None, "confidence": "high", "uncertainty_note": None},
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
                {"id": 1, "type": "message", "date": "2026-04-28T15:00:00", "from": "Антон", "from_id": "user1", "text": "old"},
                {"id": 2, "type": "message", "date": "2026-04-28T16:00:00", "from": "Антон", "from_id": "user1", "text": "new"},
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
            "from_name": "Антон",
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
        (people_path / "Антон.md").write_text("# Антон", encoding="utf-8")
        (people_path / "Anton.md").write_text("# Anton", encoding="utf-8")
        (people_path / "Марія.md").write_text("# Марія", encoding="utf-8")

        groups = VaultDeduplicator.find_duplicates(vault_path)

        assert any(set(group) == {"People/Anton.md", "People/Антон.md"} for group in groups)


def test_graph_canvas_valid_json():
    with tempfile.TemporaryDirectory() as tmp:
        vault_path = Path(tmp)
        registry = IdentityRegistry(vault_path)
        registry.data["people"]["anton"] = {
            "canonical_name": "Антон",
            "aliases": [],
            "telegram_ids": [],
            "file": "People/Антон.md",
            "sources": [],
            "data": {"name": "Антон", "mentioned_projects": ["ORIA"]},
        }
        registry.data["projects"]["oria"] = {
            "canonical_name": "ORIA",
            "aliases": [],
            "file": "Projects/ORIA.md",
            "sources": [],
            "data": {"name": "ORIA"},
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
        "from_name": "Антон",
    }], {"people": [], "projects": [], "events": [], "themes": []})

    assert result is None
