import os
import sqlite3
import uuid
import datetime
from werkzeug.security import generate_password_hash

DB_PATH = "ema.db"

def is_postgres():
    return os.environ.get("DATABASE_URL","").startswith("postgres")

def get_conn():
    if is_postgres():
        import psycopg2
        return psycopg2.connect(os.environ.get("DATABASE_URL"))
    else:
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        return conn

def ph(sqlite_sql, pg_sql):
    return pg_sql if is_postgres() else sqlite_sql

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    cur.execute("CREATE TABLE IF NOT EXISTS patients (id TEXT PRIMARY KEY, full_name TEXT NOT NULL, phone TEXT, email TEXT, created_at TEXT)")

    cur.execute("CREATE TABLE IF NOT EXISTS staff_notify_emails (id TEXT PRIMARY KEY, email TEXT NOT NULL UNIQUE, role TEXT, created_at TEXT)")
    cur.execute("SELECT COUNT(*) FROM staff_notify_emails")
    if cur.fetchone()[0]==0:
        cur.execute(ph("INSERT INTO staff_notify_emails VALUES (?,?,?,?)",
                       "INSERT INTO staff_notify_emails VALUES (%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), "emaqms42@gmail.com", "admin", datetime.datetime.now().isoformat()))

    cur.execute("CREATE TABLE IF NOT EXISTS services (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    cur.execute("SELECT COUNT(*) FROM services")
    if cur.fetchone()[0]==0:
        cur.execute(ph("INSERT INTO services VALUES (?,?)",
                       "INSERT INTO services VALUES (%s,%s)"),
                    (str(uuid.uuid4()), "General Consultation"))

    cur.execute("CREATE TABLE IF NOT EXISTS facilities (id TEXT PRIMARY KEY, name TEXT NOT NULL)")
    cur.execute("SELECT COUNT(*) FROM facilities")
    if cur.fetchone()[0]==0:
        cur.execute(ph("INSERT INTO facilities VALUES (?,?)",
                       "INSERT INTO facilities VALUES (%s,%s)"),
                    (str(uuid.uuid4()), "Botho University Clinic"))

    cur.execute("""
        CREATE TABLE IF NOT EXISTS appointments (
            id TEXT PRIMARY KEY,
            patient_id TEXT,
            facility_id TEXT,
            service_id TEXT,
            preferred_date TEXT,
            status TEXT,
            booking_type TEXT,
            created_at TEXT,
            approved_time TEXT,
            approved_at TEXT,
            checked_in_at TEXT,
            called_at TEXT,
            completed_at TEXT,
            notification_sent TEXT,
            extra1 TEXT,
            extra2 TEXT
        )
    """)

    cur.execute("CREATE TABLE IF NOT EXISTS queue (id TEXT PRIMARY KEY, appointment_id TEXT, queue_number TEXT, status TEXT, created_at TEXT, called_at TEXT)")

    cur.execute("CREATE TABLE IF NOT EXISTS audit (id TEXT PRIMARY KEY, action TEXT, appointment_id TEXT, reference TEXT, user TEXT, from_status TEXT, to_status TEXT, timestamp TEXT, detail TEXT)")

    cur.execute("CREATE TABLE IF NOT EXISTS users (id TEXT PRIMARY KEY, username TEXT NOT NULL UNIQUE, password_hash TEXT NOT NULL, role TEXT NOT NULL, failed_attempts INTEGER DEFAULT 0, locked_until TEXT)")
    cur.execute("SELECT COUNT(*) FROM users")
    if cur.fetchone()[0]==0:
        cur.execute(ph("INSERT INTO users VALUES (?,?,?,?,?,?)",
                       "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), "admin", generate_password_hash("Admin@ema.4040"), "admin", 0, None))
        cur.execute(ph("INSERT INTO users VALUES (?,?,?,?,?,?)",
                       "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), "reception", generate_password_hash("BUclinic123"), "reception", 0, None))
        cur.execute(ph("INSERT INTO users VALUES (?,?,?,?,?,?)",
                       "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), "clinician", generate_password_hash("BUclinic123"), "clinician", 0, None))
        cur.execute(ph("INSERT INTO users VALUES (?,?,?,?,?,?)",
                       "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), "dumisane", generate_password_hash("Manager@ema.123"), "manager", 0, None))

    conn.commit()
    conn.close()
    print("DB init done - FINAL: users 6cols, appointments 16cols, staff_emails with emaqms@gmail.com")