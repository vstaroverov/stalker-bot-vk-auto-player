import base64
import json
import os
from datetime import datetime
import httpx
import ollama
from difflib import get_close_matches, SequenceMatcher
from map_knowledge import MAP_DESCRIPTION
from stash_knowledge import STASH_DESCRIPTION

FEEDBACK_FILE = os.path.join(os.path.dirname(__file__), "feedback.json")

DEFAULT_STRATEGY = """Ты играешь в текстовую игру "Сталкер" ВКонтакте.

=== ПРИОРИТЕТЫ (строго по порядку) ===

1. ГОЛОД (Сытость):
   - Если сытость упала до 0 или близко — НЕМЕДЛЕННО ешь, иначе смерть.
   - Последовательность: "Костёр" → "Перекусить" → выбрать еду (Колбаса / Хлеб / Сгущёнка).
   - Если еды нет: "Купить еду" → выбрать продукт → назад → съесть → продолжить.
   - Не исследуй, не дерись пока не поел.

2. ЗДОРОВЬЕ (HP):
   - В БОЮ: аптечки НЕ используй если HP выше 20% — продолжай стрелять "Очередью".
   - Аптечку используй только если HP ≤ 20% и враг ещё жив.
   - После боя (вне боя): если HP ниже 60% — иди к костру: "Костёр" → "Отдохнуть".
   - НЕ начинай новый бой с HP < 30% — сначала отдохни у костра.
   - При аномалии: если HP упало ниже 30% — отступи и восстановись.

3. БОЛТЫ (расходник для аномалий):
   - Всегда следи за количеством болтов.
   - Если болтов МЕНЬШЕ 50 — иди на Свалку и добывай ресурсы до максимума.
   - На Свалке: выбирай "Добыть ресурсы" / "Добыть болты" пока не наберёшь максимум.
   - Без болтов нельзя нормально работать в аномалиях и искать артефакты.

4. АНОМАЛИИ:
   - Если наткнулся на аномалию при исследовании — не уходи, ищи артефакт.
   - Бросай болты в аномалию чтобы её прощупать и найти безопасный путь.
   - Следи за HP во время работы в аномалии — если упало ниже 50%, сначала лечись.
   - После нахождения артефакта — забирай, это ценно.
   - Если аномалия слишком опасна и HP падает быстро — отступи.

5. БОЙ С МОНСТРАМИ:
   - УБИВАЙ ВСЕХ кнопкой "Очередь" / "Стрелять" / "Атаковать" — это основной способ боя.
   - УБЕГАЙ только если враг одновременно имеет МНОГО HP (>300) И БОЛЬШОЙ УРОН (>30 за удар).
   - Если враг сильный но один из условий не выполнен — всё равно бей.
   - Следи за HP в бою: если упало ниже 30% — сначала отступи и вылечись, потом вернись.
   - Приоритет атаки: "Очередь" > "Стрелять" > "Атаковать" > "Ударить".
   - Лучшие для прокачки: Тушканы, Слепые псы, Крысы, обычные мутанты.
   - Убегай точно от: Псевдогигант, Химера (очень высокий урон и HP).

6. ТАЙНИКИ И СЕЙФЫ:
   - Если есть активная карта тайника (статус 1) — иди в ту зону и исследуй.
   - Приоритет: Холмы (100к+АКМ) > Рыхлые земли (70к+пистолет) > Обочина (50к) > Загрязнённая роща (аптечки).
   - Коды сейфов вводи из базы.

7. ИССЛЕДОВАНИЕ ЗОН:
   - Исследуй зоны для артефактов, тайников, опыта.
   - Начинай с безопасных: Деревня новичков, Обочина, Дорога к деревне.
   - С опытом переходи в: Лощина (+30% опыт), Свалка, Перевалочный пункт.
   - Не заходи в Средние болота без сильной брони.

8. РЕСУРСЫ:
   - Подбирай артефакты — ценные всегда.
   - Собирай патроны, снаряжение.
   - Не трать деньги на ненужное.

ЗАПРЕЩЕНО:
- Исследовать с нулевой сытостью.
- Вступать в бой с HP < 30%.
- Работать в аномалии с болтами < 10 штук.
- Бросать ценные предметы (артефакты, оружие) без причины.

Если ситуация непонятна — выбирай Костёр или осторожное действие."""

# --- Контролёр ---
_QA_PATH = os.path.join(os.path.dirname(__file__), "controller_qa.json")
with open(_QA_PATH, encoding="utf-8") as _f:
    _CONTROLLER_QA: list[dict] = json.load(_f)

CONTROLLER_KEYWORDS = [
    "контролёр", "контролер", "загадка", "загадок", "вопрос контролёра", "вопрос контролера",
    "сыграй со мной", "три правильных ответа", "если победишь", "ежели проиграешь",
    "поплатишься", "перекинь свой разум", "время течет и сквозь пыль",
]

