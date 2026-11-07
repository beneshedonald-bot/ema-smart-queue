import os, uuid, datetime, threading
from dotenv import load_dotenv
load_dotenv()
import resend
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify, session
from flask_mail import Mail, Message
from werkzeug.security import check_password_hash
from functools import wraps
from database.database import get_conn, init_db, ph

# SendGrid for Render live (HTTP API - not blocked) + Resend
try:
    from sendgrid import SendGridAPIClient
    from sendgrid.helpers.mail import Mail as SGMail
    SENDGRID_AVAILABLE = True
except:
    SENDGRID_AVAILABLE = False

app = Flask(__name__)
app.secret_key = os.environ.get("SECRET_KEY", "ema-secret-key-2024")
app.config['MAIL_SERVER'] = os.environ.get("MAIL_SERVER", "smtp.gmail.com")
app.config['MAIL_PORT'] = int(os.environ.get("MAIL_PORT", 587))
app.config['MAIL_USE_TLS'] = True
app.config['MAIL_USERNAME'] = os.environ.get("MAIL_USERNAME", "noreply@emasmarqueue.com")
app.config['MAIL_PASSWORD'] = os.environ.get("MAIL_PASSWORD", "")
app.config['MAIL_DEFAULT_SENDER'] = app.config['MAIL_USERNAME']
mail = Mail(app)

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if 'user_id' not in session:
            return redirect(url_for('staff_login'))
        return f(*args, **kwargs)
    return decorated

# ========== EMAIL FUNCTIONS (Resend + SendGrid + Gmail) ==========
def send_email_async(app_obj, msg):
    with app_obj.app_context():
        try:
            mail.send(msg)
            print(f"Email OK to {msg.recipients}")
        except Exception as e:
            print(f"Email FAILED: {e}")

def send_via_sendgrid(to_emails, subject, body):
    # ===== NEW: Try Resend FIRST (noreply@emasmarqueue.com → Inbox) =====
    resend_key = os.environ.get("RESEND_API_KEY")
    if resend_key:
        try:
            resend.api_key = resend_key
            from_email = os.environ.get("MAIL_USERNAME", "noreply@emasmarqueue.com")
            if "<" not in from_email:
                from_email = f"EMA Smart Queue <{from_email}>"
            if isinstance(to_emails, str):
                to_list = [to_emails]
            else:
                to_list = to_emails
            params = {"from": from_email, "to": to_list, "subject": subject, "html": body}
            email = resend.Emails.send(params)
            print(f"Email OK via Resend to {to_emails} id {email.get('id')}")
            return True, f"Resend {email.get('id')}"
        except Exception as e:
            print(f"Resend FAILED: {e}, trying SendGrid...")
    
    if not SENDGRID_AVAILABLE:
        return False, "SendGrid not installed"
    api_key = os.environ.get("SENDGRID_API_KEY")
    if not api_key:
        return False, "No SENDGRID_API_KEY - using Gmail fallback"
    if isinstance(to_emails, str):
        to_emails = [to_emails]
    from_email = os.environ.get("MAIL_USERNAME", "noreply@emasmarqueue.com")
    message = SGMail(
        from_email=from_email,
        to_emails=to_emails,
        subject=subject,
        html_content=body
    )
    try:
        sg = SendGridAPIClient(api_key)
        response = sg.send(message)
        print(f"Email OK via SendGrid to {to_emails} status {response.status_code}")
        return True, f"SendGrid {response.status_code}"
    except Exception as e:
        print(f"SendGrid FAILED: {e}")
        return False, str(e)

