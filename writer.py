"""
writer.py — Генерація Obsidian vault з Markdown-файлами.
"""

from pathlib import Path
from datetime import datetime

from config import sanitize_filename


class ObsidianWriter:
    """Генератор Obsidian vault."""

    def __init__(self, vault_path: Path):
        self.vault_path = vault_path
        for folder in ("People", "Projects", "Events", "Themes", "Chats"):
            (vault_path / folder).mkdir(parents=True, exist_ok=True)

    def write_all(self, merge_report: dict, chat_name: str) -> dict:
        """Записує всі сутності у vault."""
        stats = {"created": {}, "updated": {}}
        for entity_type in ("people", "projects", "events", "themes"):
            created = 0
            updated = 0
            for item in (merge_report.get(entity_type) or []):
                action = item["action"]
                data = item["data"]
                canonical_key = item["canonical_key"]

                if entity_type == "people":
                    self._write_person(data, chat_name, action)
                elif entity_type == "projects":
                    self._write_project(data, chat_name, action)
                elif entity_type == "events":
                    self._write_event(data, chat_name, action)
                elif entity_type == "themes":
                    self._write_theme(data, chat_name, action)

                if action == "create":
                    created += 1
                else:
                    updated += 1

            stats["created"][entity_type] = created
            stats["updated"][entity_type] = updated
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
            f"processed: {now}",
            f"language: {chat_language}",
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
        people_names = [p.get("name", "") for p in (entities.get("people") or [])]
        if people_names:
            lines.append("## Люди")
            for name in people_names:
                lines.append(f"- [[{name}]]")
            lines.append("")

        # Проєкти
        project_names = [p.get("name", "") for p in (entities.get("projects") or [])]
        if project_names:
            lines.append("## Проєкти")
            for name in project_names:
                lines.append(f"- [[{name}]]")
            lines.append("")

        # Події
        event_names = [e.get("name", "") for e in (entities.get("events") or [])]
        if event_names:
            lines.append("## Події")
            for name in event_names:
                lines.append(f"- [[{name}]]")
            lines.append("")

        # Теми
        theme_tags = [t.get("tag", "") for t in (entities.get("themes") or [])]
        if theme_tags:
            lines.append("## Теми")
            for tag in theme_tags:
                lines.append(f"- [[{tag}]]")
            lines.append("")

        file_path.write_text("\n".join(lines), encoding="utf-8")

    # --- Person ---

    def _write_person(self, data: dict, chat_name: str, action: str) -> None:
        name = data.get("name", "Unknown")
        safe_name = sanitize_filename(name)
        file_path = self.vault_path / "People" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        if action == "update" and file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            existing = self._append_update_footer(existing, chat_name, now)
            file_path.write_text(existing, encoding="utf-8")
            return

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
            f"confidence: {confidence}",
            f"telegram_id: {telegram_id or ''}",
            f"relation: {rels.get('relation_to_me', 'невідомо')}",
            f"closeness: {rels.get('closeness', 'далекий')}",
            "---",
            "",
            f"# 👤 {name}",
            "",
        ]

        if confidence != "high" and data.get("uncertainty_note"):
            lines += [
                "> [!warning] Неточні дані",
                f"> {data['uncertainty_note']}",
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
        if self._v(prof.get("position")): prof_lines.append(f"**Посада:** {prof['position']}")
        if self._v(prof.get("company")): prof_lines.append(f"**Компанія:** {prof['company']}")
        if self._v(prof.get("industry")): prof_lines.append(f"**Сфера:** {prof['industry']}")
        if self._v(prof.get("occupation")): prof_lines.append(f"**Діяльність:** {prof['occupation']}")
        if self._v(prof.get("skills")): prof_lines.append(f"**Навички:** {self._join(prof['skills'])}")

        edu_lines = []
        if self._v(edu.get("degree")): edu_lines.append(f"**Ступінь:** {edu['degree']}")
        if self._v(edu.get("institution")): edu_lines.append(f"**Заклад:** {edu['institution']}")
        if self._v(edu.get("field")): edu_lines.append(f"**Спеціальність:** {edu['field']}")
        if self._v(edu.get("graduation_year")): edu_lines.append(f"**Рік закінчення:** {edu['graduation_year']}")

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
        if self._v(lifestyle.get("alcohol")): ls_lines.append(f"**Алкоголь:** {lifestyle['alcohol']}")
        if self._v(lifestyle.get("smoking")): ls_lines.append(f"**Куріння:** {lifestyle['smoking']}")
        if self._v(lifestyle.get("sleep_pattern")): ls_lines.append(f"**Режим:** {lifestyle['sleep_pattern']}")
        if self._v(lifestyle.get("car")): ls_lines.append(f"**Авто:** {lifestyle['car']}")
        travel = []
        if self._v(lifestyle.get("travel_history")): travel.append(f"**Бував у:** {self._join(lifestyle['travel_history'])}")
        if self._v(lifestyle.get("dream_destinations")): travel.append(f"**Хоче відвідати:** {self._join(lifestyle['dream_destinations'])}")
        if ls_lines or travel:
            lines += ["## 🎯 Спосіб життя", ""] + ls_lines
            if travel: lines += ["", "### Подорожі"] + travel
            lines += ["", "---", ""]

        # Фінанси
        fin_lines = []
        if self._v(finances.get("income_level")): fin_lines.append(f"**Рівень доходу:** {finances['income_level']}")
        if self._v(finances.get("spending_habits")): fin_lines.append(f"**Звички витрат:** {finances['spending_habits']}")
        if self._v(finances.get("business_activity")): fin_lines.append(f"**Бізнес-активність:** {finances['business_activity']}")
        if self._v(finances.get("financial_problems")): fin_lines.append(f"**Фінансові проблеми:** {finances['financial_problems']}")
        if fin_lines:
            lines += ["## 💰 Фінанси", ""] + fin_lines + ["", "---", ""]

        # Здоров'я
        h_lines = []
        if self._v(health.get("general")): h_lines.append(f"**Загальне:** {health['general']}")
        if self._v(health.get("known_conditions")): h_lines.append(f"**Відомі особливості:** {self._join(health['known_conditions'])}")
        if self._v(health.get("sports_activity")): h_lines.append(f"**Фізична активність:** {health['sports_activity']}")
        if self._v(health.get("diet")): h_lines.append(f"**Харчування:** {health['diet']}")
        if h_lines:
            lines += ["## 🏥 Здоров'я", ""] + h_lines + ["", "---", ""]

        # Психологія
        p_lines = []
        if self._v(psych.get("communication_style")): p_lines.append(f"**Стиль спілкування:** {psych['communication_style']}")
        if self._v(psych.get("humor_style")): p_lines.append(f"**Гумор:** {psych['humor_style']}")
        if self._v(psych.get("temperament")): p_lines.append(f"**Темперамент:** {psych['temperament']}")
        if self._v(psych.get("values")): p_lines.append(f"**Цінності:** {self._join(psych['values'])}")
        if self._v(psych.get("political_views")): p_lines.append(f"**Політичні погляди:** {psych['political_views']}")
        if self._v(psych.get("religion")): p_lines.append(f"**Релігія:** {psych['religion']}")
        fears = self._list_items(psych.get("fears"))
        insec = self._list_items(psych.get("insecurities"))
        motiv = self._list_items(psych.get("motivations"))
        goals = self._list_items(psych.get("life_goals"))
        probs = self._list_items(psych.get("current_problems"))
        if p_lines or fears or motiv or goals or probs:
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
        if self._v(comms.get("responds_well_to")): c_lines.append(f"**Добре реагує на:** {comms['responds_well_to']}")
        if self._v(comms.get("best_time_to_reach")): c_lines.append(f"**Найкращий час:** {comms['best_time_to_reach']}")
        if self._v(comms.get("typical_response_speed")): c_lines.append(f"**Швидкість відповіді:** {comms['typical_response_speed']}")
        if self._v(comms.get("uses_voice_messages")): c_lines.append(f"**Голосові:** {comms['uses_voice_messages']}")
        if self._v(comms.get("emoji_usage")): c_lines.append(f"**Емодзі:** {comms['emoji_usage']}")
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
        if self._v(rels.get("relation_description")): rel_extra.append(f"**Опис:** {rels['relation_description']}")
        if self._v(rels.get("romantic_history_with_me")): rel_extra.append(f"**Романтична історія:** {rels['romantic_history_with_me']}")
        friends = self._link_list(rels.get("friends_with"))
        conflicts = self._link_list(rels.get("conflicts_with"))
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
        if quotes:
            lines += ["## 💭 Характерні цитати", ""]
            for q in quotes:
                if q: lines.append(f"> {q}")
                lines.append("")
            lines += ["---", ""]

        # Факти
        facts = self._list_items(data.get("facts"))
        if facts:
            lines += ["## 📝 Інші факти"] + facts + [""]

        # Проєкти, Події, Теми
        mp = self._link_list(data.get("mentioned_projects"))
        if mp: lines += ["## 📁 Проєкти"] + mp + [""]
        me = self._link_list(data.get("mentioned_events"))
        if me: lines += ["## 📅 Події"] + me + [""]
        mt = data.get("mentioned_themes") or []
        if mt:
            lines += ["## 🏷 Теми", " ".join(f"#{t}" for t in mt), ""]

        # Футер
        lines += [
            "---",
            f"*Джерела: {chat_name}*",
            f"*Оновлено: {now}*",
        ]

        file_path.write_text("\n".join(lines), encoding="utf-8")

    # --- Project ---

    def _write_project(self, data: dict, chat_name: str, action: str) -> None:
        name = data.get("name", "Unknown")
        safe_name = sanitize_filename(name)
        file_path = self.vault_path / "Projects" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        if action == "update" and file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            existing = self._append_update_footer(existing, chat_name, now)
            file_path.write_text(existing, encoding="utf-8")
            return

        confidence = data.get("confidence", "medium")
        lines = [
            "---", "tags: [project]",
            f"status: {data.get('status', 'невідомо')}",
            f"confidence: {confidence}", "---", "",
            f"# 📁 {name}", "",
        ]
        if confidence != "high" and data.get("uncertainty_note"):
            lines += ["> [!warning] Неточні дані", f"> {data['uncertainty_note']}", ""]
        if self._v(data.get("description")):
            lines += ["## Опис", data["description"], ""]
        if self._v(data.get("status")):
            lines += ["## Статус", data["status"], ""]
        participants = self._link_list(data.get("participants"))
        if participants:
            lines += ["## Учасники"] + participants + [""]
        kd = self._list_items(data.get("key_dates"))
        if kd:
            lines += ["## Ключові дати"] + kd + [""]
        lines += ["---", f"*Джерела: {chat_name}*", f"*Оновлено: {now}*"]
        file_path.write_text("\n".join(lines), encoding="utf-8")

    # --- Event ---

    def _write_event(self, data: dict, chat_name: str, action: str) -> None:
        name = data.get("name", "Unknown")
        safe_name = sanitize_filename(name)
        file_path = self.vault_path / "Events" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        if action == "update" and file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            existing = self._append_update_footer(existing, chat_name, now)
            file_path.write_text(existing, encoding="utf-8")
            return

        confidence = data.get("confidence", "medium")
        lines = [
            "---", "tags: [event]",
            f"date: {data.get('date', '')}",
            f"confidence: {confidence}", "---", "",
            f"# 📅 {name}", "",
        ]
        if confidence != "high" and data.get("uncertainty_note"):
            lines += ["> [!warning] Неточні дані", f"> {data['uncertainty_note']}", ""]
        if self._v(data.get("date")):
            lines += ["## Дата", str(data["date"]), ""]
        if self._v(data.get("description")):
            lines += ["## Опис", data["description"], ""]
        participants = self._link_list(data.get("participants"))
        if participants:
            lines += ["## Учасники"] + participants + [""]
        rp = self._link_list(data.get("related_projects"))
        if rp:
            lines += ["## Пов'язані проєкти"] + rp + [""]
        lines += ["---", f"*Джерела: {chat_name}*", f"*Оновлено: {now}*"]
        file_path.write_text("\n".join(lines), encoding="utf-8")

    # --- Theme ---

    def _write_theme(self, data: dict, chat_name: str, action: str) -> None:
        tag = data.get("tag", data.get("name", "unknown"))
        safe_name = sanitize_filename(tag)
        file_path = self.vault_path / "Themes" / f"{safe_name}.md"
        now = datetime.now().strftime("%Y-%m-%d")

        if action == "update" and file_path.exists():
            existing = file_path.read_text(encoding="utf-8")
            existing = self._append_update_footer(existing, chat_name, now)
            file_path.write_text(existing, encoding="utf-8")
            return

        lines = [
            "---", f"tags: [theme, {tag}]", "---", "",
            f"# 💬 {tag}", "",
        ]
        if self._v(data.get("description")):
            lines.append(data["description"])
            lines.append("")
        mc = data.get("message_count", 0)
        if mc:
            lines += [f"**Згадувань:** ~{mc}", ""]
        lines += ["---", f"*Джерела: {chat_name}*"]
        file_path.write_text("\n".join(lines), encoding="utf-8")

    # --- Helpers ---

    @staticmethod
    def _v(val) -> bool:
        """Перевіряє чи значення не порожнє."""
        if val is None: return False
        if isinstance(val, str) and val.strip() in ("", "невідомо", "null"): return False
        if isinstance(val, list) and len(val) == 0: return False
        return True

    @staticmethod
    def _join(items) -> str:
        if not items or not isinstance(items, list): return ""
        return ", ".join(str(i) for i in items if i)

    @staticmethod
    def _list_items(items) -> list:
        if not items or not isinstance(items, list): return []
        return [f"- {item}" for item in items if item]

    @staticmethod
    def _link_list(items) -> list:
        if not items or not isinstance(items, list): return []
        return [f"- [[{item}]]" for item in items if item]

    @staticmethod
    def _build_table(rows: list) -> str:
        """Будує markdown-таблицю, пропускаючи порожні рядки."""
        valid_rows = [(label, val) for label, val in rows if ObsidianWriter._v(val)]
        if not valid_rows: return ""
        lines = ["| | |", "|---|---|"]
        for label, val in valid_rows:
            lines.append(f"| {label} | {val} |")
        return "\n".join(lines)

    @staticmethod
    def _append_update_footer(existing: str, chat_name: str, date: str) -> str:
        footer = f"\n- Доповнено з: {chat_name} ({date})\n"
        if footer.strip() not in existing:
            existing += footer
        return existing