# Фразы окончания игры с контролёром
CONTROLLER_END_KEYWORDS = [
    "контролёр забрал", "контролер забрал", "продолжаем путь",
    "ты выиграл", "победил в игре", "проиграл контролёру",
]


def find_controller_answer(text: str) -> str | None:
    text_low = text.lower()
    best_score = 0
    best_answer = None
    for item in _CONTROLLER_QA:
        q_low = item["q"].lower()
        if q_low in text_low:
            return item["a"]
        score = SequenceMatcher(None, q_low, text_low).ratio()
        if score > best_score:
            best_score = score
            best_answer = item["a"]
    if best_score >= 0.45:
        return best_answer
    return None


# --- Сейфы ---
_USER_CODES_FILE = os.path.join(os.path.dirname(__file__), "user_safe_codes.json")

SAFE_CODES = {
    "высокая трава": "9904",
    "тёмная тернистая роща": "5468",
    "темная тернистая роща": "5468",
    "тернистая роща": "5468",
    "кпп с д-3": "3834",
    "кпп с д3": "3834",
    "заброшенный бункер": "3834",
    "туннель под мостом": "4424",
    "тропа на свалку": "3166",
    "тропа около свалки": "3166",
}

# Загружаем пользовательские коды поверх встроенных
if os.path.exists(_USER_CODES_FILE):
    with open(_USER_CODES_FILE, encoding="utf-8") as _uf:
        SAFE_CODES.update(json.load(_uf))


def save_user_safe_code(location: str, code: str):
    """Сохраняет пользовательский код сейфа и добавляет в SAFE_CODES."""
    SAFE_CODES[location.lower()] = code
    data = {}
    if os.path.exists(_USER_CODES_FILE):
        with open(_USER_CODES_FILE, encoding="utf-8") as f:
            data = json.load(f)
    data[location.lower()] = code
    with open(_USER_CODES_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)


WRONG_CODE_KEYWORDS = [
    "неверный код", "код не подходит", "неправильный код",
    "неверный пароль", "ошибка кода", "код неверен",
    "неправильный пароль", "не тот код", "попробуй ещё",
    "попробуйте ещё", "не подходит", "неверно"
]

# Код вводится ТОЛЬКО когда есть и запрос кода И контекст сейфа/замка одновременно
SAFE_CODE_WORDS = ["код", "пароль", "кодовый"]
SAFE_CONTEXT_WORDS = ["сейф", "замок", "дверь", "бункер", "кладовая"]

# Порог уверенности — ниже этого значения спрашиваем пользователя
CONFIDENCE_THRESHOLD = 0.25


VISION_MODEL_KEYWORDS = ["vision", "llava", "moondream", "minicpm", "bakllava", "cogvlm"]


def model_supports_vision(model_name: str) -> bool:
    return any(kw in model_name.lower() for kw in VISION_MODEL_KEYWORDS)


