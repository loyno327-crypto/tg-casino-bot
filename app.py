from flask import Flask, request
import datetime
import json
import os
import random
import sqlite3
import string
import traceback

import requests

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN or TOKEN environment variable")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()
DB_PATH = os.environ.get("BOT_DB_PATH", "bot.db")

app = Flask(__name__)


# ---------------- DB ----------------
def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def table_columns(table_name):
    conn = db()
    rows = conn.execute(f"PRAGMA table_info({table_name})").fetchall()
    conn.close()
    return {row["name"] for row in rows}


def ensure_column(table_name, column_name, definition):
    if column_name in table_columns(table_name):
        return
    conn = db()
    conn.execute(f"ALTER TABLE {table_name} ADD COLUMN {column_name} {definition}")
    conn.commit()
    conn.close()


def generate_player_code(length=6):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(alphabet) for _ in range(length))
        conn = db()
        exists = conn.execute(
            "SELECT 1 FROM users WHERE player_code = ?",
            (code,)
        ).fetchone()
        conn.close()
        if not exists:
            return code


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

    cur.execute("""
    CREATE TABLE IF NOT EXISTS battles (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        challenger_id TEXT,
        challenger_code TEXT,
        opponent_id TEXT,
        opponent_code TEXT,
        case_name TEXT,
        status TEXT,
        challenger_item_name TEXT,
        challenger_item_price INTEGER,
        opponent_item_name TEXT,
        opponent_item_price INTEGER,
        winner_id TEXT,
        created_at TEXT,
        resolved_at TEXT
    )
    """)

    conn.commit()
    conn.close()

    ensure_column("users", "player_code", "TEXT")
    ensure_column("users", "battles_won", "INTEGER DEFAULT 0")
    ensure_column("users", "battles_lost", "INTEGER DEFAULT 0")

    conn = db()
    users_without_code = conn.execute(
        "SELECT telegram_id FROM users WHERE player_code IS NULL OR player_code = ''"
    ).fetchall()
    for row in users_without_code:
        conn.execute(
            "UPDATE users SET player_code = ? WHERE telegram_id = ?",
            (generate_player_code(), row["telegram_id"])
        )
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

SLOT_SYMBOLS = ["🍒", "🍋", "⭐", "💎", "7️⃣", "🍀", "🔥"]
SLOT_PAYLINES = {
    3: (5, "🔥 ДЖЕКПОТ x5"),
    2: (2, "✨ Две одинаковые! x2"),
}

SKINS_DATA = [
    {"name": item["name"], "rarity": item["rarity"], "price": item["price"], "case": case_name}
    for case_name, case_data in CASES.items()
    for item in case_data["items"]
]

UPGRADE_OPTIONS = {
    "5%": 5,
    "10%": 10,
    "20%": 20,
    "30%": 30,
    "50%": 50,
}


# ---------------- USER ----------------
def get_user(tid):
    conn = db()
    user = conn.execute(
        "SELECT * FROM users WHERE telegram_id = ?",
        (str(tid),)
    ).fetchone()
    conn.close()
    return user


def get_user_by_code(player_code):
    conn = db()
    user = conn.execute(
        "SELECT * FROM users WHERE player_code = ?",
        (player_code.upper(),)
    ).fetchone()
    conn.close()
    return user


def create_user(tid, name):
    conn = db()
    conn.execute(
        """
        INSERT OR IGNORE INTO users (telegram_id, first_name, balance, created_at, player_code, battles_won, battles_lost)
        VALUES (?, ?, ?, ?, ?, 0, 0)
        """,
        (
            str(tid),
            name,
            1000,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            generate_player_code(),
        )
    )
    conn.execute(
        "UPDATE users SET first_name = COALESCE(?, first_name) WHERE telegram_id = ?",
        (name, str(tid))
    )
    conn.commit()
    conn.close()


def update_balance(tid, delta):
    conn = db()
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
        (delta, str(tid))
    )
    conn.commit()
    conn.close()


def add_win(tid):
    conn = db()
    conn.execute(
        "UPDATE users SET wins = wins + 1 WHERE telegram_id = ?",
        (str(tid),)
    )
    conn.commit()
    conn.close()


