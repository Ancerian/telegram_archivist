"""
transcriber.py — Локальна транскрипція голосових і кружків через faster-whisper.
"""

import sys
from pathlib import Path


class LocalTranscriber:
    """Транскрипція аудіо через faster-whisper."""

    def __init__(self, model_size: str = "small"):
        self.model_size = model_size
        self.model = None

    def _load_model(self):
        """Ліниве завантаження моделі."""
        if self.model is not None:
            return

        try:
            from faster_whisper import WhisperModel
            print(f"  🔧 Завантаження моделі Whisper ({self.model_size})...")
            self.model = WhisperModel(
                self.model_size,
                device="cpu",
                compute_type="int8",
            )
            print(f"  ✅ Модель завантажено")
        except Exception as e:
            print(f"  ❌ Помилка завантаження моделі Whisper: {e}", file=sys.stderr)
            raise

    def unload(self):
        """Вивантажує модель з пам'яті для звільнення RAM перед LLM."""
        if self.model is not None:
            del self.model
            self.model = None
            import gc
            gc.collect()
            print("  🧹 Whisper модель вивантажено з пам'яті")

    def transcribe(self, file_path: Path) -> dict:
        """
        Транскрибує один файл.
        Повертає {"text": str, "language": str} або {"text": "", "language": null} при помилці.
        """
        try:
            self._load_model()
            segments, info = self.model.transcribe(
                str(file_path),
                language=None,  # Автовизначення мови
                beam_size=5,
            )
            text_parts = []
            for segment in segments:
                text_parts.append(segment.text.strip())

            return {
                "text": " ".join(text_parts),
                "language": info.language if info else None,
            }
        except Exception as e:
            print(f"  ⚠️ Помилка транскрипції {file_path.name}: {e}", file=sys.stderr)
            return {"text": "", "language": None}

    def transcribe_batch(self, messages: list, input_path: Path = None, progress_callback=None) -> list:
        """
        Обробляє повідомлення з media_type voice_message або video_message.
        Пропускає мініатюри кружків (_thumb.jpg).
        Заповнює поля transcript і detected_language.
        Кешує результати у transcripts.json.

        progress_callback(done, total, filename, lang, from_cache) — опціональний колбек.
        """
        import json
        cache_file = None
        cache = {}

        if input_path:
            cache_file = input_path / "transcripts.json"
            if cache_file.exists():
                try:
                    with open(cache_file, "r", encoding="utf-8") as f:
                        cache = json.load(f)
                except Exception as e:
                    print(f"  ⚠️ Не вдалося завантажити кеш транскрипцій: {e}")

        # Фільтруємо повідомлення для транскрипції
        to_transcribe = []
        for msg in messages:
            media_type = msg.get("media_type")
            file_path = msg.get("file_path")

            if media_type not in ("voice_message", "video_message"):
                continue
            if file_path is None:
                continue
            if not file_path.exists():
                continue
            if file_path.name.endswith("_thumb.jpg"):
                continue

            to_transcribe.append(msg)

        if not to_transcribe:
            print("  ℹ️ Немає файлів для транскрипції")
            return messages

        total = len(to_transcribe)
        print(f"  🎙️ Знайдено {total} файлів для транскрипції")

        dirty = False
        for i, msg in enumerate(to_transcribe, 1):
            file_path = msg["file_path"]
            file_key = file_path.name
            
            from_cache = False
            lang = None

            if file_key in cache:
                print(f"  [Кеш] {i}/{total}: {file_key}")
                msg["transcript"] = cache[file_key].get("text", "")
                lang = cache[file_key].get("language")
                if lang:
                    msg["detected_language"] = lang
                from_cache = True
            else:
                print(f"  Транскрибую {i}/{total}: {file_key}", end="")
                result = self.transcribe(file_path)
                msg["transcript"] = result["text"]

                if result["language"]:
                    msg["detected_language"] = result["language"]
                    lang = result["language"]
                    print(f" (мова: {lang})")
                else:
                    print()
                
                cache[file_key] = {"text": result["text"], "language": result["language"]}
                dirty = True

            if progress_callback:
                progress_callback(i, total, file_path.name, lang, from_cache)
                
            # Зберігаємо кеш кожні 5 файлів або в кінці
            if dirty and cache_file and (i % 5 == 0 or i == total):
                try:
                    with open(cache_file, "w", encoding="utf-8") as f:
                        json.dump(cache, f, ensure_ascii=False, indent=2)
                    dirty = False
                except Exception as e:
                    print(f"  ⚠️ Помилка збереження кешу: {e}")

        return messages
