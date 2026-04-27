#!/usr/bin/env python3
"""
main.py — Telegram Archivist CLI.
Аналізує експорти Telegram-чатів і генерує Obsidian vault.
"""

import argparse
import os
import sys
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()


def main():
    ap = argparse.ArgumentParser(
        description="Telegram Archivist — аналіз чатів → Obsidian vault"
    )
    ap.add_argument("--input", required=True, help="Папка з експортом Telegram")
    ap.add_argument("--vault", required=True, help="Корінь Obsidian vault")
    ap.add_argument("--provider", default="google", choices=["google", "anthropic", "openai"],
                     help="LLM провайдер (default: google)")
    ap.add_argument("--api-key", default=None, help="API ключ (або з env)")
    ap.add_argument("--no-transcribe", action="store_true", help="Пропустити транскрипцію")
    ap.add_argument("--whisper-model", default="small", choices=["tiny", "small", "medium"],
                     help="Розмір моделі Whisper (default: small)")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    vault_path = Path(args.vault).resolve()

    # Визначити API ключ
    api_key = args.api_key
    if not api_key:
        env_map = {
            "google": "GOOGLE_API_KEY",
            "anthropic": "ANTHROPIC_API_KEY",
            "openai": "OPENAI_API_KEY",
        }
        env_var = env_map.get(args.provider, "")
        api_key = os.environ.get(env_var)
        if not api_key:
            print(f"❌ API ключ не знайдено. Вкажіть --api-key або встановіть {env_var}")
            sys.exit(1)

    # Імпорти модулів проєкту
    from registry import IdentityRegistry
    from parser import TelegramParser
    from transcriber import LocalTranscriber
    from analyzer import EntityAnalyzer
    from merger import EntityMerger
    from writer import ObsidianWriter

    # --- 1. Завантаження реєстру ---
    print("\n[1/5] Завантаження реєстру...")
    registry = IdentityRegistry(vault_path)
    registry.load()

    # --- 2. Парсинг експорту ---
    print("\n[2/5] Парсинг експорту...")
    parser = TelegramParser()
    parser.load(input_path)
    messages = parser.get_messages()
    chat_name = parser.get_chat_name()
    chat_language = parser.get_chat_language()
    print(f"  📋 Чат: {chat_name}")
    print(f"  📝 Повідомлень: {len(messages)}, мова: {chat_language}")

    # --- 3. Транскрипція ---
    if not args.no_transcribe:
        media_count = sum(
            1 for m in messages
            if m.get("media_type") in ("voice_message", "video_message")
            and m.get("file_path") is not None
        )
        print(f"\n[3/5] Транскрипція голосових та кружків... ({media_count} файлів)")
        if media_count > 0:
            transcriber = LocalTranscriber(model_size=args.whisper_model)
            messages = transcriber.transcribe_batch(messages)
        else:
            print("  ℹ️ Немає медіафайлів для транскрипції")
    else:
        print("\n[3/5] Транскрипція пропущена (--no-transcribe)")

    # --- 4. Аналіз через LLM ---
    print(f"\n[4/5] Аналіз через {args.provider}...")
    known_entities = registry.get_all_names()
    analyzer = EntityAnalyzer(
        provider=args.provider,
        api_key=api_key,
        chat_name=chat_name,
        chat_language=chat_language,
    )
    analyzed_entities = analyzer.analyze(messages, known_entities)

    # --- 5. Запис у vault ---
    print("\n[5/5] Запис у vault...")
    merger = EntityMerger(registry)
    merge_report = merger.merge(analyzed_entities, chat_name)

    writer = ObsidianWriter(vault_path)
    stats = writer.write_all(merge_report, chat_name)
    writer.write_chat_index(chat_name, messages, analyzed_entities, chat_language)
    registry.save()

    # --- Статистика ---
    created = stats.get("created", {})
    updated = stats.get("updated", {})
    print(f"""
✅ Готово!
   Мова чату: {chat_language}
   Створено:    {created.get('people', 0)} людей, {created.get('projects', 0)} проєктів, {created.get('events', 0)} подій, {created.get('themes', 0)} тем
   Доповнено:   {updated.get('people', 0)} людей, {updated.get('projects', 0)} проєктів, {updated.get('events', 0)} подій, {updated.get('themes', 0)} тем
   Vault: {vault_path}
""")


if __name__ == "__main__":
    main()
