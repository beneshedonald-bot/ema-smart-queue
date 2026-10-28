import os
import uuid
import datetime
from flask import Flask, render_template, request, redirect, url_for, session, flash
from database.database import get_conn, init_db, is_postgres
from flask_mail import Mail, Message
from datetime import timedelta, datetime as dt
from werkzeug.security import check_password_hash
from functools import wraps

app = Flask(__name__)
app.config['SECRET_KEY'] = os.environ.get("SECRET_KEY", "ema-final-secure-2026")
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(minutes=30)
app.config['MAIL_SERVER'] = 'smtp.gmail.com'
app.config['MAIL_PORT'] = 587
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME", "emaqms@gmail.com")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD", "gzah hfra zthe kksg")
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']
mail = Mail(app)

try:
    init_db()
except Exception as e:
    print(f"DB init: {e}")

def ph(sqlite_q, pg_q):
    return pg_q if is_postgres() else sqlite_q

def get_initials(full_name):
    parts = [p for p in full_name.strip().split() if p]
    if len(parts) >= 2:
        return (parts[0][0] + parts[-1][0]).upper()
    elif parts:
        return parts[0][:2].upper()
    return "XX"

def generate_ema_code(full_name, cur):
    initials = get_initials(full_name)
    try:
        cur.execute("SELECT COUNT(*) FROM patients")
        count = cur.fetchone()[0] + 1
    except:
        count = 1
    # Make sure code is unique
    for i in range(count, count + 100):
        code = f"E{i:02d}{initials}" if i < 100 else f"E{i}{initials}"
        try:
            if is_postgres():
                cur.execute("SELECT id FROM patients WHERE id=%s", (code,))
            else:
                cur.execute("SELECT id FROM patients WHERE id=?", (code,))
            if not cur.fetchone():
                return code
        except:
            return code
    return f"E{count:02d}{initials}"

def generate_queue_no(cur):
    today = dt.now().strftime("%Y-%m-%d")
    try:
        if is_postgres():
            cur.execute("SELECT COUNT(*) FROM queue WHERE DATE(created_at)=%s", (today,))
        else:
            cur.execute("SELECT COUNT(*) FROM queue WHERE DATE(created_at)=?", (today,))
        count = cur.fetchone()[0] + 1
    except:
        count = 1
    return f"NO{count:02d}"

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if "username" not in session:
            flash("Please login first")
            return redirect(url_for("staff_login"))
        session["last_activity"] = dt.now().isoformat()
        return f(*args, **kwargs)
    return decorated

def role_required(*allowed_roles):
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            if "role" not in session:
                return redirect(url_for("staff_login"))
            if session["role"] not in allowed_roles and session["role"] != "admin":
                flash("Access denied")
                return redirect(url_for("staff_dashboard"))
            return f(*args, **kwargs)
        return decorated
    return decorator

def send_approval_email(to_email, patient_name, approved_time, facility):
    if not to_email or "@" not in str(to_email):
        return False, "No email"
    try:
        msg = Message(f"Appointment APPROVED - {facility}", recipients=[to_email])
        msg.body = f"Hi {patient_name},\n\nYour appointment at {facility} is APPROVED.\n\nApproved Time: {approved_time}\nFacility: {facility}\n\nPlease arrive 10 minutes early.\n\nEma! Smart Queue\n"
        mail.send(msg)
        return True, f"Email sent to {to_email}"
    except Exception as e:
        print(f"Email failed: {e}")
        return False, str(e)

def send_call_email(to_email, patient_name, queue_no, facility):
    if not to_email or "@" not in str(to_email):
        return False, "No email"
    try:
        msg = Message(f"Now Calling – Queue {queue_no} – {facility}", recipients=[to_email])
        msg.body = f"Hi {patient_name},\n\nYou are now being CALLED at {facility}.\n\nQueue No: {queue_no}\nFacility: {facility}\n\nPlease proceed to consultation room immediately.\n\nEma! Smart Queue\n"
        mail.send(msg)
        return True, f"Call email sent to {to_email}"
    except Exception as e:
        print(f"Call email failed: {e}")
        return False, str(e)

