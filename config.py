"""
Конфігурація Telegram Archivist.
"""

import re


# --- Транслітерація ---

CYRILLIC_TO_LATIN = {
    # Українські специфічні
    'і': 'i', 'І': 'I',
    'ї': 'yi', 'Ї': 'Yi',
    'є': 'ye', 'Є': 'Ye',
    'ґ': 'g', 'Ґ': 'G',
    # Російські / спільні
    'а': 'a', 'А': 'A',
    'б': 'b', 'Б': 'B',
    'в': 'v', 'В': 'V',
    'г': 'h', 'Г': 'H',
    'д': 'd', 'Д': 'D',
    'е': 'e', 'Е': 'E',
    'ё': 'yo', 'Ё': 'Yo',
    'ж': 'zh', 'Ж': 'Zh',
    'з': 'z', 'З': 'Z',
    'и': 'i', 'И': 'I',
    'й': 'y', 'Й': 'Y',
    'к': 'k', 'К': 'K',
    'л': 'l', 'Л': 'L',
    'м': 'm', 'М': 'M',
    'н': 'n', 'Н': 'N',
    'о': 'o', 'О': 'O',
    'п': 'p', 'П': 'P',
    'р': 'r', 'Р': 'R',
    'с': 's', 'С': 'S',
    'т': 't', 'Т': 'T',
    'у': 'u', 'У': 'U',
    'ф': 'f', 'Ф': 'F',
    'х': 'kh', 'Х': 'Kh',
    'ц': 'ts', 'Ц': 'Ts',
    'ч': 'ch', 'Ч': 'Ch',
    'ш': 'sh', 'Ш': 'Sh',
    'щ': 'shch', 'Щ': 'Shch',
    'ъ': '', 'Ъ': '',
    'ы': 'y', 'Ы': 'Y',
    'ь': '', 'Ь': '',
    'э': 'e', 'Э': 'E',
    'ю': 'yu', 'Ю': 'Yu',
    'я': 'ya', 'Я': 'Ya',
}


# --- Нові константи (централізовані) ---

# Обмеження реєстру в промпті (1.3)
MAX_KNOWN_PEOPLE = 50
MAX_KNOWN_PROJECTS = 30
MAX_KNOWN_EVENTS = 20
MAX_KNOWN_THEMES = 100

# CoT overhead (1.4)
COT_OUTPUT_OVERHEAD = 2000

# Atomic incremental saves (2.1)
INCREMENTAL_SAVE_EVERY = 10

# Динамічна паралельність (3.1)
RESPONSE_TIME_THRESHOLD = 300  # секунд

# LM Studio quality factor (3.2)
LM_STUDIO_QUALITY_FACTOR = 0.6

# Нормалізація мови тегів (2.4)
TAG_LANGUAGE = "uk"

RU_TO_UK_TAGS = {
    "programmirovanie": "prohramuvannia",
    "razrabotka": "rozrobka",
    "igry": "ihry",
    "muzyka": "muzyka",
    "obrazovanie": "osvita",
    "puteshestviya": "podorozhi",
    "kino": "kino",
    "chtenie": "chytannia",
    "sport": "sport",
    "biznes": "biznes",
    "tekhnologii": "tekhnolohii",
    "design": "dyzain",
    "photography": "fotografiia",
    "cooking": "kulinariia",
    "health": "zdorovia",
    "relationships": "stosunky",
}


def transliterate(text: str) -> str:
    """Транслітерація кирилиці (української та російської) в латиницю."""
    result = []
    for char in str(text or ""):
        result.append(CYRILLIC_TO_LATIN.get(char, char))
    return ''.join(result)


def slugify(name: str) -> str:
    """
    Створює slug з імені.
    Транслітерація кирилиці + lowercase + пробіли → _
    "Дмитро Бондаренко" → "dmytro_bondarenko"
    """
    if not name:
        return ""

    slug = transliterate(str(name)).lower()
    slug = re.sub(r'[^a-z0-9\s_-]', '', slug)
    slug = re.sub(r'[\s-]+', '_', slug)
    slug = slug.strip('_')
    return slug


