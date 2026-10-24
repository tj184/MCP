
import logging
import os
import sqlite3
import threading
import time
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

import requests
from dotenv import load_dotenv


# --------------------------------------------------
# Configuration
# --------------------------------------------------

PROJECT_DIR = Path(__file__).resolve().parent.parent
DB_PATH = PROJECT_DIR / "reminders.db"

load_dotenv(PROJECT_DIR / ".env")

LOCAL_TZ = ZoneInfo("Asia/Kolkata")

POLL_INTERVAL_SECONDS = 10
MAX_ATTEMPTS = 10
MAX_RETRY_DELAY_SECONDS = 300
STALE_SENDING_MINUTES = 5

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)s | %(name)s | %(message)s",
)

logger = logging.getLogger("reminder_service")

_worker_lock = threading.Lock()
_worker_thread = None


# --------------------------------------------------
# Time helpers
# --------------------------------------------------

def utc_now():
    return datetime.now(timezone.utc)


def utc_iso(value=None):
    value = value or utc_now()
    return value.astimezone(timezone.utc).isoformat(
        timespec="microseconds"
    )


# --------------------------------------------------
# Database
# --------------------------------------------------

@contextmanager
def db_connection():
    """
    Open a SQLite connection and always close it.
    The connection context commits on success and rolls
    back on exceptions.
    """
    conn = sqlite3.connect(
        str(DB_PATH),
        timeout=30,
    )
    conn.row_factory = sqlite3.Row

    try:
        conn.execute("PRAGMA busy_timeout = 30000")
        conn.execute("PRAGMA journal_mode = WAL")

        yield conn
        conn.commit()

    except Exception:
        conn.rollback()
        raise

    finally:
        conn.close()


def init_db():
    """Create the reminders table and migrate older databases."""

    with db_connection() as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                message TEXT NOT NULL,
                due_at TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                attempts INTEGER NOT NULL DEFAULT 0,
                next_attempt_at TEXT,
                last_error TEXT,
                updated_at TEXT
            )
        """)

        # Add columns to an existing database created by
        # the previous version of this program.
        existing_columns = {
            row["name"]
            for row in conn.execute(
                "PRAGMA table_info(reminders)"
            ).fetchall()
        }

        migrations = {
            "attempts": (
                "ALTER TABLE reminders "
                "ADD COLUMN attempts INTEGER NOT NULL DEFAULT 0"
            ),
            "next_attempt_at": (
                "ALTER TABLE reminders ADD COLUMN next_attempt_at TEXT"
            ),
            "last_error": (
                "ALTER TABLE reminders ADD COLUMN last_error TEXT"
            ),
            "updated_at": (
                "ALTER TABLE reminders ADD COLUMN updated_at TEXT"
            ),
        }

        for column, sql in migrations.items():
            if column not in existing_columns:
                conn.execute(sql)

        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_reminders_due
            ON reminders(status, due_at)
        """)

    logger.info("Reminder database initialized at %s", DB_PATH)


# --------------------------------------------------
# Telegram delivery
# --------------------------------------------------

def send_telegram(message: str):
    """Send a Telegram message and raise an error on failure."""

    bot_token = os.getenv("TELEGRAM_BOT_TOKEN")
    chat_id = os.getenv("TELEGRAM_CHAT_ID")

    if not bot_token:
        raise RuntimeError(
            "TELEGRAM_BOT_TOKEN is missing from the environment"
        )

    if not chat_id:
        raise RuntimeError(
            "TELEGRAM_CHAT_ID is missing from the environment"
        )

    url = f"https://api.telegram.org/bot{bot_token}/sendMessage"

    response = requests.post(
        url,
        json={
            "chat_id": chat_id,
            "text": message,
        },
        timeout=20,
    )

    response.raise_for_status()
    result = response.json()

    if not result.get("ok"):
        raise RuntimeError(
            result.get("description", "Telegram rejected the message")
        )

    logger.info("Telegram reminder delivered successfully")


# --------------------------------------------------
# Create reminder
# --------------------------------------------------

def create_reminder(message: str, scheduled_at: str) -> dict:
    """
    Schedule a Telegram reminder.

    scheduled_at must be an ISO 8601 datetime containing
    a timezone, for example:
    2026-10-25T08:00:00+05:30
    """

    if not isinstance(message, str) or not message.strip():
        raise ValueError("Message must not be empty")

    message = message.strip()

    if len(message) > 4000:
        raise ValueError("Message must not exceed 4000 characters")

    if not isinstance(scheduled_at, str):
        raise ValueError("scheduled_at must be an ISO 8601 string")

    try:
        due = datetime.fromisoformat(
            scheduled_at.strip().replace("Z", "+00:00")
        )
    except ValueError as exc:
        raise ValueError(
            "Invalid scheduled_at. Use ISO 8601, "
            "e.g. 2026-10-25T08:00:00+05:30"
        ) from exc

    if due.tzinfo is None or due.utcoffset() is None:
        raise ValueError(
            "scheduled_at must include a timezone offset"
        )

    due_utc = due.astimezone(timezone.utc)

    if due_utc <= utc_now():
        raise ValueError(
            "Reminder time must be in the future"
        )

    now_string = utc_iso()

    with db_connection() as conn:
        cursor = conn.execute(
            """
            INSERT INTO reminders (
                message,
                due_at,
                status,
                attempts,
                next_attempt_at,
                updated_at
            )
            VALUES (?, ?, 'pending', 0, ?, ?)
            """,
            (
                message,
                utc_iso(due_utc),
                now_string,
                now_string,
            ),
        )

        reminder_id = cursor.lastrowid

    local_due = due_utc.astimezone(LOCAL_TZ)

    logger.info(
        "Reminder %s scheduled for %s",
        reminder_id,
        local_due.isoformat(),
    )

    return {
        "status": "scheduled",
        "reminder_id": reminder_id,
        "message": message,
        "scheduled_at": local_due.isoformat(),
        "timezone": "Asia/Kolkata",
    }