def add_loss(tid):
    conn = db()
    conn.execute(
        "UPDATE users SET losses = losses + 1 WHERE telegram_id = ?",
        (str(tid),)
    )
    conn.commit()
    conn.close()


def add_battle_result(tid, won):
    column = "battles_won" if won else "battles_lost"
    conn = db()
    conn.execute(
        f"UPDATE users SET {column} = COALESCE({column}, 0) + 1 WHERE telegram_id = ?",
        (str(tid),)
    )
    conn.commit()
    conn.close()


# ---------------- SESSION ----------------
def set_session(tid, state, payload=None):
    payload_json = json.dumps(payload or {}, ensure_ascii=False)
    conn = db()
    conn.execute(
        """
        INSERT INTO sessions (telegram_id, state, payload)
        VALUES (?, ?, ?)
        ON CONFLICT(telegram_id) DO UPDATE SET state = excluded.state, payload = excluded.payload
        """,
        (str(tid), state, payload_json)
    )
    conn.commit()
    conn.close()


def get_session(tid):
    conn = db()
    session = conn.execute(
        "SELECT * FROM sessions WHERE telegram_id = ?",
        (str(tid),)
    ).fetchone()
    conn.close()
    return session


def get_session_payload(session):
    if not session or not session["payload"]:
        return {}
    try:
        return json.loads(session["payload"])
    except Exception:
        return {}


def clear_session(tid):
    conn = db()
    conn.execute("DELETE FROM sessions WHERE telegram_id = ?", (str(tid),))
    conn.commit()
    conn.close()