def send_approval_email(to_email, patient_name, approved_time, facility, queue_no="", line=""):
    if not to_email or "@" not in str(to_email): return False, "No email"
    subject = f"Appointment APPROVED - {facility} - {queue_no} {line}"
    body = f"Hi {patient_name},\n\nYour appointment at {facility} is APPROVED.\nApproved Time: {approved_time}\n{line} - Queue No: {queue_no}\nFacility: {facility}\nPlease arrive 2 min early.\nCheck your position: https://emasmarqueue.com/status/\n\nEma! Smart Queue\n"
    ok, _ = send_via_sendgrid(to_email, subject, body)
    if ok: return True, "SendGrid"
    try:
        msg = Message(subject, recipients=[to_email])
        msg.body = body
        threading.Thread(target=send_email_async, args=(app, msg), daemon=True).start()
        return True, "queued Gmail"
    except Exception as e:
        print(f"Approval email fail: {e}"); return False, str(e)

def send_call_email(to_email, patient_name, queue_no, facility):
    if not to_email or "@" not in str(to_email): return False, "No email"
    subject = f"Now Calling – Queue {queue_no} – {facility}"
    body = f"Hi {patient_name},\nYou are now CALLED at {facility}.\nQueue No: {queue_no}\nPlease proceed now.\n\nEma! Smart Queue\n"
    ok, _ = send_via_sendgrid(to_email, subject, body)
    if ok: return True, "SendGrid"
    try:
        msg = Message(subject, recipients=[to_email])
        msg.body = body
        threading.Thread(target=send_email_async, args=(app, msg), daemon=True).start()
        return True, "queued Gmail"
    except Exception as e:
        print(f"Call email fail: {e}"); return False, str(e)

def send_staff_new_booking_email(patient_name, patient_id, booked_date, service):
    try:
        conn = get_conn(); cur = conn.cursor()
        try:
            cur.execute("SELECT email FROM staff_notify_emails")
            rows = cur.fetchall()
            staff_emails = [r[0] for r in rows] if rows else ["beneshedonald@icloud.com"]
        except: staff_emails = ["beneshedonald@icloud.com"]
        conn.close()
        if not staff_emails: staff_emails = ["beneshedonald@icloud.com"]
        subject = f"NEW BOOKING – {patient_name} – {patient_id} – {booked_date}"
        body = f"New patient booked\nPatient: {patient_name}\nID: {patient_id}\nDate: {booked_date}\nService: {service}\nApprove: https://emasmarqueue.com/staff/login\n\nEma! Smart Queue\n"
        ok, _ = send_via_sendgrid(staff_emails, subject, body)
        if ok:
            print(f"Staff notify via Resend/SendGrid to {staff_emails}")
            return True
        msg = Message(subject, recipients=staff_emails)
        msg.body = body
        threading.Thread(target=send_email_async, args=(app, msg), daemon=True).start()
        print(f"Staff notify via Gmail to {staff_emails}")
        return True
    except Exception as e:
        print(f"Staff notify failed: {e}"); return False

# ========== ROUTES ==========
@app.route("/")
def home_user():
    conn = get_conn(); cur = conn.cursor()
    try:
        cur.execute("SELECT COUNT(*) FROM queue WHERE status!='COMPLETED' AND date(created_at)=date('now','localtime')")
        qcount = cur.fetchone()[0]
    except: qcount = 0
    conn.close()
    return render_template("home_user.html", queue_count=qcount)

