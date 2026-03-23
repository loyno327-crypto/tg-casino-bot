from flask import Flask, request
import datetime
import json
import os
import random
import sqlite3
import string
import traceback

import requests
from supabase import Client, create_client

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN") or os.environ.get("TOKEN")
if not TOKEN:
    raise RuntimeError("Set TELEGRAM_BOT_TOKEN or TOKEN environment variable")

BASE_URL = f"https://api.telegram.org/bot{TOKEN}"
WEBHOOK_URL = os.environ.get("TELEGRAM_WEBHOOK_URL", "").strip()


def resolve_db_path():
    explicit_path = (os.environ.get("BOT_DB_PATH") or "").strip()
    if explicit_path:
        return explicit_path
    persistent_dir = "/var/data"
    if os.path.isdir(persistent_dir) or os.access(os.path.dirname(persistent_dir) or "/", os.W_OK):
        return os.path.join(persistent_dir, "bot.db")
    return "bot.db"


DB_PATH = resolve_db_path()
SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").strip()
SUPABASE_KEY = (os.environ.get("SUPABASE_KEY") or "").strip()
SUPABASE_USERS_TABLE = (os.environ.get("SUPABASE_USERS_TABLE") or "users").strip()
SUPABASE_CLIENT = create_client(SUPABASE_URL, SUPABASE_KEY) if SUPABASE_URL and SUPABASE_KEY else None

app = Flask(__name__)


