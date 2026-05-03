"""
merger.py — Мерж результатів аналізу з існуючим реєстром.
"""

from config import slugify, higher_confidence
from registry import IdentityRegistry, sanitize_tag


class EntityMerger:
    """Мерж аналізованих сутностей з реєстром."""

    def __init__(self, registry: IdentityRegistry):
        self.registry = registry

    def merge(self, analyzed_entities: dict, chat_name: str) -> dict:
        """
        Для кожної сутності:
        1. Шукає в реєстрі
        2. Якщо знайдена → action="update"
        3. Якщо ні → action="create"
        """
        merge_report = {
            "people": [],
            "projects": [],
            "events": [],
            "themes": [],
        }

        # People
        for person in (analyzed_entities.get("people") or []):
            name = person.get("name", "Unknown")
            telegram_id = person.get("telegram_id")

            canonical_key = self.registry.find_person(name, telegram_id)

            if canonical_key:
                # Оновити
                existing_entry = self.registry.data["people"].get(canonical_key, {})
                existing_data = existing_entry.get("data", {})

                # Якщо в реєстрі немає даних (старий формат), ініціалізуємо базовими полями
                if not existing_data:
                    existing_data = {"name": existing_entry.get("canonical_name", name)}

                merged_data = merge_entity_data(existing_data, person)
                merged_data["_chat_source"] = chat_name

                # Оновити реєстр (метадані + повне досьє)
                nicknames = person.get("identity", {}).get("nicknames", []) or []
                aliases = list(set(nicknames + [name]))
                tg_ids = [telegram_id] if telegram_id else []

                self.registry.update_person(canonical_key, {
                    "aliases": aliases,
                    "telegram_ids": tg_ids,
                    "sources": [chat_name],
                })
                # Зберігаємо оновлене досьє
                self.registry.data["people"][canonical_key]["data"] = merged_data

                merge_report["people"].append({
                    "action": "update",
                    "canonical_key": canonical_key,
                    "data": merged_data,
                })
            else:
                # Створити
                nicknames = person.get("identity", {}).get("nicknames", []) or []
                aliases = list(set(nicknames + [name]))
                tg_ids = [telegram_id] if telegram_id else []

                person["_chat_source"] = chat_name

                canonical_key = self.registry.add_person({
                    "canonical_name": name,
                    "aliases": aliases,
                    "telegram_ids": tg_ids,
                    "sources": [chat_name],
                    "full_dossier": person
                })

                merge_report["people"].append({
                    "action": "create",
                    "canonical_key": canonical_key,
                    "data": person,
                })

        # Projects
        for project in (analyzed_entities.get("projects") or []):
            name = project.get("name", "Unknown")
            canonical_key = self.registry.find_entity("projects", name)

            if canonical_key:
                existing_entry = self.registry.data["projects"].get(canonical_key, {})
                existing_data = existing_entry.get("data", {})
                if not existing_data:
                    existing_data = {"name": existing_entry.get("canonical_name", name)}

                merged_data = merge_entity_data(existing_data, project)
                merged_data["_chat_source"] = chat_name

                self.registry.update_entity("projects", canonical_key, {
                    "aliases": [],
                    "sources": [chat_name],
                })
                self.registry.data["projects"][canonical_key]["data"] = merged_data

                merge_report["projects"].append({
                    "action": "update",
                    "canonical_key": canonical_key,
                    "data": merged_data,
                })
            else:
                project["_chat_source"] = chat_name
                canonical_key = self.registry.add_entity("projects", {
                    "canonical_name": name,
                    "aliases": [],
                    "sources": [chat_name],
                    "full_dossier": project
                })

                merge_report["projects"].append({
                    "action": "create",
                    "canonical_key": canonical_key,
                    "data": project,
                })

        # Events
        for event in (analyzed_entities.get("events") or []):
            name = event.get("name", "Unknown")
            canonical_key = self.registry.find_entity("events", name)

            if canonical_key:
                existing_entry = self.registry.data["events"].get(canonical_key, {})
                existing_data = existing_entry.get("data", {})
                if not existing_data:
                    existing_data = {"name": existing_entry.get("canonical_name", name)}

                merged_data = merge_entity_data(existing_data, event)
                merged_data["_chat_source"] = chat_name

                self.registry.update_entity("events", canonical_key, {
                    "aliases": [],
                    "sources": [chat_name],
                })
                self.registry.data["events"][canonical_key]["data"] = merged_data

                merge_report["events"].append({
                    "action": "update",
                    "canonical_key": canonical_key,
                    "data": merged_data,
                })
            else:
                event["_chat_source"] = chat_name
                canonical_key = self.registry.add_entity("events", {
                    "canonical_name": name,
                    "aliases": [],
                    "sources": [chat_name],
                    "full_dossier": event
                })

                merge_report["events"].append({
                    "action": "create",
                    "canonical_key": canonical_key,
                    "data": event,
                })

        # Themes
        for theme in (analyzed_entities.get("themes") or []):
            if not isinstance(theme, dict):
                theme = {"tag": theme}
            tag = sanitize_tag(theme.get("tag") or theme.get("name") or "unknown")
            theme["tag"] = tag
            canonical_key = self.registry.find_entity("themes", tag)

            if canonical_key:
                existing_entry = self.registry.data["themes"].get(canonical_key, {})
                existing_data = existing_entry.get("data", {})
                if not existing_data:
                    existing_data = {"tag": existing_entry.get("canonical_name", tag)}

                merged_data = merge_entity_data(existing_data, theme)
                # Сумувати message_count
                merged_data["message_count"] = (
                    (existing_data.get("message_count") or 0) +
                    (theme.get("message_count") or 0)
                )
                merged_data["tag"] = sanitize_tag(merged_data.get("tag") or tag)
                merged_data["_chat_source"] = chat_name

                self.registry.update_entity("themes", canonical_key, {
                    "aliases": [],
                    "sources": [chat_name],
                })
                self.registry.data["themes"][canonical_key]["data"] = merged_data

                merge_report["themes"].append({
                    "action": "update",
                    "canonical_key": canonical_key,
                    "data": merged_data,
                })
            else:
                theme["_chat_source"] = chat_name
                canonical_key = self.registry.add_entity("themes", {
                    "canonical_name": tag,
                    "aliases": [],
                    "sources": [chat_name],
                    "full_dossier": theme
                })

                merge_report["themes"].append({
                    "action": "create",
                    "canonical_key": canonical_key,
                    "data": theme,
                })

        return merge_report

    def _get_existing_person_data(self, canonical_key: str) -> dict:
        """Застарілий метод."""
        person = self.registry.data.get("people", {}).get(canonical_key, {})
        return person.get("data", {})

    def _get_existing_entity_data(self, entity_type: str, canonical_key: str) -> dict:
        """Застарілий метод."""
        entity = self.registry.data.get(entity_type, {}).get(canonical_key, {})
        return entity.get("data", {})


