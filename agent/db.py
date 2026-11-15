"""SQLite schema + seed data. The eval harness grades calls by what ends up in these tables."""

import os
import re
import sqlite3
from datetime import date, datetime, timedelta

DB_PATH = os.getenv("NIGHTSHIFT_DB", "nightshift.db")

SCHEMA = """
DROP TABLE IF EXISTS customers;
DROP TABLE IF EXISTS slots;
DROP TABLE IF EXISTS visits;
DROP TABLE IF EXISTS pages;
DROP TABLE IF EXISTS safety_calls;
DROP TABLE IF EXISTS transfers;

CREATE TABLE customers (
    id INTEGER PRIMARY KEY,
    name TEXT NOT NULL,
    phone TEXT NOT NULL,        -- digits only, 10 long
    address TEXT NOT NULL
);
CREATE TABLE slots (
    id TEXT PRIMARY KEY,        -- e.g. 2026-11-16-09
    day TEXT NOT NULL,          -- YYYY-MM-DD
    start_hour INTEGER NOT NULL,
    visit_id INTEGER            -- NULL = open
);
CREATE TABLE visits (
    id INTEGER PRIMARY KEY,
    customer_id INTEGER NOT NULL,
    slot_id TEXT NOT NULL,
    issue TEXT NOT NULL,
    address TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'booked'   -- booked | cancelled
);
CREATE TABLE pages (
    id INTEGER PRIMARY KEY,
    urgency TEXT NOT NULL,      -- emergency | safety_fyi
    summary TEXT NOT NULL,
    address TEXT NOT NULL,
    callback TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE safety_calls (
    id INTEGER PRIMARY KEY,
    hazard TEXT NOT NULL,
    address TEXT,
    callback TEXT,
    created_at TEXT NOT NULL
);
CREATE TABLE transfers (
    id INTEGER PRIMARY KEY,
    reason TEXT NOT NULL,
    created_at TEXT NOT NULL
);
"""


def normalize_phone(phone: str) -> str:
    """'(716) 555-0142' -> '7165550142'. Keeps last 10 digits."""
    return re.sub(r"\D", "", phone or "")[-10:]


def connect(path: str | None = None) -> sqlite3.Connection:
    # check_same_thread=False: voice mode calls tools from a worker thread
    conn = sqlite3.connect(path or DB_PATH, check_same_thread=False)
    conn.row_factory = sqlite3.Row  # rows behave like dicts
    return conn


def business_days_after(today: date, n: int = 2) -> list[date]:
    days, d = [], today
    while len(days) < n:
        d += timedelta(days=1)
        if d.weekday() < 5:  # Mon-Fri
            days.append(d)
    return days


def init_db(path: str | None = None, today: date | None = None, slot_starts=(9, 11, 13, 15)) -> sqlite3.Connection:
    """Wipe and reseed. Every eval scenario starts from this exact state."""
    conn = connect(path)
    conn.executescript(SCHEMA)
    today = today or date.today()

    for day in business_days_after(today):
        for h in slot_starts:
            conn.execute(
                "INSERT INTO slots (id, day, start_hour) VALUES (?, ?, ?)",
                (f"{day.isoformat()}-{h:02d}", day.isoformat(), h),
            )

    customers = [
        ("Sarah Chen", "7165550142", "42 Elmwood Ave, Buffalo"),
        ("Dave Miller", "7165550199", "118 Hertel Ave, Buffalo"),
        ("Priya Patel", "7165550177", "9 Delaware Rd, Kenmore"),
    ]
    conn.executemany("INSERT INTO customers (name, phone, address) VALUES (?, ?, ?)", customers)

    first_day = business_days_after(today)[0].isoformat()
    existing = [  # (customer_id, start_hour, issue)
        (1, 11, "dripping kitchen faucet"),
        (2, 15, "water heater flush"),
    ]
    for cust_id, hour, issue in existing:
        slot_id = f"{first_day}-{hour:02d}"
        addr = conn.execute("SELECT address FROM customers WHERE id=?", (cust_id,)).fetchone()["address"]
        cur = conn.execute(
            "INSERT INTO visits (customer_id, slot_id, issue, address) VALUES (?, ?, ?, ?)",
            (cust_id, slot_id, issue, addr),
        )
        conn.execute("UPDATE slots SET visit_id=? WHERE id=?", (cur.lastrowid, slot_id))

    conn.commit()
    return conn


def now_iso() -> str:
    return datetime.now().isoformat(timespec="seconds")
