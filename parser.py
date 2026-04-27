"""
parser.py — Парсинг експорту Telegram Desktop.
"""

import json
import sys
from pathlib import Path

try:
    from langdetect import detect, LangDetectException
except ImportError:
    detect = None
    LangDetectException = Exception


class TelegramParser:
    """Парсер експорту Telegram Desktop."""

    def __init__(self):
        self.raw_data = None
        self.input_path = None
        self._messages = None

    def load(self, input_path: Path) -> None:
        """Завантажує result.json."""
        self.input_path = input_path
        result_file = input_path / "result.json"

        if not result_file.exists():
            raise FileNotFoundError(f"Файл не знайдено: {result_file}")

        with open(result_file, "r", encoding="utf-8") as f:
            self.raw_data = json.load(f)

        self._messages = None  # Скидаємо кеш

    def get_chat_name(self) -> str:
        """Повертає назву чату."""
        return self.raw_data.get("name", "Unknown Chat")

    def get_messages(self) -> list:
        """Повертає список нормалізованих повідомлень."""
        if self._messages is not None:
            return self._messages

        self._messages = []
        raw_messages = self.raw_data.get("messages", [])

        for msg in raw_messages:
            # Пропускаємо сервісні повідомлення
            if msg.get("type") != "message":
                continue

            # Побудова тексту
            text = self._extract_text(msg.get("text", ""))

            # Побудова file_path
            file_path = None
            raw_file = msg.get("file")
            if raw_file:
                # Пропускаємо заглушки Telegram про невикачані файли
                if str(raw_file).startswith("(File not included"):
                    pass
                else:
                    candidate = self.input_path / raw_file
                    if candidate.exists():
                        file_path = candidate
                    else:
                        print(f"  [!] Файл не знайдено: {candidate}", file=sys.stderr)

            # Визначення мови
            detected_language = None
            if text and len(text) > 20 and detect is not None:
                try:
                    detected_language = detect(text)
                except LangDetectException:
                    pass

            normalized = {
                "id": msg.get("id"),
                "date": msg.get("date", ""),
                "from_name": msg.get("from", "Unknown"),
                "from_id": msg.get("from_id", ""),
                "text": text,
                "media_type": msg.get("media_type"),
                "file_path": file_path,
                "duration": msg.get("duration_seconds"),
                "transcript": None,
                "detected_language": detected_language,
            }
            self._messages.append(normalized)

        return self._messages

    def get_chat_language(self) -> str:
        """
        Визначає переважну мову чату через langdetect
        по перших 100 текстових повідомленнях.
        Повертає "ru" | "uk" | "en" | "mixed"
        """
        if detect is None:
            return "mixed"

        messages = self.get_messages()
        lang_counts = {}
        checked = 0

        for msg in messages:
            if checked >= 100:
                break
            text = msg.get("text", "")
            if text and len(text) > 20:
                try:
                    lang = detect(text)
                    lang_counts[lang] = lang_counts.get(lang, 0) + 1
                    checked += 1
                except LangDetectException:
                    pass

        if not lang_counts:
            return "mixed"

        # Знаходимо домінуючу мову
        total = sum(lang_counts.values())
        top_lang = max(lang_counts, key=lang_counts.get)
        top_ratio = lang_counts[top_lang] / total

        if top_ratio >= 0.7:
            if top_lang in ("ru", "uk", "en"):
                return top_lang
        return "mixed"

    @staticmethod
    def _extract_text(text_field) -> str:
        """
        text може бути рядком або масивом об'єктів.
        У такому випадку збирати всі вкладені .text поля в один рядок.
        """
        if isinstance(text_field, str):
            return text_field

        if isinstance(text_field, list):
            parts = []
            for item in text_field:
                if isinstance(item, str):
                    parts.append(item)
                elif isinstance(item, dict):
                    parts.append(item.get("text", ""))
            return "".join(parts)

        return str(text_field) if text_field else ""
