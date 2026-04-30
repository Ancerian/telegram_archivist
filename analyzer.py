"""
analyzer.py — Аналіз повідомлень через LLM (Gemini / Claude / OpenAI / Local).
"""

import json
import re
import sys
import os
from pathlib import Path
from datetime import datetime
from config import SYSTEM_PROMPT


class SmartBatcher:
    """Розумний батчер, що розбиває повідомлення по контексту (діалоги)."""
    @staticmethod
    def _estimate_tokens(msg: dict) -> int:
        text = msg.get("text") or ""
        transcript = msg.get("transcript") or ""
        # Cyrillic tokenization is often 2.5 - 4 tokens per word for local models.
        # Adding 20 tokens overhead for date, name, and formatting per message.
        tokens = len(text.split()) * 3.0 + 20
        if transcript:
            tokens += len(transcript.split()) * 3.0
        return tokens

    @staticmethod
    def split_by_context(messages: list, target_tokens: int, absolute_tokens: int) -> list[dict]:
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
            session_tokens = sum(SmartBatcher._estimate_tokens(m) for m in session)
            
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
                        m_tokens = SmartBatcher._estimate_tokens(m)
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
                 is_running_callback=None, max_tokens=128000, absolute_max_tokens=128000):
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
        Аналізує повідомлення батчами по 50 паралельно.
        Підтримує динамічну зміну кількості потоків, розумне розбиття батчів та чекпоінти.
        """
        import concurrent.futures
        import time
        from config import SYSTEM_PROMPT
        
        # Оцінюємо розмір статичного оверхеду (системний промпт + вже знайдені сутності)
        # Рахуємо приблизно 3 токени на слово для кирилиці
        system_words = len(SYSTEM_PROMPT.split())
        entities_words = len(json.dumps(known_entities, ensure_ascii=False).split())
        static_overhead_tokens = int((system_words + entities_words) * 3.0) + 500 # 500 запас
        
        # Віднімаємо цей оверхед від цільового розміру батчу
        actual_max_tokens = max(1000, self.max_tokens - static_overhead_tokens)
        actual_absolute_tokens = max(1000, self.absolute_max_tokens - static_overhead_tokens)

        batch_list = SmartBatcher.split_by_context(messages, actual_max_tokens, actual_absolute_tokens)
        total_batches = len(batch_list)
        total_tokens = sum(sum(SmartBatcher._estimate_tokens(m) for m in b["messages"]) for b in batch_list)

        def _format_time(seconds):
            seconds = int(seconds)
            if seconds < 3600:
                return f"{seconds // 60:02d}:{seconds % 60:02d}"
            return f"{seconds // 3600}:{(seconds % 3600) // 60:02d}:{seconds % 60:02d}"

        msg = f"📊 Аналіз: {total_batches} батчів | ~{int(total_tokens)} токенів всього | ETA: ~{_format_time(total_batches * 10)} хв"
        print(msg)
        if self.progress_callback:
            self.progress_callback(msg)

        accumulated = {
            "people": [],
            "projects": [],
            "events": [],
            "themes": [],
        }
        processed_batch_nums = set()

        # 1. Завантаження чекпоінту
        if checkpoint_path and checkpoint_path.exists():
            try:
                with open(checkpoint_path, "r", encoding="utf-8") as f:
                    checkpoint = json.load(f)
                    
                if checkpoint.get("batching_version") != 2:
                    raise ValueError("Старий кеш аналізу несумісний")
                    
                accumulated = checkpoint.get("accumulated", accumulated)
                processed_batch_nums = set(checkpoint.get("processed_batches", []))
                
                removed_count = 0
                for k in ["people", "projects", "events", "themes"]:
                    if k in accumulated and isinstance(accumulated[k], list):
                        key_name = "tag" if k == "themes" else "name"
                        valid_items = []
                        for item in accumulated[k]:
                            if isinstance(item, dict) and item.get(key_name):
                                valid_items.append(item)
                            else:
                                removed_count += 1
                        accumulated[k] = valid_items
                
                if removed_count > 0:
                    clean_msg = f"  🧹 Очищено {removed_count} битих сутностей з кешу"
                    print(clean_msg)
                    if self.progress_callback:
                        self.progress_callback(clean_msg)
                
                msg = f"  🔄 Відновлено прогрес: {len(processed_batch_nums)}/{total_batches} батчів"
                print(msg)
                if self.progress_callback:
                    self.progress_callback(msg)
            except Exception as e:
                msg = f"  ⚠️ Старий кеш аналізу несумісний — починаємо заново ({e})"
                print(msg)
                if self.progress_callback:
                    self.progress_callback(msg)
                try:
                    os.remove(checkpoint_path)
                except Exception:
                    pass

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
            if not checkpoint_path:
                return
            try:
                temp_path = checkpoint_path.with_suffix(".tmp")
                with open(temp_path, "w", encoding="utf-8") as f:
                    json.dump({
                        "batching_version": 2,
                        "accumulated": accumulated,
                        "processed_batches": list(processed_batch_nums)
                    }, f, ensure_ascii=False, indent=2)
                temp_path.replace(checkpoint_path)
            except Exception as e:
                print(f"  ⚠️ Помилка збереження чекпоінту: {e}")

        def _process_batch(batch_tuple, depth=0):
            b_num, batch = batch_tuple
            max_retries = 3
            
            user_message = self._build_user_message(batch, known_entities, messages)
            
            for attempt in range(max_retries):
                if self.is_running_callback and not self.is_running_callback():
                    return None
                
                attempt_str = f" (спроба {attempt + 1}/{max_retries})" if attempt > 0 else ""
                indent = "  " * (depth + 1)
                msg = f"{indent}📊 Батч {b_num}/{total_batches} ({len(batch)} повідомлень){attempt_str}"
                print(msg)
                if self.progress_callback:
                    self.progress_callback(msg)

                try:
                    response_text = self._call_llm(user_message)
                    if response_text:
                        parsed = self._validate_and_fix(response_text, b_num, user_message)
                        if parsed:
                            return parsed
                except Exception as e:
                    err_str = str(e)
                    should_split = False
                    if ("Context size" in err_str or "context_length_exceeded" in err_str or "payload" in err_str.lower()):
                        should_split = True
                        warn_msg = f"  ⚠️ Батч {b_num}: контекст переповнено. Розділяю навпіл...\n      Деталі: {err_str}"
                        
                    if should_split and len(batch) > 1:
                        mid = len(batch) // 2
                        print(warn_msg, file=sys.stderr)
                        if self.progress_callback:
                            self.progress_callback(warn_msg)
                        
                        res1 = _process_batch((b_num, batch[:mid]), depth + 1)
                        res2 = _process_batch((b_num, batch[mid:]), depth + 1)
                        
                        if res1 and res2:
                            self._accumulate(res1, res2)
                            return res1
                        return res1 or res2
                    
                    err_msg = f"  ❌ Помилка LLM у батчі {b_num}: {e}"
                    print(err_msg, file=sys.stderr)
                    if self.progress_callback:
                        self.progress_callback(err_msg)
                
                if attempt < max_retries - 1:
                    wait_time = (attempt + 1) * 5
                    for _ in range(wait_time * 10):
                        if self.is_running_callback and not self.is_running_callback():
                            return None
                        time.sleep(0.1)

            return None

        processed_count = len(processed_batch_nums)

        def run_queue(queue_batches, force_max=None):
            nonlocal processed_count
            if not queue_batches:
                return
            
            queue_batches = [(num, b) for num, b in queue_batches if num not in processed_batch_nums]
            if not queue_batches:
                return

            def get_current_max():
                if force_max is not None:
                    return force_max
                if callable(self.max_concurrent):
                    try:
                        return max(1, int(self.max_concurrent()))
                    except Exception:
                        return 1
                return max(1, int(self.max_concurrent))

            with concurrent.futures.ThreadPoolExecutor(max_workers=32) as executor:
                future_to_num = {}
                batch_iter = iter(queue_batches)
                batch_iter_exhausted = False
                
                while True:
                    if self.is_running_callback and not self.is_running_callback():
                        if sys.version_info >= (3, 9):
                            executor.shutdown(wait=False, cancel_futures=True)
                        else:
                            executor.shutdown(wait=False)
                        break

                    # 1. Перевірка завершених задач
                    for f in list(future_to_num.keys()):
                        if f.done():
                            b_num = future_to_num.pop(f)
                            try:
                                parsed = f.result()
                                if parsed:
                                    self._accumulate(accumulated, parsed)
                                    msg = f"  ✅ Батч {b_num} оброблено успішно"
                                    print(msg)
                                    if self.progress_callback:
                                        self.progress_callback(msg)
                                else:
                                    msg = f"  ⚠️ Батч {b_num} не повернув корисних даних"
                                    print(msg)
                                    if self.progress_callback:
                                        self.progress_callback(msg)
                                
                                processed_batch_nums.add(b_num)
                                processed_count += 1
                                _save_checkpoint()
                            except Exception as e:
                                err_msg = f"  ❌ Критична помилка у батчі {b_num}: {e}"
                                print(err_msg, file=sys.stderr)
                                if self.progress_callback:
                                    self.progress_callback(err_msg)
                                processed_batch_nums.add(b_num)
                                processed_count += 1

                    # 2. Подача нових задач згідно з лімітом
                    if not batch_iter_exhausted:
                        current_max = get_current_max()
                        while len(future_to_num) < current_max:
                            try:
                                next_batch_tuple = next(batch_iter)
                                b_num, _ = next_batch_tuple
                                fut = executor.submit(_process_batch, next_batch_tuple)
                                future_to_num[fut] = b_num
                            except StopIteration:
                                batch_iter_exhausted = True
                                break
                    
                    # Якщо більше немає активних задач і ітератор вичерпано — виходимо
                    if batch_iter_exhausted and not future_to_num:
                        break
                    
                    time.sleep(0.1)

        # Фаза 1: Нормальні батчі
        if batches:
            if self.progress_callback:
                self.progress_callback("  ▶ Фаза 1: Нормальні батчі (динамічна паралельність)")
            run_queue(batches)
        
        # Фаза 2: Величезні батчі
        if huge_batches and (not self.is_running_callback or self.is_running_callback()):
            if self.provider == "local":
                if self.progress_callback:
                    self.progress_callback("  ▶ Фаза 2: Величезні батчі (примусово 1 потік для LM Studio)")
                run_queue(huge_batches, force_max=1)
            else:
                if self.progress_callback:
                    self.progress_callback("  ▶ Фаза 2: Величезні батчі (динамічна паралельність)")
                run_queue(huge_batches)

        # Видаляємо чекпоінт після успішного завершення
        if processed_count >= total_batches and checkpoint_path and checkpoint_path.exists():
            try:
                os.remove(checkpoint_path)
                print("  ✨ Аналіз завершено, чекпоінт видалено")
            except Exception:
                pass

        return accumulated

    def _build_user_message(self, batch: list, known_entities: dict, all_messages: list) -> str:
        """Будує user message для батчу."""
        dates = [m["date"] for m in all_messages if m.get("date")]
        first_date = dates[0] if dates else "?"
        last_date = dates[-1] if dates else "?"

        participants = sorted(set(
            m["from_name"] for m in all_messages
            if m.get("from_name") and m["from_name"] != "Unknown"
        ))

        lines = []
        for msg in batch:
            date_str = msg.get("date", "?")
            if "T" in date_str:
                date_str = date_str.replace("T", " ")

            from_name = msg.get("from_name", "?")
            text = msg.get("text", "")
            media_type = msg.get("media_type")
            transcript = msg.get("transcript")
            duration = msg.get("duration")
            lang = msg.get("detected_language")

            is_overlap = msg.get("is_overlap")

            if media_type == "voice_message":
                lang_str = f", {lang}" if lang else ""
                dur_str = f", {duration}s" if duration else ""
                content = f"[voice{dur_str}{lang_str}]"
                if transcript:
                    content += f" {transcript}"
                line = f"[{date_str}] {from_name}: {content}"
            elif media_type == "video_message":
                lang_str = f", {lang}" if lang else ""
                dur_str = f", {duration}s" if duration else ""
                content = f"[video_note{dur_str}{lang_str}]"
                if transcript:
                    content += f" {transcript}"
                line = f"[{date_str}] {from_name}: {content}"
            elif media_type == "sticker":
                line = f"[{date_str}] {from_name}: [sticker]"
            elif media_type and "photo" in str(media_type):
                content = f"[photo]"
                if text:
                    content += f" {text}"
                line = f"[{date_str}] {from_name}: {content}"
            elif media_type:
                content = f"[{media_type}]"
                if text:
                    content += f" {text}"
                line = f"[{date_str}] {from_name}: {content}"
            elif text:
                line = f"[{date_str}] {from_name}: {text}"
            else:
                continue

            if is_overlap:
                line = f"[КОНТЕКСТ З ПОПЕРЕДНЬОГО БАТЧУ — не аналізуй] {line}"
            lines.append(line)

        messages_text = "\n".join(lines)

        return f"""Відомі сутності (не дублюй):
{json.dumps(known_entities, ensure_ascii=False)}

