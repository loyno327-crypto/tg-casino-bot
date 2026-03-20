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


def db_connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = db_connect()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        telegram_id TEXT UNIQUE,
        username TEXT,
        first_name TEXT,
        balance INTEGER DEFAULT 1000,
        games_played INTEGER DEFAULT 0,
        wins INTEGER DEFAULT 0,
        losses INTEGER DEFAULT 0,
        earned_math INTEGER DEFAULT 0,
        created_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS sessions (
        telegram_id TEXT PRIMARY KEY,
        state TEXT,
        payload TEXT,
        updated_at TEXT
    )
    """)

    conn.commit()
    conn.close()


def get_user(telegram_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM users WHERE telegram_id = ?", (str(telegram_id),))
    user = cur.fetchone()
    conn.close()
    return user


def create_user(telegram_id, username, first_name):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    INSERT OR IGNORE INTO users (telegram_id, username, first_name, balance, created_at)
    VALUES (?, ?, ?, ?, ?)
    """, (
        str(telegram_id),
        username or "",
        first_name or "",
        1000,
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def update_balance(telegram_id, amount):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users
    SET balance = balance + ?
    WHERE telegram_id = ?
    """, (amount, str(telegram_id)))
    conn.commit()
    conn.close()


def update_stats_after_game(telegram_id, win, delta):
    conn = db_connect()
    cur = conn.cursor()

    if win:
        cur.execute("""
        UPDATE users
        SET games_played = games_played + 1,
            wins = wins + 1,
            balance = balance + ?
        WHERE telegram_id = ?
        """, (delta, str(telegram_id)))
    else:
        cur.execute("""
        UPDATE users
        SET games_played = games_played + 1,
            losses = losses + 1,
            balance = balance + ?
        WHERE telegram_id = ?
        """, (delta, str(telegram_id)))

    conn.commit()
    conn.close()


def add_math_reward(telegram_id, reward):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    UPDATE users
    SET balance = balance + ?,
        earned_math = earned_math + ?
    WHERE telegram_id = ?
    """, (reward, reward, str(telegram_id)))
    conn.commit()
    conn.close()