def merge_entity_data(existing: dict, new: dict) -> dict:
    """
    Мерж даних сутності:
    - list-поля: об'єднати, дедуплікувати
    - sources, aliases, telegram_ids: доповнити
    - confidence: взяти найвищий
    - uncertainty_note: обнулити якщо confidence виріс
    - scalar null-поля: заповнити якщо в new є значення
    - status: перезаписати якщо новий не "невідомо"
    """
    result = dict(existing)

    for key, new_val in new.items():
        if key.startswith("_"):
            result[key] = new_val
            continue

        if new_val is None:
            continue

        existing_val = result.get(key)

        if isinstance(new_val, list):
            if isinstance(existing_val, list):
                merged = list(existing_val)
                for item in new_val:
                    if item not in merged:
                        merged.append(item)
                result[key] = merged
            else:
                result[key] = new_val

        elif isinstance(new_val, dict):
            if isinstance(existing_val, dict):
                result[key] = merge_entity_data(existing_val, new_val)
            else:
                result[key] = new_val

        elif key == "confidence":
            result[key] = higher_confidence(
                existing_val or "low",
                new_val or "low",
            )
        elif key == "status":
            if new_val and new_val != "невідомо":
                result[key] = new_val
        elif key == "message_count":
            result[key] = (existing_val or 0) + (new_val or 0)
        else:
            if existing_val is None or existing_val == "" or existing_val == "невідомо" or existing_val == "null":
                result[key] = new_val

    # Обнулити uncertainty_note якщо confidence виріс до high
    if result.get("confidence") == "high":
        result["uncertainty_note"] = None

    return result
