from flask import Flask, request
import requests
import os
import sqlite3
import random
import datetime
import json

TOKEN = os.environ.get("TOKEN")
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

    conn.commit()
    conn.close()


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


# ---------------- TELEGRAM ----------------
def send(chat_id, text, keyboard=None):
    payload = {
        "chat_id": chat_id,
        "text": text
    }

    if keyboard:
        payload["reply_markup"] = keyboard

    requests.post(
        f"{BASE_URL}/sendMessage",
        json=payload,
        timeout=20
    )


def main_menu():
    return {
        "keyboard": [
            ["Баланс", "Играть"],
            ["Заработать", "Статистика"]
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


def earn_menu():
    return {
        "keyboard": [
            ["Пример"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


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
    data = request.get_json(silent=True) or {}

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


init_db()
