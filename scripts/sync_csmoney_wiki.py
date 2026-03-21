"""Populate `data/skin_catalog.db` from wiki.cs.money weapon pages.

This script is intentionally separate from the bot runtime. It is designed to crawl
CS.MONEY wiki pages, extract skin names and direct image URLs, and upsert them into
`data/skin_catalog.db` for later integration into the bot.

Expected usage (in an environment that can reach wiki.cs.money):
    python scripts/sync_csmoney_wiki.py
"""

from __future__ import annotations

import json
import re
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import requests

ROOT = Path(__file__).resolve().parents[1]
DB_PATH = ROOT / 'data' / 'skin_catalog.db'
USER_AGENT = 'Mozilla/5.0 (compatible; tg-casino-bot/1.0; +https://wiki.cs.money/)'
BASE_URL = 'https://wiki.cs.money'
WEAPON_SLUGS = [
    'ak-47', 'm4a4', 'm4a1-s', 'awp', 'desert-eagle', 'usp-s', 'glock-18',
    'p250', 'five-seven', 'cz75-auto', 'p2000', 'dual-berettas', 'r8-revolver',
    'tec-9', 'mp9', 'mac-10', 'ump-45', 'mp7', 'p90', 'pp-bizon', 'famas',
    'galil-ar', 'aug', 'sg-553', 'ssg-08', 'nova', 'xm1014', 'mag-7',
    'sawed-off', 'g3sg1', 'scar-20', 'negev', 'm249'
]

SKIN_LINK_RE = re.compile(r'href="(?P<path>/weapons/(?P<weapon>[^"]+?)/(?P<slug>[^"]+))"')
TITLE_RE = re.compile(r'<title>(?P<title>[^<]+)</title>', re.IGNORECASE)
OG_IMAGE_RE = re.compile(r'<meta[^>]+property="og:image"[^>]+content="(?P<url>[^"]+)"', re.IGNORECASE)
RARITY_RE = re.compile(r'Skin Features.*?quality of .*? is (?P<rarity>[A-Za-z\- ]+?)\.', re.DOTALL)
PRICE_RE = re.compile(r'\$\s*([\d\s,]+(?:\.\d+)?)')


@dataclass
class SkinRecord:
    weapon: str
    skin_name: str
    full_name: str
    rarity: str | None
    price: int | None
    source_case: str | None
    source_url: str
    image_url: str | None
    image_source: str = 'wiki.cs.money'


def session() -> requests.Session:
    s = requests.Session()
    s.headers.update({'User-Agent': USER_AGENT})
    return s


def fetch_text(s: requests.Session, url: str) -> str:
    response = s.get(url, timeout=30)
    response.raise_for_status()
    return response.text


def parse_title(html: str) -> str | None:
    m = TITLE_RE.search(html)
    return m.group('title').split('—')[0].strip() if m else None


def parse_image_url(html: str) -> str | None:
    m = OG_IMAGE_RE.search(html)
    return m.group('url').strip() if m else None


def parse_rarity(html: str) -> str | None:
    m = RARITY_RE.search(html)
    return m.group('rarity').strip() if m else None


def parse_price(html: str) -> int | None:
    prices = PRICE_RE.findall(html)
    if not prices:
        return None
    raw = prices[0].replace(' ', '').replace(',', '')
    try:
        return int(float(raw))
    except ValueError:
        return None


def discover_skin_urls(s: requests.Session, weapon_slug: str) -> Iterable[str]:
    html = fetch_text(s, f'{BASE_URL}/weapons/{weapon_slug}')
    found = []
    seen = set()
    for match in SKIN_LINK_RE.finditer(html):
        path = match.group('path')
        if path not in seen:
            seen.add(path)
            found.append(f'{BASE_URL}{path}')
    return found


def build_record(s: requests.Session, skin_url: str) -> SkinRecord | None:
    html = fetch_text(s, skin_url)
    title = parse_title(html)
    if not title or '|' not in title:
        return None
    weapon, skin_name = [part.strip() for part in title.split('|', 1)]
    return SkinRecord(
        weapon=weapon,
        skin_name=skin_name,
        full_name=title,
        rarity=parse_rarity(html),
        price=parse_price(html),
        source_case=None,
        source_url=skin_url,
        image_url=parse_image_url(html),
    )


def upsert(records: list[SkinRecord], db_path: Path = DB_PATH) -> None:
    conn = sqlite3.connect(db_path)
    conn.execute(
        '''
        CREATE TABLE IF NOT EXISTS skins (
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
        INSERT INTO skins (weapon, skin_name, full_name, rarity, price, source_case, source_url, image_url, image_source)
        VALUES (:weapon, :skin_name, :full_name, :rarity, :price, :source_case, :source_url, :image_url, :image_source)
        ON CONFLICT(full_name) DO UPDATE SET
            rarity=excluded.rarity,
            price=COALESCE(excluded.price, skins.price),
            source_url=excluded.source_url,
            image_url=COALESCE(excluded.image_url, skins.image_url),
            image_source=excluded.image_source
        ''',
        [record.__dict__ for record in records],
    )
    conn.commit()
    conn.close()


def main() -> None:
    s = session()
    records: list[SkinRecord] = []
    for weapon_slug in WEAPON_SLUGS:
        try:
            urls = discover_skin_urls(s, weapon_slug)
        except Exception as exc:
            print(f'Failed to load weapon page {weapon_slug}: {exc}')
            continue
        for skin_url in urls:
            try:
                record = build_record(s, skin_url)
            except Exception as exc:
                print(f'Failed to parse {skin_url}: {exc}')
                continue
            if record:
                records.append(record)
                print(f'+ {record.full_name}')
    upsert(records)
    print(json.dumps({'synced': len(records), 'db_path': str(DB_PATH)}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