@app.route("/book", methods=["GET", "POST"])
def book():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM facilities"); facilities = cur.fetchall()
    cur.execute("SELECT * FROM services"); services = cur.fetchall()
    if request.method=="POST":
        full_name = request.form.get("full_name","").strip()
        phone = request.form.get("phone","").strip()
        email = request.form.get("email","").strip().lower()
        preferred_date = request.form.get("preferred_date","").strip() or request.form.get("date","").strip()
        facility_id = request.form.get("facility_id")
        service_id = request.form.get("service_id")
        if not full_name or not preferred_date:
            flash("Name and date required"); conn.close()
            return render_template("book.html", facilities=facilities, services=services)
        now = datetime.datetime.now().isoformat()
        cur.execute(ph("SELECT id FROM patients WHERE full_name=? AND phone=? AND email=?", "SELECT id FROM patients WHERE full_name=%s AND phone=%s AND email=%s"), (full_name, phone, email))
        row = cur.fetchone()
        if row: patient_id = row[0]
        else:
            cur.execute("SELECT COUNT(*) FROM patients"); count = cur.fetchone()[0]
            patient_id = f"E{count+1:02d}DB"
            cur.execute(ph("INSERT INTO patients VALUES (?,?,?,?,?)", "INSERT INTO patients VALUES (%s,%s,%s,%s,%s)"), (patient_id, full_name, phone, email, now))
        appt_id = str(uuid.uuid4())
        cur.execute(ph("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", "INSERT INTO appointments VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"), (appt_id, patient_id, facility_id, service_id, preferred_date, "BOOKED", "ONLINE", now, None, None, None, None, now, None, None, None))
        cur.execute(ph("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)", "INSERT INTO audit VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"), (str(uuid.uuid4()), "BOOK", appt_id, patient_id, "patient", None, "BOOKED", now, f"Booked {preferred_date}"))
        try: conn.commit()
        except: conn.rollback()
        try: send_staff_new_booking_email(full_name, patient_id, preferred_date, "General")
        except Exception as e: print(f"Staff notify error: {e}")
        conn.close()
        return redirect(url_for("status_view", appt_id=appt_id))
    conn.close()
    return render_template("book.html", facilities=facilities, services=services)

@app.route("/status/<appt_id>")
def status_view(appt_id):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("SELECT a.*, p.full_name, p.phone, p.email, p.id as patient_code, f.name as facility_name, s.name as service_name FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN facilities f ON a.facility_id=f.id LEFT JOIN services s ON a.service_id=s.id WHERE a.id=?", "SELECT a.*, p.full_name, p.phone, p.email, p.id as patient_code, f.name as facility_name, s.name as service_name FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN facilities f ON a.facility_id=f.id LEFT JOIN services s ON a.service_id=s.id WHERE a.id=%s"), (appt_id,))
    appt = cur.fetchone()
    if not appt:
        conn.close()
        flash("Not found"); return redirect(url_for("home_user"))
    # --- Way 2 + 3: Position in YOUR line only ---
    # appt tuple: 0=id, 3=service_id, 4=preferred_date, 8=approved_time (check your INSERT order)
    # Get queue_number for this booking
    cur.execute(ph("SELECT queue_number FROM queue WHERE appointment_id=?", "SELECT queue_number FROM queue WHERE appointment_id=%s"), (appt_id,))
    qrow = cur.fetchone()
    queue_no = qrow[0] if qrow else None
    position = None
    line = None
    if queue_no and str(queue_no).startswith("L1"):
        line = "LINE 1"
        prefix = "L1-%"
    elif queue_no and str(queue_no).startswith("L2"):
        line = "LINE 2"
        prefix = "L2-%"
    else:
        line = None
        prefix = None
    if line:
        # approved_time is appt[8] in your INSERT (approved_time column)
        try:
            my_time = appt[8]
            my_date = appt[4]
            cur.execute(ph("SELECT COUNT(*) FROM appointments a JOIN queue q ON q.appointment_id=a.id WHERE a.preferred_date=? AND q.queue_number LIKE ? AND a.approved_time IS NOT NULL AND a.approved_time < ? AND a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED')", "SELECT COUNT(*) FROM appointments a JOIN queue q ON q.appointment_id=a.id WHERE a.preferred_date=%s AND q.queue_number LIKE %s AND a.approved_time IS NOT NULL AND a.approved_time < %s AND a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED')"), (my_date, prefix, my_time))
            ahead = cur.fetchone()[0]
            position = ahead + 1
        except Exception as e:
            print(f"Position calc failed: {e}")
            position = None
    conn.close()
    return render_template("status.html", appt=appt, position=position, line=line, queue_no=queue_no)

