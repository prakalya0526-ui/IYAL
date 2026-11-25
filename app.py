"""IYAL server with multiple Telegram guardians per device."""
import os
import sqlite3
import time
from datetime import datetime, timedelta, timezone

import requests
from flask import Flask, jsonify, redirect, render_template_string, request

app = Flask(__name__)

BOT_TOKEN = os.environ.get("BOT_TOKEN", "")
API_KEY = os.environ.get("API_KEY", "demo-key")
ADMIN_PIN = os.environ.get("ADMIN_PIN", "1234")
DB = os.environ.get("DB_PATH", "safety.db")
IST = timezone(timedelta(hours=5, minutes=30))


def db():
    c = sqlite3.connect(DB)
    c.row_factory = sqlite3.Row
    return c


def init_db():
    c = db()
    c.executescript("""
        CREATE TABLE IF NOT EXISTS devices(
            device_id TEXT PRIMARY KEY, guard_name TEXT, chat_id TEXT);
        CREATE TABLE IF NOT EXISTS guardians(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            device_id TEXT NOT NULL,
            guard_name TEXT NOT NULL,
            chat_id TEXT NOT NULL,
            UNIQUE(device_id, chat_id));
        CREATE TABLE IF NOT EXISTS locations(
            device_id TEXT PRIMARY KEY, lat REAL, lng REAL, acc REAL, ts INTEGER);
        CREATE TABLE IF NOT EXISTS alerts(
            id INTEGER PRIMARY KEY AUTOINCREMENT, device_id TEXT, reason TEXT,
            lat REAL, lng REAL, source TEXT, area TEXT, ts INTEGER);
    """)
    # Migrate existing single-guardian records into the new guardians table.
    old_rows = c.execute(
        "SELECT device_id, guard_name, chat_id FROM devices"
    ).fetchall()
    for row in old_rows:
        if row["chat_id"]:
            c.execute(
                "INSERT OR IGNORE INTO guardians(device_id,guard_name,chat_id) VALUES(?,?,?)",
                (row["device_id"], row["guard_name"] or "Guardian", row["chat_id"]),
            )

    # Keep the existing DEV001 auto-registration behaviour.
    seed = os.environ.get("DEFAULT_CHAT_ID")
    if seed:
        c.execute(
            "INSERT OR IGNORE INTO devices(device_id,guard_name,chat_id) VALUES('DEV001','Security Guard 1',?)",
            (seed,),
        )
        c.execute(
            "INSERT OR IGNORE INTO guardians(device_id,guard_name,chat_id) VALUES('DEV001','Security Guard 1',?)",
            (seed,),
        )
    c.commit()
    c.close()


init_db()


def tg(method, payload):
    if not BOT_TOKEN:
        print("BOT_TOKEN not set; would send:", method, payload)
        return False
    try:
        r = requests.post(
            f"https://api.telegram.org/bot{BOT_TOKEN}/{method}",
            json=payload,
            timeout=10,
        )
        print("telegram", method, r.status_code, r.text[:300])
        return r.ok
    except Exception as e:
        print("telegram error:", e)
        return False



def reverse_geocode(lat, lng):
    try:
        r = requests.get(
            "https://nominatim.openstreetmap.org/reverse",
            params={
                "lat": lat,
                "lon": lng,
                "format": "json"
            },
            headers={"User-Agent": "iyal-hackathon"},
            timeout=5
        ).json()

        return r.get("display_name", "Unknown area")

    except Exception as e:
        print("Location error:", e)
        return "Unknown area"