# --------------------------------------------------
# Claim reminders safely
# --------------------------------------------------

def claim_due_reminder():
    """
    Claim one due reminder in a short SQLite transaction.

    BEGIN IMMEDIATE prevents two workers from claiming
    the same pending reminder simultaneously.
    """

    now = utc_iso()
    stale_before = utc_iso(
        utc_now() - timedelta(minutes=STALE_SENDING_MINUTES)
    )

    with db_connection() as conn:
        conn.execute("BEGIN IMMEDIATE")

        # Recover reminders left in 'sending' after a crash.
        # A message might be sent twice if the crash happened
        # after Telegram accepted it but before SQLite updated.
        conn.execute(
            """
            UPDATE reminders
            SET status = 'pending',
                updated_at = ?
            WHERE status = 'sending'
              AND (updated_at IS NULL OR updated_at <= ?)
            """,
            (now, stale_before),
        )

        row = conn.execute(
            """
            SELECT *
            FROM reminders
            WHERE status = 'pending'
              AND due_at <= ?
              AND (
                  next_attempt_at IS NULL
                  OR next_attempt_at = ''
                  OR next_attempt_at <= ?
              )
            ORDER BY due_at, id
            LIMIT 1
            """,
            (now, now),
        ).fetchone()

        if row is None:
            return None

        conn.execute(
            """
            UPDATE reminders
            SET status = 'sending',
                updated_at = ?
            WHERE id = ? AND status = 'pending'
            """,
            (now, row["id"]),
        )

        return {
            "id": row["id"],
            "message": row["message"],
            "attempts": row["attempts"],
        }


# --------------------------------------------------
# Process and retry
# --------------------------------------------------

def process_reminder(reminder: dict):
    reminder_id = reminder["id"]
    message = reminder["message"]
    attempt_number = reminder["attempts"] + 1

    try:
        send_telegram("⏰ Reminder\n\n" + message)

        with db_connection() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = 'sent',
                    attempts = ?,
                    last_error = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (attempt_number, utc_iso(), reminder_id),
            )

        logger.info("Reminder %s marked as sent", reminder_id)

    except Exception as exc:
        logger.exception(
            "Reminder %s delivery attempt %s failed",
            reminder_id,
            attempt_number,
        )

        if attempt_number >= MAX_ATTEMPTS:
            new_status = "failed"
            next_attempt = None

            logger.error(
                "Reminder %s exhausted all retry attempts",
                reminder_id,
            )
        else:
            new_status = "pending"

            delay = min(
                10 * (2 ** (attempt_number - 1)),
                MAX_RETRY_DELAY_SECONDS,
            )

            next_attempt = utc_iso(
                utc_now() + timedelta(seconds=delay)
            )

        with db_connection() as conn:
            conn.execute(
                """
                UPDATE reminders
                SET status = ?,
                    attempts = ?,
                    next_attempt_at = ?,
                    last_error = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    new_status,
                    attempt_number,
                    next_attempt,
                    str(exc)[:1000],
                    utc_iso(),
                    reminder_id,
                ),
            )


# --------------------------------------------------
# Background worker
# --------------------------------------------------

def reminder_worker():
    logger.info(
        "Reminder worker started; polling every %s seconds",
        POLL_INTERVAL_SECONDS,
    )

    while True:
        try:
            reminder = claim_due_reminder()

            if reminder is not None:
                process_reminder(reminder)

        except Exception:
            logger.exception("Unexpected reminder worker error")

        time.sleep(POLL_INTERVAL_SECONDS)


def start_reminder_worker():
    """
    Start one reminder worker per Python process.
    Call this from the actual application startup.
    """

    global _worker_thread

    with _worker_lock:
        if (
            _worker_thread is not None
            and _worker_thread.is_alive()
        ):
            logger.info("Reminder worker is already running")
            return _worker_thread

        init_db()

        _worker_thread = threading.Thread(
            target=reminder_worker,
            name="telegram-reminder-worker",
            daemon=True,
        )

        _worker_thread.start()

        logger.info("Reminder worker thread launched")

        return _worker_thread


# Initialize the database when this module is imported.
init_db()