@app.route("/queue")
def queue_public():
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("SELECT q.queue_number, q.status, q.created_at, a.approved_time, p.id as patient_code FROM queue q JOIN appointments a ON q.appointment_id=a.id JOIN patients p ON a.patient_id=p.id WHERE date(a.preferred_date)=date('now','localtime') AND q.status!='COMPLETED' ORDER BY q.queue_number ASC, a.approved_time ASC", "SELECT q.queue_number, q.status, q.created_at, a.approved_time, p.id as patient_code FROM queue q JOIN appointments a ON q.appointment_id=a.id JOIN patients p ON a.patient_id=p.id WHERE a.preferred_date::date=CURRENT_DATE AND q.status!='COMPLETED' ORDER BY q.queue_number ASC, a.approved_time ASC"))
    queue = cur.fetchall(); conn.close()
    # Split into Line 1 and Line 2 - NO service shown for confidentiality
    line1 = [r for r in queue if str(r[0]).startswith("L1")]
    line2 = [r for r in queue if str(r[0]).startswith("L2")]
    # Old bookings with NOxx (no L prefix) go to Line 1 so they still show
    old = [r for r in queue if not str(r[0]).startswith("L1") and not str(r[0]).startswith("L2")]
    line1 = old + line1
    return render_template("queue_public.html", queue=queue, line1=line1, line2=line2)

@app.route("/staff/login", methods=["GET","POST"])
def staff_login():
    if request.method=="POST":
        username = request.form.get("username","").strip(); password = request.form.get("password","")
        conn = get_conn(); cur = conn.cursor()
        cur.execute(ph("SELECT * FROM users WHERE username=?", "SELECT * FROM users WHERE username=%s"), (username,))
        user = cur.fetchone()
        if not user: flash("Invalid username"); conn.close(); return render_template("staff_login.html")
        locked_until = user[5]
        if locked_until:
            try:
                lt = datetime.datetime.fromisoformat(locked_until)
                if datetime.datetime.now() < lt: flash(f"Locked until {locked_until}"); conn.close(); return render_template("staff_login.html")
            except: pass
        if check_password_hash(user[2], password):
            cur.execute(ph("UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=?", "UPDATE users SET failed_attempts=0, locked_until=NULL WHERE username=%s"), (username,)); conn.commit()
            session['user_id']=user[0]; session['username']=user[1]; session['role']=user[3]; conn.close()
            return redirect(url_for('staff_dashboard'))
        else:
            failed = (user[4] or 0)+1
            if failed>=5:
                lock_time = (datetime.datetime.now()+datetime.timedelta(minutes=15)).isoformat()
                cur.execute(ph("UPDATE users SET failed_attempts=?, locked_until=? WHERE username=?", "UPDATE users SET failed_attempts=%s, locked_until=%s WHERE username=%s"), (failed, lock_time, username)); flash("Locked 15 min")
            else: cur.execute(ph("UPDATE users SET failed_attempts=? WHERE username=?", "UPDATE users SET failed_attempts=%s WHERE username=%s"), (failed, username)); flash(f"Invalid {failed}/5")
            conn.commit(); conn.close(); return render_template("staff_login.html")
    return render_template("staff_login.html")

@app.route("/staff/logout")
def staff_logout(): session.clear(); return redirect(url_for('staff_login'))

@app.route("/staff/dashboard")
@login_required
def staff_dashboard():
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("SELECT a.id, a.status, a.preferred_date as preferred_time, a.created_at, a.approved_time, q.queue_number, p.id as patient_code, p.full_name, s.name as service_name FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN queue q ON q.appointment_id=a.id LEFT JOIN services s ON a.service_id=s.id WHERE a.status!='COMPLETED' ORDER BY CASE a.status WHEN 'BOOKED' THEN 1 WHEN 'APPROVED' THEN 2 WHEN 'CHECKED_IN' THEN 3 WHEN 'CALLED' THEN 4 ELSE 5 END, a.created_at DESC", "SELECT a.id, a.status, a.preferred_date as preferred_time, a.created_at, a.approved_time, q.queue_number, p.id as patient_code, p.full_name, s.name as service_name FROM appointments a JOIN patients p ON a.patient_id=p.id LEFT JOIN queue q ON q.appointment_id=a.id LEFT JOIN services s ON a.service_id=s.id WHERE a.status!='COMPLETED' ORDER BY CASE a.status WHEN 'BOOKED' THEN 1 WHEN 'APPROVED' THEN 2 WHEN 'CHECKED_IN' THEN 3 WHEN 'CALLED' THEN 4 ELSE 5 END, a.created_at DESC"))
    appointments = cur.fetchall(); conn.close()
    return render_template("staff_dashboard.html", appointments=appointments)

