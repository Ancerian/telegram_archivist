#!/usr/bin/env python3
"""
merge_to_txt.py — Експорт чату Telegram в один текстовий файл з урахуванням транскрипцій.
"""

import json
import argparse
import os
import sys
from pathlib import Path
from datetime import datetime
from parser import TelegramParser



def main():
    parser = argparse.ArgumentParser(description="Експорт чату Telegram у формат .txt")
    parser.add_argument("--input", required=True, help="Шлях до папки з експортом Telegram (де лежить result.json)")
    parser.add_argument("--output", help="Шлях до вихідного .txt файлу")
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.exists():
        print(f"❌ Помилка: Папка {input_path} не існує.")
        sys.exit(1)

    # 1. Завантажуємо повідомлення через TelegramParser
    tg_parser = TelegramParser()
    try:
        tg_parser.load(input_path)
    except Exception as e:
        print(f"❌ Помилка завантаження result.json: {e}")
        sys.exit(1)

    chat_name = tg_parser.get_chat_name()
    messages = tg_parser.get_messages()

    # 2. Завантажуємо транскрипції, якщо вони є
    transcripts = {}
    trans_file = input_path / "transcripts.json"
    if trans_file.exists():
        try:
            with open(trans_file, "r", encoding="utf-8") as f:
                transcripts = json.load(f)
        except Exception as e:
            print(f"⚠️ Не вдалося завантажити transcripts.json: {e}")

    # 3. Визначаємо шлях до виходу
    if args.output:
        output_file = Path(args.output)
    else:
        # Безпечне ім'я файлу
        safe_name = "".join([c if c.isalnum() or c in (" ", "_", "-") else "_" for c in chat_name]).strip()
        output_file = input_path.parent / f"{safe_name}.txt"

    # 4. Формуємо файл
    transcription_count = 0
    message_count = 0

    media_labels = {
        "photo": "[фото]",
        "video_file": "[відео]",
        "sticker": "[стікер]",
        "animation": "[анімація]",
        "audio_file": "[аудіо]",
        "file": "[файл]",
        "voice_message": "voice",
        "video_message": "video_note"
    }

    try:
        with open(output_file, "w", encoding="utf-8") as f:
            for msg in messages:
                message_count += 1
                
                # Час
                dt_str = "????"
                if msg.get("date"):
                    try:
                        dt = datetime.fromisoformat(msg["date"].replace("Z", "+00:00"))
                        dt_str = dt.strftime("%Y-%m-%d %H:%M")
                    except:
                        dt_str = str(msg["date"])

                # Автор
                author = f"{msg.get('from_name', 'Unknown')} ({msg.get('from_id', 'unknown')})"
                
                # Контент (Медіа + Текст)
                content_parts = []
                media_type = msg.get("media_type")
                
                if media_type:
                    label = media_labels.get(media_type, f"[{media_type}]")
                    
                    if media_type in ("voice_message", "video_message"):
                        duration = msg.get("duration", 0)
                        transcript_text = None
                        
                        # Шукаємо транскрипцію
                        if msg.get("file_path"):
                            file_key = msg["file_path"].name
                            if file_key in transcripts:
                                transcript_text = transcripts[file_key].get("text")
                                transcription_count += 1
                        
                        if transcript_text:
                            content_parts.append(f"[{label}, {duration}s] {transcript_text}")
                        else:
                            content_parts.append(f"[{label}, {duration}s]")
                    else:
                        content_parts.append(label)

                # Текст повідомлення
                text = msg.get("text", "")
                if text:
                    content_parts.append(text)

                line_content = " ".join(content_parts)
                f.write(f"[{dt_str}] {author}: {line_content}\n")

        # 5. Статистика
        file_size = os.path.getsize(output_file)
        
        # Функція розрахунку розміру вручну, щоб не залежати від math
        def get_readable_size(size):
            for unit in ['B', 'KB', 'MB', 'GB']:
                if size < 1024.0:
                    return f"{size:.2f} {unit}"
                size /= 1024.0
            return f"{size:.2f} TB"

        print(f"\n✅ Готово!")
        print(f"   Повідомлень: {message_count}")
        print(f"   З транскрипціями: {transcription_count}")
        print(f"   Збережено: {output_file}")
        print(f"   Розмір файлу: {get_readable_size(file_size)}")

    except Exception as e:
        print(f"❌ Помилка запису файлу: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
