from flask import Flask, request
import requests
import os
import sqlite3
import random
import datetime

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
def set_session(tid, state, payload=""):
    conn = db()
    conn.execute("""
    INSERT INTO sessions (telegram_id, state, payload)
    VALUES (?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET state=?, payload=?
    """, (str(tid), state, payload, state, payload))
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
            ["Слот"],
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
            ["Назад"]
        ],
        "resize_keyboard": True
    }


# ---------------- GAME SLOT ----------------
def format_slot_result(res, title, info, balance):
    return (
        f"🎰 СЛОТ 🎰\n"
        f"┌─────────────┐\n"
        f"│ {' '.join(res)} │\n"
        f"└─────────────┘\n\n"
        f"{title}\n"
        f"{info}\n\n"
        f"💰 Баланс: {balance}"
    )


def slot(tid, bet):
    user = get_user(tid)

    if user["balance"] < bet:
        return None, "Недостаточно монет для такой ставки."

    symbols = ["🍒", "🍋", "⭐", "💎", "7️⃣", "🍀"]
    res = [random.choice(symbols) for _ in range(3)]

    counts = {}
    for x in res:
        counts[x] = counts.get(x, 0) + 1

    max_count = max(counts.values())

    if max_count == 3:
        win_amount = bet * 5
        profit = win_amount - bet
        update_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        text = format_slot_result(
            res,
            "🔥 ДЖЕКПОТ x5",
            f"Ставка: {bet}\nВыигрыш: {win_amount}\nЧистая прибыль: +{profit}",
            updated["balance"]
        )
        return True, text

    if max_count == 2:
        win_amount = bet * 2
        profit = win_amount - bet
        update_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        text = format_slot_result(
            res,
            "✨ Есть пара x2",
            f"Ставка: {bet}\nВыигрыш: {win_amount}\nЧистая прибыль: +{profit}",
            updated["balance"]
        )
        return True, text

    update_balance(tid, -bet)
    add_loss(tid)
    updated = get_user(tid)
    text = format_slot_result(
        res,
        "❌ Не повезло",
        f"Ставка: {bet}\nПотеря: -{bet}",
        updated["balance"]
    )
    return False, text


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
    user = msg["from"]

    create_user(user["id"], user.get("first_name", "Игрок"))
    u = get_user(user["id"])
    session = get_session(user["id"])

    # START
    if text == "/start":
        clear_session(user["id"])
        send(
            chat,
            f"Привет, {u['first_name']}!\nТвой баланс: {u['balance']} монет.",
            main_menu()
        )
        return "ok", 200

    # BACK
    if text == "Назад":
        clear_session(user["id"])
        send(chat, "Главное меню:", main_menu())
        return "ok", 200

    # BALANCE
    if text == "Баланс":
        u = get_user(user["id"])
        send(chat, f"💰 Баланс: {u['balance']} монет", main_menu())
        return "ok", 200

    # STATS
    if text == "Статистика":
        u = get_user(user["id"])
        send(
            chat,
            f"📊 Статистика\n\n"
            f"Имя: {u['first_name']}\n"
            f"Баланс: {u['balance']}\n"
            f"Побед: {u['wins']}\n"
            f"Поражений: {u['losses']}",
            main_menu()
        )
        return "ok", 200

    # GAME MENU
    if text == "Играть":
        clear_session(user["id"])
        send(chat, "🎮 Выбери игру:", game_menu())
        return "ok", 200

    # SLOT
    if text == "Слот":
        clear_session(user["id"])
        send(chat, "🎰 Выбери ставку:", bet_menu())
        return "ok", 200

    if text in ["10", "50", "100"]:
        bet = int(text)
        _, result_text = slot(user["id"], bet)
        # Оставляем в игровом меню, не возвращаем в главное
        send(chat, result_text, bet_menu())
        return "ok", 200

    # EARN
    if text == "Заработать":
        clear_session(user["id"])
        send(chat, "🧠 Выбери способ заработка:", earn_menu())
        return "ok", 200

    if text == "Пример":
        question, answer = gen_math()
        set_session(user["id"], "math", answer)
        send(
            chat,
            f"🧠 Реши пример:\n\n{question}\n\n"
            f"Награда за правильный ответ: 100 монет",
            earn_menu()
        )
        return "ok", 200

    if session and session["state"] == "math":
        correct_answer = session["payload"]

        if text == correct_answer:
            update_balance(user["id"], 100)
            clear_session(user["id"])
            updated_user = get_user(user["id"])
            send(
                chat,
                f"✅ Верно! +100 монет\n"
                f"💰 Текущий баланс: {updated_user['balance']}",
                earn_menu()
            )
            return "ok", 200
        else:
            clear_session(user["id"])
            send(
                chat,
                f"❌ Неверно.\nПравильный ответ: {correct_answer}",
                earn_menu()
            )
            return "ok", 200

    send(chat, "Выбери действие:", main_menu())
    return "ok", 200


init_db()