@app.route("/staff/new-count")
@login_required
def new_count():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM appointments WHERE status='BOOKED'")
    count = cur.fetchone()[0]; conn.close()
    return jsonify({"new_booked": count, "count": count})

@app.route("/staff/approve/<appt_id>", methods=["POST"])
@login_required
def approve(appt_id):
    conn = get_conn(); cur = conn.cursor()
    try:
        approved_time = request.form.get("approved_time","09:00")
        cur.execute(ph("SELECT a.*, p.full_name, p.email FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.id=?", "SELECT a.*, p.full_name, p.email FROM appointments a JOIN patients p ON a.patient_id=p.id WHERE a.id=%s"), (appt_id,))
        row = cur.fetchone()
        if not row: flash("Not found"); conn.close(); return redirect(url_for('staff_dashboard'))
        # row tuple: a.* = 16 cols, then full_name, email. service_id = row[3], preferred_date = row[4]
        service_id = row[3]
        preferred_date = row[4]
        # Get service name
        cur.execute(ph("SELECT name FROM services WHERE id=?", "SELECT name FROM services WHERE id=%s"), (service_id,))
        srow = cur.fetchone()
        service_name = srow[0] if srow else ""

        # --- ASSIGN LINE ---
        if service_name == "COUNSELING SERVICES":
            line = "LINE 2"
            prefix = "L2"
        elif service_name == "HIV TESTING SERVICES":
            # HIV -> shorter line wins, all 3 nurses do HIV
            cur.execute(ph("SELECT COUNT(*) FROM queue q JOIN appointments a ON q.appointment_id=a.id WHERE a.preferred_date=? AND q.queue_number LIKE 'L1-%' AND a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED')", "SELECT COUNT(*) FROM queue q JOIN appointments a ON q.appointment_id=a.id WHERE a.preferred_date=%s AND q.queue_number LIKE 'L1-%%' AND a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED')"), (preferred_date,))
            l1_count = cur.fetchone()[0]
            cur.execute(ph("SELECT COUNT(*) FROM queue q JOIN appointments a ON q.appointment_id=a.id WHERE a.preferred_date=? AND q.queue_number LIKE 'L2-%' AND a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED')", "SELECT COUNT(*) FROM queue q JOIN appointments a ON q.appointment_id=a.id WHERE a.preferred_date=%s AND q.queue_number LIKE 'L2-%%' AND a.status IN ('APPROVED','CHECKED_IN','WAITING','CALLED')"), (preferred_date,))
            l2_count = cur.fetchone()[0]
            if l2_count < l1_count:
                line = "LINE 2"; prefix = "L2"
            else:
                line = "LINE 1"; prefix = "L1"
        else:
            # GENERAL, ART, PREP & PEP, CONTRACEPTIVES, CANCER
            line = "LINE 1"; prefix = "L1"

        # --- DENY if time goes backwards IN SAME LINE ONLY ---
        cur.execute(ph("SELECT MAX(a.approved_time) FROM appointments a JOIN queue q ON q.appointment_id=a.id WHERE a.preferred_date=? AND q.queue_number LIKE ? AND a.approved_time IS NOT NULL", "SELECT MAX(a.approved_time) FROM appointments a JOIN queue q ON q.appointment_id=a.id WHERE a.preferred_date=%s AND q.queue_number LIKE %s AND a.approved_time IS NOT NULL"), (preferred_date, f"{prefix}-%"))
        last_time_row = cur.fetchone()
        last_time = last_time_row[0] if last_time_row else None
        if last_time and approved_time and approved_time < last_time:
            conn.close()
            flash(f"DENIED! {approved_time} is earlier than last {line} time {last_time}. Pick a time AFTER {last_time} for {line}.")
            return redirect(url_for('staff_dashboard'))

        now = datetime.datetime.now().isoformat()
        cur.execute(ph("UPDATE appointments SET status='APPROVED', approved_time=?, approved_at=? WHERE id=?", "UPDATE appointments SET status='APPROVED', approved_time=%s, approved_at=%s WHERE id=%s"), (approved_time, now, appt_id))
        # --- AUTO Queue Number PER LINE ---
        cur.execute(ph("SELECT COUNT(*) FROM queue q JOIN appointments a ON q.appointment_id=a.id WHERE a.preferred_date=? AND q.queue_number LIKE ?", "SELECT COUNT(*) FROM queue q JOIN appointments a ON q.appointment_id=a.id WHERE a.preferred_date=%s AND q.queue_number LIKE %s"), (preferred_date, f"{prefix}-%"))
        qcount_in_line = cur.fetchone()[0]
        queue_no = f"{prefix}-NO{qcount_in_line+1:02d}"; qid = str(uuid.uuid4())
        cur.execute(ph("INSERT INTO queue VALUES (?,?,?,?,?,?)", "INSERT INTO queue VALUES (%s,%s,%s,%s,%s,%s)"), (qid, appt_id, queue_no, "WAITING", now, None))
        cur.execute(ph("INSERT INTO audit VALUES (?,?,?,?,?,?,?,?,?)", "INSERT INTO audit VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)"), (str(uuid.uuid4()), "APPROVE", appt_id, queue_no, session.get('username'), "BOOKED", "APPROVED", now, f"Approved {approved_time} {line}"))
        conn.commit()
        try:
            conn2 = get_conn(); c2 = conn2.cursor()
            c2.execute(ph("SELECT p.email, p.full_name FROM patients p JOIN appointments a ON a.patient_id=p.id WHERE a.id=?", "SELECT p.email, p.full_name FROM patients p JOIN appointments a ON a.patient_id=p.id WHERE a.id=%s"), (appt_id,))
            pr = c2.fetchone()
            if pr: send_approval_email(pr[0], pr[1], approved_time, "Botho University Clinic", queue_no, line)
            conn2.close()
        except Exception as e: print(f"Approve email error: {e}")
        flash(f"Approved {line} - {queue_no} at {approved_time}")
    except Exception as e:
        print(f"Approve failed: {e}"); conn.rollback(); flash(f"Approve failed: {e}")
    finally: conn.close()
    return redirect(url_for('staff_dashboard'))

