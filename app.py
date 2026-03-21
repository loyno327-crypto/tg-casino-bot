from flask import Flask, request
import requests
import os
import sqlite3
import random
import datetime
import json
import traceback

TOKEN = os.environ.get("7771814257:AAH_YRPXRo2wVmxCUkxha0U8daGxGchPRHQ")
if not TOKEN:
    raise RuntimeError("TOKEN environment variable is not set")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"

app = Flask(__name__)
DB_PATH = "bot.db"


# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id TEXT PRIMARY KEY,
        first_name TEXT,
        balance INTEGER DEFAULT 1000,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        telegram_id TEXT PRIMARY KEY,
        state TEXT,
        payload TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS inventory (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT,
        skin_name TEXT,
        rarity TEXT,
        price INTEGER,
        case_name TEXT,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS case_history (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT,
        case_name TEXT,
        skin_name TEXT,
        rarity TEXT,
        price INTEGER,
        created_at TEXT
    )
    """)

    conn.commit()
    conn.close()


# ---------------- CASE DATA ----------------
CASES = {
    "Fracture Case": {
        "price": 200,
        "items": [
            {"name": "Glock-18 | Bunsen Burner", "rarity": "Consumer", "price": 80, "chance": 30},
            {"name": "MP5-SD | Kitbash", "rarity": "Industrial", "price": 120, "chance": 24},
            {"name": "P2000 | Gnarled", "rarity": "Mil-Spec", "price": 220, "chance": 20},
            {"name": "AK-47 | Legion of Anubis", "rarity": "Restricted", "price": 650, "chance": 12},
            {"name": "M4A4 | Tooth Fairy", "rarity": "Classified", "price": 1400, "chance": 8},
            {"name": "Desert Eagle | Printstream", "rarity": "Covert", "price": 4000, "chance": 5},
            {"name": "★ Butterfly Knife | Fade", "rarity": "Knife", "price": 25000, "chance": 1},
        ]
    },
    "Danger Case": {
        "price": 350,
        "items": [
            {"name": "UMP-45 | Carbon Fiber", "rarity": "Consumer", "price": 120, "chance": 28},
            {"name": "P250 | Supernova", "rarity": "Industrial", "price": 180, "chance": 24},
            {"name": "AWP | Atheris", "rarity": "Mil-Spec", "price": 450, "chance": 20},
            {"name": "AK-47 | Slate", "rarity": "Restricted", "price": 950, "chance": 14},
            {"name": "USP-S | Neo-Noir", "rarity": "Classified", "price": 2200, "chance": 8},
            {"name": "M4A1-S | Printstream", "rarity": "Covert", "price": 6500, "chance": 5},
            {"name": "★ Karambit | Doppler", "rarity": "Knife", "price": 42000, "chance": 1},
        ]
    }
}

RARITY_EMOJI = {
    "Consumer": "⚪",
    "Industrial": "🔵",
    "Mil-Spec": "🟦",
    "Restricted": "🟪",
    "Classified": "🩷",
    "Covert": "🔴",
    "Knife": "🟡",
}


# ---------------- USER ----------------
def get_user(tid):
    conn = db()
    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id=?",
        (str(tid),)
    ).fetchone()
    conn.close()
    return user


def create_user(tid, name):
    conn = db()
    conn.execute("""
    INSERT OR IGNORE INTO users (telegram_id, first_name, balance, created_at)
    VALUES (?, ?, ?, ?)
    """, (str(tid), name, 1000, datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
    conn.commit()
    conn.close()


def update_balance(tid, delta):
    conn = db()
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE telegram_id=?",
        (delta, str(tid))
    )
    conn.commit()
    conn.close()


def add_win(tid):
    conn = db()
    conn.execute(
        "UPDATE users SET wins = wins + 1 WHERE telegram_id=?",
        (str(tid),)
    )
    conn.commit()
    conn.close()


def add_loss(tid):
    conn = db()
    conn.execute(
        "UPDATE users SET losses = losses + 1 WHERE telegram_id=?",
        (str(tid),)
    )
    conn.commit()
    conn.close()


# ---------------- SESSION ----------------
def set_session(tid, state, payload=None):
    payload_json = json.dumps(payload or {}, ensure_ascii=False)

    conn = db()
    conn.execute("""
    INSERT INTO sessions (telegram_id, state, payload)
    VALUES (?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET state=?, payload=?
    """, (str(tid), state, payload_json, state, payload_json))
    conn.commit()
    conn.close()


def get_session(tid):
    conn = db()
    s = conn.execute(
        "SELECT * FROM sessions WHERE telegram_id=?",
        (str(tid),)
    ).fetchone()
    conn.close()
    return s


def get_session_payload(session):
    if not session or not session["payload"]:
        return {}
    try:
        return json.loads(session["payload"])
    except Exception:
        return {}


def clear_session(tid):
    conn = db()
    conn.execute("DELETE FROM sessions WHERE telegram_id=?", (str(tid),))
    conn.commit()
    conn.close()


# ---------------- INVENTORY / CASES ----------------
def add_item_to_inventory(tid, item, case_name):
    conn = db()
    conn.execute("""
    INSERT INTO inventory (telegram_id, skin_name, rarity, price, case_name, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(tid),
        item["name"],
        item["rarity"],
        item["price"],
        case_name,
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def add_case_history(tid, item, case_name):
    conn = db()
    conn.execute("""
    INSERT INTO case_history (telegram_id, case_name, skin_name, rarity, price, created_at)
    VALUES (?, ?, ?, ?, ?, ?)
    """, (
        str(tid),
        case_name,
        item["name"],
        item["rarity"],
        item["price"],
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def get_inventory(tid, limit=20):
    conn = db()
    rows = conn.execute("""
    SELECT id, skin_name, rarity, price, case_name
    FROM inventory
    WHERE telegram_id = ?
    ORDER BY id DESC
    LIMIT ?
    """, (str(tid), limit)).fetchall()
    conn.close()
    return rows


def get_inventory_item(tid, inventory_id):
    conn = db()
    row = conn.execute("""
    SELECT *
    FROM inventory
    WHERE telegram_id = ? AND id = ?
    """, (str(tid), inventory_id)).fetchone()
    conn.close()
    return row


def sell_item(tid, item_id):
    conn = db()
    row = conn.execute("""
    SELECT id, price, skin_name
    FROM inventory
    WHERE telegram_id = ? AND id = ?
    """, (str(tid), item_id)).fetchone()

    if not row:
        conn.close()
        return False, "❌ Предмет не найден."

    sell_price = row["price"]
    skin_name = row["skin_name"]

    conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
        (sell_price, str(tid))
    )
    conn.commit()
    conn.close()

    return True, f"💸 Продано: {skin_name}\nПолучено: {sell_price} монет"


def format_inventory(rows):
    if not rows:
        return "🎒 Инвентарь пуст."

    text = "🎒 Твой инвентарь:\n\n"
    for row in rows:
        emoji = RARITY_EMOJI.get(row["rarity"], "▫️")
        text += (
            f"#{row['id']} | {emoji} {row['skin_name']}\n"
            f"{row['rarity']} | {row['price']} монет\n"
            f"Кейс: {row['case_name']}\n\n"
        )
    text += "Чтобы продать предмет, напиши: sell ID\nПример: sell 15"
    return text.strip()


def roll_case(case_name):
    case = CASES.get(case_name)
    if not case:
        return None
    items = case["items"]
    weights = [item["chance"] for item in items]
    return random.choices(items, weights=weights, k=1)[0]


def open_case(tid, case_name):
    user = get_user(tid)
    case = CASES.get(case_name)

    if not case:
        return None, "❌ Кейс не найден."

    case_price = case["price"]

    if user["balance"] < case_price:
        return None, "❌ Недостаточно монет для открытия кейса."

    update_balance(tid, -case_price)

    item = roll_case(case_name)
    if not item:
        update_balance(tid, case_price)
        return None, "❌ Ошибка открытия кейса."

    add_item_to_inventory(tid, item, case_name)
    add_case_history(tid, item, case_name)

    updated = get_user(tid)
    emoji = RARITY_EMOJI.get(item["rarity"], "▫️")

    text = (
        f"📦 {case_name}\n\n"
        f"🎉 Тебе выпало:\n"
        f"{emoji} {item['name']}\n"
        f"Редкость: {item['rarity']}\n"
        f"Цена: {item['price']} монет\n\n"
        f"💰 Баланс: {updated['balance']}"
    )

    return item, text


# ---------------- TELEGRAM ----------------
def send(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        payload["reply_markup"] = keyboard

    try:
        r = requests.post(
            f"{BASE_URL}/sendMessage",
            json=payload,
            timeout=20
        )
        print("SEND STATUS:", r.status_code, flush=True)
        print("SEND BODY:", r.text, flush=True)
        return r
    except Exception as e:
        print("SEND ERROR:", str(e), flush=True)
        print(traceback.format_exc(), flush=True)
        return None


def main_menu():
    return {
        "keyboard": [
            ["Баланс", "Играть"],
            ["Кейсы", "Инвентарь"],
            ["Апгрейд", "Заработать"],
            ["Статистика"]
        ],
        "resize_keyboard": True
    }


def upgrade_percent_menu():
    return {
        "keyboard": [
            ["5%", "10%", "30%"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


def game_menu():
    return {
        "keyboard": [
            ["Слот", "Рулетка"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


SKINS_DATA = [
    {"name": "Glock-18 | Bunsen Burner", "rarity": "Consumer", "price": 80, "case": "Fracture Case"},
    {"name": "MP5-SD | Kitbash", "rarity": "Industrial", "price": 120, "case": "Fracture Case"},
    {"name": "P2000 | Gnarled", "rarity": "Mil-Spec", "price": 220, "case": "Fracture Case"},
    {"name": "AK-47 | Legion of Anubis", "rarity": "Restricted", "price": 650, "case": "Fracture Case"},
    {"name": "M4A4 | Tooth Fairy", "rarity": "Classified", "price": 1400, "case": "Fracture Case"},
    {"name": "Desert Eagle | Printstream", "rarity": "Covert", "price": 4000, "case": "Fracture Case"},
    {"name": "★ Butterfly Knife | Fade", "rarity": "Knife", "price": 25000, "case": "Fracture Case"},

    {"name": "UMP-45 | Carbon Fiber", "rarity": "Consumer", "price": 120, "case": "Danger Case"},
    {"name": "P250 | Supernova", "rarity": "Industrial", "price": 180, "case": "Danger Case"},
    {"name": "AWP | Atheris", "rarity": "Mil-Spec", "price": 450, "case": "Danger Case"},
    {"name": "AK-47 | Slate", "rarity": "Restricted", "price": 950, "case": "Danger Case"},
    {"name": "USP-S | Neo-Noir", "rarity": "Classified", "price": 2200, "case": "Danger Case"},
    {"name": "M4A1-S | Printstream", "rarity": "Covert", "price": 6500, "case": "Danger Case"},
    {"name": "★ Karambit | Doppler", "rarity": "Knife", "price": 42000, "case": "Danger Case"},
]


def get_upgrade_target(from_price, percent):
    if percent <= 5:
        min_price = int(from_price * 8)
        max_price = int(from_price * 15)
    elif percent <= 10:
        min_price = int(from_price * 4)
        max_price = int(from_price * 8)
    elif percent <= 30:
        min_price = int(from_price * 2)
        max_price = int(from_price * 4)
    else:
        min_price = int(from_price * 1.2)
        max_price = int(from_price * 2)

    candidates = [
        skin for skin in SKINS_DATA
        if skin["price"] > from_price and min_price <= skin["price"] <= max_price
    ]

    if not candidates:
        candidates = [skin for skin in SKINS_DATA if skin["price"] > from_price]

    if not candidates:
        return None

    return random.choice(candidates)


def earn_menu():
    return {
        "keyboard": [
            ["Пример"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


def perform_simple_upgrade(tid, inventory_id, percent):
    item = get_inventory_item(tid, inventory_id)
    if not item:
        return "❌ Предмет не найден."

    from_price = item["price"]
    target = get_upgrade_target(from_price, percent)

    if not target:
        return "❌ Не найдено подходящих целей для апгрейда."

    roll = random.uniform(0, 100)

    conn = db()

    if roll <= percent:
        conn.execute("DELETE FROM inventory WHERE id = ?", (inventory_id,))
        conn.execute("""
        INSERT INTO inventory (telegram_id, skin_name, rarity, price, case_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """, (
            str(tid),
            target["name"],
            target["rarity"],
            target["price"],
            target["case"],
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        ))
        conn.commit()
        conn.close()

        return (
            f"🚀 АПГРЕЙД УСПЕШЕН\n\n"
            f"Было: {item['skin_name']} ({item['price']})\n"
            f"Стало: {target['name']} ({target['price']})\n"
            f"Шанс: {percent}%"
        )

    conn.execute("DELETE FROM inventory WHERE id = ?", (inventory_id,))
    conn.commit()
    conn.close()

    return (
        f"💥 АПГРЕЙД НЕУДАЧЕН\n\n"
        f"Сгорело: {item['skin_name']} ({item['price']})\n"
        f"Цель была: {target['name']} ({target['price']})\n"
        f"Шанс: {percent}%"
    )


def bet_menu():
    return {
        "keyboard": [
            ["10", "50", "100"],
            ["Своя ставка"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


def roulette_menu():
    return {
        "keyboard": [
            ["Красное", "Чёрное"],
            ["Чёт", "Нечёт"],
            ["Число"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


def case_menu():
    return {
        "keyboard": [
            [f"Fracture Case (200)", f"Danger Case (350)"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


# ---------------- HELPERS ----------------
RED_NUMBERS = {
    1, 3, 5, 7, 9, 12, 14, 16, 18,
    19, 21, 23, 25, 27, 30, 32, 34, 36
}

BLACK_NUMBERS = {
    2, 4, 6, 8, 10, 11, 13, 15, 17,
    20, 22, 24, 26, 28, 29, 31, 33, 35
}


def wheel_color(number):
    if number == 0:
        return "Зелёное"
    if number in RED_NUMBERS:
        return "Красное"
    return "Чёрное"


def format_balance_text(user):
    return f"💰 Баланс: {user['balance']} монет"


def safe_int(text):
    try:
        return int(text)
    except Exception:
        return None


# ---------------- SLOT ----------------
def slot_spin(tid, bet):
    user = get_user(tid)

    if bet <= 0:
        return "❌ Ставка должна быть больше 0."

    if user["balance"] < bet:
        return "❌ Недостаточно монет для такой ставки."

    symbols = ["🍒", "🍋", "⭐", "💎", "7️⃣", "🍀", "🔥"]
    reels = [random.choice(symbols) for _ in range(3)]

    counts = {}
    for s in reels:
        counts[s] = counts.get(s, 0) + 1

    max_count = max(counts.values())

    border = "╔══════════════╗\n"
    middle = f"║ {' │ '.join(reels)} ║\n"
    footer = "╚══════════════╝"

    if max_count == 3:
        win_amount = bet * 5
        profit = win_amount - bet
        update_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎰 СЛОТ\n\n"
            f"{border}{middle}{footer}\n\n"
            f"🔥 ДЖЕКПОТ x5\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{profit}\n\n"
            f"{format_balance_text(updated)}"
        )

    if max_count == 2:
        win_amount = bet * 2
        profit = win_amount - bet
        update_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎰 СЛОТ\n\n"
            f"{border}{middle}{footer}\n\n"
            f"✨ Две одинаковые! x2\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{profit}\n\n"
            f"{format_balance_text(updated)}"
        )

    update_balance(tid, -bet)
    add_loss(tid)
    updated = get_user(tid)
    return (
        f"🎰 СЛОТ\n\n"
        f"{border}{middle}{footer}\n\n"
        f"❌ Не повезло\n"
        f"Ставка: {bet}\n"
        f"Потеря: -{bet}\n\n"
        f"{format_balance_text(updated)}"
    )


# ---------------- ROULETTE ----------------
def roulette_resolve(tid, bet, bet_type, bet_value):
    user = get_user(tid)

    if bet is None or bet <= 0:
        return "❌ Некорректная ставка."

    if user["balance"] < bet:
        return "❌ Недостаточно монет для такой ставки."

    number = random.randint(0, 36)
    color = wheel_color(number)

    won = False
    multiplier = 0
    title = "❌ Ставка проиграла"

    if bet_type == "color":
        if number != 0 and bet_value.lower() == color.lower():
            won = True
            multiplier = 2
            title = "🔥 Победа по цвету"
    elif bet_type == "parity":
        if number != 0:
            if bet_value == "Чёт" and number % 2 == 0:
                won = True
                multiplier = 2
                title = "🔥 Победа по чётности"
            elif bet_value == "Нечёт" and number % 2 == 1:
                won = True
                multiplier = 2
                title = "🔥 Победа по чётности"
    elif bet_type == "number":
        if str(number) == str(bet_value):
            won = True
            multiplier = 36
            title = "💥 ТОЧНОЕ ПОПАДАНИЕ"

    if won:
        win_amount = bet * multiplier
        profit = win_amount - bet
        update_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎡 РУЛЕТКА\n\n"
            f"Выпало: {number} ({color})\n\n"
            f"{title}\n"
            f"Ставка: {bet}\n"
            f"Выплата: {win_amount}\n"
            f"Чистая прибыль: +{profit}\n\n"
            f"{format_balance_text(updated)}"
        )

    update_balance(tid, -bet)
    add_loss(tid)
    updated = get_user(tid)
    return (
        f"🎡 РУЛЕТКА\n\n"
        f"Выпало: {number} ({color})\n\n"
        f"❌ Не повезло\n"
        f"Ставка: {bet}\n"
        f"Потеря: -{bet}\n\n"
        f"{format_balance_text(updated)}"
    )


# ---------------- MATH ----------------
def gen_math():
    a = random.randint(5, 50)
    b = random.randint(5, 50)
    op = random.choice(["+", "-", "*"])

    if op == "+":
        answer = a + b
    elif op == "-":
        answer = a - b
    else:
        answer = a * b

    return f"{a} {op} {b}", str(answer)


# ---------------- ROUTES ----------------
@app.route("/", methods=["GET"])
def home():
    return "ok", 200


@app.route("/", methods=["POST"])
def bot():
    try:
        data = request.get_json(silent=True) or {}
        print("INCOMING UPDATE:", json.dumps(data, ensure_ascii=False), flush=True)

        if "message" not in data:
            return "ok", 200

        msg = data["message"]
        chat = msg["chat"]["id"]
        text = msg.get("text", "").strip()
        tg_user = msg["from"]

        user_id = tg_user["id"]

        create_user(user_id, tg_user.get("first_name", "Игрок"))
        user = get_user(user_id)
        session = get_session(user_id)
        payload = get_session_payload(session)

        lower_text = text.lower()

        # START
        if text == "/start":
            clear_session(user_id)
            send(
                chat,
                f"👋 Привет, {user['first_name']}!\n"
                f"Твой баланс: {user['balance']} монет.",
                main_menu()
            )
            return "ok", 200

        # SELL ITEM
        if lower_text.startswith("sell "):
            parts = lower_text.split()
            if len(parts) == 2:
                item_id = safe_int(parts[1])
                if item_id is None:
                    send(chat, "❌ Формат: sell ID\nПример: sell 12", main_menu())
                    return "ok", 200

                ok, result = sell_item(user_id, item_id)
                updated = get_user(user_id)
                send(chat, f"{result}\n\n💰 Баланс: {updated['balance']}", main_menu())
                return "ok", 200

        # BACK
        if text == "Назад":
            clear_session(user_id)
            send(chat, "Главное меню:", main_menu())
            return "ok", 200

        # BALANCE
        if text == "Баланс":
            user = get_user(user_id)
            send(chat, format_balance_text(user), main_menu())
            return "ok", 200

        # STATS
        if text == "Статистика":
            user = get_user(user_id)
            send(
                chat,
                f"📊 Статистика\n\n"
                f"Имя: {user['first_name']}\n"
                f"Баланс: {user['balance']}\n"
                f"Побед: {user['wins']}\n"
                f"Поражений: {user['losses']}",
                main_menu()
            )
            return "ok", 200

        # GAME MENU
        if text == "Играть":
            clear_session(user_id)
            send(chat, "🎮 Выбери игру:", game_menu())
            return "ok", 200

        # SLOT FLOW
        if text == "Слот":
            clear_session(user_id)
            set_session(user_id, "slot_wait_bet")
            send(chat, "🎰 Выбери ставку или нажми «Своя ставка»:", bet_menu())
            return "ok", 200

        if session and session["state"] == "slot_wait_bet":
            if text == "Своя ставка":
                set_session(user_id, "slot_wait_custom_bet")
                send(chat, "💬 Введи свою ставку числом:", bet_menu())
                return "ok", 200

            if text in ["10", "50", "100"]:
                bet = int(text)
                result_text = slot_spin(user_id, bet)
                set_session(user_id, "slot_wait_bet")
                send(chat, result_text, bet_menu())
                return "ok", 200

        if session and session["state"] == "slot_wait_custom_bet":
            bet = safe_int(text)
            if bet is None or bet <= 0:
                send(chat, "❌ Введи ставку числом больше 0.", bet_menu())
                return "ok", 200

            result_text = slot_spin(user_id, bet)
            set_session(user_id, "slot_wait_bet")
            send(chat, result_text, bet_menu())
            return "ok", 200

        # ROULETTE FLOW
        if text == "Рулетка":
            clear_session(user_id)
            set_session(user_id, "roulette_wait_bet")
            send(chat, "🎡 Введи ставку для рулетки:", roulette_menu())
            send(chat, "💬 Напиши сумму ставки числом.")
            return "ok", 200

        if session and session["state"] == "roulette_wait_bet":
            bet = safe_int(text)
            if bet is None or bet <= 0:
                send(chat, "❌ Введи ставку числом больше 0.")
                return "ok", 200

            set_session(user_id, "roulette_wait_type", {"bet": bet})
            send(
                chat,
                f"🎡 Ставка принята: {bet}\n"
                f"Теперь выбери тип ставки:",
                roulette_menu()
            )
            return "ok", 200

        if session and session["state"] == "roulette_wait_type":
            bet = payload.get("bet")

            if text in ["Красное", "Чёрное"]:
                result = roulette_resolve(user_id, bet, "color", text)
                set_session(user_id, "roulette_wait_bet")
                send(chat, result, roulette_menu())
                send(chat, "💬 Хочешь ещё? Введи новую ставку числом.", roulette_menu())
                return "ok", 200

            if text in ["Чёт", "Нечёт"]:
                result = roulette_resolve(user_id, bet, "parity", text)
                set_session(user_id, "roulette_wait_bet")
                send(chat, result, roulette_menu())
                send(chat, "💬 Хочешь ещё? Введи новую ставку числом.", roulette_menu())
                return "ok", 200

            if text == "Число":
                set_session(user_id, "roulette_wait_number", {"bet": bet})
                send(chat, "🔢 Введи число от 0 до 36:")
                return "ok", 200

            send(chat, "Выбери вариант ставки: Красное, Чёрное, Чёт, Нечёт или Число.", roulette_menu())
            return "ok", 200

        if session and session["state"] == "roulette_wait_number":
            bet = payload.get("bet")
            number = safe_int(text)

            if number is None or number < 0 or number > 36:
                send(chat, "❌ Введи число от 0 до 36.")
                return "ok", 200

            result = roulette_resolve(user_id, bet, "number", number)
            set_session(user_id, "roulette_wait_bet")
            send(chat, result, roulette_menu())
            send(chat, "💬 Хочешь ещё? Введи новую ставку числом.", roulette_menu())
            return "ok", 200

        # CASES
        if text == "Кейсы":
            clear_session(user_id)
            send(
                chat,
                "📦 Выбери кейс:\n"
                "Fracture Case — 200\n"
                "Danger Case — 350",
                case_menu()
            )
            return "ok", 200

        if text == "Fracture Case (200)":
            _, result_text = open_case(user_id, "Fracture Case")
            send(chat, result_text, case_menu())
            return "ok", 200

        if text == "Danger Case (350)":
            _, result_text = open_case(user_id, "Danger Case")
            send(chat, result_text, case_menu())
            return "ok", 200

        if text == "Инвентарь":
            rows = get_inventory(user_id)
            send(chat, format_inventory(rows), main_menu())
            return "ok", 200

        # UPGRADE PLACEHOLDER
        if text == "Апгрейд":
            send(chat, "🛠 Апгрейд пока не подключён в меню.", main_menu())
            return "ok", 200

        # EARN
        if text == "Заработать":
            clear_session(user_id)
            send(chat, "🧠 Выбери способ заработка:", earn_menu())
            return "ok", 200

        if text == "Пример":
            question, answer = gen_math()
            set_session(user_id, "math", {"answer": answer})
            send(
                chat,
                f"🧠 Реши пример:\n\n{question}\n\n"
                f"Награда за правильный ответ: 100 монет",
                earn_menu()
            )
            return "ok", 200

        if session and session["state"] == "math":
            correct_answer = str(payload.get("answer", ""))

            if text == correct_answer:
                update_balance(user_id, 100)
                clear_session(user_id)
                updated_user = get_user(user_id)
                send(
                    chat,
                    f"✅ Верно! +100 монет\n"
                    f"{format_balance_text(updated_user)}",
                    earn_menu()
                )
                return "ok", 200
            else:
                clear_session(user_id)
                send(
                    chat,
                    f"❌ Неверно.\nПравильный ответ: {correct_answer}",
                    earn_menu()
                )
                return "ok", 200

        send(chat, "Выбери действие:", main_menu())
        return "ok", 200

    except Exception as e:
        print("BOT ERROR:", str(e), flush=True)
        print(traceback.format_exc(), flush=True)
        return "ok", 200


init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=10000, debug=True)
