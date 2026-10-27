"""Supabase PostgreSQL storage for SmartFind."""
import json
import os
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from threading import Lock

_SUPABASE_DATABASE_URL = ""
_INITIALIZED_TARGETS = set()
_INITIALIZATION_LOCK = Lock()


def configure_supabase(database_url):
    global _SUPABASE_DATABASE_URL
    _SUPABASE_DATABASE_URL = str(database_url or os.environ.get("SUPABASE_DB_URL", "")).strip()


def _storage_target():
    return ("postgres", _SUPABASE_DATABASE_URL)


def _postgres_connection():
    if not _SUPABASE_DATABASE_URL:
        raise RuntimeError("Supabase database_url is required; SQLite storage is no longer supported.")
    try:
        import psycopg
    except ImportError as exc:
        raise RuntimeError("Supabase storage requires psycopg. Install requirements.txt.") from exc
    return psycopg.connect(_SUPABASE_DATABASE_URL, sslmode="require", connect_timeout=10)


def initialize_storage():
    """Apply this backend's schema once per process, outside normal query paths.

    The statements are deliberately idempotent so first starts in separate app
    processes remain safe.  Normal reads and writes never execute schema DDL.
    """
    target = _storage_target()
    if target in _INITIALIZED_TARGETS:
        return
    with _INITIALIZATION_LOCK:
        if target in _INITIALIZED_TARGETS:
            return
        connection = _postgres_connection()
        try:
            connection.execute("""CREATE TABLE IF NOT EXISTS reports (
                id TEXT PRIMARY KEY,
                payload JSONB NOT NULL,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS app_meta (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS guest_accounts (
                id TEXT PRIMARY KEY,
                recovery_code_hash TEXT NOT NULL UNIQUE,
                created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )""")
            connection.execute("""CREATE TABLE IF NOT EXISTS notifications (
                id BIGSERIAL PRIMARY KEY,
                key TEXT NOT NULL UNIQUE,
                pair_key TEXT NOT NULL,
                recipient TEXT NOT NULL,
                item TEXT NOT NULL,
                score INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                read_at TEXT,
                email_status TEXT NOT NULL DEFAULT 'pending',
                email_attempted_at TEXT,
                email_sent_at TEXT,
                email_error TEXT
            )""")
            connection.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_status TEXT NOT NULL DEFAULT 'pending'")
            connection.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_attempted_at TEXT")
            connection.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_sent_at TEXT")
            connection.execute("ALTER TABLE notifications ADD COLUMN IF NOT EXISTS email_error TEXT")
            # Keep the existing table-level access posture; direct database
            # connections continue to use the configured database role.
            connection.execute("ALTER TABLE reports ENABLE ROW LEVEL SECURITY")
            connection.execute("ALTER TABLE app_meta ENABLE ROW LEVEL SECURITY")
            connection.execute("ALTER TABLE guest_accounts ENABLE ROW LEVEL SECURITY")
            connection.execute("ALTER TABLE notifications ENABLE ROW LEVEL SECURITY")
            connection.commit()
        except Exception:
            connection.rollback()
            raise
        finally:
            connection.close()
        _INITIALIZED_TARGETS.add(target)


@contextmanager
def _connect():
    """Open one short-lived transactional connection for one storage operation."""
    initialize_storage()
    connection = _postgres_connection()
    try:
        yield connection
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()


def load_reports():
    """Read reports in insertion order and ensure older records have a brand field."""
    with _connect() as connection:
        order = "created_at, id"
        select = "payload::text"
        rows = connection.execute(f"SELECT {select} FROM reports ORDER BY {order}").fetchall()
    reports = [json.loads(row[0]) if isinstance(row[0], str) else row[0] for row in rows]
    for report in reports:
        report.setdefault("brand", "")
    return reports


def save_report(report):
    """Insert or update one report while retaining its original insertion order."""
    payload = dict(report)
    payload.setdefault("brand", "")
    with _connect() as connection:
        placeholder = "%s"
        json_value = f"{placeholder}::jsonb"
        connection.execute(f"""INSERT INTO reports (id, payload) VALUES ({placeholder}, {json_value})
            ON CONFLICT(id) DO UPDATE SET payload = excluded.payload""",
                           (payload["id"], json.dumps(payload, ensure_ascii=False)))


def delete_report(report_id):
    with _connect() as connection:
        placeholder = "%s"
        connection.execute(f"DELETE FROM reports WHERE id = {placeholder}", (report_id,))


def create_guest_account(guest_id, recovery_code_hash):
    with _connect() as connection:
        connection.execute("INSERT INTO guest_accounts (id, recovery_code_hash) VALUES (%s, %s)",
                           (guest_id, recovery_code_hash))


def find_guest_account(recovery_code_hash):
    with _connect() as connection:
        row = connection.execute(
            "SELECT id FROM guest_accounts WHERE recovery_code_hash = %s",
            (recovery_code_hash,),
        ).fetchone()
    return row[0] if row else None