@app.route("/staff/checkin/<appt_id>", methods=["POST"])
@login_required
def checkin(appt_id):
    conn = get_conn(); cur = conn.cursor(); now = datetime.datetime.now().isoformat()
    cur.execute(ph("UPDATE appointments SET status='CHECKED_IN', checked_in_at=? WHERE id=?", "UPDATE appointments SET status='CHECKED_IN', checked_in_at=%s WHERE id=%s"), (now, appt_id))
    conn.commit(); conn.close(); flash("Checked in"); return redirect(url_for('staff_dashboard'))

@app.route("/staff/call/<appt_id>", methods=["POST"])
@login_required
def call_patient(appt_id):
    conn = get_conn(); cur = conn.cursor()
    try:
        now = datetime.datetime.now().isoformat()
        cur.execute(ph("UPDATE appointments SET status='CALLED', called_at=? WHERE id=?", "UPDATE appointments SET status='CALLED', called_at=%s WHERE id=%s"), (now, appt_id))
        cur.execute(ph("UPDATE queue SET status='CALLED', called_at=? WHERE appointment_id=?", "UPDATE queue SET status='CALLED', called_at=%s WHERE appointment_id=%s"), (now, appt_id))
        cur.execute(ph("SELECT q.queue_number, p.email, p.full_name, f.name as facility_name FROM queue q JOIN appointments a ON q.appointment_id=a.id JOIN patients p ON a.patient_id=p.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=?", "SELECT q.queue_number, p.email, p.full_name, f.name as facility_name FROM queue q JOIN appointments a ON q.appointment_id=a.id JOIN patients p ON a.patient_id=p.id LEFT JOIN facilities f ON a.facility_id=f.id WHERE a.id=%s"), (appt_id,))
        row = cur.fetchone(); conn.commit()
        if row: send_call_email(row[1], row[2], row[0], row[3] or "Botho University Clinic")
        flash("Called")
    except Exception as e: print(f"Call failed: {e}"); conn.rollback(); flash(f"Call failed: {e}")
    finally: conn.close()
    return redirect(url_for('staff_dashboard'))

