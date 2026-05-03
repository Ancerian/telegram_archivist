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
    ap.add_argument("--provider", default="google", choices=["google", "anthropic", "openai", "local"],
                     help="LLM провайдер (default: google)")
    ap.add_argument("--api-key", default=None, help="API ключ (або з env)")
    ap.add_argument("--local-url", default="http://localhost:1234/v1", help="URL для локальної LLM")
    ap.add_argument("--parallel", type=int, default=4, help="Кількість паралельних запитів до LLM")
    ap.add_argument("--cot", action="store_true", help="Використовувати двоетапний аналіз (Chain of Thought)")
    ap.add_argument("--no-transcribe", action="store_true", help="Пропустити транскрипцію")
    ap.add_argument("--whisper-model", default="small", choices=["tiny", "small", "medium"],
                     help="Розмір моделі Whisper (default: small)")
    ap.add_argument("--model", default=None, help="Назва моделі LLM")
    ap.add_argument("--no-graph", action="store_true", help="Не генерувати _Graph.canvas")
    ap.add_argument("--no-dedupe", action="store_true", help="Не запускати дедуплікацію vault")
    args = ap.parse_args()

    input_path = Path(args.input).resolve()
    vault_path = Path(args.vault).resolve()

    # Визначити API ключ
    api_key = args.api_key
    if not api_key and args.provider != "local":
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
    from deduplicator import VaultDeduplicator

    # --- 1. Завантаження реєстру ---
    print("\n[1/6] Завантаження реєстру...")
    registry = IdentityRegistry(vault_path)
    registry.load()

    # --- 2. Парсинг експорту ---
    print("\n[2/6] Парсинг експорту...")
    parser = TelegramParser()
    parser.load(input_path)
    all_messages = parser.get_messages()
    messages = all_messages
    chat_name = parser.get_chat_name()
    chat_language = parser.get_chat_language()
    print(f"  📋 Чат: {chat_name}")
    print(f"  📝 Повідомлень: {len(all_messages)}, мова: {chat_language}")

    checkpoint_path = input_path / "llm_checkpoint.json"
    last_processed = EntityAnalyzer.get_last_processed_date(checkpoint_path)
    if last_processed:
        messages = parser.get_new_messages(last_processed)
        print(f"  🔄 Знайдено {len(messages)} нових повідомлень")

    # --- 3. Транскрипція ---
    if not args.no_transcribe:
        media_count = sum(
            1 for m in messages
            if m.get("media_type") in ("voice_message", "video_message")
            and m.get("file_path") is not None
        )
        print(f"\n[3/6] Транскрипція голосових та кружків... ({media_count} файлів)")
        if media_count > 0:
            transcriber = LocalTranscriber(model_size=args.whisper_model)
            messages = transcriber.transcribe_batch(messages)
        else:
            print("  ℹ️ Немає медіафайлів для транскрипції")
    else:
        print("\n[3/6] Транскрипція пропущена (--no-transcribe)")

    # --- 4. Аналіз через LLM ---
    print(f"\n[4/6] Аналіз через {args.provider}...")
    known_entities = registry.get_all_names()
    analyzer = EntityAnalyzer(
        provider=args.provider,
        api_key=api_key,
        chat_name=chat_name,
        chat_language=chat_language,
        model=args.model,
        local_url=args.local_url,
        max_concurrent=args.parallel,
        use_cot=args.cot
    )
    analyzed_entities = analyzer.analyze(messages, known_entities, checkpoint_path=checkpoint_path)

    summary_messages = analyzer.last_analyzed_messages or messages
    summary_text = analyzer.generate_chat_summary(summary_messages, analyzed_entities)

    # --- 5. Запис у vault ---
    print("\n[5/6] Запис у vault...")
    merger = EntityMerger(registry)
    merge_report = merger.merge(analyzed_entities, chat_name)

    writer = ObsidianWriter(vault_path, registry=registry)
    stats = writer.write_all(merge_report, chat_name)
    writer.write_chat_index(chat_name, all_messages, analyzed_entities, chat_language)
    if summary_text:
        writer.write_chat_summary(chat_name, summary_messages, summary_text)
        print("  📝 Summary чату збережено")
    if not args.no_graph:
        graph_path = writer.write_graph_canvas()
        if graph_path:
            print(f"  🕸️ Граф зв'язків: {graph_path}")
    registry.save()

    # --- 6. Дедуплікація ---
    if not args.no_dedupe:
        print("\n[6/6] Дедуплікація vault...")
        deduplicator = VaultDeduplicator()
        duplicate_groups = deduplicator.find_duplicates(vault_path)
        merged_count = deduplicator.merge_duplicates(duplicate_groups, registry)
        registry.save()
        if not args.no_graph:
            writer.write_graph_canvas()
        print(f"  🔍 Знайдено {len(duplicate_groups)} груп дублікатів, злито {merged_count} файлів")
    else:
        print("\n[6/6] Дедуплікація пропущена (--no-dedupe)")

    # --- Статистика ---
    created = stats.get("created", {})
    updated = stats.get("updated", {})
    skipped = stats.get("skipped", {})
    successful = {
        key: created.get(key, 0) + updated.get(key, 0)
        for key in ("people", "projects", "events", "themes")
    }
    print(f"""
✅ Готово!
   Мова чату: {chat_language}
   📊 Статистика запису:
   ✅ Успішно: {successful.get('people', 0)} людей, {successful.get('projects', 0)} проєктів, {successful.get('events', 0)} подій, {successful.get('themes', 0)} тем
   🔄 Оновлено: {updated.get('people', 0)} людей, {updated.get('projects', 0)} проєктів, {updated.get('events', 0)} подій, {updated.get('themes', 0)} тем
   ⚠️ Пропущено (без імені): {skipped.get('total', 0)} сутностей
   📎 Entity links: {stats.get('entity_links', 0)} посилань створено
   Vault: {vault_path}
""")


if __name__ == "__main__":
    main()