def notification_keys():
    with _connect() as connection:
        rows = connection.execute("SELECT key FROM notifications").fetchall()
    return {row[0] for row in rows}


def save_notifications(notifications):
    """Insert new inbox rows once; return how many were created."""
    if not notifications:
        return 0
    with _connect() as connection:
        placeholder = "%s"
        created = 0
        for entry in notifications:
            cursor = connection.execute(f"""INSERT INTO notifications
                (key, pair_key, recipient, item, score, created_at, email_status)
                VALUES ({placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder}, {placeholder})
                ON CONFLICT (key) DO NOTHING""",
                               (entry["key"], entry["pair_key"], entry["recipient"], entry["item"],
                                entry["score"], entry["time"],
                                "not_applicable" if str(entry["recipient"]).startswith("guest:") else "pending"))
            created += cursor.rowcount
        return created


def load_notifications(recipient, unread_only=False):
    placeholder = "%s"
    query = """SELECT id, key, pair_key, recipient, item, score, created_at, read_at
        , email_status, email_attempted_at, email_sent_at, email_error
        FROM notifications WHERE recipient = """ + placeholder
    params = [str(recipient).strip().casefold()]
    if unread_only:
        query += " AND read_at IS NULL"
    query += " ORDER BY id DESC"
    with _connect() as connection:
        rows = connection.execute(query, params).fetchall()
    columns = ("id", "key", "pair_key", "recipient", "item", "score", "time", "read_at",
               "email_status", "email_attempted_at", "email_sent_at", "email_error")
    return [dict(zip(columns, row)) for row in rows]


def pending_notification_emails():
    with _connect() as connection:
        rows = connection.execute("""SELECT id, key, pair_key, recipient, item, score, created_at
            FROM notifications WHERE email_status = 'pending'
            AND recipient NOT LIKE 'guest:%' ORDER BY id""").fetchall()
    columns = ("id", "key", "pair_key", "recipient", "item", "score", "time")
    return [dict(zip(columns, row)) for row in rows]


def claim_notification_email(notification_id):
    """Atomically claim a pending message so concurrent sessions cannot send twice."""
    attempted_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    with _connect() as connection:
        placeholder = "%s"
        cursor = connection.execute("""UPDATE notifications SET email_status = 'sending',
            email_attempted_at = PLACEHOLDER1, email_error = NULL
            WHERE id = PLACEHOLDER2 AND email_status = 'pending'""".replace(
                "PLACEHOLDER1", placeholder).replace("PLACEHOLDER2", placeholder),
                                       (attempted_at, notification_id))
        return cursor.rowcount == 1


def fail_stuck_notification_emails(stale_after_seconds=120):
    """Turn abandoned SMTP claims into failed entries after the send timeout window."""
    cutoff = (datetime.now(timezone.utc) - timedelta(seconds=stale_after_seconds)).isoformat(timespec="seconds")
    with _connect() as connection:
        placeholder = "%s"
        cursor = connection.execute("""UPDATE notifications SET email_status = 'failed',
            email_error = 'SMTP attempt did not finish; check the inbox before retrying.'
            WHERE email_status = 'sending'
            AND (email_attempted_at IS NULL OR email_attempted_at < PLACEHOLDER)""".replace(
                "PLACEHOLDER", placeholder), (cutoff,))
        return cursor.rowcount


def finish_notification_email(notification_id, status, timestamp=None, error=None):
    if status not in {"sent", "failed"}:
        raise ValueError("Email status must be 'sent' or 'failed'.")
    with _connect() as connection:
        placeholder = "%s"
        connection.execute(f"""UPDATE notifications SET email_status = {placeholder},
            email_sent_at = {placeholder}, email_error = {placeholder} WHERE id = {placeholder}""",
                           (status, timestamp if status == "sent" else None,
                            str(error)[:500] if error else None, notification_id))


def retry_notification_email(notification_id, recipient):
    with _connect() as connection:
        placeholder = "%s"
        cursor = connection.execute(f"""UPDATE notifications SET email_status = 'pending',
            email_error = NULL, email_attempted_at = NULL
            WHERE id = {placeholder} AND recipient = {placeholder} AND email_status = 'failed'""",
                                    (notification_id, str(recipient).strip().casefold()))
        return cursor.rowcount == 1


def mark_notification_read(notification_id, recipient, timestamp):
    with _connect() as connection:
        placeholder = "%s"
        connection.execute(f"""UPDATE notifications SET read_at = {placeholder}
            WHERE id = {placeholder} AND recipient = {placeholder} AND read_at IS NULL""",
                           (timestamp, notification_id, str(recipient).strip().casefold()))


def mark_all_notifications_read(recipient, timestamp):
    with _connect() as connection:
        placeholder = "%s"
        connection.execute(f"""UPDATE notifications SET read_at = {placeholder}
            WHERE recipient = {placeholder} AND read_at IS NULL""",
                           (timestamp, str(recipient).strip().casefold()))