# ---------------- DB ----------------
def db():
    db_dir = os.path.dirname(DB_PATH)
    if db_dir:
        os.makedirs(db_dir, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA synchronous=NORMAL")
    conn.execute("PRAGMA busy_timeout = 30000")
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


def using_supabase_user_store():
    return SUPABASE_CLIENT is not None


def supabase_table():
    return SUPABASE_CLIENT.table(SUPABASE_USERS_TABLE)


def normalize_user_record(record):
    if not record:
        return None
    return {
        "telegram_id": int(record["telegram_id"]),
        "first_name": record.get("name") or "Игрок",
        "name": record.get("name") or "Игрок",
        "player_code": record.get("player_code") or "",
        "balance": int(record.get("balance") or 700),
        "wins": int(record.get("wins_games") or 0),
        "losses": int(record.get("losses_games") or 0),
        "wins_games": int(record.get("wins_games") or 0),
        "losses_games": int(record.get("losses_games") or 0),
        "battles_won": int(record.get("wins_battles") or 0),
        "battles_lost": int(record.get("losses_battles") or 0),
        "wins_battles": int(record.get("wins_battles") or 0),
        "losses_battles": int(record.get("losses_battles") or 0),
        "created_at": record.get("created_at"),
    }


def generate_player_code(length=6):
    alphabet = string.ascii_uppercase + string.digits
    while True:
        code = "".join(random.choice(alphabet) for _ in range(length))
        if using_supabase_user_store():
            response = supabase_table().select("telegram_id").eq("player_code", code).limit(1).execute()
            exists = bool(response.data)
        else:
            conn = db()
            exists = conn.execute("SELECT 1 FROM users WHERE player_code = ?", (code,)).fetchone()
            conn.close()
        if not exists:
            return code


def init_db():
    conn = db()
    cur = conn.cursor()

    cur.execute("""
    CREATE TABLE IF NOT EXISTS users (
        telegram_id INTEGER PRIMARY KEY,
        name TEXT,
        player_code TEXT,
        balance INTEGER DEFAULT 700,
        wins_games INTEGER DEFAULT 0,
        losses_games INTEGER DEFAULT 0,
        wins_battles INTEGER DEFAULT 0,
        losses_battles INTEGER DEFAULT 0,
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
        challenger_item_rarity TEXT,
        challenger_item_price INTEGER,
        opponent_item_name TEXT,
        opponent_item_rarity TEXT,
        opponent_item_price INTEGER,
        winner_id TEXT,
        created_at TEXT,
        resolved_at TEXT
    )
    """)

    cur.execute("""
    CREATE TABLE IF NOT EXISTS friends (
        user_id TEXT,
        friend_id TEXT,
        created_at TEXT,
        PRIMARY KEY (user_id, friend_id)
    )
    """)

    conn.commit()
    conn.close()

    ensure_column("users", "name", "TEXT")
    ensure_column("users", "player_code", "TEXT")
    ensure_column("users", "balance", "INTEGER DEFAULT 700")
    ensure_column("users", "wins_games", "INTEGER DEFAULT 0")
    ensure_column("users", "losses_games", "INTEGER DEFAULT 0")
    ensure_column("users", "wins_battles", "INTEGER DEFAULT 0")
    ensure_column("users", "losses_battles", "INTEGER DEFAULT 0")
    ensure_column("users", "created_at", "TEXT")
    ensure_column("users", "first_name", "TEXT")
    ensure_column("users", "wins", "INTEGER DEFAULT 0")
    ensure_column("users", "losses", "INTEGER DEFAULT 0")
    ensure_column("users", "battles_won", "INTEGER DEFAULT 0")
    ensure_column("users", "battles_lost", "INTEGER DEFAULT 0")
    ensure_column("users", "last_deposit_at", "TEXT")
    ensure_column("battles", "challenger_item_rarity", "TEXT")
    ensure_column("battles", "opponent_item_rarity", "TEXT")

    conn = db()
    conn.execute("UPDATE users SET name = COALESCE(name, first_name)")
    conn.execute("UPDATE users SET first_name = COALESCE(first_name, name)")
    conn.execute("UPDATE users SET wins_games = COALESCE(wins_games, wins, 0)")
    conn.execute("UPDATE users SET losses_games = COALESCE(losses_games, losses, 0)")
    conn.execute("UPDATE users SET wins_battles = COALESCE(wins_battles, battles_won, 0)")
    conn.execute("UPDATE users SET losses_battles = COALESCE(losses_battles, battles_lost, 0)")
    conn.execute("UPDATE users SET balance = COALESCE(balance, 700)")
    rows = conn.execute("SELECT telegram_id FROM users WHERE player_code IS NULL OR player_code = ''").fetchall()
    for row in rows:
        conn.execute(
            "UPDATE users SET player_code = ? WHERE telegram_id = ?",
            (generate_player_code(), row["telegram_id"]),
        )
    conn.commit()
    conn.close()


# ---------------- CASE DATA ----------------
CASES = {
    "Fracture Case": {
        "price": 200,
        "items": [
            {"name": "Glock-18 | Bunsen Burner", "rarity": "Consumer", "price": 80, "chance": 18},
            {"name": "MAC-10 | Allure", "rarity": "Consumer", "price": 95, "chance": 16},
            {"name": "Tec-9 | Brother", "rarity": "Industrial", "price": 130, "chance": 14},
            {"name": "SG 553 | Ol' Rusty", "rarity": "Industrial", "price": 150, "chance": 12},
            {"name": "P2000 | Gnarled", "rarity": "Mil-Spec", "price": 220, "chance": 11},
            {"name": "Galil AR | Connexion", "rarity": "Mil-Spec", "price": 270, "chance": 9},
            {"name": "AK-47 | Legion of Anubis", "rarity": "Restricted", "price": 650, "chance": 8},
            {"name": "M4A4 | Tooth Fairy", "rarity": "Classified", "price": 1400, "chance": 6},
            {"name": "Desert Eagle | Printstream", "rarity": "Covert", "price": 4000, "chance": 4},
            {"name": "★ Butterfly Knife | Fade", "rarity": "Knife", "price": 25000, "chance": 2},
        ],
    },
    "Danger Case": {
        "price": 350,
        "items": [
            {"name": "UMP-45 | Carbon Fiber", "rarity": "Consumer", "price": 120, "chance": 18},
            {"name": "P250 | Nevermore", "rarity": "Consumer", "price": 140, "chance": 15},
            {"name": "P250 | Supernova", "rarity": "Industrial", "price": 180, "chance": 14},
            {"name": "G3SG1 | Scavenger", "rarity": "Industrial", "price": 210, "chance": 12},
            {"name": "AWP | Atheris", "rarity": "Mil-Spec", "price": 450, "chance": 11},
            {"name": "MP9 | Modest Threat", "rarity": "Mil-Spec", "price": 520, "chance": 9},
            {"name": "AK-47 | Slate", "rarity": "Restricted", "price": 950, "chance": 8},
            {"name": "USP-S | Neo-Noir", "rarity": "Classified", "price": 2200, "chance": 6},
            {"name": "M4A1-S | Printstream", "rarity": "Covert", "price": 6500, "chance": 5},
            {"name": "★ Karambit | Doppler", "rarity": "Knife", "price": 42000, "chance": 2},
        ],
    },
    "Recoil Case": {
        "price": 500,
        "items": [
            {"name": "FAMAS | Meow 36", "rarity": "Consumer", "price": 180, "chance": 22.5},
            {"name": "Galil AR | Destroyer", "rarity": "Consumer", "price": 220, "chance": 20},
            {"name": "MAC-10 | Monkeyflage", "rarity": "Industrial", "price": 260, "chance": 17},
            {"name": "R8 Revolver | Crazy 8", "rarity": "Industrial", "price": 320, "chance": 14},
            {"name": "M4A4 | Poly Mag", "rarity": "Mil-Spec", "price": 520, "chance": 10},
            {"name": "AWP | Chromatic Aberration", "rarity": "Restricted", "price": 1200, "chance": 7},
            {"name": "USP-S | Printstream", "rarity": "Classified", "price": 3500, "chance": 5},
            {"name": "★ Ursus Knife | Tiger Tooth", "rarity": "Knife", "price": 28000, "chance": 4.3},
            {"name": "★ Butterfly Knife | Lore", "rarity": "Knife", "price": 120000, "chance": 0.1},
        ],
    },
    "Prisma Case": {
        "price": 700,
        "items": [
            {"name": "MP5-SD | Acid Wash", "rarity": "Consumer", "price": 220, "chance": 21},
            {"name": "AUG | Sweeper", "rarity": "Consumer", "price": 250, "chance": 18},
            {"name": "XM1014 | Incinegator", "rarity": "Industrial", "price": 330, "chance": 16},
            {"name": "R8 Revolver | Skull Crusher", "rarity": "Industrial", "price": 420, "chance": 14},
            {"name": "P250 | Visions", "rarity": "Mil-Spec", "price": 650, "chance": 11},
            {"name": "M4A1-S | Decimator", "rarity": "Restricted", "price": 1650, "chance": 8},
            {"name": "AK-47 | Neon Rider", "rarity": "Classified", "price": 4200, "chance": 6},
            {"name": "★ Talon Knife | Fade", "rarity": "Knife", "price": 44000, "chance": 5.9},
            {"name": "★ Karambit | Marble Fade", "rarity": "Knife", "price": 150000, "chance": 0.1},
        ],
    },
    "Gamma 2 Case": {
        "price": 1000,
        "items": [
            {"name": "Five-SeveN | Scumbria", "rarity": "Consumer", "price": 280, "chance": 22},
            {"name": "SCAR-20 | Powercore", "rarity": "Consumer", "price": 320, "chance": 18},
            {"name": "P90 | Chopper", "rarity": "Industrial", "price": 420, "chance": 16},
            {"name": "Tec-9 | Fuel Injector", "rarity": "Industrial", "price": 540, "chance": 13},
            {"name": "AK-47 | Orbit Mk01", "rarity": "Mil-Spec", "price": 850, "chance": 12},
            {"name": "M4A1-S | Mecha Industries", "rarity": "Restricted", "price": 2100, "chance": 8},
            {"name": "FAMAS | Roll Cage", "rarity": "Classified", "price": 5200, "chance": 6},
            {"name": "★ Flip Knife | Gamma Doppler", "rarity": "Knife", "price": 52000, "chance": 4.9},
            {"name": "★ M9 Bayonet | Lore", "rarity": "Knife", "price": 175000, "chance": 0.1},
        ],
    },
    "Chroma 3 Case": {
        "price": 1500,
        "items": [
            {"name": "PP-Bizon | Judgement of Anubis", "rarity": "Consumer", "price": 350, "chance": 21},
            {"name": "SG 553 | Atlas", "rarity": "Consumer", "price": 390, "chance": 18},
            {"name": "Glock-18 | Weasel", "rarity": "Industrial", "price": 520, "chance": 16},
            {"name": "CZ75-Auto | Red Astor", "rarity": "Industrial", "price": 680, "chance": 14},
            {"name": "M4A1-S | Chantico's Fire", "rarity": "Mil-Spec", "price": 1200, "chance": 11},
            {"name": "AWP | Fever Dream", "rarity": "Restricted", "price": 2600, "chance": 8},
            {"name": "USP-S | Kill Confirmed", "rarity": "Classified", "price": 6800, "chance": 6},
            {"name": "★ Bayonet | Doppler", "rarity": "Knife", "price": 64000, "chance": 5.9},
            {"name": "★ Skeleton Knife | Fade", "rarity": "Knife", "price": 210000, "chance": 0.1},
        ],
    },
    "Dreams & Nightmares Case": {
        "price": 2500,
        "items": [
            {"name": "MP7 | Abyssal Apparition", "rarity": "Consumer", "price": 480, "chance": 21},
            {"name": "Dual Berettas | Melondrama", "rarity": "Consumer", "price": 520, "chance": 18},
            {"name": "FAMAS | Rapid Eye Movement", "rarity": "Industrial", "price": 740, "chance": 16},
            {"name": "XM1014 | Zombie Offensive", "rarity": "Industrial", "price": 920, "chance": 13},
            {"name": "USP-S | Ticket to Hell", "rarity": "Mil-Spec", "price": 1500, "chance": 11},
            {"name": "AK-47 | Nightwish", "rarity": "Restricted", "price": 3400, "chance": 8},
            {"name": "MP9 | Starlight Protector", "rarity": "Classified", "price": 8200, "chance": 7},
            {"name": "★ Huntsman Knife | Gamma Doppler", "rarity": "Knife", "price": 76000, "chance": 5.8},
            {"name": "★ Karambit | Gamma Doppler Emerald", "rarity": "Knife", "price": 350000, "chance": 0.1},
        ],
    },
}

RARITY_EMOJI = {
    "Consumer": "⚪",
    "Industrial": "🔵",
    "Mil-Spec": "🟦",
    "Restricted": "🟪",
    "Classified": "🩷",
    "Covert": "🔴",
    "Knife": "🟡",
    "Legendary": "✨",
}

EXTRA_SKINS = [
    {"name": "Five-SeveN | Violent Daimyo", "rarity": "Consumer", "price": 70, "case": "Workshop"},
    {"name": "Nova | Exo", "rarity": "Consumer", "price": 85, "case": "Workshop"},
    {"name": "MP7 | Cirrus", "rarity": "Consumer", "price": 90, "case": "Workshop"},
    {"name": "P90 | Grim", "rarity": "Industrial", "price": 110, "case": "Workshop"},
    {"name": "UMP-45 | Exposure", "rarity": "Industrial", "price": 160, "case": "Workshop"},
    {"name": "FAMAS | Mecha Industries", "rarity": "Industrial", "price": 210, "case": "Workshop"},
    {"name": "CZ75-Auto | Xiangliu", "rarity": "Mil-Spec", "price": 260, "case": "Workshop"},
    {"name": "MP9 | Mount Fuji", "rarity": "Mil-Spec", "price": 320, "case": "Workshop"},
    {"name": "AUG | Syd Mead", "rarity": "Mil-Spec", "price": 380, "case": "Workshop"},
    {"name": "Glock-18 | Vogue", "rarity": "Restricted", "price": 480, "case": "Workshop"},
    {"name": "M4A4 | Cyber Security", "rarity": "Restricted", "price": 780, "case": "Workshop"},
    {"name": "AK-47 | Ice Coaled", "rarity": "Restricted", "price": 980, "case": "Workshop"},
    {"name": "USP-S | Monster Mashup", "rarity": "Classified", "price": 1450, "case": "Workshop"},
    {"name": "AWP | Chromatic Aberration", "rarity": "Classified", "price": 1800, "case": "Workshop"},
    {"name": "Desert Eagle | Code Red", "rarity": "Classified", "price": 2300, "case": "Workshop"},
    {"name": "AK-47 | Nightwish", "rarity": "Covert", "price": 3100, "case": "Workshop"},
    {"name": "M4A1-S | Player Two", "rarity": "Covert", "price": 4200, "case": "Workshop"},
    {"name": "AWP | Asiimov", "rarity": "Covert", "price": 6900, "case": "Workshop"},
    {"name": "★ Talon Knife | Marble Fade", "rarity": "Knife", "price": 18000, "case": "Workshop"},
    {"name": "★ Skeleton Knife | Crimson Web", "rarity": "Knife", "price": 27000, "case": "Workshop"},
    {"name": "★ M9 Bayonet | Gamma Doppler", "rarity": "Knife", "price": 38000, "case": "Workshop"},
    {"name": "Dragon Lore Replica", "rarity": "Legendary", "price": 52000, "case": "Collectors"},
    {"name": "Howl Legacy", "rarity": "Legendary", "price": 76000, "case": "Collectors"},
    {"name": "Karambit | Ruby Dream", "rarity": "Legendary", "price": 98000, "case": "Collectors"},
]

SKINS_DATA = [
    {"name": item["name"], "rarity": item["rarity"], "price": item["price"], "case": case_name}
    for case_name, case_data in CASES.items()
    for item in case_data["items"]
] + EXTRA_SKINS

UPGRADE_OPTIONS = {"5%": 5, "10%": 10, "20%": 20, "30%": 30, "50%": 50}
ACTIVE_BATTLE_STATUSES = ("pending", "accepted")

SLOT_SYMBOLS = [
    {"symbol": "🍒", "weight": 18},
    {"symbol": "🍋", "weight": 16},
    {"symbol": "🍇", "weight": 14},
    {"symbol": "🔔", "weight": 12},
    {"symbol": "⭐", "weight": 10},
    {"symbol": "💎", "weight": 8},
    {"symbol": "7️⃣", "weight": 6},
    {"symbol": "👑", "weight": 5},
    {"symbol": "🔥", "weight": 4},
    {"symbol": "🃏", "weight": 3},
    {"symbol": "🎯", "weight": 2},
    {"symbol": "⚡", "weight": 2},
]

SPECIAL_SLOT_MULTIPLIERS = {
    "7️⃣": 8,
    "💎": 7,
    "👑": 9,
    "🔥": 10,
    "🃏": 12,
    "🎯": 14,
    "⚡": 15,
}


# ---------------- USER ----------------
def user_select_sql():
    return """
        SELECT
            telegram_id,
            COALESCE(name, first_name) AS first_name,
            COALESCE(name, first_name) AS name,
            player_code,
            COALESCE(balance, 700) AS balance,
            COALESCE(wins_games, wins, 0) AS wins,
            COALESCE(losses_games, losses, 0) AS losses,
            COALESCE(wins_games, wins, 0) AS wins_games,
            COALESCE(losses_games, losses, 0) AS losses_games,
            COALESCE(wins_battles, battles_won, 0) AS battles_won,
            COALESCE(losses_battles, battles_lost, 0) AS battles_lost,
            COALESCE(wins_battles, battles_won, 0) AS wins_battles,
            COALESCE(losses_battles, battles_lost, 0) AS losses_battles,
            created_at
        FROM users
    """


def get_or_create_user(telegram_id, name):
    telegram_id = int(telegram_id)
    name = name or "Игрок"

    if using_supabase_user_store():
        response = supabase_table().select("*").eq("telegram_id", telegram_id).limit(1).execute()
        if response.data:
            existing = response.data[0]
            if name and existing.get("name") != name:
                supabase_table().update({"name": name}).eq("telegram_id", telegram_id).execute()
                existing["name"] = name
            return normalize_user_record(existing)

        payload = {
            "telegram_id": telegram_id,
            "name": name,
            "player_code": generate_player_code(),
            "balance": 700,
            "wins_games": 0,
            "losses_games": 0,
            "wins_battles": 0,
            "losses_battles": 0,
        }
        response = supabase_table().insert(payload).execute()
        return normalize_user_record(response.data[0])

    conn = db()
    existing = conn.execute(user_select_sql() + " WHERE telegram_id = ?", (telegram_id,)).fetchone()
    if existing:
        conn.execute(
            "UPDATE users SET name = COALESCE(?, name), first_name = COALESCE(?, first_name) WHERE telegram_id = ?",
            (name, name, telegram_id),
        )
        conn.commit()
        user = conn.execute(user_select_sql() + " WHERE telegram_id = ?", (telegram_id,)).fetchone()
        conn.close()
        return user

    conn.execute(
        """
        INSERT INTO users (
            telegram_id, name, first_name, player_code, balance,
            wins_games, losses_games, wins_battles, losses_battles, created_at,
            wins, losses, battles_won, battles_lost
        )
        VALUES (?, ?, ?, ?, 700, 0, 0, 0, 0, ?, 0, 0, 0, 0)
        """,
        (
            telegram_id,
            name,
            name,
            generate_player_code(),
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        ),
    )
    conn.commit()
    user = conn.execute(user_select_sql() + " WHERE telegram_id = ?", (telegram_id,)).fetchone()
    conn.close()
    return user


def get_user(tid):
    tid = int(tid)
    if using_supabase_user_store():
        response = supabase_table().select("*").eq("telegram_id", tid).limit(1).execute()
        return normalize_user_record(response.data[0]) if response.data else None
    conn = db()
    user = conn.execute(user_select_sql() + " WHERE telegram_id = ?", (tid,)).fetchone()
    conn.close()
    return user


def get_user_by_code(player_code):
    code = (player_code or "").upper()
    if using_supabase_user_store():
        response = supabase_table().select("*").eq("player_code", code).limit(1).execute()
        return normalize_user_record(response.data[0]) if response.data else None
    conn = db()
    user = conn.execute(user_select_sql() + " WHERE player_code = ?", (code,)).fetchone()
    conn.close()
    return user


def get_user_stats(telegram_id):
    return get_user(telegram_id)


def search_players(query, exclude_tid=None, limit=8):
    query = (query or "").strip()
    exclude_tid = int(exclude_tid) if exclude_tid is not None else None
    like_query = query.lower()

    if using_supabase_user_store():
        response = supabase_table().select("*").limit(limit).execute()
        rows = [normalize_user_record(item) for item in response.data]
        filtered = []
        for row in rows:
            if exclude_tid is not None and row["telegram_id"] == exclude_tid:
                continue
            if not query or like_query in (row["first_name"] or "").lower() or like_query in (row["player_code"] or "").lower() or str(row["telegram_id"]) == query:
                filtered.append(row)
        return filtered[:limit]

    conn = db()
    like_sql = f"%{like_query}%"
    if query.isdigit():
        rows = conn.execute(
            user_select_sql() +
            """
             WHERE telegram_id = ? AND (? IS NULL OR telegram_id != ?)
             LIMIT ?
            """,
            (int(query), exclude_tid, exclude_tid, limit),
        ).fetchall()
        if rows:
            conn.close()
            return rows

    rows = conn.execute(
        user_select_sql() +
        """
        WHERE (? IS NULL OR telegram_id != ?)
          AND (
            LOWER(COALESCE(name, first_name, '')) LIKE ?
            OR LOWER(player_code) LIKE ?
            OR CAST(telegram_id AS TEXT) = ?
          )
        ORDER BY COALESCE(name, first_name) COLLATE NOCASE ASC
        LIMIT ?
        """,
        (exclude_tid, exclude_tid, like_sql, like_sql, query, limit),
    ).fetchall()
    conn.close()
    return rows


def create_user(tid, name):
    return get_or_create_user(tid, name)


def update_balance(telegram_id, balance):
    telegram_id = int(telegram_id)
    balance = int(balance)
    if using_supabase_user_store():
        supabase_table().update({"balance": balance}).eq("telegram_id", telegram_id).execute()
        return
    conn = db()
    conn.execute("UPDATE users SET balance = ?, first_name = COALESCE(first_name, name), name = COALESCE(name, first_name) WHERE telegram_id = ?", (balance, telegram_id))
    conn.commit()
    conn.close()


def adjust_balance(telegram_id, delta):
    user = get_or_create_user(telegram_id, "Игрок")
    update_balance(telegram_id, user["balance"] + delta)


def increment_game_win(telegram_id):
    telegram_id = int(telegram_id)
    if using_supabase_user_store():
        user = get_or_create_user(telegram_id, "Игрок")
        supabase_table().update({"wins_games": user["wins_games"] + 1}).eq("telegram_id", telegram_id).execute()
        return
    conn = db()
    conn.execute(
        "UPDATE users SET wins_games = COALESCE(wins_games, 0) + 1, wins = COALESCE(wins, 0) + 1 WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()
    conn.close()


def increment_game_loss(telegram_id):
    telegram_id = int(telegram_id)
    if using_supabase_user_store():
        user = get_or_create_user(telegram_id, "Игрок")
        supabase_table().update({"losses_games": user["losses_games"] + 1}).eq("telegram_id", telegram_id).execute()
        return
    conn = db()
    conn.execute(
        "UPDATE users SET losses_games = COALESCE(losses_games, 0) + 1, losses = COALESCE(losses, 0) + 1 WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()
    conn.close()


def increment_battle_win(telegram_id):
    telegram_id = int(telegram_id)
    if using_supabase_user_store():
        user = get_or_create_user(telegram_id, "Игрок")
        supabase_table().update({"wins_battles": user["wins_battles"] + 1}).eq("telegram_id", telegram_id).execute()
        return
    conn = db()
    conn.execute(
        "UPDATE users SET wins_battles = COALESCE(wins_battles, 0) + 1, battles_won = COALESCE(battles_won, 0) + 1 WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()
    conn.close()


def increment_battle_loss(telegram_id):
    telegram_id = int(telegram_id)
    if using_supabase_user_store():
        user = get_or_create_user(telegram_id, "Игрок")
        supabase_table().update({"losses_battles": user["losses_battles"] + 1}).eq("telegram_id", telegram_id).execute()
        return
    conn = db()
    conn.execute(
        "UPDATE users SET losses_battles = COALESCE(losses_battles, 0) + 1, battles_lost = COALESCE(battles_lost, 0) + 1 WHERE telegram_id = ?",
        (telegram_id,),
    )
    conn.commit()
    conn.close()


def add_win(tid):
    increment_game_win(tid)


def add_loss(tid):
    increment_game_loss(tid)


def add_battle_result(tid, won):
    if won:
        increment_battle_win(tid)
    else:
        increment_battle_loss(tid)


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
        (str(tid), state, payload_json),
    )
    conn.commit()
    conn.close()


def get_session(tid):
    conn = db()
    session = conn.execute("SELECT * FROM sessions WHERE telegram_id = ?", (str(tid),)).fetchone()
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
        ),
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
        ),
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
        (str(tid), limit),
    ).fetchall()
    conn.close()
    return rows