@app.route("/")
def home_user():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM queue WHERE status IN ('WAITING','CALLED')")
        cnt = cur.fetchone()[0]
    except:
        cnt = 0
    conn.close()
    return render_template("home_user.html", queue_count=cnt)

@app.route("/book", methods=["GET", "POST"])
def book():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM facilities"); facilities = cur.fetchall()
    cur.execute("SELECT * FROM services"); services = cur.fetchall()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        facility_id = request.form.get("facility_id")
        service_id = request.form.get("service_id")
        preferred_date = request.form.get("date", "").strip()  # e.g. 2026-10-29
        # PERMANENT ID LOGIC: Reuse ONLY if full_name + phone + email ALL same
        existing_id = None
        try:
            if full_name and phone and email:
                cur.execute(ph("SELECT id FROM patients WHERE full_name=? AND phone=? AND email=?",
                               "SELECT id FROM patients WHERE full_name=%s AND phone=%s AND email=%s"),
                            (full_name, phone, email))
                r = cur.fetchone()
                if r:
                    existing_id = r["id"] if isinstance(r, dict) else r[0]
        except Exception as e:
            print(f"Lookup error: {e}")

        now = datetime.datetime.now().isoformat()
        if existing_id:
            patient_id = existing_id
            print(f"Reusing existing patient {patient_id}")
        else:
            patient_id = generate_ema_code(full_name, cur)
            cur.execute(ph("INSERT INTO patients VALUES (?,?,?,?,?)",
                           "INSERT INTO patients VALUES (%s,%s,%s,%s,%s)"),
                        (patient_id, full_name, phone, email, now))
            print(f"New patient {patient_id}")

        appt_id = str(uuid.uuid4())
        cur.execute(ph("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       "INSERT INTO appointments VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"),
                    (appt_id, patient_id, facility_id, service_id, preferred_date, "BOOKED", "ONLINE", now, None, None, None, None, now, None, None, None))
        cur.execute(ph("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)",
                       "INSERT INTO audit VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), "BOOKED", appt_id, full_name, full_name, None, "BOOKED", now, f"PatientID:{patient_id}"))
        conn.commit(); conn.close()
        return redirect(url_for("status_view", appt_id=appt_id))
    conn.close()
    return render_template("book.html", facilities=facilities, services=services)

@app.route("/queue")
def queue_public():
    conn = get_conn(); cur = conn.cursor()
    try:
        if is_postgres():
            cur.execute("SELECT q.queue_number, p.full_name, p.id as patient_code, q.status, a.approved_time FROM queue q JOIN appointments a ON q.appointment_id=a.id JOIN patients p ON a.patient_id=p.id WHERE q.status IN ('WAITING','CALLED') AND DATE(q.created_at)=CURRENT_DATE ORDER BY q.created_at")
        else:
            cur.execute("SELECT q.queue_number, p.full_name, p.id as patient_code, q.status, a.approved_time FROM queue q JOIN appointments a ON q.appointment_id=a.id JOIN patients p ON a.patient_id=p.id WHERE q.status IN ('WAITING','CALLED') AND DATE(q.created_at)=DATE('now') ORDER BY q.created_at")
        rows = cur.fetchall()
    except:
        rows = []
    conn.close()
    return render_template("queue_public.html", queue=rows)

@app.route("/status/<appt_id>")
def status_view(appt_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("SELECT a.*, p.full_name, p.id as patient_code, s.name as service_name, f.name as facility_name FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN services s ON a.service_id=s.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=?",
                   "SELECT a.*, p.full_name, p.id as patient_code, s.name as service_name, f.name as facility_name FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN services s ON a.service_id=s.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=%s"), (appt_id,))
    row = cur.fetchone()
    conn.close()
    return render_template("status.html", appt=row, appt_id=appt_id)

@app.route("/staff/login", methods=["GET", "POST"])
def staff_login():
    if request.method == "POST":
        username = request.form.get("username").strip().lower()
        password = request.form.get("password")
        conn = get_conn(); cur = conn.cursor()
        cur.execute(ph("SELECT * FROM users WHERE username=?", "SELECT * FROM users WHERE username=%s"), (username,))
        user = cur.fetchone()
        if user:
            stored_hash = user["password"] if isinstance(user, dict) else user[2]
            try:
                valid = check_password_hash(stored_hash, password)
            except:
                valid = (stored_hash == password)
            if valid:
                cur.execute(ph("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=?",
                               "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=%s"), (username,))
                conn.commit()
                session["username"] = user["username"] if isinstance(user, dict) else user[1]
                session["role"] = user["role"] if isinstance(user, dict) else user[3]
                session["last_activity"] = dt.now().isoformat()
                session.permanent = True
                conn.close()
                return redirect(url_for("staff_dashboard"))
            else:
                flash("Invalid password")
        else:
            flash("Invalid username")
        conn.close()
    return render_template("staff_login.html")

@app.route("/staff/dashboard")
@login_required
def staff_dashboard():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT a.*, p.full_name, p.id as patient_code, s.name as service_name, f.name as facility_name, q.queue_number FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN services s ON a.service_id=s.id LEFT JOIN facilities f ON a.facility_id=f.id LEFT JOIN queue q ON q.appointment_id=a.id ORDER BY a.created_at DESC")
    appts = cur.fetchall()
    timetable = []; booked_times = []
    try:
        if is_postgres():
            cur.execute("SELECT a.approved_time, p.full_name, p.id as patient_code FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED') AND DATE(a.approved_at)=CURRENT_DATE AND a.approved_time IS NOT NULL ORDER BY a.approved_time")
        else:
            cur.execute("SELECT a.approved_time, p.full_name, p.id as patient_code FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED') AND DATE(a.approved_at)=DATE('now') AND a.approved_time IS NOT NULL ORDER BY a.approved_time")
        timetable = cur.fetchall()
        booked_times = [r["approved_time"] if isinstance(r, dict) else r[0] for r in timetable]
    except:
        pass
    conn.close()
    return render_template("staff_dashboard.html", appointments=appts, total_today=len(appts), timetable=timetable, booked_times=booked_times)
 
@app.route("/staff/new-count")
@login_required
def new_count():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM appointments WHERE status='BOOKED'")
        new_booked = cur.fetchone()[0]
        cur.execute("SELECT COUNT(*) FROM appointments WHERE DATE(created_at)=DATE('now') OR DATE(created_at)=CURRENT_DATE")
        today_total = cur.fetchone()[0]
    except:
        new_booked = 0
        today_total = 0
    conn.close()
    return {"new_booked": new_booked, "today_total": today_total}

@app.route("/staff/approve/<appt_id>", methods=["POST"])
@login_required
@role_required("reception", "clinician", "manager", "admin")
def approve(appt_id):
    approved_time = request.form.get("approved_time", "09:00")
    notify = request.form.get("notify", "Call")
    now = datetime.datetime.now().isoformat()
    conn = get_conn(); cur = conn.cursor()
    # Clash check
    try:
        if is_postgres():
            cur.execute("SELECT p.full_name FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.approved_time=%s AND DATE(a.approved_at)=CURRENT_DATE AND a.status!='COMPLETED' AND a.id!=%s", (approved_time, appt_id))
        else:
            cur.execute("SELECT p.full_name FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.approved_time=? AND DATE(a.approved_at)=DATE('now') AND a.status!='COMPLETED' AND a.id!=?", (approved_time, appt_id))
        clash = cur.fetchone()
        if clash:
            cname = clash["full_name"] if isinstance(clash, dict) else clash[0]
            flash(f"CLASH: {approved_time} taken by {cname}")
            conn.close()
            return redirect(url_for("staff_dashboard"))
    except:
        pass
    cur.execute(ph("UPDATE appointments SET status='APPROVED', approved_time=?, approved_at=?, notification_sent=? WHERE id=?",
                   "UPDATE appointments SET status='APPROVED', approved_time=%s, approved_at=%s, notification_sent=%s WHERE id=%s"), (approved_time, now, notify, appt_id))
    # Email approval – restored
    try:
        cur.execute(ph("SELECT p.full_name, p.email, f.name FROM patients p JOIN appointments a ON a.patient_id=p.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=?",
                       "SELECT p.full_name, p.email, f.name FROM patients p JOIN appointments a ON a.patient_id=p.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=%s"), (appt_id,))
        info = cur.fetchone()
        if info:
            pname = info["full_name"] if isinstance(info, dict) else info[0]
            email = info["email"] if isinstance(info, dict) else info[1]
            fname = info["name"] if isinstance(info, dict) else info[2] if len(info) > 2 else "Botho University Clinic"
            if isinstance(info, dict):
                fname = info.get("name") or "Botho University Clinic"
            sent, msg = send_approval_email(email, pname, approved_time, fname)
            detail = f"Time {approved_time} via {notify} - {msg}"
        else:
            detail = f"Time {approved_time}"
    except Exception as e:
        detail = f"Time {approved_time} - {e}"
    cur.execute(ph("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)", "INSERT INTO audit VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"),
                (str(uuid.uuid4()), "APPROVED", appt_id, appt_id, session["username"], "BOOKED", "APPROVED", now, detail))
    conn.commit(); conn.close()
    flash(detail)
    return redirect(url_for("staff_dashboard"))

@app.route("/staff/checkin/<appt_id>", methods=["POST"])
@login_required
@role_required("reception", "clinician", "manager", "admin")
def checkin(appt_id):
    now = datetime.datetime.now().isoformat()
    conn = get_conn(); cur = conn.cursor()
    qnum = generate_queue_no(cur)
    cur.execute(ph("UPDATE appointments SET status='CHECKED_IN', checked_in_at=? WHERE id=?",
                   "UPDATE appointments SET status='CHECKED_IN', checked_in_at=%s WHERE id=%s"), (now, appt_id))
    cur.execute(ph("INSERT INTO queue VALUES (?,?,?,?,?,?,?,?)", "INSERT INTO queue VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"),
                (str(uuid.uuid4()), appt_id, qnum, "WAITING", now, None, None, None))
    cur.execute(ph("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)", "INSERT INTO audit VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"),
                (str(uuid.uuid4()), "CHECKED_IN", appt_id, appt_id, session["username"], "APPROVED", "CHECKED_IN", now, f"Queue {qnum}"))
    conn.commit(); conn.close()
    flash(f"Checked in {qnum}")
    return redirect(url_for("staff_dashboard"))

@app.route("/staff/call/<appt_id>", methods=["POST"])
@login_required
@role_required("reception", "clinician", "manager", "admin")
def call_patient(appt_id):
    now = datetime.datetime.now().isoformat()
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("UPDATE appointments SET status='CALLED', called_at=? WHERE id=?",
                   "UPDATE appointments SET status='CALLED', called_at=%s WHERE id=%s"), (now, appt_id))
    cur.execute(ph("UPDATE queue SET status='CALLED', called_at=? WHERE appointment_id=?",
                   "UPDATE queue SET status='CALLED', called_at=%s WHERE appointment_id=%s"), (now, appt_id))
    # Send email when called
    try:
        cur.execute(ph("SELECT p.full_name, p.email, q.queue_number, f.name FROM patients p JOIN appointments a ON a.patient_id=p.id JOIN queue q ON q.appointment_id=a.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=?",
                       "SELECT p.full_name, p.email, q.queue_number, f.name FROM patients p JOIN appointments a ON a.patient_id=p.id JOIN queue q ON q.appointment_id=a.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=%s"), (appt_id,))
        info = cur.fetchone()
        if info:
            pname = info["full_name"] if isinstance(info, dict) else info[0]
            email = info["email"] if isinstance(info, dict) else info[1]
            qnum = info["queue_number"] if isinstance(info, dict) else info[2]
            fname = info["name"] if isinstance(info, dict) else info[3] if len(info)>3 else "Botho University Clinic"
            if isinstance(info, dict):
                fname = info.get("name") or "Botho University Clinic"
            send_call_email(email, pname, qnum, fname)
    except Exception as e:
        print(f"Call email error: {e}")
    conn.commit(); conn.close()
    flash(f"Called {appt_id} – email sent if exists")
    return redirect(url_for("staff_dashboard"))

@app.route("/staff/complete/<appt_id>", methods=["POST"])
@login_required
@role_required("reception", "clinician", "manager", "admin")
def complete(appt_id):
    now = datetime.datetime.now().isoformat()
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("UPDATE appointments SET status='COMPLETED', completed_at=? WHERE id=?",
                   "UPDATE appointments SET status='COMPLETED', completed_at=%s WHERE id=%s"), (now, appt_id))
    cur.execute(ph("UPDATE queue SET status='COMPLETED', completed_at=? WHERE appointment_id=?",
                   "UPDATE queue SET status='COMPLETED', completed_at=%s WHERE appointment_id=%s"), (now, appt_id))
    conn.commit(); conn.close()
    return redirect(url_for("staff_dashboard"))

@app.route("/staff/walkin", methods=["GET", "POST"])
@login_required
@role_required("reception", "clinician", "manager", "admin")
def walkin():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM facilities"); facilities = cur.fetchall()
    cur.execute("SELECT * FROM services"); services = cur.fetchall()
    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        facility_id = request.form.get("facility_id")
        service_id = request.form.get("service_id")
        existing_id = None
        try:
            cur.execute(ph("SELECT id FROM patients WHERE full_name=? AND phone=? AND email=?",
                           "SELECT id FROM patients WHERE full_name=%s AND phone=%s AND email=%s"),
                        (full_name, phone, email))
            r = cur.fetchone()
            if r:
                existing_id = r["id"] if isinstance(r, dict) else r[0]
        except:
            pass
        now = datetime.datetime.now().isoformat()
        if existing_id:
            patient_id = existing_id
        else:
            patient_id = generate_ema_code(full_name, cur)
            cur.execute(ph("INSERT INTO patients VALUES (?,?,?,?,?)",
                           "INSERT INTO patients VALUES (%s,%s,%s,%s,%s)"), (patient_id, full_name, phone, email, now))
        appt_id = str(uuid.uuid4())
        cur.execute(ph("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                       "INSERT INTO appointments VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"),
                    (appt_id, patient_id, facility_id, service_id, None, "CHECKED_IN", "WALKIN", now, None, None, None, None, now, None, None, None))
        qnum = generate_queue_no(cur)
        cur.execute(ph("INSERT INTO queue VALUES (?,?,?,?,?,?,?,?)",
                       "INSERT INTO queue VALUES (%s,%s,%s,%s,%s,%s,%s,%s)"),
                    (str(uuid.uuid4()), appt_id, qnum, "WAITING", now, None, None, None))
        conn.commit(); conn.close()
        flash(f"Walk-in {patient_id} {qnum}")
        return redirect(url_for("staff_dashboard"))
    conn.close()
    return render_template("walkin.html", facilities=facilities, services=services)

@app.route("/staff/reports")
@login_required
@role_required("reception", "clinician", "manager", "admin")
def reports():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) as c FROM appointments GROUP BY status"); by_status = cur.fetchall()
    cur.execute("SELECT s.name, COUNT(*) as c FROM appointments a JOIN services s ON a.service_id=s.id GROUP BY s.name"); by_service = cur.fetchall()
    cur.execute("SELECT * FROM audit ORDER BY timestamp DESC LIMIT 40"); activity = cur.fetchall()
    conn.close()
    return render_template("reports.html", by_status=by_status, by_service=by_service, activity=activity)

@app.route("/staff/users", methods=["GET", "POST"])
@login_required
@role_required("admin")
def manage_users():
    conn = get_conn(); cur = conn.cursor()
    if request.method == "POST":
        action = request.form.get("action")
        if action == "add":
            username = request.form.get("username").strip().lower()
            password = request.form.get("password")
            role = request.form.get("role")
            name = request.form.get("name") or username
            if username and password and role:
                from werkzeug.security import generate_password_hash
                hashed = generate_password_hash(password)
                cur.execute(ph("INSERT INTO users VALUES (?,?,?,?,?,?,?)",
                               "INSERT INTO users VALUES (%s,%s,%s,%s,%s,%s,%s)"),
                            (str(uuid.uuid4()), username, hashed, role, name, 0, None))
                conn.commit()
                flash(f"User {username} created")
    cur.execute("SELECT username, role, name FROM users ORDER BY role, username")
    users = cur.fetchall()
    conn.close()
    return render_template("staff_users.html", users=users)

@app.route("/staff/logout")
def staff_logout():
    session.clear()
    return redirect(url_for("staff_login"))

if __name__ == "__main__":
    init_db()
    port = int(os.environ.get("PORT", 5000))
    app.run(host="0.0.0.0", port=port, debug=False)