class AIAgent:
    def __init__(self, model: str = "llama3.2", strategy: str = ""):
        self.model = model
        self.strategy = strategy or DEFAULT_STRATEGY
        self.context_history = []
        self.feedback: list[dict] = self._load_feedback()
        self.vision = model_supports_vision(model)
        self.controller_game_active = False

    # ---------- Feedback ----------

    def _load_feedback(self) -> list:
        if os.path.exists(FEEDBACK_FILE):
            with open(FEEDBACK_FILE, encoding="utf-8") as f:
                return json.load(f)
        return []

    def _save_feedback(self):
        with open(FEEDBACK_FILE, "w", encoding="utf-8") as f:
            json.dump(self.feedback, f, ensure_ascii=False, indent=2)

    def add_feedback(self, game_text: str, buttons: list, choice: str,
                     is_good: bool, correction: str = None):
        entry = {
            "ts": datetime.now().isoformat(timespec="seconds"),
            "situation": game_text[:300],
            "buttons": buttons,
            "choice": choice,
            "rating": "good" if is_good else "bad",
        }
        if correction:
            entry["correction"] = correction
        self.feedback.append(entry)
        self._save_feedback()

    def _feedback_prompt_block(self) -> str:
        good = [e for e in self.feedback if e["rating"] == "good"][-5:]
        bad  = [e for e in self.feedback if e["rating"] == "bad"][-5:]
        lines = []
        if good:
            lines.append("ХОРОШИЕ РЕШЕНИЯ (делай так):")
            for e in good:
                lines.append(f'  Ситуация: "{e["situation"][:80]}..." → Нажал: "{e["choice"]}" ✓')
        if bad:
            lines.append("ПЛОХИЕ РЕШЕНИЯ (избегай):")
            for e in bad:
                corr = f' → Надо было: "{e["correction"]}"' if e.get("correction") else ""
                lines.append(f'  Ситуация: "{e["situation"][:80]}..." → Нажал: "{e["choice"]}" ✗{corr}')
        return "\n".join(lines)

    # ---------- Core decision ----------

    def decide(self, game_text: str, buttons: list,
               photo_url: str = None) -> tuple:
        """Returns (choice, log_msg, confidence 0.0-1.0)"""
        button_labels = [b['label'] for b in buttons]
        text_low = game_text.lower()

        # Контролёр — обнаружение начала/конца игры
        if any(kw in text_low for kw in CONTROLLER_END_KEYWORDS):
            self.controller_game_active = False
        if any(kw in text_low for kw in CONTROLLER_KEYWORDS):
            self.controller_game_active = True

        # Контролёр — использовать Q&A базу пока игра активна
        if self.controller_game_active:
            qa_answer = find_controller_answer(game_text)
            if qa_answer:
                matched = self._match_button(qa_answer, button_labels)[0]
                return matched, f"[КОНТРОЛЁР] Ответ из базы: «{qa_answer}» → «{matched}»", 1.0

        # Сейф
        safe_code = self._find_safe_code(game_text)
        if safe_code:
            return safe_code, f"[СЕЙФ] Код: «{safe_code}»", 1.0

        # Обратная связь в промпт
        fb_block = self._feedback_prompt_block()
        system = (
            "Ты управляешь персонажем в текстовой игре ВКонтакте.\n\n"
            + MAP_DESCRIPTION + "\n\n"
            + STASH_DESCRIPTION + "\n\n"
            + (fb_block + "\n\n" if fb_block else "")
            + "Твоя стратегия:\n" + self.strategy + "\n\n"
            "ВАЖНО: отвечай строго в формате двух строк:\n"
            "КНОПКА: <точный текст кнопки из списка>\n"
            "МЫСЛЬ: <одно предложение — почему именно эта кнопка>\n"
            "Никаких других слов, кавычек вокруг кнопки, номеров."
        )

        buttons_block = "\n".join(f'- "{label}"' for label in button_labels)
        map_note = "\n[К сообщению прикреплена карта.]" if photo_url else ""
        user_msg = (
            f"Ситуация:\n{game_text}{map_note}\n\n"
            f"Доступные кнопки:\n{buttons_block}\n\n"
            "Какую кнопку нажать?"
        )

        message = {"role": "user", "content": user_msg}
        if photo_url and self.vision:
            img = self._fetch_image(photo_url)
            if img:
                message["images"] = [img]

        self.context_history.append(message)
        messages = (
            [{"role": "system", "content": system}]
            + self.context_history[-20:]
        )

        response = ollama.chat(model=self.model, messages=messages)
        raw = response.message.content.strip()
        self.context_history.append({"role": "assistant", "content": raw})

        # Разбираем формат "КНОПКА: ...\nМЫСЛЬ: ..."
        raw_button = raw
        thought = ""
        for line in raw.splitlines():
            line = line.strip()
            if line.lower().startswith("кнопка:"):
                raw_button = line.split(":", 1)[1].strip().strip('"\'«»')
            elif line.lower().startswith("мысль:"):
                thought = line.split(":", 1)[1].strip()

        # Если модель не выдала формат — используем весь текст как кнопку
        if raw_button == raw:
            raw_button = raw.splitlines()[0].strip().strip('"\'«»')

        matched, confidence = self._match_button(raw_button, button_labels)
        log = f"ИИ ({confidence:.0%}): «{matched}»"
        if thought:
            log += f"\n  💭 {thought}"
        return matched, log, confidence

    # ---------- Helpers ----------

    def _find_safe_code(self, game_text: str) -> str | None:
        text_low = game_text.lower()
        # Требуем ОДНОВРЕМЕННО слово про код И слово про сейф/замок
        has_code_word = any(kw in text_low for kw in SAFE_CODE_WORDS)
        has_context   = any(kw in text_low for kw in SAFE_CONTEXT_WORDS)
        if not (has_code_word and has_context):
            return None
        for location, code in SAFE_CODES.items():
            if location in text_low:
                return code
        return None

    def _fetch_image(self, url: str) -> str | None:
        try:
            return base64.b64encode(httpx.get(url, timeout=10).content).decode()
        except Exception:
            return None

    def _match_button(self, answer: str, button_labels: list) -> tuple:
        """Returns (matched_label, confidence 0.0-1.0)"""
        answer_low = answer.lower().strip()

        for label in button_labels:
            if label.lower() == answer_low:
                return label, 1.0

        matches = get_close_matches(answer, button_labels, n=1, cutoff=0.35)
        if matches:
            score = SequenceMatcher(None, answer_low, matches[0].lower()).ratio()
            return matches[0], max(0.5, score)

        for label in button_labels:
            if label.lower() in answer_low or answer_low in label.lower():
                return label, 0.45

        if answer.strip().isdigit():
            idx = int(answer.strip()) - 1
            if 0 <= idx < len(button_labels):
                return button_labels[idx], 0.7

        return button_labels[0], 0.1  # fallback — низкая уверенность

    def reset_context(self):
        self.context_history = []