def get_inventory_item(tid, inventory_id):
    conn = db()
    row = conn.execute("SELECT * FROM inventory WHERE telegram_id = ? AND id = ?", (str(tid), inventory_id)).fetchone()
    conn.close()
    return row


def sell_item(tid, item_id):
    conn = db()
    row = conn.execute(
        "SELECT id, price, skin_name FROM inventory WHERE telegram_id = ? AND id = ?",
        (str(tid), item_id),
    ).fetchone()
    if not row:
        conn.close()
        return False, "❌ Предмет не найден."
    conn.execute("DELETE FROM inventory WHERE id = ?", (item_id,))
    conn.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (row["price"], str(tid)))
    conn.commit()
    conn.close()
    return True, f"💸 Продано: {row['skin_name']}\nПолучено: {row['price']} монет"


def inventory_action_menu(rows):
    keyboard = [["Продать всё", "Обновить инвентарь"]]
    for row in rows[:10]:
        keyboard.append([f"Продать #{row['id']}", f"Апгрейд #{row['id']}"])
    keyboard.append(["Главное меню"])
    return {"keyboard": keyboard, "resize_keyboard": True}


def format_inventory(rows):
    if not rows:
        return "🎒 Инвентарь пуст."
    lines = ["🎒 Твой инвентарь:", ""]
    for row in rows:
        emoji = RARITY_EMOJI.get(row["rarity"], "▫️")
        lines.append(f"#{row['id']} | {emoji} {row['skin_name']}")
        lines.append(f"{row['rarity']} | {row['price']} монет")
        lines.append(f"Источник: {row['case_name']}")
        lines.append("")
    lines.append("Ниже есть кнопки «Продать #ID» и «Апгрейд #ID»." )
    return "\n".join(lines).strip()