@app.route("/staff/complete/<appt_id>", methods=["POST"])
@login_required
def complete(appt_id):
    conn = get_conn(); cur = conn.cursor(); now = datetime.datetime.now().isoformat()
    cur.execute(ph("UPDATE appointments SET status='COMPLETED', completed_at=? WHERE id=?", "UPDATE appointments SET status='COMPLETED', completed_at=%s WHERE id=%s"), (now, appt_id))
    cur.execute(ph("UPDATE queue SET status='COMPLETED' WHERE appointment_id=?", "UPDATE queue SET status='COMPLETED' WHERE appointment_id=%s"), (appt_id,)); conn.commit(); conn.close(); flash("Completed"); return redirect(url_for('staff_dashboard'))

@app.route("/staff/walkin", methods=["GET","POST"])
@login_required
def walkin():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT * FROM facilities"); facilities = cur.fetchall()
    cur.execute("SELECT * FROM services"); services = cur.fetchall()
    if request.method=="POST":
        full_name = request.form.get("full_name","").strip(); phone = request.form.get("phone","").strip(); email = request.form.get("email","").strip().lower()
        facility_id = request.form.get("facility_id"); service_id = request.form.get("service_id")
        now = datetime.datetime.now().isoformat(); today = datetime.datetime.now().strftime("%Y-%m-%d")
        cur.execute(ph("SELECT id FROM patients WHERE full_name=? AND phone=? AND email=?", "SELECT id FROM patients WHERE full_name=%s AND phone=%s AND email=%s"), (full_name, phone, email))
        row = cur.fetchone()
        if row: patient_id = row[0]
        else:
            cur.execute("SELECT COUNT(*) FROM patients"); count = cur.fetchone()[0]; patient_id = f"E{count+1:02d}DB"
            cur.execute(ph("INSERT INTO patients VALUES (?,?,?,?,?)", "INSERT INTO patients VALUES (%s,%s,%s,%s,%s)"), (patient_id, full_name, phone, email, now))
        appt_id = str(uuid.uuid4())
        cur.execute(ph("INSERT INTO appointments VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", "INSERT INTO appointments VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)"), (appt_id, patient_id, facility_id, service_id, today, "APPROVED", "WALKIN", now, "Now", now, now, None, None, None, None, None))
        cur.execute(ph("SELECT COUNT(*) FROM queue WHERE date(created_at)=date('now','localtime')", "SELECT COUNT(*) FROM queue WHERE created_at::date=CURRENT_DATE")); qcount = cur.fetchone()[0]
        queue_no = f"NO{qcount+1:02d}"; qid = str(uuid.uuid4())
        cur.execute(ph("INSERT INTO queue VALUES (?,?,?,?,?,?)", "INSERT INTO queue VALUES (%s,%s,%s,%s,%s,%s)"), (qid, appt_id, queue_no, "WAITING", now, None))
        conn.commit(); conn.close(); flash(f"Walk-in {patient_id} {queue_no}"); return redirect(url_for('staff_dashboard'))
    conn.close(); return render_template("walkin.html", facilities=facilities, services=services)