# ---------------- INVENTORY / CASES ----------------
def add_item_to_inventory(tid, item, case_name):
    conn = db()
    conn.execute(
        """
        INSERT INTO inventory (telegram_id, skin_name, rarity, price, case_name, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(tid),
            item["name"],
            item["rarity"],
            item["price"],
            case_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    conn.commit()
    conn.close()


def remove_inventory_item(item_id):
    conn = db()
    conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.commit()
    conn.close()


def add_case_history(tid, item, case_name):
    conn = db()
    conn.execute(
        """
        INSERT INTO case_history (telegram_id, case_name, skin_name, rarity, price, created_at)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (
            str(tid),
            case_name,
            item["name"],
            item["rarity"],
            item["price"],
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    conn.commit()
    conn.close()


def get_inventory(tid, limit=20):
    conn = db()
    rows = conn.execute(
        """
        SELECT id, skin_name, rarity, price, case_name
        FROM inventory
        WHERE telegram_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (str(tid), limit)
    ).fetchall()
    conn.close()
    return rows


def get_inventory_item(tid, inventory_id):
    conn = db()
    row = conn.execute(
        "SELECT * FROM inventory WHERE telegram_id = ? AND id = ?",
        (str(tid), inventory_id)
    ).fetchone()
    conn.close()
    return row


def sell_item(tid, item_id):
    conn = db()
    row = conn.execute(
        "SELECT id, price, skin_name FROM inventory WHERE telegram_id = ? AND id = ?",
        (str(tid), item_id)
    ).fetchone()

    if not row:
        conn.close()
        return False, "❌ Предмет не найден."

    conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.execute(
        "UPDATE users SET balance = balance + ? WHERE telegram_id = ?",
        (row["price"], str(tid))
    )
    conn.commit()
    conn.close()
    return True, f"💸 Продано: {row['skin_name']}\nПолучено: {row['price']} монет"


def format_inventory(rows):
    if not rows:
        return "🎒 Инвентарь пуст."

    lines = ["🎒 Твой инвентарь:", ""]
    for row in rows:
        emoji = RARITY_EMOJI.get(row["rarity"], "▫️")
        lines.append(f"#{row['id']} | {emoji} {row['skin_name']}")
        lines.append(f"{row['rarity']} | {row['price']} монет")
        lines.append(f"Кейс: {row['case_name']}")
        lines.append("")
    lines.append("Чтобы продать предмет, напиши: sell ID")
    lines.append("Чтобы начать апгрейд, напиши: upgrade ID")
    return "\n".join(lines).strip()


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
    if user["balance"] < case["price"]:
        return None, "❌ Недостаточно монет для открытия кейса."

    update_balance(tid, -case["price"])
    item = roll_case(case_name)
    if not item:
        update_balance(tid, case["price"])
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
def telegram_api(method, payload):
    return requests.post(
        f"{BASE_URL}/{method}",
        json=payload,
        timeout=20
    )


def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard
    try:
        response = telegram_api("sendMessage", payload)
        print("SEND STATUS:", response.status_code, flush=True)
        print("SEND BODY:", response.text, flush=True)
        return response
    except Exception as exc:
        print("SEND ERROR:", str(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        return None


def configure_webhook():
    if not WEBHOOK_URL:
        print("WEBHOOK SKIPPED: TELEGRAM_WEBHOOK_URL is not set", flush=True)
        return
    webhook_url = WEBHOOK_URL.rstrip("/") + "/"
    try:
        response = telegram_api("setWebhook", {"url": webhook_url})
        print("WEBHOOK STATUS:", response.status_code, flush=True)
        print("WEBHOOK BODY:", response.text, flush=True)
        response.raise_for_status()
    except Exception as exc:
        print("WEBHOOK ERROR:", str(exc), flush=True)
        print(traceback.format_exc(), flush=True)


@app.route("/set_webhook", methods=["POST", "GET"])
def set_webhook_route():
    configure_webhook()
    return {"ok": True, "webhook_url": WEBHOOK_URL.rstrip("/") + "/" if WEBHOOK_URL else ""}, 200


# ---------------- MENUS ----------------
def main_menu():
    return {
        "keyboard": [
            ["Баланс", "Играть"],
            ["Кейсы", "Инвентарь"],
            ["Апгрейд", "Сражения"],
            ["Заработать", "Статистика"],
        ],
        "resize_keyboard": True,
    }


def game_menu():
    return {
        "keyboard": [["Слот", "Рулетка"], ["Назад"]],
        "resize_keyboard": True,
    }


def bet_menu():
    return {
        "keyboard": [["10", "50", "100"], ["Своя ставка"], ["Назад"]],
        "resize_keyboard": True,
    }


def roulette_menu():
    return {
        "keyboard": [["Красное", "Чёрное"], ["Чёт", "Нечёт"], ["Число"], ["Назад"]],
        "resize_keyboard": True,
    }


def case_menu():
    return {
        "keyboard": [["Fracture Case (200)", "Danger Case (350)"], ["Назад"]],
        "resize_keyboard": True,
    }


def earn_menu():
    return {
        "keyboard": [["Пример"], ["Назад"]],
        "resize_keyboard": True,
    }


def upgrade_percent_menu():
    return {
        "keyboard": [["5%", "10%", "20%"], ["30%", "50%"], ["Назад"]],
        "resize_keyboard": True,
    }


def battle_menu():
    return {
        "keyboard": [["Создать сражение", "Мои сражения"], ["Назад"]],
        "resize_keyboard": True,
    }


def battle_case_menu():
    return {
        "keyboard": [["Fracture Case", "Danger Case"], ["Назад"]],
        "resize_keyboard": True,
    }


# ---------------- HELPERS ----------------
RED_NUMBERS = {1, 3, 5, 7, 9, 12, 14, 16, 18, 19, 21, 23, 25, 27, 30, 32, 34, 36}
BLACK_NUMBERS = {2, 4, 6, 8, 10, 11, 13, 15, 17, 20, 22, 24, 26, 28, 29, 31, 33, 35}


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


def normalize_case_name(text):
    if text == "Fracture Case (200)":
        return "Fracture Case"
    if text == "Danger Case (350)":
        return "Danger Case"
    return text


def format_item(item):
    emoji = RARITY_EMOJI.get(item["rarity"], "▫️")
    return f"{emoji} {item['name']} ({item['price']})"


def format_stats(user):
    return (
        f"📊 Статистика\n\n"
        f"Имя: {user['first_name']}\n"
        f"Код игрока: {user['player_code']}\n"
        f"Баланс: {user['balance']}\n"
        f"Побед в играх: {user['wins']}\n"
        f"Поражений в играх: {user['losses']}\n"
        f"Побед в сражениях: {user['battles_won']}\n"
        f"Поражений в сражениях: {user['battles_lost']}"
    )


def build_slot_board(reels):
    top = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    bottom = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    lines = [
        "╔═══════════════════╗",
        f"║ {' '.join(top)} ║",
        f"║▶ {' │ '.join(reels)} ◀║",
        f"║ {' '.join(bottom)} ║",
        "╚═══════════════════╝",
    ]
    return "\n".join(lines)


def get_upgrade_target(from_price, percent):
    ratio_map = {
        5: (7.0, 15.0),
        10: (4.0, 8.0),
        20: (2.5, 5.0),
        30: (1.8, 3.5),
        50: (1.2, 2.2),
    }
    min_ratio, max_ratio = ratio_map.get(percent, (1.2, 2.0))
    min_price = int(from_price * min_ratio)
    max_price = int(from_price * max_ratio)
    candidates = [
        skin for skin in SKINS_DATA
        if skin["price"] > from_price and min_price <= skin["price"] <= max_price
    ]
    if not candidates:
        candidates = [skin for skin in SKINS_DATA if skin["price"] > from_price]
    return random.choice(candidates) if candidates else None


def perform_upgrade(tid, inventory_id, percent):
    item = get_inventory_item(tid, inventory_id)
    if not item:
        return "❌ Предмет не найден или уже использован."

    target = get_upgrade_target(item["price"], percent)
    if not target:
        return "❌ Не найдено подходящих целей для апгрейда."

    roll = random.uniform(0, 100)
    success = roll <= percent

    remove_inventory_item(inventory_id)
    if success:
        add_item_to_inventory(tid, target, target["case"])
        result = (
            f"🚀 АПГРЕЙД УСПЕШЕН\n\n"
            f"Было: {item['skin_name']} ({item['price']})\n"
            f"Стало: {target['name']} ({target['price']})\n"
            f"Шанс: {percent}%\n"
            f"Прокрутка удачи: {roll:.2f}"
        )
    else:
        result = (
            f"💥 АПГРЕЙД НЕУДАЧЕН\n\n"
            f"Сгорело: {item['skin_name']} ({item['price']})\n"
            f"Цель была: {target['name']} ({target['price']})\n"
            f"Шанс: {percent}%\n"
            f"Прокрутка удачи: {roll:.2f}"
        )

    rows = get_inventory(tid)
    inventory_preview = format_inventory(rows)
    return f"{result}\n\n{inventory_preview}"


def create_battle(challenger, opponent, case_name):
    conn = db()
    cursor = conn.execute(
        """
        INSERT INTO battles (
            challenger_id, challenger_code, opponent_id, opponent_code, case_name,
            status, created_at
        )
        VALUES (?, ?, ?, ?, ?, 'pending', ?)
        """,
        (
            challenger["telegram_id"],
            challenger["player_code"],
            opponent["telegram_id"],
            opponent["player_code"],
            case_name,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        )
    )
    battle_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return battle_id


def get_battle(battle_id):
    conn = db()
    battle = conn.execute("SELECT * FROM battles WHERE id = ?", (battle_id,)).fetchone()
    conn.close()
    return battle


def list_user_battles(tid, limit=10):
    conn = db()
    rows = conn.execute(
        """
        SELECT * FROM battles
        WHERE challenger_id = ? OR opponent_id = ?
        ORDER BY id DESC
        LIMIT ?
        """,
        (str(tid), str(tid), limit)
    ).fetchall()
    conn.close()
    return rows


def format_battle_list(rows):
    if not rows:
        return "⚔️ Сражений пока нет."
    lines = ["⚔️ Последние сражения:", ""]
    for row in rows:
        lines.append(
            f"#{row['id']} | {row['challenger_code']} vs {row['opponent_code']} | {row['case_name']} | {row['status']}"
        )
    return "\n".join(lines)


def resolve_battle(battle_id):
    battle = get_battle(battle_id)
    if not battle or battle["status"] != "accepted":
        return None

    challenger_item = roll_case(battle["case_name"])
    opponent_item = roll_case(battle["case_name"])
    if not challenger_item or not opponent_item:
        return None

    challenger_price = challenger_item["price"]
    opponent_price = opponent_item["price"]

    winner_id = None
    result_title = "🤝 Ничья"
    if challenger_price > opponent_price:
        winner_id = battle["challenger_id"]
        result_title = "🏆 Победил вызывающий игрок"
    elif opponent_price > challenger_price:
        winner_id = battle["opponent_id"]
        result_title = "🏆 Победил приглашённый игрок"

    case_price = CASES[battle["case_name"]]["price"]
    total_pot = case_price * 2

    if winner_id:
        update_balance(winner_id, total_pot)
        loser_id = battle["opponent_id"] if winner_id == battle["challenger_id"] else battle["challenger_id"]
        add_battle_result(winner_id, True)
        add_battle_result(loser_id, False)
    else:
        update_balance(battle["challenger_id"], case_price)
        update_balance(battle["opponent_id"], case_price)

    conn = db()
    conn.execute(
        """
        UPDATE battles
        SET status = 'completed', challenger_item_name = ?, challenger_item_price = ?,
            opponent_item_name = ?, opponent_item_price = ?, winner_id = ?, resolved_at = ?
        WHERE id = ?
        """,
        (
            challenger_item["name"],
            challenger_price,
            opponent_item["name"],
            opponent_price,
            winner_id,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            battle_id,
        )
    )
    conn.commit()
    conn.close()

    battle = get_battle(battle_id)
    return (
        battle,
        f"⚔️ СРАЖЕНИЕ #{battle_id}\n\n"
        f"Кейс: {battle['case_name']}\n"
        f"{battle['challenger_code']}: {battle['challenger_item_name']} ({battle['challenger_item_price']})\n"
        f"{battle['opponent_code']}: {battle['opponent_item_name']} ({battle['opponent_item_price']})\n\n"
        f"{result_title}\n"
        f"Банк: {total_pot} монет"
    )


def accept_battle(battle_id, user_id):
    battle = get_battle(battle_id)
    if not battle:
        return "❌ Сражение не найдено.", None
    if battle["opponent_id"] != str(user_id):
        return "❌ Это приглашение адресовано не тебе.", None
    if battle["status"] != "pending":
        return f"❌ Сражение уже имеет статус: {battle['status']}.", None

    case_price = CASES[battle["case_name"]]["price"]
    challenger = get_user(battle["challenger_id"])
    opponent = get_user(battle["opponent_id"])
    if challenger["balance"] < case_price:
        return "❌ У создателя сражения уже не хватает монет на участие.", None
    if opponent["balance"] < case_price:
        return "❌ У тебя недостаточно монет для принятия сражения.", None

    update_balance(challenger["telegram_id"], -case_price)
    update_balance(opponent["telegram_id"], -case_price)

    conn = db()
    conn.execute("UPDATE battles SET status = 'accepted' WHERE id = ?", (battle_id,))
    conn.commit()
    conn.close()

    return None, resolve_battle(battle_id)


def decline_battle(battle_id, user_id):
    battle = get_battle(battle_id)
    if not battle:
        return "❌ Сражение не найдено."
    if battle["opponent_id"] != str(user_id):
        return "❌ Это приглашение адресовано не тебе."
    if battle["status"] != "pending":
        return f"❌ Сражение уже имеет статус: {battle['status']}."
    conn = db()
    conn.execute("UPDATE battles SET status = 'declined', resolved_at = ? WHERE id = ?", (
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        battle_id,
    ))
    conn.commit()
    conn.close()
    return f"❌ Ты отклонил сражение #{battle_id}."


# ---------------- SLOT ----------------
def slot_spin(tid, bet):
    user = get_user(tid)
    if bet <= 0:
        return "❌ Ставка должна быть больше 0."
    if user["balance"] < bet:
        return "❌ Недостаточно монет для такой ставки."

    reels = [random.choice(SLOT_SYMBOLS) for _ in range(3)]
    counts = {}
    for symbol in reels:
        counts[symbol] = counts.get(symbol, 0) + 1
    max_count = max(counts.values())
    board = build_slot_board(reels)

    if max_count in SLOT_PAYLINES:
        multiplier, title = SLOT_PAYLINES[max_count]
        win_amount = bet * multiplier
        profit = win_amount - bet
        update_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎰 СЛОТ-МАШИНА\n\n{board}\n\n"
            f"{title}\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{profit}\n\n"
            f"{format_balance_text(updated)}"
        )

    update_balance(tid, -bet)
    add_loss(tid)
    updated = get_user(tid)
    return (
        f"🎰 СЛОТ-МАШИНА\n\n{board}\n\n"
        f"💨 Барабаны остановились мимо кассы\n"
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
        if number != 0 and ((bet_value == "Чёт" and number % 2 == 0) or (bet_value == "Нечёт" and number % 2 == 1)):
            won = True
            multiplier = 2
            title = "🔥 Победа по чётности"
    elif bet_type == "number" and str(number) == str(bet_value):
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

        if text == "/start":
            clear_session(user_id)
            send(
                chat,
                f"👋 Привет, {user['first_name']}!\n"
                f"Твой код игрока: {user['player_code']}\n"
                f"Твой баланс: {user['balance']} монет.",
                main_menu(),
            )
            return "ok", 200

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

        if lower_text.startswith("upgrade "):
            parts = lower_text.split()
            if len(parts) == 2:
                item_id = safe_int(parts[1])
                if item_id is None:
                    send(chat, "❌ Формат: upgrade ID\nПример: upgrade 15", main_menu())
                    return "ok", 200
                item = get_inventory_item(user_id, item_id)
                if not item:
                    send(chat, "❌ Предмет не найден. Проверь ID в инвентаре.", main_menu())
                    return "ok", 200
                set_session(user_id, "upgrade_choose_percent", {"inventory_id": item_id})
                send(
                    chat,
                    f"🛠 Апгрейд предмета #{item_id}\n"
                    f"{item['skin_name']} ({item['price']})\n\n"
                    f"Выбери шанс апгрейда:",
                    upgrade_percent_menu(),
                )
                return "ok", 200

        if lower_text.startswith("battle accept "):
            battle_id = safe_int(lower_text.split()[-1])
            error_text, battle_result = accept_battle(battle_id, user_id)
            if error_text:
                send(chat, error_text, main_menu())
                return "ok", 200
            _, result_text = battle_result
            battle = get_battle(battle_id)
            send(chat, f"✅ Ты принял сражение.\n\n{result_text}", main_menu())
            send(int(battle["challenger_id"]), f"⚔️ Твое приглашение приняли.\n\n{result_text}", main_menu())
            return "ok", 200

        if lower_text.startswith("battle decline "):
            battle_id = safe_int(lower_text.split()[-1])
            result_text = decline_battle(battle_id, user_id)
            battle = get_battle(battle_id)
            send(chat, result_text, main_menu())
            if battle:
                send(int(battle["challenger_id"]), f"⚠️ Игрок отклонил сражение #{battle_id}.", main_menu())
            return "ok", 200

        if text == "Назад":
            clear_session(user_id)
            send(chat, "Главное меню:", main_menu())
            return "ok", 200

        if text == "Баланс":
            send(chat, format_balance_text(get_user(user_id)), main_menu())
            return "ok", 200

        if text == "Статистика":
            send(chat, format_stats(get_user(user_id)), main_menu())
            return "ok", 200

        if text == "Играть":
            clear_session(user_id)
            send(chat, "🎮 Выбери игру:", game_menu())
            return "ok", 200

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
                result_text = slot_spin(user_id, int(text))
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
            send(chat, f"🎡 Ставка принята: {bet}\nТеперь выбери тип ставки:", roulette_menu())
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

        if text == "Кейсы":
            clear_session(user_id)
            send(chat, "📦 Выбери кейс:\nFracture Case — 200\nDanger Case — 350", case_menu())
            return "ok", 200

        if text in ["Fracture Case (200)", "Danger Case (350)"]:
            _, result_text = open_case(user_id, normalize_case_name(text))
            send(chat, result_text, case_menu())
            return "ok", 200

        if text == "Инвентарь":
            send(chat, format_inventory(get_inventory(user_id)), main_menu())
            return "ok", 200

        if text == "Апгрейд":
            clear_session(user_id)
            rows = get_inventory(user_id)
            send(
                chat,
                "🛠 Для апгрейда открой инвентарь и напиши команду upgrade ID.\n\n" + format_inventory(rows),
                main_menu(),
            )
            return "ok", 200

        if session and session["state"] == "upgrade_choose_percent":
            percent = UPGRADE_OPTIONS.get(text)
            inventory_id = payload.get("inventory_id")
            if not percent:
                send(chat, "Выбери шанс из меню ниже.", upgrade_percent_menu())
                return "ok", 200
            clear_session(user_id)
            send(chat, perform_upgrade(user_id, inventory_id, percent), main_menu())
            return "ok", 200

        if text == "Сражения":
            clear_session(user_id)
            send(
                chat,
                f"⚔️ Сражения по коду игрока.\nТвой код: {user['player_code']}\n"
                f"Чтобы пригласить, выбери «Создать сражение».",
                battle_menu(),
            )
            return "ok", 200

        if text == "Мои сражения":
            send(chat, format_battle_list(list_user_battles(user_id)), battle_menu())
            return "ok", 200

        if text == "Создать сражение":
            clear_session(user_id)
            set_session(user_id, "battle_wait_code")
            send(chat, "🆔 Введи код игрока, которого хочешь вызвать.", battle_menu())
            return "ok", 200

        if session and session["state"] == "battle_wait_code":
            opponent = get_user_by_code(text.upper())
            if not opponent:
                send(chat, "❌ Игрок с таким кодом не найден.", battle_menu())
                return "ok", 200
            if opponent["telegram_id"] == str(user_id):
                send(chat, "❌ Нельзя вызвать самого себя.", battle_menu())
                return "ok", 200
            set_session(user_id, "battle_wait_case", {"opponent_code": opponent["player_code"]})
            send(
                chat,
                f"✅ Игрок найден: {opponent['first_name']} ({opponent['player_code']}).\nВыбери кейс для сражения.",
                battle_case_menu(),
            )
            return "ok", 200

        if session and session["state"] == "battle_wait_case":
            case_name = normalize_case_name(text)
            if case_name not in CASES:
                send(chat, "Выбери кейс из меню ниже.", battle_case_menu())
                return "ok", 200

            opponent = get_user_by_code(payload.get("opponent_code", ""))
            if not opponent:
                clear_session(user_id)
                send(chat, "❌ Игрок больше недоступен. Попробуй ещё раз.", battle_menu())
                return "ok", 200

            case_price = CASES[case_name]["price"]
            challenger = get_user(user_id)
            if challenger["balance"] < case_price:
                clear_session(user_id)
                send(chat, f"❌ Нужно минимум {case_price} монет для этого сражения.", battle_menu())
                return "ok", 200

            battle_id = create_battle(challenger, opponent, case_name)
            clear_session(user_id)
            send(
                chat,
                f"📨 Приглашение отправлено игроку {opponent['first_name']} ({opponent['player_code']}).\n"
                f"Сражение #{battle_id}, кейс: {case_name}.\n"
                f"Цена входа для каждого: {case_price} монет.",
                battle_menu(),
            )
            send(
                int(opponent["telegram_id"]),
                f"⚔️ Тебя вызвали на сражение!\n\n"
                f"Сражение #{battle_id}\n"
                f"От: {challenger['first_name']} ({challenger['player_code']})\n"
                f"Кейс: {case_name}\n"
                f"Вход: {case_price} монет\n\n"
                f"Чтобы принять: battle accept {battle_id}\n"
                f"Чтобы отклонить: battle decline {battle_id}",
                main_menu(),
            )
            return "ok", 200

        if text == "Заработать":
            clear_session(user_id)
            send(chat, "🧠 Выбери способ заработка:", earn_menu())
            return "ok", 200

        if text == "Пример":
            question, answer = gen_math()
            set_session(user_id, "math", {"answer": answer})
            send(chat, f"🧠 Реши пример:\n\n{question}\n\nНаграда за правильный ответ: 100 монет", earn_menu())
            return "ok", 200

        if session and session["state"] == "math":
            correct_answer = str(payload.get("answer", ""))
            if text == correct_answer:
                update_balance(user_id, 100)
                clear_session(user_id)
                updated_user = get_user(user_id)
                send(chat, f"✅ Верно! +100 монет\n{format_balance_text(updated_user)}", earn_menu())
                return "ok", 200
            clear_session(user_id)
            send(chat, f"❌ Неверно.\nПравильный ответ: {correct_answer}", earn_menu())
            return "ok", 200

        send(chat, "Выбери действие:", main_menu())
        return "ok", 200

    except Exception as exc:
        print("BOT ERROR:", str(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        return "ok", 200


init_db()
configure_webhook()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
