"""
registry.py — Керування реєстром сутностей (_registry.json).
"""

import json
from pathlib import Path
from difflib import SequenceMatcher

from config import slugify, transliterate, higher_confidence


class IdentityRegistry:
    """Керує _registry.json в корені vault."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        self.registry_path = vault_path / "_registry.json"
        self.data = {
            "people": {},
            "projects": {},
            "events": {},
            "themes": {},
        }

    def load(self) -> None:
        """Завантажує реєстр, якщо немає — створює порожній."""
        if self.registry_path.exists():
            with open(self.registry_path, "r", encoding="utf-8") as f:
                self.data = json.load(f)
            # Переконатися що всі ключі існують
            for key in ("people", "projects", "events", "themes"):
                if key not in self.data:
                    self.data[key] = {}
            print(f"  📂 Реєстр завантажено: {sum(len(v) for v in self.data.values())} сутностей")
        else:
            print("  📂 Реєстр не знайдено, створюю новий")

    def save(self) -> None:
        """Зберігає реєстр."""
        self.vault_path.mkdir(parents=True, exist_ok=True)
        with open(self.registry_path, "w", encoding="utf-8") as f:
            json.dump(self.data, f, ensure_ascii=False, indent=2)

    def find_person(self, name: str, telegram_id: str | None = None) -> str | None:
        """
        Пошук за пріоритетом:
        1. Збіг telegram_id
        2. Точний збіг canonical_name або aliases (case-insensitive)
        3. Нечіткий збіг через SequenceMatcher з порогом 0.85
        """
        people = self.data.get("people", {})

        # 1. Збіг telegram_id
        if telegram_id:
            for key, person in people.items():
                if telegram_id in person.get("telegram_ids", []):
                    return key

        # 2. Точний збіг (case-insensitive)
        name_lower = name.lower().strip()
        name_translit = transliterate(name).lower().strip()

        for key, person in people.items():
            # Перевірка canonical_name
            if person.get("canonical_name", "").lower().strip() == name_lower:
                return key
            if transliterate(person.get("canonical_name", "")).lower().strip() == name_translit:
                return key

            # Перевірка aliases
            for alias in person.get("aliases", []):
                if alias.lower().strip() == name_lower:
                    return key
                if transliterate(alias).lower().strip() == name_translit:
                    return key

        # 3. Нечіткий збіг
        best_match = None
        best_ratio = 0.0

        for key, person in people.items():
            candidates = [person.get("canonical_name", "")] + person.get("aliases", [])
            for candidate in candidates:
                # Порівнюємо і оригінал, і транслітерацію
                for a, b in [
                    (name_lower, candidate.lower()),
                    (name_translit, transliterate(candidate).lower()),
                ]:
                    ratio = SequenceMatcher(None, a, b).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = key

        if best_ratio >= 0.85 and best_match:
            return best_match

        return None

    def find_entity(self, entity_type: str, name: str) -> str | None:
        """Пошук сутності за типом і назвою."""
        entities = self.data.get(entity_type, {})
        name_lower = name.lower().strip()
        name_translit = transliterate(name).lower().strip()

        # Точний збіг
        for key, entity in entities.items():
            if entity.get("canonical_name", "").lower().strip() == name_lower:
                return key
            if transliterate(entity.get("canonical_name", "")).lower().strip() == name_translit:
                return key
            for alias in entity.get("aliases", []):
                if alias.lower().strip() == name_lower:
                    return key

        # Нечіткий збіг
        best_match = None
        best_ratio = 0.0

        for key, entity in entities.items():
            candidates = [entity.get("canonical_name", "")] + entity.get("aliases", [])
            for candidate in candidates:
                for a, b in [
                    (name_lower, candidate.lower()),
                    (name_translit, transliterate(candidate).lower()),
                ]:
                    ratio = SequenceMatcher(None, a, b).ratio()
                    if ratio > best_ratio:
                        best_ratio = ratio
                        best_match = key

        if best_ratio >= 0.85 and best_match:
            return best_match

        return None

    def add_person(self, data: dict) -> str:
        """Додає нову людину до реєстру."""
        name = data.get("canonical_name", data.get("name", "Unknown"))
        key = slugify(name)

        # Унікальний ключ
        original_key = key
        counter = 2
        while key in self.data["people"]:
            key = f"{original_key}_{counter}"
            counter += 1

        self.data["people"][key] = {
            "canonical_name": name,
            "aliases": data.get("aliases", []),
            "telegram_ids": data.get("telegram_ids", []),
            "file": f"People/{name}.md",
            "sources": data.get("sources", []),
        }
        return key

    def add_entity(self, entity_type: str, data: dict) -> str:
        """Додає нову сутність до реєстру."""
        name = data.get("canonical_name", data.get("name", "Unknown"))
        key = slugify(name)

        original_key = key
        counter = 2
        while key in self.data.get(entity_type, {}):
            key = f"{original_key}_{counter}"
            counter += 1

        folder_map = {
            "projects": "Projects",
            "events": "Events",
            "themes": "Themes",
        }

        if entity_type not in self.data:
            self.data[entity_type] = {}

        self.data[entity_type][key] = {
            "canonical_name": name,
            "aliases": data.get("aliases", []),
            "file": f"{folder_map.get(entity_type, entity_type)}/{name}.md",
            "sources": data.get("sources", []),
        }
        return key

    def update_person(self, canonical_key: str, new_data: dict) -> None:
        """Оновлює дані про людину."""
        person = self.data["people"].get(canonical_key)
        if not person:
            return

        # Додати нові aliases
        existing_aliases = set(person.get("aliases", []))
        for alias in new_data.get("aliases", []):
            existing_aliases.add(alias)
        person["aliases"] = list(existing_aliases)

        # Додати нові telegram_ids
        existing_ids = set(person.get("telegram_ids", []))
        for tid in new_data.get("telegram_ids", []):
            existing_ids.add(tid)
        person["telegram_ids"] = list(existing_ids)

        # Додати нові sources
        existing_sources = set(person.get("sources", []))
        for src in new_data.get("sources", []):
            existing_sources.add(src)
        person["sources"] = list(existing_sources)

    def update_entity(self, entity_type: str, canonical_key: str, new_data: dict) -> None:
        """Оновлює дані про сутність."""
        entity = self.data.get(entity_type, {}).get(canonical_key)
        if not entity:
            return

        existing_aliases = set(entity.get("aliases", []))
        for alias in new_data.get("aliases", []):
            existing_aliases.add(alias)
        entity["aliases"] = list(existing_aliases)

        existing_sources = set(entity.get("sources", []))
        for src in new_data.get("sources", []):
            existing_sources.add(src)
        entity["sources"] = list(existing_sources)

    def get_all_names(self) -> dict:
        """Повертає всі імена для підказки LLM."""
        result = {
            "known_people": [],
            "known_projects": [],
            "known_events": [],
            "known_themes": [],
        }

        for key, person in self.data.get("people", {}).items():
            name = person.get("canonical_name", key)
            aliases = person.get("aliases", [])
            if aliases:
                result["known_people"].append(f"{name} (aliases: {', '.join(aliases)})")
            else:
                result["known_people"].append(name)

        for key, proj in self.data.get("projects", {}).items():
            result["known_projects"].append(proj.get("canonical_name", key))

        for key, event in self.data.get("events", {}).items():
            result["known_events"].append(event.get("canonical_name", key))

        for key, theme in self.data.get("themes", {}).items():
            result["known_themes"].append(theme.get("canonical_name", key))

        return result