Чат: {self.chat_name}
Мова чату: {self.chat_language}
Період: {first_date} — {last_date}
Учасники чату: {', '.join(participants)}

Повідомлення:
{messages_text}"""

    def _call_llm(self, user_message: str) -> str:
        """Викликає LLM провайдер."""
        if self.provider == "google":
            return self._call_google(user_message)
        elif self.provider == "anthropic":
            return self._call_anthropic(user_message)
        elif self.provider == "openai":
            return self._call_openai(user_message)
        elif self.provider == "local":
            return self._call_local(user_message)
        else:
            raise ValueError(f"Невідомий провайдер: {self.provider}")

    def _call_google(self, user_message: str) -> str:
        """Виклик Google Gemini."""
        import google.generativeai as genai
        genai.configure(api_key=self.api_key)
        model_name = self.model or "gemini-2.0-flash"
        model = genai.GenerativeModel(model_name)
        response = model.generate_content(SYSTEM_PROMPT + "\n\n" + user_message)
        return response.text

    def _call_anthropic(self, user_message: str) -> str:
        """Виклик Anthropic Claude."""
        import anthropic
        client = anthropic.Anthropic(api_key=self.api_key)
        model_name = self.model or "claude-sonnet-4-20250514"
        response = client.messages.create(
            model=model_name,
            max_tokens=4096,
            system=SYSTEM_PROMPT,
            messages=[{"role": "user", "content": user_message}],
        )
        return response.content[0].text

    def _call_openai(self, user_message: str) -> str:
        """Виклик OpenAI."""
        import openai
        client = openai.OpenAI(api_key=self.api_key)
        model_name = self.model or "gpt-4o"
        response = client.chat.completions.create(
            model=model_name,
            max_tokens=4096,
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content

    def _call_local(self, user_message: str) -> str:
        """Виклик локальної LLM через LM Studio (OpenAI-compatible API)."""
        import openai
        client = openai.OpenAI(
            base_url=self.local_url,
            api_key="lm-studio",
        )
        model_name = self.model or "local-model"
        response = client.chat.completions.create(
            model=model_name,
            temperature=0.3,
            timeout=3600, # Збільшено тайм-аут до 60 хвилин для дуже великих контекстів і повільних моделей
            messages=[
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_message},
            ],
        )
        return response.choices[0].message.content

    def _validate_and_fix(self, text: str, batch_num: int, original_prompt: str) -> dict:
        """Валідує та виправляє JSON з відповіді LLM."""
        
        def _ensure_keys(parsed_dict: dict) -> dict:
            filtered_count = 0
            for k in ["people", "projects", "events", "themes"]:
                if k not in parsed_dict or not isinstance(parsed_dict[k], list):
                    parsed_dict[k] = []
                else:
                    valid_items = []
                    key_name = "tag" if k == "themes" else "name"
                    for item in parsed_dict[k]:
                        if isinstance(item, dict) and item.get(key_name):
                            valid_items.append(item)
                        else:
                            filtered_count += 1
                    parsed_dict[k] = valid_items
            if filtered_count > 0 and self.progress_callback:
                self.progress_callback(f"  ⚠️ Відфільтровано {filtered_count} сутність(ей) без імені в батчі {batch_num}")
            return parsed_dict

        # Крок 1: Прямий парсинг
        text_clean = re.sub(r',\s*([}\]])', r'\1', text)
        try:
            parsed = json.loads(text_clean)
            if isinstance(parsed, dict):
                return _ensure_keys(parsed)
        except json.JSONDecodeError:
            pass

        # Крок 2: Вирізати JSON і виправити типові помилки
        def _try_regex_parse(t: str):
            match = re.search(r'\{.*\}', t, re.DOTALL)
            if match:
                json_str = match.group()
                # Виправити одинарні лапки, якщо вони не в словах з апострофами
                json_str = re.sub(r"(?<![a-zA-Zа-яА-ЯіІїЇєЄґҐ])'|'(?![a-zA-Zа-яА-ЯіІїЇєЄґҐ])", '"', json_str)
                # None/True/False
                json_str = re.sub(r'\bNone\b', 'null', json_str)
                json_str = re.sub(r'\bTrue\b', 'true', json_str)
                json_str = re.sub(r'\bFalse\b', 'false', json_str)
                # Trailing commas
                json_str = re.sub(r',\s*([}\]])', r'\1', json_str)
                
                # Знайти останню закриваючу дужку
                last_brace = json_str.rfind('}')
                if last_brace != -1:
                    json_str = json_str[:last_brace+1]
                    
                try:
                    p = json.loads(json_str)
                    if isinstance(p, dict):
                        return _ensure_keys(p)
                except json.JSONDecodeError:
                    pass
            return None

        parsed = _try_regex_parse(text_clean)
        if parsed:
            if self.progress_callback:
                self.progress_callback(f"  🔧 Батч {batch_num}: JSON успішно виправлено регулярками")
            return parsed
            
        # Крок 3: Recovery prompt
        if self.progress_callback:
            self.progress_callback(f"  ⚠️ Батч {batch_num}: JSON зламаний, надсилаю recovery prompt...")
            
        preview = text[:500]
        recovery_prompt = f"""Твоя попередня відповідь містила невалідний JSON.