def set_session(telegram_id, state, payload=""):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    INSERT INTO sessions (telegram_id, state, payload, updated_at)
    VALUES (?, ?, ?, ?)
    ON CONFLICT(telegram_id) DO UPDATE SET
        state=excluded.state,
        payload=excluded.payload,
        updated_at=excluded.updated_at
    """, (
        str(telegram_id),
        state,
        payload,
        datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    ))
    conn.commit()
    conn.close()


def get_session(telegram_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("SELECT * FROM sessions WHERE telegram_id = ?", (str(telegram_id),))
    session = cur.fetchone()
    conn.close()
    return session


def clear_session(telegram_id):
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("DELETE FROM sessions WHERE telegram_id = ?", (str(telegram_id),))
    conn.commit()
    conn.close()


def send_message(chat_id, text, keyboard=None):
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
            ["Заработать", "Статистика"],
            ["Топ"]
        ],
        "resize_keyboard": True
    }


def games_menu():
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
            ["Решить пример"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


def slot_bet_menu():
    return {
        "keyboard": [
            ["10", "50", "100"],
            ["Назад"]
        ],
        "resize_keyboard": True
    }


def ensure_user(user_data):
    telegram_id = user_data["id"]
    username = user_data.get("username", "")
    first_name = user_data.get("first_name", "Player")

    if not get_user(telegram_id):
        create_user(telegram_id, username, first_name)


def format_balance(user):
    return (
        f"Игрок: {user['first_name']}\n"
        f"Баланс: {user['balance']} монет"
    )


def format_stats(user):
    return (
        f"Игрок: {user['first_name']}\n"
        f"Баланс: {user['balance']} монет\n"
        f"Игр сыграно: {user['games_played']}\n"
        f"Побед: {user['wins']}\n"
        f"Поражений: {user['losses']}\n"
        f"Заработано на примерах: {user['earned_math']} монет"
    )


def get_top_players():
    conn = db_connect()
    cur = conn.cursor()
    cur.execute("""
    SELECT first_name, balance
    FROM users
    ORDER BY balance DESC, id ASC
    LIMIT 10
    """)
    rows = cur.fetchall()
    conn.close()
    return rows


def play_slot(telegram_id, bet):
    user = get_user(telegram_id)
    if not user:
        return "Сначала нажми /start"

    if user["balance"] < bet:
        return "Недостаточно монет для такой ставки."

    symbols = ["🍒", "🍋", "⭐", "💎", "7️⃣"]
    result = [random.choice(symbols) for _ in range(3)]

    counts = {}
    for s in result:
        counts[s] = counts.get(s, 0) + 1

    max_count = max(counts.values())

    if max_count == 3:
        win_amount = bet * 5
        delta = win_amount - bet
        update_stats_after_game(telegram_id, True, delta)
        return (
            f"{' '.join(result)}\n"
            f"Джекпот! x5\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{delta}"
        )

    if max_count == 2:
        win_amount = bet * 2
        delta = win_amount - bet
        update_stats_after_game(telegram_id, True, delta)
        return (
            f"{' '.join(result)}\n"
            f"Есть пара! x2\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{delta}"
        )

    delta = -bet
    update_stats_after_game(telegram_id, False, delta)
    return (
        f"{' '.join(result)}\n"
        f"Не повезло.\n"
        f"Ставка: {bet}\n"
        f"Итог: {delta}"
    )


def create_math_task():
    a = random.randint(1, 30)
    b = random.randint(1, 30)
    op = random.choice(["+", "-", "*"])

    if op == "+":
        answer = a + b
    elif op == "-":
        answer = a - b
    else:
        answer = a * b

    question = f"{a} {op} {b}"
    return question, answer


@app.route("/", methods=["GET"])
def health():
    return "ok", 200


@app.route("/", methods=["POST"])
def webhook():
    data = request.get_json(silent=True) or {}

    if "message" not in data:
        return "ok", 200

    message = data["message"]
    chat_id = message["chat"]["id"]
    text = message.get("text", "").strip()
    user_data = message["from"]

    ensure_user(user_data)
    telegram_id = user_data["id"]

    session = get_session(telegram_id)
    user = get_user(telegram_id)

    if text == "/start":
        clear_session(telegram_id)
        send_message(
            chat_id,
            f"Привет, {user['first_name']}!\nТвой стартовый баланс: {user['balance']} монет.",
            main_menu()
        )
        return "ok", 200

    if text == "Назад":
        clear_session(telegram_id)
        send_message(chat_id, "Главное меню:", main_menu())
        return "ok", 200

    if text == "Баланс":
        send_message(chat_id, format_balance(user), main_menu())
        return "ok", 200

    if text == "Статистика":
        send_message(chat_id, format_stats(user), main_menu())
        return "ok", 200

    if text == "Топ":
        rows = get_top_players()
        if not rows:
            send_message(chat_id, "Пока нет игроков.", main_menu())
            return "ok", 200

        result = "Топ игроков:\n\n"
        for i, row in enumerate(rows, start=1):
            result += f"{i}. {row['first_name']} — {row['balance']} монет\n"

        send_message(chat_id, result.strip(), main_menu())
        return "ok", 200

    if text == "Играть":
        send_message(chat_id, "Выбери игру:", games_menu())
        return "ok", 200

    if text == "Слот":
        send_message(chat_id, "Выбери ставку:", slot_bet_menu())
        return "ok", 200

    if text in ["10", "50", "100"]:
        bet = int(text)
        result = play_slot(telegram_id, bet)
        updated_user = get_user(telegram_id)
        send_message(
            chat_id,
            f"{result}\n\nТекущий баланс: {updated_user['balance']} монет",
            games_menu()
        )
        return "ok", 200

    if text == "Заработать":
        send_message(chat_id, "Выбери способ:", earn_menu())
        return "ok", 200

    if text == "Решить пример":
        question, answer = create_math_task()
        set_session(telegram_id, "math_wait_answer", str(answer))
        send_message(
            chat_id,
            f"Реши пример:\n{question}\n\nНаграда за правильный ответ: 10 монет",
            earn_menu()
        )
        return "ok", 200

    if session and session["state"] == "math_wait_answer":
        correct_answer = session["payload"]

        if text == correct_answer:
            add_math_reward(telegram_id, 10)
            clear_session(telegram_id)
            updated_user = get_user(telegram_id)
            send_message(
                chat_id,
                f"Верно! +10 монет\nТекущий баланс: {updated_user['balance']} монет",
                earn_menu()
            )
            return "ok", 200
        else:
            clear_session(telegram_id)
            send_message(
                chat_id,
                f"Неверно. Правильный ответ: {correct_answer}",
                earn_menu()
            )
            return "ok", 200

    send_message(chat_id, "Выбери действие в меню.", main_menu())
    return "ok", 200


init_db()