@app.route("/staff/reports")
@login_required
def reports():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT status, COUNT(*) as c FROM appointments GROUP BY status")
    by_status = cur.fetchall()
    cur.execute("SELECT s.name, COUNT(*) as c FROM appointments a JOIN services s ON a.service_id=s.id GROUP BY s.name")
    by_service = cur.fetchall()
    conn.close()
    return render_template("reports.html", by_status=by_status, by_service=by_service)

@app.route("/staff/users")
@login_required
def staff_users():
    conn = get_conn(); cur = conn.cursor()
    cur.execute("SELECT id, username, role, failed_attempts, locked_until FROM users ORDER BY role"); users = cur.fetchall(); conn.close()
    return render_template("staff_users.html", users=users)

@app.route("/staff/emails", methods=["GET", "POST"])
@login_required
def staff_emails():
    conn = get_conn(); cur = conn.cursor()
    if request.method=="POST":
        email = request.form.get("email","").strip().lower(); role = request.form.get("role","reception")
        if email and "@" in email:
            try:
                cur.execute(ph("INSERT INTO staff_notify_emails VALUES (?,?,?,?)", "INSERT INTO staff_notify_emails VALUES (%s,%s,%s,%s)"), (str(uuid.uuid4()), email, role, datetime.datetime.now().isoformat())); conn.commit(); flash(f"Added {email}")
            except: flash(f"{email} already exists")
    cur.execute("SELECT * FROM staff_notify_emails ORDER BY created_at DESC"); emails = cur.fetchall(); conn.close()
    return render_template("staff_emails.html", emails=emails)

@app.route("/staff/emails/delete/<eid>", methods=["POST"])
@login_required
def delete_staff_email(eid):
    conn = get_conn(); cur = conn.cursor()
    cur.execute(ph("DELETE FROM staff_notify_emails WHERE id=?", "DELETE FROM staff_notify_emails WHERE id=%s"), (eid,)); conn.commit(); conn.close(); flash("Removed"); return redirect(url_for('staff_emails'))

# ===== DELETE BOOKING – Staff can delete mistakes/duplicates =====
@app.route('/staff/appointments/delete/<appointment_id>', methods=['GET', 'POST'])
def staff_delete_appointment(appointment_id):
    if 'user_id' not in session:
        return redirect(url_for('staff_login'))
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(ph("DELETE FROM appointments WHERE id=?", "DELETE FROM appointments WHERE id=%s"), (appointment_id,))
        conn.commit(); conn.close()
        flash(f"Deleted booking {appointment_id[:8]} – duplicate removed", "success")
    except Exception as e:
        print(f"Delete FAILED: {e}")
        flash(f"Delete failed: {e}", "danger")
    return redirect(url_for('staff_dashboard'))

# ===== CANCEL BOOKING – Patient can cancel own booking =====
@app.route('/cancel/<appointment_id>', methods=['GET', 'POST'])
def patient_cancel_appointment(appointment_id):
    try:
        conn = get_conn(); cur = conn.cursor()
        cur.execute(ph("SELECT status FROM appointments WHERE id=?", "SELECT status FROM appointments WHERE id=%s"), (appointment_id,))
        row = cur.fetchone()
        if not row:
            flash("Booking not found", "danger")
            conn.close()
            return redirect(url_for('home_user'))
        cur.execute(ph("UPDATE appointments SET status='cancelled' WHERE id=?", "UPDATE appointments SET status='cancelled' WHERE id=%s"), (appointment_id,))
        conn.commit(); conn.close()
        flash("Your booking cancelled", "success")
        return redirect(url_for('home_user'))
    except Exception as e:
        print(f"Cancel FAILED: {e}")
        flash(f"Cancel failed: {e}", "danger")
        return redirect(url_for('home_user'))

init_db()
if __name__ == "__main__":
    app.run(debug=True)