Ось що ти повернув: {preview}...

Поверни ТІЛЬКИ валідний JSON за схемою. Без пояснень."""

        try:
            recovery_response = self._call_llm(recovery_prompt)
            if recovery_response:
                # Проста перевірка
                rec_clean = re.sub(r',\s*([}\]])', r'\1', recovery_response)
                match = re.search(r'\{.*\}', rec_clean, re.DOTALL)
                if match:
                    parsed = json.loads(match.group())
                    if isinstance(parsed, dict):
                        if self.progress_callback:
                            self.progress_callback(f"  ✅ Батч {batch_num}: JSON успішно відновлено через LLM")
                        return _ensure_keys(parsed)
        except Exception as e:
            if self.progress_callback:
                self.progress_callback(f"  ❌ Помилка recovery prompt: {e}")
                
        preview_err = text[:150].replace("\n", " ") + ("..." if len(text) > 150 else "")
        raise ValueError(f"LLM повернув текст, який не є валідним JSON-словником. Відповідь: {preview_err}")

    def _accumulate(self, accumulated: dict, batch_result: dict) -> None:
        """Акумулює результати батчів."""
        # Гарантуємо наявність ключів, щоб уникнути KeyError при злитті розбитих батчів
        for key in ["people", "projects", "events", "themes"]:
            if key not in accumulated:
                accumulated[key] = []

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
            existing = self._find_in_list(accumulated["themes"], theme.get("tag") or "", "tag")
            if existing is not None:
                accumulated["themes"][existing]["message_count"] = (
                    accumulated["themes"][existing].get("message_count", 0) +
                    theme.get("message_count", 0)
                )
                if not accumulated["themes"][existing].get("description") and theme.get("description"):
                    accumulated["themes"][existing]["description"] = theme["description"]
            else:
                accumulated["themes"].append(theme)

    @staticmethod
    def _find_in_list(items: list, name: str, key: str = "name") -> int | None:
        """Знаходить індекс елемента за іменем (case-insensitive)."""
        if not name: return None
        name_lower = name.lower().strip()
        for i, item in enumerate(items):
            if (item.get(key) or "").lower().strip() == name_lower:
                return i
        return None

    @staticmethod
    def _merge_person(existing: dict, new: dict) -> None:
        """Мержить дані про людину з нового батчу."""
        from config import higher_confidence

        for section_key in (
            "identity", "contacts", "professional", "family",
            "lifestyle", "finances", "health", "psychology",
            "communication_intel", "relationships"
        ):
            if section_key in new and new[section_key]:
                if section_key not in existing or not existing[section_key]:
                    existing[section_key] = new[section_key]
                else:
                    EntityAnalyzer._deep_merge(existing[section_key], new[section_key])

        for list_key in (
            "key_life_events", "notable_quotes", "facts",
            "mentioned_projects", "mentioned_events", "mentioned_themes"
        ):
            existing_list = existing.get(list_key, []) or []
            new_list = new.get(list_key, []) or []
            merged = list(existing_list)
            for item in new_list:
                if item not in merged:
                    merged.append(item)
            existing[list_key] = merged

        if new.get("confidence"):
            existing["confidence"] = higher_confidence(
                existing.get("confidence", "low"),
                new.get("confidence", "low"),
            )

        if not existing.get("telegram_id") and new.get("telegram_id"):
            existing["telegram_id"] = new["telegram_id"]

        if existing.get("confidence") == "high":
            existing["uncertainty_note"] = None

    @staticmethod
    def _deep_merge(existing: dict, new: dict) -> None:
        """Глибокий мерж двох словників."""
        for key, new_val in new.items():
            if new_val is None:
                continue

            existing_val = existing.get(key)

            if isinstance(new_val, list) and isinstance(existing_val, list):
                merged = list(existing_val)
                for item in new_val:
                    if item not in merged:
                        merged.append(item)
                existing[key] = merged
            elif isinstance(new_val, dict) and isinstance(existing_val, dict):
                EntityAnalyzer._deep_merge(existing_val, new_val)
            elif existing_val is None or existing_val == "" or existing_val == "невідомо":
                existing[key] = new_val

    @staticmethod
    def _merge_simple_entity(existing: dict, new: dict) -> None:
        """Мержить простих сутностей (проекти, події)."""
        from config import higher_confidence

        for key, new_val in new.items():
            if new_val is None:
                continue

            existing_val = existing.get(key)

            if isinstance(new_val, list) and isinstance(existing_val, list):
                merged = list(existing_val)
                for item in new_val:
                    if item not in merged:
                        merged.append(item)
                existing[key] = merged
            elif existing_val is None or existing_val == "" or existing_val == "невідомо":
                existing[key] = new_val

        if new.get("confidence"):
            existing["confidence"] = higher_confidence(
                existing.get("confidence", "low"),
                new.get("confidence", "low"),
            )

        if existing.get("confidence") == "high":
            existing["uncertainty_note"] = None
