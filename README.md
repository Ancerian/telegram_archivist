# 🗄 Telegram Archivist

**Telegram Archivist** — це потужний інструмент для перетворення експортованих чатів Telegram у структуровану базу знань (Second Brain) в **Obsidian**.

Він автоматично аналізує переписку за допомогою LLM (Gemini, Claude, GPT-4 або локальні моделі через LM Studio), витягує факти про людей, проекти та події, а також транскрибує голосові повідомлення.

![GUI Screenshot](gui_screenshot.png)

## ✨ Особливості

- 📝 **Розумний аналіз**: Витягує досьє на людей, опис проектів та хронологію подій.
- 🎙 **Транскрипція**: Автоматичне перетворення голосових та відео-повідомлень у текст за допомогою `faster-whisper`.
- 🧠 **Мульти-модельність**: Підтримка Google Gemini, Anthropic Claude, OpenAI та будь-яких локальних моделей через LM Studio.
- 📂 **Obsidian Integration**: Створює готові Markdown-файли з перехресними посиланнями, тегами та метаданими.
- 🌒 **Modern GUI**: Зручний графічний інтерфейс з темною темою.
- 🚀 **Smart Batching**: Інтелектуальне розбиття довгих чатів на батчі з урахуванням лімітів контексту моделі.

## 🚀 Швидкий старт

### 1. Встановлення залежностей

```bash
# Створіть віртуальне середовище
python -m venv .venv
source .venv/bin/activate  # для macOS/Linux

# Встановіть бібліотеки
pip install -r requirements.txt
```

*Примітка: Для роботи GUI на macOS може знадобитися `brew install python-tk`.*

### 2. Налаштування

1. Скопіюйте `.env.example` у `.env`:
   ```bash
   cp .env.example .env
   ```
2. Додайте ваші API ключі у файл `.env`.

### 3. Запуск

Ви можете запустити версію з графічним інтерфейсом:
```bash
python gui.py
```

Або використовувати CLI:
```bash
python main.py --input /path/to/telegram/export --vault /path/to/obsidian/vault --provider google
```

## 🛠 Технологічний стек

- **Python 3.10+**
- **LLM SDKs**: `google-generativeai`, `anthropic`, `openai`
- **Transcription**: `faster-whisper`
- **GUI**: `tkinter` (custom themed)
- **Data**: JSON Parsing & Markdown generation


