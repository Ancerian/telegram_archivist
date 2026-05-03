"""
analyzer.py — Аналіз повідомлень через LLM (Gemini / Claude / OpenAI / Local).
"""

import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime, timezone
from config import SYSTEM_PROMPT, normalize_name


class SmartBatcher:
    """Розумний батчер, що розбиває повідомлення по контексту (діалоги)."""
    @staticmethod
    def _estimate_tokens(msg: dict, provider: str = "google") -> int:
        text = (msg.get("text") or "") + " " + (msg.get("transcript") or "")
        words = len(text.split())

        if provider == "local":
            # Кирилиця важча для токенізації
            return int(words * 2.5) + 20
        else:
            # OpenAI/Anthropic/Google — стандартна оцінка
            try:
                import tiktoken
                enc = tiktoken.get_encoding("cl100k_base")
                return len(enc.encode(text)) + 20
            except ImportError:
                return int(words * 1.3) + 20

    @staticmethod
    def split_by_context(messages: list, target_tokens: int, absolute_tokens: int, provider: str = "google") -> list[dict]:
        if not messages:
            return []

        # Крок 1: Розбивка на діалогові сесії (>3 години пауза)
        sessions = []
        current_session = []
        last_time = None

        for msg in messages:
            date_str = msg.get("date")
            current_time = None
            if date_str:
                try:
                    # telegram format usually: 2024-01-01T12:00:00
                    current_time = datetime.fromisoformat(date_str.replace("Z", "+00:00"))
                except ValueError:
                    pass

            if current_time and last_time:
                diff = (current_time - last_time).total_seconds()
                if diff > 3 * 3600:
                    if current_session:
                        sessions.append(current_session)
                        current_session = []

            current_session.append(msg)
            if current_time:
                last_time = current_time

        if current_session:
            sessions.append(current_session)

        # Крок 2, 3: Жадібне збирання
        target_tokens = max(1000, target_tokens)
        absolute_tokens = max(1000, absolute_tokens)
        batches = []
        current_batch = []
        current_tokens = 0

        def flush_batch():
            nonlocal current_batch, current_tokens, batches
            if current_batch:
                batches.append({"messages": current_batch, "is_huge": False})
                current_batch = []
                current_tokens = 0

        for session in sessions:
            session_tokens = sum(SmartBatcher._estimate_tokens(m, provider) for m in session)

            if current_tokens + session_tokens <= target_tokens:
                current_batch.extend(session)
                current_tokens += session_tokens
            else:
                if current_batch:
                    flush_batch()

                if session_tokens <= target_tokens:
                    current_batch.extend(session)
                    current_tokens = session_tokens
                elif session_tokens <= absolute_tokens:
                    # Це huge batch, але він влазить у абсолютний ліміт
                    batches.append({"messages": session, "is_huge": True})
                else:
                    # Діалог більший навіть за абсолютний ліміт. Дробимо його
                    temp_batch = []
                    temp_tokens = 0
                    last_author = None
                    for m in session:
                        m_tokens = SmartBatcher._estimate_tokens(m, provider)
                        author = m.get("from_name")

                        if temp_tokens + m_tokens > absolute_tokens and temp_batch:
                            # Ділимо при зміні автора, або примусово якщо вже суттєво перебрали ліміт (напр. > 1.2x)
                            if author != last_author or temp_tokens > absolute_tokens * 1.2:
                                batches.append({"messages": temp_batch, "is_huge": True})
                                temp_batch = []
                                temp_tokens = 0

                        temp_batch.append(m)
                        temp_tokens += m_tokens
                        last_author = author

                    if temp_batch:
                        batches.append({"messages": temp_batch, "is_huge": True})

        flush_batch()

        # Крок 4: Перекриття (додаємо останні 3 повідомлення до наступного батчу)
        for i in range(1, len(batches)):
            overlap = batches[i-1]["messages"][-3:]
            marked_overlap = []
            for m in overlap:
                m_copy = m.copy()
                m_copy["is_overlap"] = True
                marked_overlap.append(m_copy)
            batches[i]["messages"] = marked_overlap + batches[i]["messages"]

        return batches