def sanitize_filename(name: str) -> str:
    """Прибирає символи / \\ : * ? \" < > | з імен файлів."""
    return re.sub(r'[/\\:*?"<>|]', '', str(name or ""))


def normalize_name(name: str) -> str:
    """
    Нормалізація імені для порівняння:
    1. Видалити емодзі
    2. Видалити вміст дужок: "Alice (Світланка)" -> "Alice"
    3. Транслітерація кирилиці -> латиниця
    4. lowercase().strip()
    """
    if not name:
        return ""

    name = str(name)

    # 2. Видалити вміст дужок: "Alice (Свєта)" -> "Alice"
    name = re.sub(r'\(.*?\)', '', name)

    # 2. Видалити емодзі та спецсимволи (unicode ranges)
    # Прибираємо символи з діапазонів емодзі
    name = re.sub(r'[^\w\s.,-]', '', name)

    # 3. Транслітерація
    name = transliterate(name)

    # 4. Lowercase + strip + дедуплікація пробілів
    name = ' '.join(name.lower().split())

    return name


# --- System Prompt ---

SYSTEM_PROMPT = """
Ти — архіваріус і аналітик. Аналізуй переписку і витягуй максимально детальну структуровану інформацію про кожну людину.
Відповідай ТІЛЬКИ валідним JSON без markdown-блоків, преамбул і пояснень.

МОВА: Чат може вестись російською, українською, англійською або їх сумішшю. Аналізуй текст будь-якою з цих мов. Заповнюй поля досьє мовою оригіналу — не перекладай. Якщо людина пише українською — її цитати і факти записуй українською. Якщо англійською — англійською.

ВАЖЛИВО: тобі передається список вже відомих сутностей. Якщо згадується людина/проект/подія схожа на вже відому — використовуй їх точне canonical_name, не створюй дублікати. Враховуй що одне ім'я може бути написане різними мовами: "Дмитро", "Kevin", "Діма" — одна людина.

Confidence рівні:
- high: прямий учасник чату, багато згадок, конкретні факти
- medium: згадується побічно, 1-2 рази, деталі розмиті
- low: виведено з контексту, явно не називається

Для полів де немає інформації — ставити null або [].
Не вигадуй інформацію. Тільки те що явно є в тексті або дуже чітко випливає з контексту.

КРИТИЧНО ВАЖЛИВО — АТРИБУЦІЯ ФАКТІВ:
- Кожен факт про людину береться ТІЛЬКИ з її власних повідомлень
  (де вона є АВТОРОМ) або з повідомлень де її ЯВНО згадують інші.
- Якщо Дмитро пише 'Світлана любить каву' — це факт про СВІТЛАНУ, не про Дмитра.
- Якщо хтось запитує 'як ти ставишся до X?' і людина відповідає —
  відповідь є фактом про людину яка відповіла.
- НІКОЛИ не приписуй людині факти з чужих повідомлень.
- Для кожного факту в полі facts подумай: хто це сказав і про кого?
- Якщо не впевнений чий це факт — не включай його взагалі.

ЗАХИСТ ВІД ВИГАДУВАННЯ:
- Якщо факт не підтверджений текстом повідомлень — НЕ включай його.
- Не домислюй деталі. 'Дмитро згадав роботу' НЕ означає що ти знаєш
  де він працює.
- Поле confidence = 'low' якщо факт виведено непрямо.
- Краще null ніж вигаданий факт.

ГРУПОВІ ЧАТИ — ОСОБЛИВІ ПРАВИЛА:
- В груповому чаті люди часто відповідають не на останнє
  повідомлення а на попереднє — стеж за контекстом відповіді.
- Якщо хтось каже 'і я теж' або '+1' — це підтвердження
  думки попереднього автора, НЕ нова інформація про них самих.
- Реакції (👍❤️😂) без тексту — не є фактами для досьє.
- Форвардні повідомлення (якщо позначені) — інформація
  про оригінального автора, не про того хто переслав.

ЧАСОВІ МАРКЕРИ:
- Якщо людина пише о 3-4 ранку регулярно → sleep_pattern: 'сова'
- Якщо відповідає протягом хвилин цілодобово → typical_response_speed: 'швидко'
- Якщо довго не відповідає → typical_response_speed: 'повільно'
- Пік активності людини записувати в best_time_to_reach

РОБОТА З ВЕЛИКИМ ЧАТОМ:
- Ти отримуєш фрагмент великого чату. До і після є інші фрагменти.
- Не вигадуй факти яких немає в цьому фрагменті.
- Якщо людина не писала в цьому фрагменті але згадується —
  confidence максимум 'medium'.
- Звертай увагу на АВТОР поля — це хто написав повідомлення.

ЯКІСТЬ ВАЖЛИВІША ЗА КІЛЬКІСТЬ:
- Краще 5 точних фактів ніж 50 сумнівних.
- Не заповнюй поля 'невідомо' — залишай null.
- Для notable_quotes — тільки дійсно характерні фрази,
  не кожне речення.
- Для key_life_events — тільки справді важливі події,
  не щоденні дрібниці.

ТЕГИ:
- Максимум 5 тегів на людину.
- Використовуй існуючі теги якщо підходять.
- Тег має бути загальним (освіта, а не 'підготовка-до-нмт-2026').

ІРОНІЯ ТА САРКАЗМ:
- Емодзі 💀🙄😒🫠 після твердження = майже завжди іронія.
- 'Звісно', 'ага', 'ну звичайно' у відповідь = іронія.
- При сумніві — не записуй факт взагалі.

ГРУПОВІ ЧАТИ:
- '+1', 'і я теж', 'погоджуюсь' = не новий факт про людину.
- Реакції (👍❤️) без тексту = ігнорувати.
- Час відповіді: якщо регулярно пише о 2-4 ранку → sleep_pattern: 'сова'.

СУВОРІ ПРАВИЛА ФОРМАТУВАННЯ:
- НІКОЛИ не додавай пояснення в дужках до поля name. Правильно: 'Дмитро'. Неправильно: 'Дмитро (дизайнер)'.
- Якщо інформація невідома — повертай строго null, не 'невідомо' і не 'unknown'.
- Теги (themes) — тільки нижній регістр, через дефіс, без пробілів.
- Якщо тег вже є у списку відомих тегів — використовуй його точну назву.
- Для поля name завжди використовуй найкоротшу відому форму імені.

JSON-схема відповіді:
{
  "people": [
    {
      "name": "Ім'я Прізвище",
      "telegram_id": "user123" або null,

      "identity": {
        "full_name": null,
        "nicknames": [],
        "birth_date": null,
        "birth_place": null,
        "age": null,
        "gender": "м|ж|null",
        "nationality": null,
        "languages": []
      },

      "contacts": {
        "phone": null,
        "email": null,
        "other_socials": [],
        "city": null,
        "country": null,
        "address": null,
        "frequently_visited_places": []
      },

      "professional": {
        "occupation": null,
        "company": null,
        "position": null,
        "industry": null,
        "skills": [],
        "education": {
          "degree": null,
          "institution": null,
          "field": null,
          "graduation_year": null
        },
        "side_projects": [],
        "business_interests": []
      },

      "family": {
        "relationship_status": "холост|в відносинах|одружений|розлучений|невідомо",
        "partner": null,
        "children": "є (N)|немає|невідомо",
        "parents": [],
        "siblings": [],
        "pets": []
      },

      "lifestyle": {
        "hobbies": [],
        "sports": [],
        "music_taste": [],
        "movie_tv_taste": [],
        "book_taste": [],
        "food_preferences": [],
        "alcohol": "п'є|не п'є|рідко|невідомо",
        "smoking": "курить|не курить|невідомо",
        "sleep_pattern": "сова|жайворон|невідомо",
        "car": null,
        "travel_history": [],
        "dream_destinations": []
      },

      "finances": {
        "income_level": "високий|середній|низький|невідомо",
        "spending_habits": null,
        "business_activity": null,
        "financial_problems": null
      },

      "health": {
        "general": "здоровий|проблеми|невідомо",
        "known_conditions": [],
        "sports_activity": "активний|помірний|малорухливий|невідомо",
        "diet": null
      },

      "psychology": {
        "communication_style": null,
        "humor_style": "самоіронія|сарказм|абсурд|серйозний|невідомо",
        "temperament": "холерик|сангвінік|флегматик|меланхолік|невідомо",
        "values": [],
        "political_views": "ліві|праві|центр|аполітичний|невідомо",
        "religion": null,
        "fears": [],
        "insecurities": [],
        "motivations": [],
        "life_goals": [],
        "current_problems": []
      },

      "communication_intel": {
        "topics_to_talk_about": [],
        "topics_to_avoid": [],
        "responds_well_to": null,
        "best_time_to_reach": null,
        "typical_response_speed": "швидко|повільно|непередбачувано",
        "uses_voice_messages": "часто|рідко|ніколи",
        "emoji_usage": "багато|мало|не використовує"
      },

      "relationships": {
        "relation_to_me": "друг|колега|знайомий|партнер|родич|невідомо",
        "relation_description": null,
        "closeness": "близький|середній|далекий",
        "how_we_met": null,
        "duration_of_acquaintance": null,
        "sentiment_toward_me": "позитивний|нейтральний|негативний|змішаний",
        "trust_level": "високий|середній|низький",
        "friends_with": [],
        "conflicts_with": [],
        "romantic_history_with_me": null
      },

      "activity": {
        "first_seen": "дата першого повідомлення або null",
        "last_seen": "дата останнього повідомлення або null",
        "message_count": null,
        "voice_message_count": null,
        "most_active_hours": [],
        "most_active_days": [],
        "reply_rate": "часто відповідає|рідко|не відповідає|невідомо"
      },

      "social": {
        "most_interacts_with": [],
        "rarely_interacts_with": [],
        "group_role": "організатор|активний учасник|спостерігач|невідомо",
        "influence_level": "високий|середній|низький|невідомо"
      },

      "digital": {
        "device_hints": [],
        "apps_mentioned": [],
        "online_habits": null
      },

      "key_life_events": [],
      "notable_quotes": [],
      "facts": [],
      "mentioned_projects": [],
      "mentioned_events": [],
      "mentioned_themes": [],

      "confidence": "high|medium|low",
      "uncertainty_note": null
    }
  ],

  "projects": [
    {
      "name": "Назва",
      "description": null,
      "status": "активний|завершений|планується|невідомо",
      "participants": [],
      "key_dates": [],
      "confidence": "high|medium|low",
      "uncertainty_note": null
    }
  ],

  "events": [
    {
      "name": "Назва",
      "date": null,
      "description": null,
      "participants": [],
      "related_projects": [],
      "confidence": "high|medium|low",
      "uncertainty_note": null
    }
  ],

  "themes": [
    {
      "tag": "slug-тег-без-пробілів",
      "description": null,
      "message_count": 0
    }
  ]
}
""".strip()


# --- Confidence ---

CONFIDENCE_ORDER = {"high": 3, "medium": 2, "low": 1}


def higher_confidence(a: str, b: str) -> str:
    """Повертає вищий рівень confidence."""
    return a if CONFIDENCE_ORDER.get(a, 0) >= CONFIDENCE_ORDER.get(b, 0) else b
