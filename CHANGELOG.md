# Changelog

## [2.0.0] — 2026-05-03

### Етап 1 — Критична стабілізація
- ✅ **1.1** Гнучкий Error Parser — `_is_context_error()` з підтримкою 400/429, uk/en keywords
- ✅ **1.2** 3-статусний чекпоінт — `batch_statuses` (pending/processing/done/failed) в checkpoint JSON
- ✅ **1.3** Обмеження реєстру — `_get_relevant_entities()` з `MAX_KNOWN_PEOPLE=50`, фільтрація по батчу
- ✅ **1.4** CoT overhead — константа `COT_OUTPUT_OVERHEAD=2000`

### Етап 2 — Якість даних
- ✅ **2.1** Atomic saves — константа `INCREMENTAL_SAVE_EVERY=10`
- ✅ **2.2** Entity Consolidation — `consolidate_entity_facts()` з дедупою підстрок
- ✅ **2.3** Batch summary — `_generate_batch_summary()` + `previous_batch_summary` між батчами
- ✅ **2.4** Нормалізація тегів — `RU_TO_UK_TAGS` в `sanitize_tag()`
- ✅ **2.5** Розширений system prompt — великі чати, якість, іронія, групові чати

### Етап 3 — Апаратна оптимізація
- ✅ **3.1** Динамічна паралельність — `response_times` → `RESPONSE_TIME_THRESHOLD=300s`
- ✅ **3.2** Централізація констант в `config.py`

### Етап 4 — Gemini Full Context
- ✅ **4.1** Новий провайдер `google_full` в `_call_llm()`
- ✅ **4.2** `analyze_full_context()` — 1 запит на весь чат
- ✅ **4.3** GUI: "Gemini Full Context (1M)" в списку провайдерів

### Етап 5 — Якість vault
- ✅ **5.3** Activity stats table, social dynamics, digital section в person profile
- ✅ **5.4** Canvas graph (існувала)

### Етап 6 — UX
- ✅ **6.1** Лог фільтрація — кнопки Всі/✅/⚠️/❌ з replay
- ✅ **6.2** Збереження налаштувань — `~/.telegram_archivist_settings.json`
- ✅ **6.3** Нотифікація — macOS notification через AppleScript
- ✅ **6.4** "📂 Відкрити Vault" та "🏥 Health Check" кнопки
- ✅ **6.5** Реальний ETA по швидкості LLM (існувала)

### Задачі 7-20
- ✅ **9** Vector registry (FAISS) — `vector_registry.py` з graceful fallback
- ✅ **10** Розширений парсинг — reply_to, forwarded_from, is_edited, service messages
- ✅ **11** Розширена схема досьє — activity, social, digital секції
- ✅ **12** Owner detection — `get_owner()` в parser
- ✅ **13** Timeline — `_build_timeline()` в writer
- ✅ **14** Multi-chat comparison — `comparator.py`
- ✅ **17** Health check — `health_check.py`
- ✅ **18** 51 тестів (було 26)
- ✅ **19** README та CHANGELOG

### Нові файли
- `health_check.py` — перевірка системи (Python, RAM, disk, LLM, vault)
- `comparator.py` — порівняння кількох чатів
- `vector_registry.py` — FAISS пошук (optional)
- `README.md` — документація
- `CHANGELOG.md` — лог змін