def roll_case(case_name):
    case = CASES.get(case_name)
    if not case:
        return None
    weights = [item["chance"] for item in case["items"]]
    return random.choices(case["items"], weights=weights, k=1)[0]


def open_case(tid, case_name):
    user = get_user(tid)
    case = CASES.get(case_name)
    if not case:
        return None, "❌ Кейс не найден."
    if user["balance"] < case["price"]:
        return None, "❌ Недостаточно монет для открытия кейса."
    adjust_balance(tid, -case["price"])
    item = roll_case(case_name)
    if not item:
        adjust_balance(tid, case["price"])
        return None, "❌ Ошибка открытия кейса."
    add_item_to_inventory(tid, item, case_name)
    add_case_history(tid, item, case_name)
    updated = get_user(tid)
    emoji = RARITY_EMOJI.get(item["rarity"], "▫️")
    return item, (
        f"📦 {case_name}\n\n"
        f"🎉 Тебе выпало:\n"
        f"{emoji} {item['name']}\n"
        f"Редкость: {item['rarity']}\n"
        f"Цена: {item['price']} монет\n\n"
        f"💰 Баланс: {updated['balance']}"
    )


def sell_all_items(tid):
    conn = db()
    rows = conn.execute("SELECT id, price FROM inventory WHERE telegram_id = ?", (str(tid),)).fetchall()
    if not rows:
        conn.close()
        return False, "🎒 Инвентарь пуст."
    total = sum(row["price"] for row in rows)
    count = len(rows)
    conn.execute("DELETE FROM inventory WHERE telegram_id = ?", (str(tid),))
    conn.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (total, str(tid)))
    conn.commit()
    conn.close()
    return True, f"💸 Продано предметов: {count}\nПолучено: {total} монет"


