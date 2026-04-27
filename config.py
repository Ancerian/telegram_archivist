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


def transliterate(text: str) -> str:
    """Транслітерація кирилиці (української та російської) в латиницю."""
    result = []
    for char in text:
        result.append(CYRILLIC_TO_LATIN.get(char, char))
    return ''.join(result)


def slugify(name: str) -> str:
    """
    Створює slug з імені.
    Транслітерація кирилиці + lowercase + пробіли → _
    "Антон Іванов" → "anton_ivanov"
    """
    slug = transliterate(name).lower()
    slug = re.sub(r'[^a-z0-9\s_-]', '', slug)
    slug = re.sub(r'[\s-]+', '_', slug)
    slug = slug.strip('_')
    return slug


def sanitize_filename(name: str) -> str:
    """Прибирає символи / \\ : * ? \" < > | з імен файлів."""
    return re.sub(r'[/\\:*?"<>|]', '', name)


# --- System Prompt ---

SYSTEM_PROMPT = """
Ти — архіваріус і аналітик. Аналізуй переписку і витягуй максимально детальну структуровану інформацію про кожну людину.
Відповідай ТІЛЬКИ валідним JSON без markdown-блоків, преамбул і пояснень.

МОВА: Чат може вестись російською, українською, англійською або їх сумішшю. Аналізуй текст будь-якою з цих мов. Заповнюй поля досьє мовою оригіналу — не перекладай. Якщо людина пише українською — її цитати і факти записуй українською. Якщо англійською — англійською.

ВАЖЛИВО: тобі передається список вже відомих сутностей. Якщо згадується людина/проект/подія схожа на вже відому — використовуй їх точне canonical_name, не створюй дублікати. Враховуй що одне ім'я може бути написане різними мовами: "Антон", "Anton", "Антін" — одна людина.

Confidence рівні:
- high: прямий учасник чату, багато згадок, конкретні факти
- medium: згадується побічно, 1-2 рази, деталі розмиті
- low: виведено з контексту, явно не називається

Для полів де немає інформації — ставити null або [].
Не вигадуй інформацію. Тільки те що явно є в тексті або дуже чітко випливає з контексту.

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
