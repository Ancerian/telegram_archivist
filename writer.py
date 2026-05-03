"""
writer.py — Генерація Obsidian vault з Markdown-файлами.
"""

import json
import logging
import re
from pathlib import Path
from datetime import datetime

from config import sanitize_filename


logger = logging.getLogger(__name__)


def render_item(item, depth=0) -> str:
    """Рендерить будь-яке значення у чистий markdown-friendly текст."""
    # Захист від нескінченної рекурсії
    if depth > 3:
        return str(item)

    if item is None:
        return ""

    if isinstance(item, bool):
        return "так" if item else "ні"

    if isinstance(item, (int, float)):
        return str(item)

    if isinstance(item, str):
        # Прибрати залишки JSON артефактів
        item = item.strip()
        if item.startswith('{') or item.startswith('['):
            try:
                parsed = json.loads(item)
                return render_item(parsed, depth + 1)
            except Exception:
                pass
        return item

    if isinstance(item, list):
        parts = [render_item(i, depth + 1) for i in item if i is not None]
        parts = [p for p in parts if p]
        return ", ".join(parts)

    if isinstance(item, dict):
        # Пріоритет полів для відображення
        if "name" in item and "description" in item and item["name"] and item["description"]:
            return f"{render_item(item['name'], depth + 1)}: {render_item(item['description'], depth + 1)}"
        if "name" in item and item["name"]:
            return render_item(item["name"], depth + 1)
        if "description" in item and item["description"]:
            return render_item(item["description"], depth + 1)
        if "tag" in item:
            return render_item(item["tag"], depth + 1)
        if "title" in item:
            return render_item(item["title"], depth + 1)
        # Fallback — всі непусті поля
        parts = []
        for k, v in item.items():
            if v and k not in ["confidence", "uncertainty_note"]:
                parts.append(render_item(v, depth + 1))
        return ", ".join(parts) if parts else ""

    return str(item)


def render_list(items, prefix="- ", link_resolver=None, entity_type=None) -> str:
    """Рендерить список як markdown bullet points."""
    if not items:
        return ""

    lines = []
    for item in items:
        if item is None:
            continue

        text = render_item(item)
        if not text or not text.strip():
            continue

        # Entity linking якщо є resolver
        if link_resolver and entity_type and isinstance(item, str):
            text = link_resolver(text, entity_type)
        elif link_resolver and entity_type and isinstance(item, dict):
            name = item.get("name") or item.get("tag") or ""
            if name:
                linked = link_resolver(name, entity_type)
                # Якщо є опис — додати після посилання
                desc = item.get("description", "")
                text = f"{linked}: {render_item(desc)}" if desc else linked

        lines.append(f"{prefix}{text}")

    return "\n".join(lines)


def safe_yaml_value(val) -> str:
    """Екранує YAML frontmatter scalar."""
    if val is None:
        return '""'
    val = str(val).strip()
    if not val:
        return '""'
    # Якщо містить двокрапку, лапки або є числом — обгорнути в лапки
    if ':' in val or '"' in val or val.isdigit():
        val = val.replace('"', '\\"')
        return f'"{val}"'
    return val


def has_content(data) -> bool:
    """Перевіряє, чи структура має хоч якийсь непорожній контент."""
    if data is None:
        return False
    if isinstance(data, str):
        return bool(data.strip())
    if isinstance(data, list):
        return any(has_content(i) for i in data)
    if isinstance(data, dict):
        return any(has_content(v) for v in data.values())
    return bool(data)


def sanitize_tag(tag: str) -> str:
    """Санітизує тег для Obsidian/Markdown."""
    if not tag:
        return ""
    # Якщо tag є dict — витягти поле tag
    if isinstance(tag, dict):
        tag = tag.get("tag") or tag.get("name") or ""
    tag = str(tag).strip().lower()
    # Замінити пробіли і підкреслення на дефіс
    tag = re.sub(r'[\s_]+', '-', tag)
    # Прибрати всі символи крім букв, цифр, дефіса
    tag = re.sub(r'[^\w\-]', '', tag)
    # Прибрати множинні дефіси
    tag = re.sub(r'-+', '-', tag).strip('-')
    return tag


