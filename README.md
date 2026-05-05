# Telegram Archivist

🗄 **Автоматичний аналіз Telegram чатів з генерацією Obsidian vault.**

## 🚀 Можливості

- **Аналіз через LLM** — підтримка Google Gemini, Anthropic Claude, OpenAI, LM Studio (локальна)
- **Розширений парсинг** — підтримка reply, forward, edited, сервісних повідомлень
- **Розширена схема досьє** — активність, соціальна динаміка, digital профіль, timeline
- **Транскрипція медіа** — голосові і відеоповідомлення через faster-whisper
- **Obsidian vault** — генерація markdown-файлів з Entity linking
- **Граф зв'язків** — автоматична генерація Canvas графу
- **Дедуплікація** — злиття дублікатів сутностей
- **Multi-chat** — підтримка порівняння кількох чатів
- **Інкрементальний режим** — аналіз тільки нових повідомлень
- **Health check** — перевірка системи перед запуском
- **FAISS пошук** — семантичний пошук по реєстру (optional)

## 📋 Встановлення

```bash
pip install -r requirements.txt
```

### Опціональні залежності

```bash
pip install jinja2        # Шаблони
pip install psutil        # Health check RAM
pip install faiss-cpu sentence-transformers  # Векторний пошук
```

## 🖥 Використання

### GUI
```bash
python gui.py
```

### CLI
```bash
python main.py --input ./ChatExport --vault ./MyVault --provider google --api-key $GOOGLE_API_KEY
```

## 📁 Структура проєкту

| Файл | Призначення |
|---|---|
| `gui.py` | Графічний інтерфейс (tkinter) |
| `analyzer.py` | Ядро LLM аналізу, SmartBatcher |
| `parser.py` | Парсер Telegram експортів |
| `writer.py` | Генерація Obsidian markdown |
| `registry.py` | Реєстр сутностей |
| `merger.py` | Злиття даних |
| `deduplicator.py` | Дедуплікація vault |
| `transcriber.py` | Транскрипція через Whisper |
| `config.py` | Конфігурація, system prompt |
| `health_check.py` | Перевірка системи |
| `comparator.py` | Multi-chat порівняння |
| `vector_registry.py` | FAISS пошук (optional) |
| `merge_to_txt.py` | Експорт чату в .txt |

## 🧪 Тестування

```bash
python -m pytest tests/ -v
```

## 📊 Архітектура

```
Telegram Export → Parser → SmartBatcher → LLM Analyzer → Merger → Registry → Writer → Obsidian Vault
                                                                                    → Canvas Graph
                                                                                    → Chat Summary
```

## ⚙️ Налаштування

Налаштування зберігаються автоматично в `~/.telegram_archivist_settings.json`.

### Змінні середовища

- `GOOGLE_API_KEY` — ключ Google Gemini
- `ANTHROPIC_API_KEY` — ключ Anthropic
- `OPENAI_API_KEY` — ключ OpenAI

## 📝 Ліцензія

MIT
