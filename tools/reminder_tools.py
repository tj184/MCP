
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv

load_dotenv()

DB_PATH = "reminders.db"
BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]
LOCAL_TZ = ZoneInfo("Asia/Kolkata")


def connect_db():
    conn = sqlite3.connect(DB_PATH, timeout=30)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS reminders (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            message TEXT NOT NULL,
            due_at TEXT NOT NULL,
            status TEXT NOT NULL DEFAULT 'pending'
        )
    """)
    conn.commit()
    return conn


def send_telegram(message: str):
    response = requests.post(
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
        json={
            "chat_id": CHAT_ID,
            "text": message
        },
        timeout=15
    )
    response.raise_for_status()
    result = response.json()
    if not result.get("ok"):
        raise RuntimeError(result.get("description", "Telegram error"))


def create_reminder(message: str, scheduled_at: str):
    if not message.strip() or len(message) > 4000:
        raise ValueError("Message must be 1-4000 characters")

    due = datetime.fromisoformat(scheduled_at)

    if due.tzinfo is None:
        raise ValueError("scheduled_at must include a timezone")

    due_utc = due.astimezone(timezone.utc)

    if due_utc <= datetime.now(timezone.utc):
        raise ValueError("Reminder time must be in the future")

    with connect_db() as conn:
        cursor = conn.execute(
            "INSERT INTO reminders (message, due_at) VALUES (?, ?)",
            (message, due_utc.isoformat())
        )
        reminder_id = cursor.lastrowid

    return {
        "status": "scheduled",
        "reminder_id": reminder_id,
        "message": message,
        "scheduled_at": due.astimezone(LOCAL_TZ).isoformat()
    }


def reminder_worker():
    while True:
        try:
            now = datetime.now(timezone.utc).isoformat()

            with connect_db() as conn:
                rows = conn.execute(
                    """SELECT id, message FROM reminders
                       WHERE status = 'pending' AND due_at <= ?
                       ORDER BY due_at LIMIT 20""",
                    (now,)
                ).fetchall()

            for reminder_id, message in rows:
                try:
                    send_telegram("⏰ Reminder\n\n" + message)
                    with connect_db() as conn:
                        conn.execute(
                            "UPDATE reminders SET status = 'sent' WHERE id = ?",
                            (reminder_id,)
                        )
                except Exception as exc:
                    print(f"Reminder {reminder_id} failed: {exc}")

        except Exception as exc:
            print("Worker error:", exc)

        time.sleep(10)


def start_reminder_worker():
    thread = threading.Thread(
        target=reminder_worker,
        daemon=True
    )
    thread.start()