class ObsidianWriter:
    """Генератор Obsidian vault."""

    def __init__(self, vault_path: Path, registry=None):
        self.vault_path = vault_path
        self.registry = registry
        self.stats = self._empty_stats()
        for folder in ("People", "Projects", "Events", "Themes", "Chats"):
            (vault_path / folder).mkdir(parents=True, exist_ok=True)

    def write_all(self, merge_report: dict, chat_name: str) -> dict:
        """Записує всі сутності у vault."""
        stats = self._empty_stats()
        self.stats = stats
        for entity_type in ("people", "projects", "events", "themes"):
            created = 0
            updated = 0
            skipped = 0
            for item in (merge_report.get(entity_type) or []):
                if not isinstance(item, dict):
                    logger.warning(f"Некоректний елемент merge_report: {type(item)}")
                    skipped += 1
                    continue

                action = item.get("action", "update")
                data = item.get("data")
                written = False

                if entity_type == "people":
                    written = self._write_person(data, chat_name, action)
                elif entity_type == "projects":
                    written = self._write_project(data, chat_name, action)
                elif entity_type == "events":
                    written = self._write_event(data, chat_name, action)
                elif entity_type == "themes":
                    written = self._write_theme(data, chat_name, action)

                if not written:
                    skipped += 1
                elif action == "create":
                    created += 1
                else:
                    updated += 1

            stats["created"][entity_type] = created
            stats["updated"][entity_type] = updated
            stats["skipped"][entity_type] = skipped
            stats["skipped"]["total"] += skipped
        return stats

    def write_chat_index(self, chat_name: str, messages: list, entities: dict, chat_language: str) -> None:
        """Записує індекс чату."""
        now = datetime.now().strftime("%Y-%m-%d")
        safe_name = sanitize_filename(chat_name)
        file_path = self.vault_path / "Chats" / f"_index_{safe_name}.md"

        dates = [m["date"] for m in messages if m.get("date")]
        first_date = dates[0] if dates else "?"
        last_date = dates[-1] if dates else "?"
        participants = sorted(set(m["from_name"] for m in messages if m.get("from_name") and m["from_name"] != "Unknown"))

        lines = [
            "---",
            "tags: [chat-index]",
            f"processed: {safe_yaml_value(now)}",
            f"language: {safe_yaml_value(chat_language)}",
            "---",
            "",
            f"# 📚 {chat_name}",
            "",
            f"**Оброблено:** {now}",
            f"**Повідомлень:** {len(messages)}",
            f"**Період:** {first_date} — {last_date}",
            f"**Учасників:** {len(participants)}",
            f"**Мова чату:** {chat_language}",
            "",
        ]

        # Люди
        people_names = [p.get("name", "") for p in (entities.get("people") or []) if isinstance(p, dict) and has_content(p.get("name"))]
        if people_names:
            lines.append("## Люди")
            for name in people_names:
                lines.append(f"- {self.resolve_link(name, 'people')}")
            lines.append("")

        # Проєкти
        project_names = [p.get("name", "") for p in (entities.get("projects") or []) if isinstance(p, dict) and has_content(p.get("name"))]
        if project_names:
            lines.append("## Проєкти")
            for name in project_names:
                lines.append(f"- {self.resolve_link(name, 'projects')}")
            lines.append("")

        # Події
        event_names = [e.get("name", "") for e in (entities.get("events") or []) if isinstance(e, dict) and has_content(e.get("name"))]
        if event_names:
            lines.append("## Події")
            for name in event_names:
                lines.append(f"- {self.resolve_link(name, 'events')}")
            lines.append("")

        # Теми
        theme_tags = [self._render_theme_tag(t) for t in (entities.get("themes") or [])]
        theme_tags = [tag for tag in theme_tags if tag]
        if theme_tags:
            lines.append("## Теми")
            for tag in theme_tags:
                link = self.resolve_link(tag, "themes")
                if not link.startswith("[["):
                    link = f"[[{tag}]]"
                    if self.stats is not None:
                        self.stats["entity_links"] = self.stats.get("entity_links", 0) + 1
                lines.append(f"- {link}")
            lines.append("")

        file_path.write_text("\n".join(lines), encoding="utf-8")

    def write_chat_summary(self, chat_name: str, messages: list, summary_text: str) -> None:
        """Записує LLM-зведення чату."""
        if not summary_text or not summary_text.strip():
            return

        now = datetime.now().strftime("%Y-%m-%d")
        safe_name = sanitize_filename(chat_name)
        file_path = self.vault_path / "Chats" / f"_summary_{safe_name}.md"
        dates = [m["date"] for m in messages if m.get("date")]
        first_date = dates[0] if dates else "?"
        last_date = dates[-1] if dates else "?"
        participants = sorted(set(m["from_name"] for m in messages if m.get("from_name") and m["from_name"] != "Unknown"))

        lines = [
            "---",
            "tags: [chat-summary]",
            f"period: {safe_yaml_value(f'{first_date} / {last_date}')}",
            f"participants: {safe_yaml_value(len(participants))}",
            "---",
            "",
            f"# 📝 Зведення: {chat_name}",
            "",
            summary_text.strip(),
            "",
            "---",
            f"*Згенеровано: {now}*",
        ]
        file_path.write_text("\n".join(lines), encoding="utf-8")

    def write_graph_canvas(self, file_name: str = "_Graph.canvas") -> Path | None:
        """Генерує Obsidian Canvas з базовими зв'язками між сутностями."""
        if not self.registry:
            return None

        nodes = []
        edges = []
        node_ids = {"people": {}, "projects": {}, "events": {}}

        def _add_nodes(entity_type, x_start, y_start, columns, color):
            for i, (key, entry) in enumerate(self.registry.data.get(entity_type, {}).items()):
                file_path = entry.get("file")
                if not file_path:
                    continue
                node_id = f"{entity_type}:{key}"
                node_ids[entity_type][key] = node_id
                nodes.append({
                    "id": node_id,
                    "type": "file",
                    "file": file_path,
                    "x": x_start + (i % columns) * 240,
                    "y": y_start + (i // columns) * 100,
                    "width": 200,
                    "height": 60,
                    "color": color,
                })

        def _item_name(item):
            if isinstance(item, dict):
                return render_item(item.get("name") or item.get("tag") or item.get("title") or item.get("description"))
            return render_item(item)

        def _iter_names(items):
            if not isinstance(items, list):
                return []
            return [name for name in (_item_name(item) for item in items) if name]

        def _add_edge(from_node, to_node, label, color):
            if not from_node or not to_node or from_node == to_node:
                return
            edge_key = (from_node, to_node, label)
            for existing in edges:
                if (existing.get("fromNode"), existing.get("toNode"), existing.get("label")) == edge_key:
                    return
            edges.append({
                "id": f"e{len(edges) + 1}",
                "fromNode": from_node,
                "toNode": to_node,
                "label": label,
                "color": color,
            })

        _add_nodes("people", 0, 0, 3, "4")
        _add_nodes("projects", 800, 0, 3, "2")
        _add_nodes("events", 400, 500, 4, "5")

        for key, entry in self.registry.data.get("people", {}).items():
            from_node = node_ids["people"].get(key)
            data = entry.get("data") or {}
            rels = data.get("relationships") or {}

            for name in _iter_names(rels.get("friends_with")):
                target_key = self.registry.find_person(name)
                _add_edge(from_node, node_ids["people"].get(target_key), "друг", "2")

            for name in _iter_names(rels.get("conflicts_with")):
                target_key = self.registry.find_person(name)
                _add_edge(from_node, node_ids["people"].get(target_key), "конфлікт", "1")

            for name in _iter_names(data.get("mentioned_projects")):
                target_key = self.registry.find_entity("projects", name)
                _add_edge(from_node, node_ids["projects"].get(target_key), "проєкт", "4")

        for key, entry in self.registry.data.get("events", {}).items():
            event_node = node_ids["events"].get(key)
            data = entry.get("data") or {}
            for name in _iter_names(data.get("participants")):
                person_key = self.registry.find_person(name)
                _add_edge(node_ids["people"].get(person_key), event_node, "учасник", "5")

        canvas = {"nodes": nodes, "edges": edges}
        file_path = self.vault_path / file_name
        file_path.write_text(json.dumps(canvas, ensure_ascii=False, indent=2), encoding="utf-8")
        return file_path

    # --- Person ---

    def _write_person(self, data: dict, chat_name: str, action: str) -> bool:
        prepared = self._prepare_write_data(data, ("canonical_name", "name"))
        if prepared is None:
            return False
        data, name = prepared

        safe_name = sanitize_filename(name)
        file_path = self.vault_path / "People" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        identity = data.get("identity") or {}
        contacts = data.get("contacts") or {}
        prof = data.get("professional") or {}
        edu = prof.get("education") or {}
        family = data.get("family") or {}
        lifestyle = data.get("lifestyle") or {}
        finances = data.get("finances") or {}
        health = data.get("health") or {}
        psych = data.get("psychology") or {}
        comms = data.get("communication_intel") or {}
        rels = data.get("relationships") or {}

        confidence = data.get("confidence", "medium")
        telegram_id = data.get("telegram_id", "")

        lines = [
            "---",
            "tags: [person]",
            f"confidence: {safe_yaml_value(confidence)}",
            f"telegram_id: {safe_yaml_value(telegram_id)}",
            f"relation: {safe_yaml_value(rels.get('relation_to_me', 'невідомо'))}",
            f"closeness: {safe_yaml_value(rels.get('closeness', 'далекий'))}",
            "---",
            "",
            f"# 👤 {name}",
            "",
        ]

        if confidence != "high" and data.get("uncertainty_note"):
            lines += [
                "> [!warning] Неточні дані",
                f"> {render_item(data['uncertainty_note'])}",
                "",
            ]

        lines.append("---")
        lines.append("")

        # Особистість
        id_table = self._build_table([
            ("Повне ім'я", identity.get("full_name")),
            ("Псевдоніми/ніки", self._join(identity.get("nicknames"))),
            ("Дата народження", identity.get("birth_date")),
            ("Місце народження", identity.get("birth_place")),
            ("Вік", identity.get("age")),
            ("Стать", identity.get("gender")),
            ("Національність", identity.get("nationality")),
            ("Мови", self._join(identity.get("languages"))),
        ])
        if id_table:
            lines += ["## 🪪 Особистість", "", id_table, "", "---", ""]

        # Контакти
        ct_table = self._build_table([
            ("Телефон", contacts.get("phone")),
            ("Email", contacts.get("email")),
            ("Місто", contacts.get("city")),
            ("Країна", contacts.get("country")),
            ("Адреса", contacts.get("address")),
            ("Інші соцмережі", self._join(contacts.get("other_socials"))),
            ("Часто буває", self._join(contacts.get("frequently_visited_places"))),
        ])
        if ct_table:
            lines += ["## 📍 Контакти та місцезнаходження", "", ct_table, "", "---", ""]

        # Професійне
        prof_lines = []
        if self._v(prof.get("position")): prof_lines.append(f"**Посада:** {render_item(prof['position'])}")
        if self._v(prof.get("company")): prof_lines.append(f"**Компанія:** {render_item(prof['company'])}")
        if self._v(prof.get("industry")): prof_lines.append(f"**Сфера:** {render_item(prof['industry'])}")
        if self._v(prof.get("occupation")): prof_lines.append(f"**Діяльність:** {render_item(prof['occupation'])}")
        if self._v(prof.get("skills")): prof_lines.append(f"**Навички:** {self._join(prof['skills'])}")

        edu_lines = []
        if self._v(edu.get("degree")): edu_lines.append(f"**Ступінь:** {render_item(edu['degree'])}")
        if self._v(edu.get("institution")): edu_lines.append(f"**Заклад:** {render_item(edu['institution'])}")
        if self._v(edu.get("field")): edu_lines.append(f"**Спеціальність:** {render_item(edu['field'])}")
        if self._v(edu.get("graduation_year")): edu_lines.append(f"**Рік закінчення:** {render_item(edu['graduation_year'])}")

        sp = self._list_items(prof.get("side_projects"))
        bi = self._list_items(prof.get("business_interests"))

        if prof_lines or edu_lines or sp or bi:
            lines += ["## 💼 Професійне", ""]
            lines += prof_lines
            if edu_lines:
                lines += ["", "### Освіта"] + edu_lines
            if sp:
                lines += ["", "### Побічні проєкти"] + sp
            if bi:
                lines += ["", "### Бізнес-інтереси"] + bi
            lines += ["", "---", ""]

        # Сім'я
        fam_table = self._build_table([
            ("Статус", family.get("relationship_status")),
            ("Партнер", family.get("partner")),
            ("Діти", family.get("children")),
            ("Домашні тварини", self._join(family.get("pets"))),
        ])
        fam_extra = []
        if self._v(family.get("parents")): fam_extra.append(f"**Батьки:** {self._join(family['parents'])}")
        if self._v(family.get("siblings")): fam_extra.append(f"**Брати/сестри:** {self._join(family['siblings'])}")
        if fam_table or fam_extra:
            lines += ["## 👨‍👩‍👧 Сім'я та особисте життя", ""]
            if fam_table: lines += [fam_table, ""]
            lines += fam_extra + ["", "---", ""]

        # Спосіб життя
        ls_lines = []
        if self._v(lifestyle.get("hobbies")): ls_lines.append(f"**Хобі:** {self._join(lifestyle['hobbies'])}")
        if self._v(lifestyle.get("sports")): ls_lines.append(f"**Спорт:** {self._join(lifestyle['sports'])}")
        if self._v(lifestyle.get("music_taste")): ls_lines.append(f"**Музика:** {self._join(lifestyle['music_taste'])}")
        if self._v(lifestyle.get("movie_tv_taste")): ls_lines.append(f"**Фільми/серіали:** {self._join(lifestyle['movie_tv_taste'])}")
        if self._v(lifestyle.get("book_taste")): ls_lines.append(f"**Книги:** {self._join(lifestyle['book_taste'])}")
        if self._v(lifestyle.get("food_preferences")): ls_lines.append(f"**Їжа:** {self._join(lifestyle['food_preferences'])}")
        if self._v(lifestyle.get("alcohol")): ls_lines.append(f"**Алкоголь:** {render_item(lifestyle['alcohol'])}")
        if self._v(lifestyle.get("smoking")): ls_lines.append(f"**Куріння:** {render_item(lifestyle['smoking'])}")
        if self._v(lifestyle.get("sleep_pattern")): ls_lines.append(f"**Режим:** {render_item(lifestyle['sleep_pattern'])}")
        if self._v(lifestyle.get("car")): ls_lines.append(f"**Авто:** {render_item(lifestyle['car'])}")
        travel = []
        if self._v(lifestyle.get("travel_history")): travel.append(f"**Бував у:** {self._join(lifestyle['travel_history'])}")
        if self._v(lifestyle.get("dream_destinations")): travel.append(f"**Хоче відвідати:** {self._join(lifestyle['dream_destinations'])}")
        if ls_lines or travel:
            lines += ["## 🎯 Спосіб життя", ""] + ls_lines
            if travel: lines += ["", "### Подорожі"] + travel
            lines += ["", "---", ""]

        # Фінанси
        fin_lines = []
        if self._v(finances.get("income_level")): fin_lines.append(f"**Рівень доходу:** {render_item(finances['income_level'])}")
        if self._v(finances.get("spending_habits")): fin_lines.append(f"**Звички витрат:** {render_item(finances['spending_habits'])}")
        if self._v(finances.get("business_activity")): fin_lines.append(f"**Бізнес-активність:** {render_item(finances['business_activity'])}")
        if self._v(finances.get("financial_problems")): fin_lines.append(f"**Фінансові проблеми:** {render_item(finances['financial_problems'])}")
        if fin_lines:
            lines += ["## 💰 Фінанси", ""] + fin_lines + ["", "---", ""]

        # Здоров'я
        h_lines = []
        if self._v(health.get("general")): h_lines.append(f"**Загальне:** {render_item(health['general'])}")
        if self._v(health.get("known_conditions")): h_lines.append(f"**Відомі особливості:** {self._join(health['known_conditions'])}")
        if self._v(health.get("sports_activity")): h_lines.append(f"**Фізична активність:** {render_item(health['sports_activity'])}")
        if self._v(health.get("diet")): h_lines.append(f"**Харчування:** {render_item(health['diet'])}")
        if h_lines:
            lines += ["## 🏥 Здоров'я", ""] + h_lines + ["", "---", ""]

        # Психологія
        p_lines = []
        if self._v(psych.get("communication_style")): p_lines.append(f"**Стиль спілкування:** {render_item(psych['communication_style'])}")
        if self._v(psych.get("humor_style")): p_lines.append(f"**Гумор:** {render_item(psych['humor_style'])}")
        if self._v(psych.get("temperament")): p_lines.append(f"**Темперамент:** {render_item(psych['temperament'])}")
        if self._v(psych.get("values")): p_lines.append(f"**Цінності:** {self._join(psych['values'])}")
        if self._v(psych.get("political_views")): p_lines.append(f"**Політичні погляди:** {render_item(psych['political_views'])}")
        if self._v(psych.get("religion")): p_lines.append(f"**Релігія:** {render_item(psych['religion'])}")
        fears = self._list_items(psych.get("fears"))
        insec = self._list_items(psych.get("insecurities"))
        motiv = self._list_items(psych.get("motivations"))
        goals = self._list_items(psych.get("life_goals"))
        probs = self._list_items(psych.get("current_problems"))
        if p_lines or fears or insec or motiv or goals or probs:
            lines += ["## 🧠 Психологія", ""] + p_lines
            if fears or insec:
                lines += ["", "### Страхи та вразливості"] + fears + insec
            if motiv or goals:
                lines += ["", "### Мотивація та цілі"] + motiv + goals
            if probs:
                lines += ["", "### Поточні проблеми"] + probs
            lines += ["", "---", ""]

        # Комунікаційна розвідка
        c_lines = []
        if self._v(comms.get("topics_to_talk_about")): c_lines.append(f"**Теми для розмови:** {self._join(comms['topics_to_talk_about'])}")
        if self._v(comms.get("topics_to_avoid")): c_lines.append(f"**Краще не піднімати:** {self._join(comms['topics_to_avoid'])}")
        if self._v(comms.get("responds_well_to")): c_lines.append(f"**Добре реагує на:** {render_item(comms['responds_well_to'])}")
        if self._v(comms.get("best_time_to_reach")): c_lines.append(f"**Найкращий час:** {render_item(comms['best_time_to_reach'])}")
        if self._v(comms.get("typical_response_speed")): c_lines.append(f"**Швидкість відповіді:** {render_item(comms['typical_response_speed'])}")
        if self._v(comms.get("uses_voice_messages")): c_lines.append(f"**Голосові:** {render_item(comms['uses_voice_messages'])}")
        if self._v(comms.get("emoji_usage")): c_lines.append(f"**Емодзі:** {render_item(comms['emoji_usage'])}")
        if c_lines:
            lines += ["## 💬 Комунікаційна розвідка", ""] + c_lines + ["", "---", ""]

        # Стосунки зі мною
        rel_table = self._build_table([
            ("Тип", rels.get("relation_to_me")),
            ("Близькість", rels.get("closeness")),
            ("Ставлення до мене", rels.get("sentiment_toward_me")),
            ("Рівень довіри", rels.get("trust_level")),
            ("Як познайомились", rels.get("how_we_met")),
            ("Знайомі", rels.get("duration_of_acquaintance")),
        ])
        rel_extra = []
        if self._v(rels.get("relation_description")): rel_extra.append(f"**Опис:** {render_item(rels['relation_description'])}")
        if self._v(rels.get("romantic_history_with_me")): rel_extra.append(f"**Романтична історія:** {render_item(rels['romantic_history_with_me'])}")
        friends = self._link_list(rels.get("friends_with"), "people")
        conflicts = self._link_list(rels.get("conflicts_with"), "people")
        if rel_table or rel_extra or friends or conflicts:
            lines += ["## 🤝 Стосунки зі мною", ""]
            if rel_table: lines += [rel_table, ""]
            lines += rel_extra
            if friends: lines += ["", "### Дружить з"] + friends
            if conflicts: lines += ["", "### Конфлікти з"] + conflicts
            lines += ["", "---", ""]

        # Ключові події
        events_list = self._list_items(data.get("key_life_events"))
        if events_list:
            lines += ["## 📖 Ключові події життя"] + events_list + ["", "---", ""]

        # Цитати
        quotes = data.get("notable_quotes") or []
        quote_lines = []
        for q in quotes:
            q_text = render_item(q)
            if q_text:
                quote_lines.extend([f"> {q_text}", ""])
        if quote_lines:
            lines += ["## 💭 Характерні цитати", ""] + quote_lines + ["---", ""]

        # Факти
        facts = self._list_items(data.get("facts"))
        if facts:
            lines += ["## 📝 Інші факти"] + facts + [""]

        # Проєкти, Події, Теми
        mp = self._link_list(data.get("mentioned_projects"), "projects")
        if mp: lines += ["## 📁 Проєкти"] + mp + [""]
        me = self._link_list(data.get("mentioned_events"), "events")
        if me: lines += ["## 📅 Події"] + me + [""]
        mt = data.get("mentioned_themes") or []
        if has_content(mt):
            tags_str = " ".join(f"#{self._render_theme_tag(t)}" for t in mt if self._render_theme_tag(t))
            if tags_str.strip():
                lines += ["## 🏷 Теми", tags_str, ""]

        # Футер
        all_sources = self._render_sources(data.get("sources"), chat_name)
        lines += [
            "---",
            f"*Джерела: {', '.join(all_sources)}*",
            f"*Останнє оновлення: {now} (через {chat_name})*",
        ]

        file_path.write_text("\n".join(lines), encoding="utf-8")
        return True

    # --- Project ---

    def _write_project(self, data: dict, chat_name: str, action: str) -> bool:
        prepared = self._prepare_write_data(data, ("canonical_name", "name"))
        if prepared is None:
            return False
        data, name = prepared

        safe_name = sanitize_filename(name)
        file_path = self.vault_path / "Projects" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        confidence = data.get("confidence", "medium")
        lines = [
            "---", "tags: [project]",
            f"status: {safe_yaml_value(data.get('status', 'невідомо'))}",
            f"confidence: {safe_yaml_value(confidence)}", "---", "",
            f"# 📁 {name}", "",
        ]
        if confidence != "high" and data.get("uncertainty_note"):
            lines += ["> [!warning] Неточні дані", f"> {render_item(data['uncertainty_note'])}", ""]
        if self._v(data.get("description")):
            lines += ["## Опис", render_item(data["description"]), ""]
        if self._v(data.get("status")):
            lines += ["## Статус", render_item(data["status"]), ""]
        participants = self._link_list(data.get("participants"), "people")
        if participants:
            lines += ["## Учасники"] + participants + [""]
        kd = self._list_items(data.get("key_dates"))
        if kd:
            lines += ["## Ключові дати"] + kd + [""]

        all_sources = self._render_sources(data.get("sources"), chat_name)
        lines += ["---", f"*Джерела: {', '.join(all_sources)}*", f"*Останнє оновлення: {now}*"]
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return True

    # --- Event ---

    def _write_event(self, data: dict, chat_name: str, action: str) -> bool:
        prepared = self._prepare_write_data(data, ("canonical_name", "name"))
        if prepared is None:
            return False
        data, name = prepared

        safe_name = sanitize_filename(name)
        file_path = self.vault_path / "Events" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        confidence = data.get("confidence", "medium")
        lines = [
            "---", "tags: [event]",
            f"date: {safe_yaml_value(data.get('date', ''))}",
            f"confidence: {safe_yaml_value(confidence)}", "---", "",
            f"# 📅 {name}", "",
        ]
        if confidence != "high" and data.get("uncertainty_note"):
            lines += ["> [!warning] Неточні дані", f"> {render_item(data['uncertainty_note'])}", ""]
        if self._v(data.get("date")):
            lines += ["## Дата", render_item(data["date"]), ""]
        if self._v(data.get("description")):
            lines += ["## Опис", render_item(data["description"]), ""]
        participants = self._link_list(data.get("participants"), "people")
        if participants:
            lines += ["## Учасники"] + participants + [""]
        rp = self._link_list(data.get("related_projects"), "projects")
        if rp:
            lines += ["## Пов'язані проєкти"] + rp + [""]

        all_sources = self._render_sources(data.get("sources"), chat_name)
        lines += ["---", f"*Джерела: {', '.join(all_sources)}*", f"*Останнє оновлення: {now}*"]
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return True

    # --- Theme ---

    def _write_theme(self, data: dict, chat_name: str, action: str) -> bool:
        prepared = self._prepare_write_data(data, ("canonical_name", "name", "tag"))
        if prepared is None:
            return False
        data, name = prepared
        if not data.get("tag"):
            data["tag"] = name

        tag = self._render_theme_tag(data)
        if not tag:
            logger.warning("Пропущено тег без імені")
            return False
        safe_name = sanitize_filename(tag)
        file_path = self.vault_path / "Themes" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        lines = [
            "---", f"tags: [theme, {tag}]", "---", "",
            f"# 💬 {tag}", "",
        ]
        if self._v(data.get("description")):
            lines.append(render_item(data["description"]))
            lines.append("")
        mc = data.get("message_count", 0)
        if mc:
            lines += [f"**Згадувань:** ~{render_item(mc)}", ""]

        all_sources = self._render_sources(data.get("sources"), chat_name)
        lines += ["---", f"*Джерела: {', '.join(all_sources)}*"]
        file_path.write_text("\n".join(lines), encoding="utf-8")
        return True

    # --- Helpers ---

    @staticmethod
    def _empty_stats() -> dict:
        return {
            "created": {},
            "updated": {},
            "skipped": {"total": 0},
            "entity_links": 0,
        }

    @staticmethod
    def _clean_none(obj):
        if isinstance(obj, list):
            return [ObsidianWriter._clean_none(i) for i in obj if i is not None]
        if isinstance(obj, dict):
            return {k: ObsidianWriter._clean_none(v) for k, v in obj.items()}
        return obj

    def _prepare_write_data(self, data: dict, name_fields=("canonical_name", "name")):
        # Перевірити що data є dict
        if not isinstance(data, dict):
            logger.warning(f"Некоректні дані для запису: {type(data)}")
            return None

        data = self._clean_none(data)

        # Перевірити canonical_name
        name = ""
        for field in name_fields:
            if has_content(data.get(field)):
                name = render_item(data.get(field))
                break

        if not name or not str(name).strip():
            logger.warning("Пропущено запис без імені")
            return None

        return data, str(name).strip()

    def _render_sources(self, sources, chat_name: str) -> list:
        if not isinstance(sources, list):
            sources = [sources] if sources else []
        rendered = [render_item(src) for src in sources]
        rendered.append(render_item(chat_name))

        result = []
        seen = set()
        for src in rendered:
            if not src:
                continue
            if src not in seen:
                result.append(src)
                seen.add(src)
        return result

    def resolve_link(self, name: str, entity_type: str) -> str:
        """Перетворює ім'я на вікі-посилання, якщо воно є в реєстрі."""
        name_text = render_item(name)
        if entity_type == "themes":
            name_text = sanitize_tag(name_text)

        if not self.registry or not name_text:
            return name_text

        found_key = None
        if entity_type == "people":
            found_key = self.registry.find_person(name_text)
        else:
            found_key = self.registry.find_entity(entity_type, name_text)

        if found_key:
            canonical_name = self.registry.data[entity_type][found_key].get("canonical_name", name_text)
            if entity_type == "themes":
                canonical_name = sanitize_tag(canonical_name)
            if self.stats is not None:
                self.stats["entity_links"] = self.stats.get("entity_links", 0) + 1
            return f"[[{canonical_name}]]"

        return name_text

    def render_item(self, item) -> str:
        return render_item(item)

    def _render_theme_tag(self, theme_data) -> str:
        """Рендерить тег теми, витягуючи поле 'tag' якщо це словник."""
        return sanitize_tag(theme_data)

    @staticmethod
    def _v(val) -> bool:
        """Перевіряє чи значення не порожнє."""
        if not has_content(val):
            return False
        if isinstance(val, str) and val.strip().lower() in ("", "невідомо", "unknown", "null", "none"):
            return False
        rendered = render_item(val).strip()
        return bool(rendered and rendered.lower() not in ("невідомо", "unknown", "null", "none"))

    def _join(self, items) -> str:
        if not items or not isinstance(items, list): return ""
        return render_item(items)

    def _list_items(self, items) -> list:
        if not items or not isinstance(items, list): return []
        rendered = render_list(items)
        return rendered.splitlines() if rendered else []

    def _link_list(self, items, entity_type: str = None) -> list:
        if not items or not isinstance(items, list): return []
        rendered = render_list(items, link_resolver=self.resolve_link, entity_type=entity_type)
        return rendered.splitlines() if rendered else []

    def _build_table(self, rows: list) -> str:
        """Будує markdown-таблицю, пропускаючи порожні рядки."""
        valid_rows = [
            (label, val) for label, val in rows
            if has_content(val) and render_item(val).strip()
        ]
        if not valid_rows: return ""
        lines = ["| | |", "|---|---|"]
        for label, val in valid_rows:
            lines.append(f"| {label} | {render_item(val)} |")
        return "\n".join(lines)
