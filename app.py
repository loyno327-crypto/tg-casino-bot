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
    user = conn.execute("SELECT * FROM users WHERE telegram_id=?", (str(tid),)).fetchone()
    conn.close()
    return user


def create_user(tid, name):
    conn = db()
    conn.execute("""
    INSERT OR IGNORE INTO users (telegram_id, first_name, balance, created_at)
    VALUES (?, ?, ?, ?)
    """, (str(tid), name, 1000, datetime.datetime.now()))
    conn.commit()
    conn.close()


def update_balance(tid, delta):
    conn = db()
    conn.execute("UPDATE users SET balance = balance + ? WHERE telegram_id=?",
                 (delta, str(tid)))
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
    s = conn.execute("SELECT * FROM sessions WHERE telegram_id=?", (str(tid),)).fetchone()
    conn.close()
    return s


def clear_session(tid):
    conn = db()
    conn.execute("DELETE FROM sessions WHERE telegram_id=?", (str(tid),))
    conn.commit()
    conn.close()


# ---------------- TELEGRAM ----------------
def send(chat_id, text, keyboard=None):
    payload = {"chat_id": chat_id, "text": text}
    if keyboard:
        payload["reply_markup"] = keyboard

    requests.post(f"{BASE_URL}/sendMessage", json=payload)


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
        "keyboard": [["Слот"], ["Назад"]],
        "resize_keyboard": True
    }


def earn_menu():
    return {
        "keyboard": [["Пример"], ["Назад"]],
        "resize_keyboard": True
    }


def bet_menu():
    return {
        "keyboard": [["10", "50", "100"], ["Назад"]],
        "resize_keyboard": True
    }


# ---------------- GAME SLOT ----------------
def slot(tid, bet):
    user = get_user(tid)

    if user["balance"] < bet:
        return "Недостаточно монет"

    symbols = ["🍒", "🍋", "⭐", "💎", "7️⃣"]
    res = [random.choice(symbols) for _ in range(3)]

    counts = {x: res.count(x) for x in res}
    max_count = max(counts.values())

    if max_count == 3:
        win = bet * 5
        update_balance(tid, win - bet)
        return f"{res}\nДЖЕКПОТ x5\n+{win - bet}"

    if max_count == 2:
        win = bet * 2
        update_balance(tid, win - bet)
        return f"{res}\nПара x2\n+{win - bet}"

    update_balance(tid, -bet)
    return f"{res}\nПроигрыш -{bet}"


# ---------------- MATH ----------------
def gen_math():
    a = random.randint(1, 20)
    b = random.randint(1, 20)
    return f"{a}+{b}", str(a + b)


# ---------------- ROUTES ----------------
@app.route("/", methods=["GET"])
def home():
    return "ok", 200


@app.route("/", methods=["POST"])
def bot():
    data = request.get_json()

    if "message" not in data:
        return "ok"

    msg = data["message"]
    chat = msg["chat"]["id"]
    text = msg.get("text", "")
    user = msg["from"]

    create_user(user["id"], user.get("first_name", "Игрок"))
    u = get_user(user["id"])
    session = get_session(user["id"])

    # START
    if text == "/start":
        clear_session(user["id"])
        send(chat, f"Привет, {u['first_name']}!\nБаланс: {u['balance']}", main_menu())
        return "ok"

    # BACK
    if text == "Назад":
        clear_session(user["id"])
        send(chat, "Меню", main_menu())
        return "ok"

    # BALANCE
    if text == "Баланс":
        send(chat, f"Баланс: {u['balance']}", main_menu())
        return "ok"

    # STATS
    if text == "Статистика":
        send(chat, f"Баланс: {u['balance']}\nПобед: {u['wins']}\nПоражений: {u['losses']}", main_menu())
        return "ok"

    # GAME
    if text == "Играть":
        send(chat, "Выбери игру", game_menu())
        return "ok"

    if text == "Слот":
        send(chat, "Ставка:", bet_menu())
        return "ok"

    if text in ["10", "50", "100"]:
        res = slot(user["id"], int(text))
        new_user = get_user(user["id"])
        send(chat, f"{res}\nБаланс: {new_user['balance']}", game_menu())
        return "ok"

    # EARN
    if text == "Заработать":
        send(chat, "Выбери", earn_menu())
        return "ok"

    if text == "Пример":
        q, a = gen_math()
        set_session(user["id"], "math", a)
        send(chat, f"Реши: {q}")
        return "ok"

    if session and session["state"] == "math":
        if text == session["payload"]:
            update_balance(user["id"], 10)
            clear_session(user["id"])
            send(chat, "Верно +10", main_menu())
        else:
            clear_session(user["id"])
            send(chat, f"Неверно. Ответ: {session['payload']}", main_menu())
        return "ok"

    send(chat, "Выбери действие", main_menu())
    return "ok"


init_db()
