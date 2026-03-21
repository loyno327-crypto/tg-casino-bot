import json
import sqlite3
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SEED_PATH = ROOT / 'data' / 'skin_catalog_seed.json'
DB_PATH = ROOT / 'data' / 'skin_catalog.db'


def build_db(seed_path: Path = SEED_PATH, db_path: Path = DB_PATH) -> None:
    skins = json.loads(seed_path.read_text(encoding='utf-8'))
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.execute('DROP TABLE IF EXISTS skins')
    conn.execute(
        '''
        CREATE TABLE skins (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            weapon TEXT NOT NULL,
            skin_name TEXT NOT NULL,
            full_name TEXT NOT NULL UNIQUE,
            rarity TEXT,
            price INTEGER,
            source_case TEXT,
            source_url TEXT,
            image_url TEXT,
            image_source TEXT DEFAULT 'wiki.cs.money',
            created_at TEXT DEFAULT CURRENT_TIMESTAMP
        )
        '''
    )
    conn.executemany(
        '''
        INSERT INTO skins (
            weapon, skin_name, full_name, rarity, price, source_case,
            source_url, image_url, image_source
        ) VALUES (:weapon, :skin_name, :full_name, :rarity, :price, :source_case,
                  :source_url, :image_url, :image_source)
        ''',
        skins,
    )
    conn.commit()
    conn.close()
    print(f'Inserted {len(skins)} skins into {db_path}')


if __name__ == '__main__':
    build_db()
