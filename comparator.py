"""
comparator.py — Порівняння кількох чатів (Multi-chat comparison).
"""

from pathlib import Path


class ChatComparator:
    """Генерує порівняльний звіт по всіх оброблених чатах."""

    def compare(self, registry, vault_path: Path) -> str:
        """Генерує порівняльний markdown звіт по всіх чатах."""
        vault_path = Path(vault_path)

        # Зібрати статистику по чатах з Chats/_index_*.md
        chats_dir = vault_path / "Chats"
        chat_indices = list(chats_dir.glob("_index_*.md")) if chats_dir.exists() else []

        # Для кожної людини — в яких чатах присутня
        person_chats = {}
        for key, person in registry.data.get("people", {}).items():
            name = person.get("canonical_name", key)
            sources = person.get("sources", [])
            if sources:
                person_chats[name] = sources

        # Знайти людей що є в кількох чатах
        multi_chat_people = {
            name: chats for name, chats in person_chats.items()
            if len(chats) > 1
        }

        return self._render_report(multi_chat_people, chat_indices, registry)

    def _render_report(self, multi_chat_people: dict, chat_indices: list, registry) -> str:
        lines = ["# 🔗 Порівняння чатів\n"]
        lines.append(f"**Оброблено чатів:** {len(chat_indices)}\n")

        # Загальна статистика
        total_people = len(registry.data.get("people", {}))
        total_projects = len(registry.data.get("projects", {}))
        total_events = len(registry.data.get("events", {}))
        total_themes = len(registry.data.get("themes", {}))
        lines.append(f"**Загалом сутностей:** {total_people} людей, {total_projects} проєктів, {total_events} подій, {total_themes} тем\n")

        if multi_chat_people:
            lines.append("## 👥 Люди в кількох чатах\n")
            for name, chats in sorted(multi_chat_people.items(), key=lambda x: -len(x[1])):
                lines.append(f"- [[{name}]]: {', '.join(chats)}")
            lines.append("")
        else:
            lines.append("## 👥 Люди в кількох чатах\n")
            lines.append("_Не знайдено людей що є в кількох чатах._\n")

        return "\n".join(lines)