class EntityAnalyzer:
    """Аналізатор сутностей через LLM."""

    def __init__(self, provider: str, api_key: str, chat_name: str, chat_language: str,
                 model: str = None, local_url: str = "http://localhost:1234/v1",
                 progress_callback=None, max_concurrent=4,
                 is_running_callback=None, max_tokens=128000, absolute_max_tokens=128000,
                 use_cot: bool = None):
        self.provider = provider
        self.api_key = api_key
        self.chat_name = chat_name
        self.chat_language = chat_language
        self.model = model
        self.local_url = local_url
        self.progress_callback = progress_callback
        self.max_concurrent = max_concurrent
        self.is_running_callback = is_running_callback
        self.max_tokens = max_tokens
        self.absolute_max_tokens = absolute_max_tokens
        # Default CoT for local models if not specified
        self.use_cot = use_cot if use_cot is not None else (provider == "local")
        self.incremental_info = {
            "enabled": False,
            "last_processed_date": None,
            "new_count": None,
        }
        self.last_analyzed_messages = []

        self._check_tiktoken()

    def _check_tiktoken(self):
        try:
            import tiktoken
            msg = "✓ tiktoken встановлено, точний підрахунок токенів"
        except ImportError:
            msg = "⚠️ tiktoken не знайдено, використовується приблизна оцінка"
        print(msg)
        if self.progress_callback:
            self.progress_callback(msg)

    def detect_max_concurrent(self) -> int:
        """Визначає скільки моделей завантажено в LM Studio."""
        if self.provider == "local" and self.local_url:
            try:
                import requests
                base_url = self.local_url.split("/v1")[0]
                r = requests.get(f"{base_url}/api/v0/models", timeout=2)
                if r.status_code == 200:
                    data = r.json().get("data", [])
                    loaded = [m for m in data if m.get("state") == "loaded" and m.get("type") == "llm"]
                    count = len(loaded)
                    if count > 0:
                        return count
            except Exception:
                pass
        return 1

    def analyze(self, messages: list, known_entities: dict, checkpoint_path: Path = None) -> dict:
        """
        Аналізує повідомлення батчами паралельно.
        """
        import concurrent.futures
        import time
        from config import SYSTEM_PROMPT

        accumulated = {
            "people": [],
            "projects": [],
            "events": [],
            "themes": [],
        }
        processed_batch_nums = set()
        checkpoint = self._load_checkpoint(checkpoint_path)
        previous_last_processed_date = checkpoint.get("last_processed_date")

        if previous_last_processed_date:
            since_dt = self._parse_datetime(previous_last_processed_date)
            if since_dt:
                messages = self._filter_messages_since(messages, since_dt)
                self.incremental_info = {
                    "enabled": True,
                    "last_processed_date": previous_last_processed_date,
                    "new_count": len(messages),
                }
                msg = f"📅 Інкрементальний режим: {len(messages)} нових повідомлень з {previous_last_processed_date}"
                print(msg)
                if self.progress_callback:
                    self.progress_callback(msg)

                if not messages:
                    msg = "✅ Нових повідомлень немає, vault актуальний"
                    print(msg)
                    if self.progress_callback:
                        self.progress_callback(msg)
                    self.last_analyzed_messages = []
                    return accumulated

        self.last_analyzed_messages = messages

        # Оцінюємо розмір статичного оверхеду
        system_words = len(SYSTEM_PROMPT.split())
        entities_words = len(json.dumps(known_entities, ensure_ascii=False).split())
        overhead_factor = 2.5 if self.provider == "local" else 1.3
        static_overhead_tokens = int((system_words + entities_words) * overhead_factor) + 500

        actual_max_tokens = max(1000, self.max_tokens - static_overhead_tokens)
        actual_absolute_tokens = max(1000, self.absolute_max_tokens - static_overhead_tokens)

        batch_list = SmartBatcher.split_by_context(messages, actual_max_tokens, actual_absolute_tokens, self.provider)
        total_batches = len(batch_list)
        total_tokens = sum(sum(SmartBatcher._estimate_tokens(m, self.provider) for m in b["messages"]) for b in batch_list)

        def _format_time(seconds):
            seconds = int(seconds)
            if seconds < 3600:
                return f"{seconds // 60:02d}:{seconds % 60:02d}"
            return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

        cot_msg = " (+ CoT)" if self.use_cot else ""
        msg = f"📊 Аналіз{cot_msg}: {total_batches} батчів | ~{int(total_tokens)} токенів | ETA: ~{_format_time(total_batches * (20 if self.use_cot else 10))} хв"
        print(msg)
        if self.progress_callback:
            self.progress_callback(msg)

        if checkpoint.get("batching_version") in (2, 3) and checkpoint.get("processed_batches"):
            accumulated = checkpoint.get("accumulated", accumulated)
            processed_batch_nums = set(checkpoint.get("processed_batches", []))
            msg = f"  🔄 Відновлено прогрес: {len(processed_batch_nums)}/{total_batches} батчів"
            print(msg)
            if self.progress_callback: self.progress_callback(msg)

        batches = []
        huge_batches = []
        for i, batch_dict in enumerate(batch_list):
            batch_num = i + 1
            if batch_num in processed_batch_nums:
                continue
            if batch_dict.get("is_huge"):
                huge_batches.append((batch_num, batch_dict["messages"]))
            else:
                batches.append((batch_num, batch_dict["messages"]))

        if not batches and not huge_batches and not processed_batch_nums:
            return accumulated

        if not batches and not huge_batches:
            print("  ✅ Всі повідомлення вже оброблені з чекпоінту")
            return accumulated

        def _save_checkpoint():
            if not checkpoint_path: return
            try:
                with open(checkpoint_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "batching_version": 3,
                        "last_processed_date": previous_last_processed_date,
                        "accumulated": accumulated,
                        "processed_batches": list(processed_batch_nums),
                    }, f, ensure_ascii=False, indent=2)
            except Exception: pass

        def _process_batch(batch_tuple, depth=0):
            b_num, batch = batch_tuple
            max_retries = 3

            user_message = self._build_user_message(batch, known_entities, messages)

            for attempt in range(max_retries):
                if self.is_running_callback and not self.is_running_callback(): return None

                attempt_str = f" (спроба {attempt + 1}/{max_retries})" if attempt > 0 else ""
                indent = "  " * (depth + 1)
                msg = f"{indent}📊 Батч {b_num}/{total_batches} ({len(batch)} повідомлень){attempt_str}"
                print(msg)
                if self.progress_callback: self.progress_callback(msg)

                try:
                    if self.use_cot:
                        # Етап 1: Вільний переказ фактів
                        cot_prompt = f"Уважно прочитай наступний фрагмент чату і перерахуй ВСІ факти про кожну людину, проєкт та подію у вільній формі. Не пропускай нічого: імена, звички, події, настрій, плани, цитати. Формат: просто список фактів, не JSON.\n\n{user_message}"
                        facts = self._call_llm(cot_prompt, is_cot_stage=True)
                        # Етап 2: Структуризація
                        structure_prompt = f"На основі цих фактів:\n{facts}\n\nТа оригінальних повідомлень:\n{user_message}\n\nЗаповни JSON структуру досьє за схемою з системного промпту."
                        response_text = self._call_llm(structure_prompt)
                    else:
                        response_text = self._call_llm(user_message)

                    if response_text:
                        parsed = self._validate_and_fix(response_text, b_num, user_message, batch)
                        if parsed:
                            return self._audit_attribution(parsed, batch)
                except Exception as e:
                    err_str = str(e).lower()
                    if ("context size" in err_str or "context length" in err_str or "context window" in err_str) and len(batch) > 1:
                        mid = len(batch) // 2
                        res1 = _process_batch((b_num, batch[:mid]), depth + 1)
                        res2 = _process_batch((b_num, batch[mid:]), depth + 1)
                        if res1 and res2:
                            self._accumulate(res1, res2)
                            return res1
                        return res1 or res2
                    print(f"  ❌ Помилка LLM у батчі {b_num}: {e}", file=sys.stderr)

                if attempt < max_retries - 1: time.sleep((attempt + 1) * 2)

            return None

        def run_queue(queue_batches, force_max=None):
            nonlocal processed_batch_nums
            if not queue_batches: return

            def get_current_max():
                if force_max is not None: return force_max
                if callable(self.max_concurrent): return max(1, int(self.max_concurrent()))
                return max(1, int(self.max_concurrent))

            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
                future_to_num = {}
                batch_iter = iter(queue_batches)
                batch_iter_exhausted = False

                while True:
                    if self.is_running_callback and not self.is_running_callback(): break

                    for f in list(future_to_num.keys()):
                        if f.done():
                            b_num = future_to_num.pop(f)
                            try:
                                parsed = f.result()
                                if parsed:
                                    self._accumulate(accumulated, parsed)
                                    if self.progress_callback: self.progress_callback(f"  ✅ Батч {b_num} оброблено")
                                processed_batch_nums.add(b_num)
                                _save_checkpoint()
                            except Exception as e:
                                print(f"  ❌ Помилка у батчі {b_num}: {e}")

                    if not batch_iter_exhausted:
                        while len(future_to_num) < get_current_max():
                            try:
                                next_batch = next(batch_iter)
                                fut = executor.submit(_process_batch, next_batch)
                                future_to_num[fut] = next_batch[0]
                            except StopIteration:
                                batch_iter_exhausted = True
                                break

                    if batch_iter_exhausted and not future_to_num: break
                    time.sleep(0.1)

        run_queue(batches)
        run_queue(huge_batches, force_max=1 if self.provider == "local" else None)

        if len(processed_batch_nums) >= total_batches:
            self._write_completion_checkpoint(checkpoint_path, messages)

        return accumulated

    @staticmethod
    def _load_checkpoint(checkpoint_path: Path | None) -> dict:
        if not checkpoint_path or not checkpoint_path.exists():
            return {}
        try:
            with open(checkpoint_path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return {}

    @staticmethod
    def get_last_processed_date(checkpoint_path: Path | None) -> datetime | None:
        checkpoint = EntityAnalyzer._load_checkpoint(checkpoint_path)
        return EntityAnalyzer._parse_datetime(checkpoint.get("last_processed_date"))

    @staticmethod
    def get_last_processed_date_text(checkpoint_path: Path | None) -> str | None:
        checkpoint = EntityAnalyzer._load_checkpoint(checkpoint_path)
        return checkpoint.get("last_processed_date")

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if not value:
            return None
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is not None:
            parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
        return parsed

    @staticmethod
    def _filter_messages_since(messages: list, since: datetime) -> list:
        since_dt = EntityAnalyzer._parse_datetime(since.isoformat()) if isinstance(since, datetime) else EntityAnalyzer._parse_datetime(since)
        if since_dt is None:
            return messages
        result = []
        for msg in messages:
            msg_dt = EntityAnalyzer._parse_datetime(msg.get("date"))
            if msg_dt and msg_dt > since_dt:
                result.append(msg)
        return result

    def _write_completion_checkpoint(self, checkpoint_path: Path | None, messages: list) -> None:
        if not checkpoint_path or not messages:
            return
        dates = [msg.get("date") for msg in messages if msg.get("date")]
        if not dates:
            return
        last_processed_date = max(dates, key=lambda d: self._parse_datetime(d) or datetime.min)
        try:
            with open(checkpoint_path, "w", encoding="utf-8") as f:
                json.dump({
                    "batching_version": 3,
                    "last_processed_date": last_processed_date,
                    "updated_at": datetime.now().isoformat(timespec="seconds"),
                }, f, ensure_ascii=False, indent=2)
        except Exception as e:
            msg = f"  ⚠️ Не вдалося зберегти дату останнього аналізу: {e}"
            print(msg, file=sys.stderr)
            if self.progress_callback:
                self.progress_callback(msg)

    def _build_user_message(self, batch: list, known_entities: dict, all_messages: list = None) -> str:
        """Будує user message з додаванням контексту відомих сутностей."""
        all_messages = all_messages or batch
        participants = sorted(set(m["from_name"] for m in all_messages if m.get("from_name") and m["from_name"] != "Unknown"))

        def _format_time(date_value) -> str:
            if not date_value:
                return "?"
            date_text = str(date_value)
            try:
                parsed = datetime.fromisoformat(date_text.replace("Z", "+00:00"))
                return parsed.strftime("%Y-%m-%d %H:%M")
            except ValueError:
                return date_text.replace("T", " ")

        def _media_label(media_type: str) -> str:
            labels = {
                "photo": "фото",
                "voice_message": "голосове",
                "video_message": "відеоповідомлення",
                "video_file": "відео",
                "animation": "анімація",
                "sticker": "стікер",
                "audio_file": "аудіо",
                "file": "файл",
            }
            return labels.get(media_type, media_type or "медіа")

        lines = []
        for msg in batch:
            date_str = _format_time(msg.get("date"))
            from_name = msg.get("from_name") or "Unknown"
            from_id = msg.get("from_id") or "unknown"
            text = msg.get("text", "")
            media_type = msg.get("media_type")
            transcript = msg.get("transcript")
            duration = msg.get("duration")
            language = msg.get("detected_language") or self.chat_language or "unknown"
            is_overlap = msg.get("is_overlap")

            block = [
                "---",
                f"АВТОР: {from_name} ({from_id})",
                f"ЧАС: {date_str}",
            ]
            if is_overlap:
                block.append("КОНТЕКСТ: так")

            if media_type in ("voice_message", "video_message"):
                duration_text = f"{duration}с" if duration is not None else "?с"
                label = "ГОЛОСОВЕ" if media_type == "voice_message" else "ВІДЕОПОВІДОМЛЕННЯ"
                block.append(f"{label} ({duration_text}, мова: {language}): {transcript or ''}")
            elif media_type:
                block.append(f"МЕДІА: [{_media_label(media_type)}]")
                if text:
                    block.append(f"ТЕКСТ: {text}")
            else:
                block.append(f"ТЕКСТ: {text}")

            block.append("---")
            lines.append("\n".join(block))

        messages_text = "\n\n".join(lines)

        # Додаємо списки відомих сутностей для запобігання дублікатів (обмежуємо до 100 останніх, щоб не переповнити контекст)
        known_people = ", ".join(known_entities.get("known_people", [])[-100:])
        known_projects = ", ".join(known_entities.get("known_projects", [])[-100:])
        known_themes = ", ".join(known_entities.get("known_themes", [])[-100:])

        return f"""ВЖЕ ВІДОМІ СУТНОСТІ (використовуй ці назви, не створюй дублікати):
Люди: {known_people}
Проєкти: {known_projects}
Теми: {known_themes}

Чат: {self.chat_name}
Період: {batch[0].get('date', '?')} — {batch[-1].get('date', '?')}
Учасники: {', '.join(participants)}

Повідомлення:
{messages_text}"""

    def _call_llm(self, user_message: str, is_cot_stage: bool = False, system_override: str = None) -> str:
        """Викликає LLM провайдер."""
        system = system_override or SYSTEM_PROMPT
        if is_cot_stage:
            system = (
                "Ти — уважний аналітик. Твоє завдання — виписати всі факти з переписки.\n"
                "КРИТИЧНО: для кожного факту зберігай правильну атрибуцію. "
                "Факт про людину бери тільки з її власного повідомлення або з явної згадки про неї. "
                "Якщо не впевнений, не включай факт."
            )

        if self.provider == "google":
            import google.generativeai as genai
            genai.configure(api_key=self.api_key)
            model = genai.GenerativeModel(self.model or "gemini-2.0-flash")
            return model.generate_content(system + "\n\n" + user_message).text
        elif self.provider == "local":
            import openai
            client = openai.OpenAI(base_url=self.local_url, api_key="lm-studio")
            response = client.chat.completions.create(
                model=self.model or "local-model",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_message}],
                temperature=0.3,
                timeout=3600
            )
            return response.choices[0].message.content
        # ... інші провайдери аналогічно
        elif self.provider == "anthropic":
            import anthropic
            client = anthropic.Anthropic(api_key=self.api_key)
            response = client.messages.create(
                model=self.model or "claude-sonnet-4-20250514",
                max_tokens=4096,
                system=system,
                messages=[{"role": "user", "content": user_message}],
            )
            return response.content[0].text
        elif self.provider == "openai":
            import openai
            client = openai.OpenAI(api_key=self.api_key)
            response = client.chat.completions.create(
                model=self.model or "gpt-4o",
                messages=[{"role": "system", "content": system}, {"role": "user", "content": user_message}],
            )
            return response.choices[0].message.content
        return ""

    def generate_chat_summary(self, messages: list, entities: dict) -> str | None:
        """Генерує коротке зведення чату без блокування основного pipeline."""
        if not messages:
            return None

        try:
            dates = [msg.get("date") for msg in messages if msg.get("date")]
            first_date = dates[0] if dates else "?"
            last_date = dates[-1] if dates else "?"
            participants = sorted(set(
                msg.get("from_name")
                for msg in messages
                if msg.get("from_name") and msg.get("from_name") != "Unknown"
            ))
            people = [p.get("name") for p in (entities.get("people") or []) if isinstance(p, dict) and p.get("name")]
            projects = [p.get("name") for p in (entities.get("projects") or []) if isinstance(p, dict) and p.get("name")]
            events = [e.get("name") for e in (entities.get("events") or []) if isinstance(e, dict) and e.get("name")]
            themes = sorted(
                [t for t in (entities.get("themes") or []) if isinstance(t, dict)],
                key=lambda item: item.get("message_count") or 0,
                reverse=True,
            )
            top_themes = [t.get("tag") or t.get("name") for t in themes[:10] if t.get("tag") or t.get("name")]

            system = (
                "Ти отримуєш список сутностей витягнутих з чату.\n"
                "Напиши короткий звіт про цей чат у вільній формі.\n"
                "Відповідай мовою чату."
            )
            user_message = f"""Чат: {self.chat_name}
Період: {first_date} — {last_date}
Учасників: {len(participants)}
Люди: {', '.join(people) if people else 'немає'}
Топ теми: {', '.join(top_themes) if top_themes else 'немає'}
Проєкти: {', '.join(projects) if projects else 'немає'}
Події: {', '.join(events) if events else 'немає'}

Напиши:
1. Загальна атмосфера чату (2-3 речення)
2. Головні теми розмов (3-5 пунктів)
3. Ключові події за період (якщо є)
4. Цікаві спостереження (необов'язково)"""

            summary = self._call_llm(user_message, system_override=system)
            return summary.strip() if summary and summary.strip() else None
        except Exception as e:
            msg = f"  ⚠️ Summary пропущено: {e}"
            print(msg, file=sys.stderr)
            if self.progress_callback:
                self.progress_callback(msg)
            return None

    def _validate_and_fix(self, text: str, batch_num: int, original_prompt: str, batch: list) -> dict:
        """Валідує та виправляє JSON."""
        def _ensure_keys(parsed_dict: dict) -> dict:
            for k in ["people", "projects", "events", "themes"]:
                if k not in parsed_dict or not isinstance(parsed_dict[k], list): parsed_dict[k] = []
            return parsed_dict

        def _apply_author_ids(parsed_dict: dict) -> dict:
            author_ids = {
                msg.get("from_name"): msg.get("from_id")
                for msg in (batch or [])
                if msg.get("from_name") and msg.get("from_id")
            }

            for person in parsed_dict.get("people", []):
                if not isinstance(person, dict):
                    continue
                name = person.get("name")
                if name in author_ids and person.get("telegram_id") is None:
                    person["telegram_id"] = author_ids[name]
            return parsed_dict

        try:
            match = re.search(r'\{.*\}', text, re.DOTALL)
            if match:
                clean_json = match.group()
                # Базова чистка для локальних моделей
                clean_json = re.sub(r',\s*([}\]])', r'\1', clean_json)
                # Одинарні лапки
                clean_json = re.sub(r"(?<![a-zA-Zа-яА-ЯіІїЇєЄґҐ])'|'(?![a-zA-Zа-яА-ЯіІїЇєЄґҐ])", '"', clean_json)
                return _apply_author_ids(_ensure_keys(json.loads(clean_json)))
        except Exception:
            pass
        return None

    def _audit_attribution(self, result: dict, batch: list) -> dict:
        """Коригує впевненість для людей, які не були авторами в поточному батчі."""
        authors = {}
        for msg in batch or []:
            name = msg.get("from_name")
            if not name:
                continue
            if name not in authors:
                authors[name] = {"messages": [], "from_id": msg.get("from_id")}
            authors[name]["messages"].append(msg.get("text") or msg.get("transcript") or "")

        author_names = {normalize_name(name) for name in authors}
        author_ids = {
            str(info.get("from_id"))
            for info in authors.values()
            if info.get("from_id")
        }

        people = result.get("people") or []
        adjusted = 0
        note = "Людина не писала в цьому фрагменті, факти отримані з чужих слів"

        for person in people:
            if not isinstance(person, dict):
                continue

            person_name = person.get("name") or person.get("canonical_name") or ""
            person_ids = []
            if person.get("telegram_id"):
                person_ids.append(person.get("telegram_id"))
            if isinstance(person.get("telegram_ids"), list):
                person_ids.extend(person.get("telegram_ids"))

            is_author_by_name = normalize_name(person_name) in author_names if person_name else False
            is_author_by_id = any(str(pid) in author_ids for pid in person_ids if pid)

            if is_author_by_name or is_author_by_id:
                continue

            changed = False
            if person.get("confidence") == "high":
                person["confidence"] = "medium"
                changed = True

            existing_note = person.get("uncertainty_note")
            if existing_note:
                if note not in str(existing_note):
                    person["uncertainty_note"] = f"{existing_note}; {note}"
                    changed = True
            else:
                person["uncertainty_note"] = note
                changed = True

            if changed:
                adjusted += 1

        msg = f"  🔍 Attribution audit: скориговано {adjusted} записів з {len(people)} людей"
        print(msg)
        if self.progress_callback:
            self.progress_callback(msg)

        return result

    def _accumulate(self, accumulated: dict, batch_result: dict) -> None:
        """Акумулює результати батчів з використанням нормалізації імен."""
        for person in (batch_result.get("people") or []):
            existing = self._find_in_list(accumulated["people"], person.get("name") or "", "name")
            if existing is not None:
                self._merge_person(accumulated["people"][existing], person)
            else:
                accumulated["people"].append(person)

        for project in (batch_result.get("projects") or []):
            existing = self._find_in_list(accumulated["projects"], project.get("name") or "", "name")
            if existing is not None:
                self._merge_simple_entity(accumulated["projects"][existing], project)
            else:
                accumulated["projects"].append(project)

        for event in (batch_result.get("events") or []):
            existing = self._find_in_list(accumulated["events"], event.get("name") or "", "name")
            if existing is not None:
                self._merge_simple_entity(accumulated["events"][existing], event)
            else:
                accumulated["events"].append(event)

        for theme in (batch_result.get("themes") or []):
            tag = theme.get("tag") or theme.get("name") or ""
            existing = self._find_in_list(accumulated["themes"], tag, "tag")
            if existing is not None:
                accumulated["themes"][existing]["message_count"] = accumulated["themes"][existing].get("message_count", 0) + theme.get("message_count", 1)
            else:
                accumulated["themes"].append(theme)

    @staticmethod
    def _find_in_list(items: list, search_name: str, key: str = "name") -> int | None:
        """Знаходить індекс за нормалізованим іменем або SequenceMatcher."""
        from difflib import SequenceMatcher
        if not search_name: return None

        name_norm = normalize_name(search_name)
        for i, item in enumerate(items):
            item_name = item.get(key) or ""
            item_norm = normalize_name(item_name)

            if item_norm == name_norm: return i
            if SequenceMatcher(None, name_norm, item_norm).ratio() >= 0.80: return i
        return None

    @staticmethod
    def _merge_person(existing: dict, new: dict) -> None:
        from merger import merge_entity_data
        merged = merge_entity_data(existing, new)
        existing.update(merged)

    @staticmethod
    def _merge_simple_entity(existing: dict, new: dict) -> None:
        from merger import merge_entity_data
        merged = merge_entity_data(existing, new)
        existing.update(merged)