def transfer_balance(sender_id, target_code, amount):
    if amount is None or amount <= 0:
        return False, "❌ Сумма перевода должна быть больше 0."
    sender = get_user(sender_id)
    recipient = get_user_by_code(target_code)
    if not recipient:
        return False, "❌ Игрок с таким кодом не найден."
    if recipient["telegram_id"] == str(sender_id):
        return False, "❌ Нельзя перевести монеты самому себе."
    if sender["balance"] < amount:
        return False, "❌ Недостаточно монет для перевода."

    conn = db()
    conn.execute("UPDATE users SET balance = balance - ? WHERE telegram_id = ?", (amount, str(sender_id)))
    conn.execute("UPDATE users SET balance = balance + ? WHERE telegram_id = ?", (amount, recipient["telegram_id"]))
    conn.commit()
    conn.close()
    return True, recipient


def add_friend(user_id, friend_code):
    user = get_user(user_id)
    friend = get_user_by_code(friend_code)
    if not friend:
        return False, "❌ Игрок с таким кодом не найден."
    if friend["telegram_id"] == str(user_id):
        return False, "❌ Нельзя добавить себя в друзья."
    conn = db()
    conn.execute(
        "INSERT OR IGNORE INTO friends (user_id, friend_id, created_at) VALUES (?, ?, ?)",
        (str(user_id), friend["telegram_id"], datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.execute(
        "INSERT OR IGNORE INTO friends (user_id, friend_id, created_at) VALUES (?, ?, ?)",
        (friend["telegram_id"], str(user_id), datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")),
    )
    conn.commit()
    changes = conn.total_changes
    conn.close()
    if changes == 0:
        return False, f"ℹ️ {friend['first_name']} уже у тебя в друзьях."
    return True, friend


def list_friends(user_id, limit=20):
    conn = db()
    rows = conn.execute(
        """
        SELECT u.telegram_id, u.first_name, u.player_code, u.balance
        FROM friends f
        JOIN users u ON u.telegram_id = f.friend_id
        WHERE f.user_id = ?
        ORDER BY u.first_name COLLATE NOCASE ASC
        LIMIT ?
        """,
        (str(user_id), limit),
    ).fetchall()
    conn.close()
    return rows


def format_friends(rows):
    if not rows:
        return "🤝 У тебя пока нет друзей. Нажми «Добавить друга»."
    lines = ["🤝 Твои друзья:", ""]
    for row in rows:
        lines.append(f"• {row['first_name']} | код {row['player_code']} | баланс {row['balance']}")
    return "\n".join(lines)


def find_active_battle_for_user(user_id):
    conn = db()
    row = conn.execute(
        """
        SELECT * FROM battles
        WHERE (challenger_id = ? OR opponent_id = ?)
          AND status IN ('pending', 'accepted')
        ORDER BY id DESC
        LIMIT 1
        """,
        (str(user_id), str(user_id)),
    ).fetchone()
    conn.close()
    return row


# ---------------- TELEGRAM ----------------
def telegram_api(method, payload):
    return requests.post(f"{BASE_URL}/{method}", json=payload, timeout=20)


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
            ["🎰 Играть", "📦 Кейсы"],
            ["🎒 Инвентарь", "⚔️ Сражения"],
            ["💸 Передать баланс", "🤝 Друзья"],
            ["💰 Баланс", "📊 Статистика"],
            ["🧠 Заработать"],
        ],
        "resize_keyboard": True,
    }


def game_menu():
    return {"keyboard": [["Слот", "Рулетка"], ["Главное меню"]], "resize_keyboard": True}


def bet_menu():
    return {"keyboard": [["10", "50", "100"], ["Своя ставка"], ["Назад"]], "resize_keyboard": True}


def roulette_menu():
    return {"keyboard": [["Красное", "Чёрное"], ["Чёт", "Нечёт"], ["Число"], ["Назад"]], "resize_keyboard": True}


def case_menu():
    return {"keyboard": [
        ["Fracture Case (200)", "Danger Case (350)"],
        ["Recoil Case (500)", "Prisma Case (700)"],
        ["Gamma 2 Case (1000)", "Chroma 3 Case (1500)"],
        ["Dreams & Nightmares Case (2500)"],
        ["Главное меню"],
    ], "resize_keyboard": True}


def earn_menu():
    return {"keyboard": [["Пример"], ["Главное меню"]], "resize_keyboard": True}


def upgrade_percent_menu():
    return {"keyboard": [["5%", "10%", "20%"], ["30%", "50%"], ["Главное меню"]], "resize_keyboard": True}


def battle_menu():
    return {"keyboard": [["Создать сражение", "Мои сражения"], ["Главное меню"]], "resize_keyboard": True}


def battle_case_menu():
    return {"keyboard": [["Fracture Case", "Danger Case"], ["Recoil Case", "Prisma Case"], ["Gamma 2 Case", "Chroma 3 Case"], ["Dreams & Nightmares Case"], ["Главное меню"]], "resize_keyboard": True}


def player_search_results_menu(players):
    keyboard = []
    for player in players[:8]:
        keyboard.append([f"Игрок {player['player_code']} | {player['first_name']}"])
    keyboard.append(["Главное меню"])
    return {"keyboard": keyboard, "resize_keyboard": True}


def answer_options_menu(options):
    keyboard = [[str(option) for option in options[:2]], [str(options[2])], ["Главное меню"]]
    return {"keyboard": keyboard, "resize_keyboard": True}


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
        return int(str(text).strip())
    except Exception:
        return None


def normalize_case_name(text):
    mapping = {
        "Fracture Case (200)": "Fracture Case",
        "Danger Case (350)": "Danger Case",
        "Recoil Case (500)": "Recoil Case",
        "Prisma Case (700)": "Prisma Case",
        "Gamma 2 Case (1000)": "Gamma 2 Case",
        "Chroma 3 Case (1500)": "Chroma 3 Case",
        "Dreams & Nightmares Case (2500)": "Dreams & Nightmares Case",
    }
    return mapping.get(text, text)


def format_stats(user):
    return (
        f"📊 Статистика\n\n"
        f"Имя: {user['first_name']}\n"
        f"Код игрока: {user['player_code']}\n"
        f"Telegram ID: {user['telegram_id']}\n"
        f"Баланс: {user['balance']}\n"
        f"Побед в играх: {user['wins']}\n"
        f"Поражений в играх: {user['losses']}\n"
        f"Побед в сражениях: {user['battles_won']}\n"
        f"Поражений в сражениях: {user['battles_lost']}"
    )


def parse_inventory_action(text, action_word):
    prefix = f"{action_word} #"
    if not text.startswith(prefix):
        return None
    return safe_int(text.split("#", 1)[1])


def format_player_result(player):
    return f"{player['first_name']} | код {player['player_code']} | id {player['telegram_id']}"


def extract_player_code_from_button(text):
    if not text.startswith("Игрок "):
        return None
    parts = text.split()
    return parts[1] if len(parts) >= 2 else None


def parse_battle_action(text, action_label):
    prefix = f"{action_label} #"
    if not text.startswith(prefix):
        return None
    return safe_int(text.split("#", 1)[1])


def weighted_slot_symbol():
    symbols = [item["symbol"] for item in SLOT_SYMBOLS]
    weights = [item["weight"] for item in SLOT_SYMBOLS]
    return random.choices(symbols, weights=weights, k=1)[0]


def build_slot_line(reels):
    return " | ".join(reels)


def get_upgrade_target(from_price, percent):
    ratio_map = {
        5: (8.0, 20.0),
        10: (5.0, 12.0),
        20: (3.0, 7.0),
        30: (2.0, 5.0),
        50: (1.2, 2.8),
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
            f"Ролл: {roll:.2f}"
        )
    else:
        result = (
            f"💥 АПГРЕЙД НЕУДАЧЕН\n\n"
            f"Сгорело: {item['skin_name']} ({item['price']})\n"
            f"Цель была: {target['name']} ({target['price']})\n"
            f"Шанс: {percent}%\n"
            f"Ролл: {roll:.2f}"
        )
    rows = get_inventory(tid)
    return f"{result}\n\n{format_inventory(rows)}"


def create_battle(challenger, opponent, case_name):
    active_challenger = find_active_battle_for_user(challenger["telegram_id"])
    if active_challenger:
        return None, f"❌ У тебя уже есть активное сражение #{active_challenger['id']}. Сначала заверши его."
    active_opponent = find_active_battle_for_user(opponent["telegram_id"])
    if active_opponent:
        return None, f"❌ У соперника уже есть активное сражение #{active_opponent['id']}."

    conn = db()
    cursor = conn.execute(
        """
        INSERT INTO battles (
            challenger_id, challenger_code, opponent_id, opponent_code, case_name, status, created_at
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
        ),
    )
    battle_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return battle_id, None


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
        (str(tid), str(tid), limit),
    ).fetchall()
    conn.close()
    return rows


def battle_action_menu(battle_id):
    return {
        "keyboard": [[f"Принять бой #{battle_id}", f"Отклонить бой #{battle_id}"], ["Главное меню"]],
        "resize_keyboard": True,
    }


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

    winner_id = None
    loser_id = None
    result_title = "🤝 Ничья — каждый получает свой дроп"
    if challenger_item["price"] > opponent_item["price"]:
        winner_id = battle["challenger_id"]
        loser_id = battle["opponent_id"]
        result_title = "🏆 Победил вызывающий игрок"
    elif opponent_item["price"] > challenger_item["price"]:
        winner_id = battle["opponent_id"]
        loser_id = battle["challenger_id"]
        result_title = "🏆 Победил приглашённый игрок"

    if winner_id:
        add_item_to_inventory(winner_id, challenger_item, battle["case_name"])
        add_item_to_inventory(winner_id, opponent_item, battle["case_name"])
        add_battle_result(winner_id, True)
        add_battle_result(loser_id, False)
    else:
        add_item_to_inventory(battle["challenger_id"], challenger_item, battle["case_name"])
        add_item_to_inventory(battle["opponent_id"], opponent_item, battle["case_name"])

    conn = db()
    conn.execute(
        """
        UPDATE battles
        SET status = 'completed',
            challenger_item_name = ?, challenger_item_rarity = ?, challenger_item_price = ?,
            opponent_item_name = ?, opponent_item_rarity = ?, opponent_item_price = ?,
            winner_id = ?, resolved_at = ?
        WHERE id = ?
        """,
        (
            challenger_item["name"],
            challenger_item["rarity"],
            challenger_item["price"],
            opponent_item["name"],
            opponent_item["rarity"],
            opponent_item["price"],
            winner_id,
            datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            battle_id,
        ),
    )
    conn.commit()
    conn.close()
    battle = get_battle(battle_id)

    pot_text = "Оба скина ушли победителю." if winner_id else "Ничья: каждый получил свой скин."
    return (
        battle,
        f"⚔️ СРАЖЕНИЕ #{battle_id}\n\n"
        f"Кейс: {battle['case_name']}\n"
        f"{battle['challenger_code']}: {battle['challenger_item_name']} ({battle['challenger_item_price']})\n"
        f"{battle['opponent_code']}: {battle['opponent_item_name']} ({battle['opponent_item_price']})\n\n"
        f"{result_title}\n{pot_text}"
    )


def accept_battle(battle_id, user_id):
    battle = get_battle(battle_id)
    if not battle:
        return "❌ Сражение не найдено.", None
    if battle["opponent_id"] != str(user_id):
        return "❌ Это приглашение адресовано не тебе.", None
    if battle["status"] != "pending":
        return f"❌ Сражение уже имеет статус: {battle['status']}.", None
    active = find_active_battle_for_user(user_id)
    if active and active["id"] != battle_id:
        return f"❌ У тебя уже есть активное сражение #{active['id']}.", None

    case_price = CASES[battle["case_name"]]["price"]
    challenger = get_user(battle["challenger_id"])
    opponent = get_user(battle["opponent_id"])
    if challenger["balance"] < case_price:
        return "❌ У создателя сражения уже не хватает монет на участие.", None
    if opponent["balance"] < case_price:
        return "❌ У тебя недостаточно монет для принятия сражения.", None

    adjust_balance(challenger["telegram_id"], -case_price)
    adjust_balance(opponent["telegram_id"], -case_price)
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
    conn.execute(
        "UPDATE battles SET status = 'declined', resolved_at = ? WHERE id = ?",
        (datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"), battle_id),
    )
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

    reels = [weighted_slot_symbol() for _ in range(3)]
    line = build_slot_line(reels)
    counts = {}
    for symbol in reels:
        counts[symbol] = counts.get(symbol, 0) + 1
    max_count = max(counts.values())
    repeated_symbol = max(counts, key=counts.get)

    if max_count == 3:
        multiplier = SPECIAL_SLOT_MULTIPLIERS.get(repeated_symbol, 5)
        win_amount = bet * multiplier
        profit = win_amount - bet
        adjust_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎰 СЛОТ\n\n{line}\n\n"
            f"🔥 Три одинаковых! x{multiplier}\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{profit}\n\n{format_balance_text(updated)}"
        )

    if max_count == 2:
        win_amount = bet * 2
        profit = win_amount - bet
        adjust_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎰 СЛОТ\n\n{line}\n\n"
            f"✨ Два одинаковых! x2\n"
            f"Ставка: {bet}\n"
            f"Выигрыш: {win_amount}\n"
            f"Чистая прибыль: +{profit}\n\n{format_balance_text(updated)}"
        )

    adjust_balance(tid, -bet)
    add_loss(tid)
    updated = get_user(tid)
    return (
        f"🎰 СЛОТ\n\n{line}\n\n"
        f"💨 Не зашло\n"
        f"Ставка: {bet}\n"
        f"Потеря: -{bet}\n\n{format_balance_text(updated)}"
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
        adjust_balance(tid, profit)
        add_win(tid)
        updated = get_user(tid)
        return (
            f"🎡 РУЛЕТКА\n\nВыпало: {number} ({color})\n\n{title}\n"
            f"Ставка: {bet}\nВыплата: {win_amount}\nЧистая прибыль: +{profit}\n\n{format_balance_text(updated)}"
        )

    adjust_balance(tid, -bet)
    add_loss(tid)
    updated = get_user(tid)
    return (
        f"🎡 РУЛЕТКА\n\nВыпало: {number} ({color})\n\n❌ Не повезло\n"
        f"Ставка: {bet}\nПотеря: -{bet}\n\n{format_balance_text(updated)}"
    )


# ---------------- MATH ----------------
def gen_math_choices():
    a = random.randint(5, 50)
    b = random.randint(5, 50)
    op = random.choice(["+", "-", "*"])
    if op == "+":
        answer = a + b
    elif op == "-":
        answer = a - b
    else:
        answer = a * b

    options = {answer}
    while len(options) < 3:
        offset = random.randint(2, 20)
        fake = answer + random.choice([-offset, offset])
        if fake >= 0:
            options.add(fake)
    options = list(options)
    random.shuffle(options)
    return f"{a} {op} {b}", answer, options


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

        user = get_or_create_user(user_id, tg_user.get("first_name", "Игрок"))
        session = get_session(user_id)
        payload = get_session_payload(session)
        lower_text = text.lower()

        if text == "/start":
            clear_session(user_id)
            send(
                chat,
                f"👋 Привет, {user['first_name']}!\nТвой код игрока: {user['player_code']}\nТвой баланс: {user['balance']} монет.",
                main_menu(),
            )
            return "ok", 200

        if text == "Продать всё":
            ok, result = sell_all_items(user_id)
            rows = get_inventory(user_id)
            updated = get_user(user_id)
            send(chat, f"{result}\n\n💰 Баланс: {updated['balance']}\n\n{format_inventory(rows)}", inventory_action_menu(rows) if rows else main_menu())
            return "ok", 200

        sell_id = parse_inventory_action(text, "Продать")
        if sell_id is not None or lower_text.startswith("sell "):
            item_id = sell_id if sell_id is not None else safe_int(lower_text.split()[-1])
            if item_id is None:
                send(chat, "❌ Не удалось распознать ID предмета.", main_menu())
                return "ok", 200
            ok, result = sell_item(user_id, item_id)
            updated = get_user(user_id)
            rows = get_inventory(user_id)
            send(chat, f"{result}\n\n💰 Баланс: {updated['balance']}\n\n{format_inventory(rows)}", inventory_action_menu(rows) if rows else main_menu())
            return "ok", 200

        upgrade_id = parse_inventory_action(text, "Апгрейд")
        if upgrade_id is not None or lower_text.startswith("upgrade "):
            item_id = upgrade_id if upgrade_id is not None else safe_int(lower_text.split()[-1])
            if item_id is None:
                send(chat, "❌ Не удалось распознать ID предмета.", main_menu())
                return "ok", 200
            item = get_inventory_item(user_id, item_id)
            if not item:
                send(chat, "❌ Предмет не найден. Проверь инвентарь.", main_menu())
                return "ok", 200
            set_session(user_id, "upgrade_choose_percent", {"inventory_id": item_id})
            send(
                chat,
                f"🛠 Апгрейд предмета #{item_id}\n{item['skin_name']} ({item['price']})\n\nВыбери шанс апгрейда:",
                upgrade_percent_menu(),
            )
            return "ok", 200

        accept_battle_id = parse_battle_action(text, "Принять бой")
        decline_battle_id = parse_battle_action(text, "Отклонить бой")

        if accept_battle_id is not None or lower_text.startswith("battle accept "):
            battle_id = accept_battle_id if accept_battle_id is not None else safe_int(lower_text.split()[-1])
            error_text, battle_result = accept_battle(battle_id, user_id)
            if error_text:
                send(chat, error_text, main_menu())
                return "ok", 200
            _, result_text = battle_result
            battle = get_battle(battle_id)
            send(chat, f"✅ Ты принял сражение.\n\n{result_text}", main_menu())
            send(int(battle["challenger_id"]), f"⚔️ Твоё приглашение приняли.\n\n{result_text}", main_menu())
            return "ok", 200

        if decline_battle_id is not None or lower_text.startswith("battle decline "):
            battle_id = decline_battle_id if decline_battle_id is not None else safe_int(lower_text.split()[-1])
            result_text = decline_battle(battle_id, user_id)
            battle = get_battle(battle_id)
            send(chat, result_text, main_menu())
            if battle:
                send(int(battle["challenger_id"]), f"⚠️ Игрок отклонил сражение #{battle_id}.", main_menu())
            return "ok", 200


        if text in {"Назад", "Главное меню"}:
            clear_session(user_id)
            send(chat, "Главное меню:", main_menu())
            return "ok", 200

        if text in {"💸 Передать баланс", "Передать баланс"}:
            clear_session(user_id)
            set_session(user_id, "transfer_wait_code")
            send(chat, "💸 Введи код игрока, которому хочешь перевести монеты.", main_menu())
            return "ok", 200

        if session and session["state"] == "transfer_wait_code":
            recipient = get_user_by_code(text)
            if not recipient or recipient["telegram_id"] == str(user_id):
                send(chat, "❌ Введи корректный код другого игрока.", main_menu())
                return "ok", 200
            set_session(user_id, "transfer_wait_amount", {"recipient_code": recipient["player_code"]})
            send(chat, f"Игрок найден: {recipient['first_name']} ({recipient['player_code']}).\nВведи сумму перевода.", main_menu())
            return "ok", 200

        if session and session["state"] == "transfer_wait_amount":
            amount = safe_int(text)
            ok, result = transfer_balance(user_id, payload.get("recipient_code", ""), amount)
            if not ok:
                send(chat, result, main_menu())
                return "ok", 200
            clear_session(user_id)
            updated = get_user(user_id)
            recipient = result
            send(chat, f"✅ Перевод выполнен игроку {recipient['first_name']} ({recipient['player_code']}).\n{format_balance_text(updated)}", main_menu())
            send(int(recipient["telegram_id"]), f"💸 Тебе перевели {amount} монет от {user['first_name']} ({user['player_code']}).", main_menu())
            return "ok", 200

        if text in {"🤝 Друзья", "Друзья"}:
            clear_session(user_id)
            send(chat, format_friends(list_friends(user_id)), friends_menu())
            return "ok", 200

        if text == "Мои друзья":
            send(chat, format_friends(list_friends(user_id)), friends_menu())
            return "ok", 200

        if text == "Добавить друга":
            clear_session(user_id)
            set_session(user_id, "friend_wait_code")
            send(chat, "🤝 Введи код игрока, которого хочешь добавить в друзья.", friends_menu())
            return "ok", 200

        if session and session["state"] == "friend_wait_code":
            ok, result = add_friend(user_id, text)
            if not ok and isinstance(result, str):
                send(chat, result, friends_menu())
                return "ok", 200
            clear_session(user_id)
            friend = result
            send(chat, f"✅ {friend['first_name']} добавлен в друзья.\n\n{format_friends(list_friends(user_id))}", friends_menu())
            send(int(friend["telegram_id"]), f"🤝 {user['first_name']} ({user['player_code']}) добавил тебя в друзья.", main_menu())
            return "ok", 200

        if text in {"Баланс", "💰 Баланс"}:
            send(chat, format_balance_text(get_user(user_id)), main_menu())
            return "ok", 200

        if text in {"Статистика", "📊 Статистика"}:
            send(chat, format_stats(get_user(user_id)), main_menu())
            return "ok", 200

        if text in {"Играть", "🎰 Играть"}:
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
                set_session(user_id, "slot_wait_bet")
                send(chat, slot_spin(user_id, int(text)), bet_menu())
                return "ok", 200

        if session and session["state"] == "slot_wait_custom_bet":
            bet = safe_int(text)
            if bet is None or bet <= 0:
                send(chat, "❌ Введи ставку числом больше 0.", bet_menu())
                return "ok", 200
            set_session(user_id, "slot_wait_bet")
            send(chat, slot_spin(user_id, bet), bet_menu())
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
                set_session(user_id, "roulette_wait_bet")
                send(chat, roulette_resolve(user_id, bet, "color", text), roulette_menu())
                send(chat, "💬 Хочешь ещё? Введи новую ставку числом.", roulette_menu())
                return "ok", 200
            if text in ["Чёт", "Нечёт"]:
                set_session(user_id, "roulette_wait_bet")
                send(chat, roulette_resolve(user_id, bet, "parity", text), roulette_menu())
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
            set_session(user_id, "roulette_wait_bet")
            send(chat, roulette_resolve(user_id, bet, "number", number), roulette_menu())
            send(chat, "💬 Хочешь ещё? Введи новую ставку числом.", roulette_menu())
            return "ok", 200

        if text in {"Кейсы", "📦 Кейсы"}:
            clear_session(user_id)
            send(chat, "📦 Выбери кейс:\nFracture Case — 200\nDanger Case — 350\nRecoil Case — 500\nPrisma Case — 700\nGamma 2 Case — 1000\nChroma 3 Case — 1500\nDreams & Nightmares Case — 2500", case_menu())
            return "ok", 200

        if normalize_case_name(text) in CASES and text.endswith(")"):
            _, result_text = open_case(user_id, normalize_case_name(text))
            send(chat, result_text, case_menu())
            return "ok", 200

        if text in {"Инвентарь", "🎒 Инвентарь", "Обновить инвентарь"}:
            rows = get_inventory(user_id)
            send(chat, format_inventory(rows), inventory_action_menu(rows) if rows else main_menu())
            return "ok", 200

        if text == "Апгрейд":
            rows = get_inventory(user_id)
            send(
                chat,
                "🛠 Выбери предмет кнопкой «Апгрейд #ID» из инвентаря.\n\n" + format_inventory(rows),
                inventory_action_menu(rows) if rows else main_menu(),
            )
            return "ok", 200

        if session and session["state"] == "upgrade_choose_percent":
            percent = UPGRADE_OPTIONS.get(text)
            inventory_id = payload.get("inventory_id")
            if not percent:
                send(chat, "Выбери шанс из меню ниже.", upgrade_percent_menu())
                return "ok", 200
            clear_session(user_id)
            rows_before = get_inventory(user_id)
            send(chat, perform_upgrade(user_id, inventory_id, percent), inventory_action_menu(get_inventory(user_id)) if rows_before else main_menu())
            return "ok", 200

        if text in {"Сражения", "⚔️ Сражения"}:
            clear_session(user_id)
            send(
                chat,
                f"⚔️ Сражения. Можно искать соперника по имени, коду или Telegram ID.\nТвой код: {user['player_code']}",
                battle_menu(),
            )
            return "ok", 200

        if text == "Мои сражения":
            send(chat, format_battle_list(list_user_battles(user_id)), battle_menu())
            return "ok", 200

        if text == "Создать сражение":
            clear_session(user_id)
            set_session(user_id, "battle_wait_search")
            send(chat, "🔎 Введи имя игрока, его код или Telegram ID для поиска соперника.", battle_menu())
            return "ok", 200

        if session and session["state"] == "battle_wait_search":
            players = search_players(text, exclude_tid=user_id)
            if not players:
                send(chat, "❌ Никого не нашли. Попробуй имя, код или Telegram ID ещё раз.", battle_menu())
                return "ok", 200
            serialized = [dict(player) for player in players]
            set_session(user_id, "battle_wait_select_player", {"players": serialized})
            results_text = "\n".join([format_player_result(player) for player in players])
            send(chat, f"Найденные игроки:\n\n{results_text}\n\nВыбери игрока кнопкой ниже.", player_search_results_menu(players))
            return "ok", 200

        if session and session["state"] == "battle_wait_select_player":
            selected_code = extract_player_code_from_button(text)
            if not selected_code:
                send(chat, "Выбери соперника кнопкой из списка ниже.", player_search_results_menu(payload.get("players", [])))
                return "ok", 200
            opponent = get_user_by_code(selected_code)
            if not opponent:
                clear_session(user_id)
                send(chat, "❌ Игрок больше недоступен. Попробуй поиск снова.", battle_menu())
                return "ok", 200
            set_session(user_id, "battle_wait_case", {"opponent_code": opponent["player_code"]})
            send(chat, f"✅ Соперник выбран: {format_player_result(opponent)}\nВыбери кейс для сражения.", battle_case_menu())
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
                send(chat, f"❌ Нужно минимум {case_price} монет для участия в этом сражении.", battle_menu())
                return "ok", 200
            battle_id, battle_error = create_battle(challenger, opponent, case_name)
            if battle_error:
                clear_session(user_id)
                send(chat, battle_error, battle_menu())
                return "ok", 200
            clear_session(user_id)
            send(
                chat,
                f"📨 Приглашение отправлено игроку {format_player_result(opponent)}.\n"
                f"Сражение #{battle_id}, кейс: {case_name}.\n"
                f"Монеты списываются только после принятия боя.",
                battle_menu(),
            )
            send(
                int(opponent["telegram_id"]),
                f"⚔️ Тебя вызвали на сражение!\n\n"
                f"Сражение #{battle_id}\n"
                f"От: {format_player_result(challenger)}\n"
                f"Кейс: {case_name}\n"
                f"Вход: {case_price} монет\n"
                f"Награда: победитель получает оба выпавших скина\n\n"
                f"Нажми кнопку ниже, чтобы принять или отклонить вызов.",
                battle_action_menu(battle_id),
            )
            return "ok", 200

        if text in {"Заработать", "🧠 Заработать"}:
            clear_session(user_id)
            send(chat, "🧠 Выбери способ заработка:", earn_menu())
            return "ok", 200

        if text == "Пример":
            question, answer, options = gen_math_choices()
            set_session(user_id, "math_choice", {"answer": answer, "options": options})
            send(chat, f"🧠 Реши пример:\n\n{question}\n\nВыбери один из трёх вариантов:", answer_options_menu(options))
            return "ok", 200

        if session and session["state"] == "math_choice":
            correct_answer = safe_int(payload.get("answer"))
            chosen_answer = safe_int(text)
            if chosen_answer is None:
                send(chat, "Выбери один из трёх вариантов кнопкой ниже.", answer_options_menu(payload.get("options", [])))
                return "ok", 200
            clear_session(user_id)
            if chosen_answer == correct_answer:
                adjust_balance(user_id, 100)
                updated_user = get_user(user_id)
                send(chat, f"✅ Верно! +100 монет\n{format_balance_text(updated_user)}", earn_menu())
                return "ok", 200
            send(chat, f"❌ Неверно. Правильный ответ: {correct_answer}", earn_menu())
            return "ok", 200

        send(chat, "Выбери действие:", main_menu())
        return "ok", 200

    except Exception as exc:
        print("BOT ERROR:", str(exc), flush=True)
        print(traceback.format_exc(), flush=True)
        return "ok", 200


def friends_menu():
    return {"keyboard": [["Добавить друга", "Мои друзья"], ["Главное меню"]], "resize_keyboard": True}


print(f"DB PATH: {DB_PATH}", flush=True)
print(f"USER STORE: {'supabase' if SUPABASE_CLIENT else 'sqlite'}", flush=True)
init_db()
configure_webhook()

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    app.run(host="0.0.0.0", port=port, debug=True)
