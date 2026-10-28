import os
import sqlite3
from werkzeug.security import generate_password_hash

# Use Render Postgres if DATABASE_URL exists, else local SQLite
DATABASE_URL = os.environ.get("DATABASE_URL")
DB_PATH = os.path.join(os.path.dirname(__file__), "..", "ema.db")

def is_postgres():
    return DATABASE_URL is not None and DATABASE_URL.startswith("postgres")

def get_conn():
    if is_postgres():
        import psycopg2
        import psycopg2.extras
        conn = psycopg2.connect(DATABASE_URL)
        return conn
    else:
        conn = sqlite3.connect(DB_PATH, timeout=15, check_same_thread=False)
        conn.execute("PRAGMA journal_mode=WAL;")
        conn.execute("PRAGMA busy_timeout=15000;")
        conn.row_factory = sqlite3.Row
        return conn

def init_db():
    conn = get_conn()
    cur = conn.cursor()

    # ---------- PATIENTS - Permanent ID E01DB ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                created_at TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS patients (
                id TEXT PRIMARY KEY,
                full_name TEXT NOT NULL,
                phone TEXT,
                email TEXT,
                created_at TEXT
            )
        """)

    # ---------- FACILITIES ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS facilities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS facilities (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                location TEXT
            )
        """)

    # ---------- SERVICES ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                duration INTEGER
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS services (
                id TEXT PRIMARY KEY,
                name TEXT NOT NULL,
                duration INTEGER
            )
        """)

    # ---------- APPOINTMENTS ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                patient_id TEXT REFERENCES patients(id),
                facility_id TEXT,
                service_id TEXT,
                preferred_time TEXT,
                status TEXT,
                booking_type TEXT,
                created_at TEXT,
                approved_time TEXT,
                approved_at TEXT,
                checked_in_at TEXT,
                called_at TEXT,
                completed_at TEXT,
                notification_sent TEXT,
                created_date TEXT,
                updated_at TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS appointments (
                id TEXT PRIMARY KEY,
                patient_id TEXT,
                facility_id TEXT,
                service_id TEXT,
                preferred_time TEXT,
                status TEXT,
                booking_type TEXT,
                created_at TEXT,
                approved_time TEXT,
                approved_at TEXT,
                checked_in_at TEXT,
                called_at TEXT,
                completed_at TEXT,
                notification_sent TEXT,
                created_date TEXT,
                updated_at TEXT
            )
        """)

    # ---------- QUEUE - Daily NO01 ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id TEXT PRIMARY KEY,
                appointment_id TEXT,
                queue_number TEXT,
                status TEXT,
                created_at TEXT,
                called_at TEXT,
                completed_at TEXT,
                updated_at TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS queue (
                id TEXT PRIMARY KEY,
                appointment_id TEXT,
                queue_number TEXT,
                status TEXT,
                created_at TEXT,
                called_at TEXT,
                completed_at TEXT,
                updated_at TEXT
            )
        """)

    # ---------- USERS - Secure with hash + lockout ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                name TEXT,
                failed_attempts INTEGER DEFAULT 0,
                locked_until TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                username TEXT UNIQUE NOT NULL,
                password TEXT NOT NULL,
                role TEXT NOT NULL,
                name TEXT,
                failed_attempts INTEGER DEFAULT 0,
                locked_until TEXT
            )
        """)

    # ---------- AUDIT ----------
    if is_postgres():
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id TEXT PRIMARY KEY,
                action TEXT,
                entity_id TEXT,
                entity_name TEXT,
                actor TEXT,
                old_status TEXT,
                new_status TEXT,
                timestamp TEXT,
                details TEXT
            )
        """)
    else:
        cur.execute("""
            CREATE TABLE IF NOT EXISTS audit (
                id TEXT PRIMARY KEY,
                action TEXT,
                entity_id TEXT,
                entity_name TEXT,
                actor TEXT,
                old_status TEXT,
                new_status TEXT,
                timestamp TEXT,
                details TEXT
            )
        """)

    # ---------- SEED FACILITIES ----------
    try:
        if is_postgres():
            cur.execute("SELECT COUNT(*) FROM facilities")
            count = cur.fetchone()[0]
            if count == 0:
                cur.execute("INSERT INTO facilities VALUES (%s,%s,%s)", ("f1", "Botho University Clinic", "Maseru"))
        else:
            cur.execute("SELECT COUNT(*) FROM facilities")
            count = cur.fetchone()[0]
            if count == 0:
                cur.execute("INSERT INTO facilities VALUES (?,?,?)", ("f1", "Botho University Clinic", "Maseru"))
    except Exception as e:
        print(f"Facility seed error: {e}")

    # ---------- SEED SERVICES ----------
    try:
        if is_postgres():
            cur.execute("SELECT COUNT(*) FROM services")
            count = cur.fetchone()[0]
            if count == 0:
                cur.execute("INSERT INTO services VALUES (%s,%s,%s)", ("s1", "General Consultation", 15))
                cur.execute("INSERT INTO services VALUES (%s,%s,%s)", ("s2", "Follow-up", 10))
        else:
            cur.execute("SELECT COUNT(*) FROM services")
            count = cur.fetchone()[0]
            if count == 0:
                cur.execute("INSERT INTO services VALUES (?,?,?)", ("s1", "General Consultation", 15))
                cur.execute("INSERT INTO services VALUES (?,?,?)", ("s2", "Follow-up", 10))
    except Exception as e:
        print(f"Service seed error: {e}")

    # ---------- SEED 8 SECURE USERS - KEEP YOUR EXACT PASSWORDS ----------
    import uuid
    users_seed = [
        ("admin", "Admin@ema.4040", "admin", "Admin"),
        ("dumisane", "Manager@ema.123", "manager", "Dumisane Beneshe"),
        ("lemohang", "Manager@ema.123", "manager", "Lemohang"),
        ("lerato", "Manager@ema.123", "manager", "Lerato"),
        ("mamoabi", "Manager@ema.123", "manager", "Mamoabi"),
        ("nteboheleng", "Manager@ema.123", "manager", "Nteboheleng"),
        ("reception", "BUclinic123", "reception", "Reception"),
        ("clinician", "BUclinic123", "clinician", "Clinician"),
    ]

    for username, plain_password, role, name in users_seed:
        try:
            if is_postgres():
                cur.execute("SELECT * FROM users WHERE username=%s", (username,))
            else:
                cur.execute("SELECT * FROM users WHERE username=?", (username,))
            exists = cur.fetchone()
            if not exists:
                hashed = generate_password_hash(plain_password)
                if is_postgres():
                    cur.execute("INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s,%s)", (str(uuid.uuid4()), username, hashed, role, name, 0, None))
                else:
                    cur.execute("INSERT INTO users VALUES (?,?,?,?,?,?,?)", (str(uuid.uuid4()), username, hashed, role, name, 0, None))
                print(f"Created user {username} ({role})")
            else:
                # Update to ensure hashed and unlocked
                hashed = generate_password_hash(plain_password)
                if is_postgres():
                    cur.execute("UPDATE users SET password=%s, role=%s, name=%s, failed_attempts=0, locked_until=NULL WHERE username=%s", (hashed, role, name, username))
                else:
                    cur.execute("UPDATE users SET password=?, role=?, name=?, failed_attempts=0, locked_until=NULL WHERE username=?", (hashed, role, name, username))
                print(f"Updated user {username} ({role}) - unlocked")
        except Exception as e:
            print(f"User seed {username} error: {e}")

    conn.commit()
    conn.close()
    print("DB initialized - 8 users ready, facility seeded")

if __name__ == "__main__":
    init_db()
