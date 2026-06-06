import os
import sqlite3
import base64
import json
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, redirect, url_for, jsonify, session, flash
from openai import OpenAI
from dotenv import load_dotenv
from werkzeug.security import generate_password_hash, check_password_hash
 
load_dotenv()
 
app = Flask(__name__)
app.config['UPLOAD_FOLDER'] = 'static/uploads'
app.config['MAX_CONTENT_LENGTH'] = 5 * 1024 * 1024
app.secret_key = "smartcity_secret_2024_xk9"
 
ADMIN_USERNAME = "admin"
ADMIN_PASSWORD = "smartcity123"
 
# Email config — uses Gmail SMTP
MAIL_SENDER_EMAIL    = os.getenv("MAIL_EMAIL", "")
MAIL_SENDER_PASSWORD = os.getenv("MAIL_PASSWORD", "")
 
client = OpenAI(
    api_key=os.getenv("OPENAI_API_KEY"),
    base_url="https://openrouter.ai/api/v1"
)
 
ISSUE_CATEGORIES = [
    "Pothole / Road Damage",
    "Garbage / Waste Overflow",
    "Waterlogging / Drainage",
    "Broken Streetlight",
    "Sewage / Open Drain",
    "Encroachment",
    "Other"
]
 
# ── Database ───────────────────────────────────────────────────────────────────
 
def get_db():
    db = sqlite3.connect('complaints.db')
    db.row_factory = sqlite3.Row
    return db
 
def init_db():
    db = get_db()
    # Users table
    db.execute('''
        CREATE TABLE IF NOT EXISTS users (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            name       TEXT    NOT NULL,
            email      TEXT    NOT NULL UNIQUE,
            password   TEXT    NOT NULL,
            created_at TEXT    NOT NULL
        )
    ''')
    # Complaints table — with user_id + rejection_reason columns
    db.execute('''
        CREATE TABLE IF NOT EXISTS complaints (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id          INTEGER,
            category         TEXT    NOT NULL,
            severity         TEXT    NOT NULL,
            description      TEXT    NOT NULL,
            location         TEXT    NOT NULL,
            image_path       TEXT,
            status           TEXT    DEFAULT "Pending",
            rejection_reason TEXT    DEFAULT NULL,
            created_at       TEXT    NOT NULL
        )
    ''')
    # Add missing columns if DB already existed without them
    try:
        db.execute("ALTER TABLE complaints ADD COLUMN user_id INTEGER")
    except:
        pass
    try:
        db.execute("ALTER TABLE complaints ADD COLUMN rejection_reason TEXT DEFAULT NULL")
    except:
        pass
    # Notifications table
    db.execute('''
        CREATE TABLE IF NOT EXISTS notifications (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            user_id      INTEGER NOT NULL,
            complaint_id INTEGER NOT NULL,
            message      TEXT    NOT NULL,
            status       TEXT    NOT NULL,
            is_read      INTEGER DEFAULT 0,
            created_at   TEXT    NOT NULL
        )
    ''')
    # Add ai_message column to complaints if not exists
    try:
        db.execute("ALTER TABLE complaints ADD COLUMN ai_message TEXT DEFAULT NULL")
    except:
        pass
    db.commit()
    db.close()
 
# ── Auth helpers ───────────────────────────────────────────────────────────────
 
def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("user_id"):
            return redirect(url_for("signin"))
        return f(*args, **kwargs)
    return decorated
 
def admin_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get("admin_logged_in"):
            return redirect(url_for("admin_login"))
        return f(*args, **kwargs)
    return decorated
 
# ── AI ─────────────────────────────────────────────────────────────────────────
 
def classify_image(image_path, location):
    try:
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")
        ext = image_path.rsplit(".", 1)[-1].lower()
        media_type = "image/jpeg" if ext in ("jpg", "jpeg") else f"image/{ext}"
        prompt = f"""You are an AI assistant for a Smart City Complaint system in India.
Analyze this image and identify any urban civic issue.
 
Respond ONLY in this exact JSON format, nothing else:
{{
  "category": "<one of: Pothole / Road Damage | Garbage / Waste Overflow | Waterlogging / Drainage | Broken Streetlight | Sewage / Open Drain | Encroachment | Other>",
  "severity": "<one of: High | Medium | Low>",
  "description": "<2-3 sentence clear complaint description a citizen would submit to their municipal corporation. Be specific about what you see.>"
}}
 
Location context: {location}
If no civic issue is visible, use category "Other", severity "Low", and describe what you see."""
        response = client.chat.completions.create(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": [
                {"type": "text", "text": prompt},
                {"type": "image_url", "image_url": {"url": f"data:{media_type};base64,{image_data}"}}
            ]}],
            max_tokens=400
        )
        raw = response.choices[0].message.content.strip()
        if raw.startswith("```"):
            raw = raw.split("```")[1]
            if raw.startswith("json"):
                raw = raw[4:]
        return json.loads(raw.strip())
    except:
        return {"category": "Other", "severity": "Medium",
                "description": f"Civic issue reported at {location}. Manual review required."}
 
 
def chat_with_ai(user_message, complaint_stats):
    try:
        stats_context = f"""
Smart City Complaint Assistant — Live Stats:
- Total complaints: {complaint_stats['total']}
- Pending: {complaint_stats['pending']}
- In Progress: {complaint_stats['in_progress']}
- Resolved: {complaint_stats['resolved']}
- Most reported issue: {complaint_stats['top_category']}
"""
        response = client.chat.completions.create(
            model="openai/gpt-4o",
            messages=[
                {"role": "system", "content": f"""You are a highly intelligent AI assistant built into the Smart City Complaint Assistant platform for Indian cities (SDG 11).
You can answer ANY question. You also have live platform data:
{stats_context}
Be conversational, helpful, and accurate."""},
                {"role": "user", "content": user_message}
            ],
            max_tokens=800
        )
        return response.choices[0].message.content.strip()
    except:
        return "Sorry, I am unable to respond right now. Please try again."
 
 
def generate_status_message(complaint, new_status, citizen_name, rejection_reason=None):
    """AI generates a personalized status update message for the citizen."""
    try:
        if new_status == "In Progress":
            prompt = f"""Write a short warm professional notification to citizen {citizen_name} that their complaint is now being worked on.
Complaint: {complaint['category']} at {complaint['location']}, Severity: {complaint['severity']}, ID: #{complaint['id']}
2-3 sentences. Be specific. Sound like a municipal authority. Include estimated timeframe (High=24-48hrs, Medium=3-5 days, Low=1-2 weeks). Message body only, no subject."""
        elif new_status == "Resolved":
            prompt = f"""Write a short warm professional notification to citizen {citizen_name} that their complaint has been resolved.
Complaint: {complaint['category']} at {complaint['location']}, ID: #{complaint['id']}
2-3 sentences. Be specific. Thank them for reporting. Sound like a municipal authority. Message body only."""
        elif new_status == "Rejected":
            prompt = f"""Write a short professional but empathetic notification to citizen {citizen_name} that their complaint was rejected.
Complaint: {complaint['category']} at {complaint['location']}, ID: #{complaint['id']}, Reason: {rejection_reason}
2-3 sentences. Be clear about reason. Encourage resubmit if issue persists. Message body only."""
        else:
            return None
 
        response = client.chat.completions.create(
            model="openai/gpt-4o",
            messages=[{"role": "user", "content": prompt}],
            max_tokens=200
        )
        return response.choices[0].message.content.strip()
    except:
        fallbacks = {
            "In Progress": f"Dear {citizen_name}, your complaint #{complaint['id']} regarding {complaint['category']} at {complaint['location']} has been assigned to our maintenance team. Work is now in progress.",
            "Resolved":    f"Dear {citizen_name}, your complaint #{complaint['id']} regarding {complaint['category']} at {complaint['location']} has been successfully resolved. Thank you for helping improve our city.",
            "Rejected":    f"Dear {citizen_name}, your complaint #{complaint['id']} could not be processed. Reason: {rejection_reason}. Please resubmit with clearer details if the issue persists."
        }
        return fallbacks.get(new_status, "")
 
 
def send_email_notification(to_email, citizen_name, complaint_id, status, ai_message):
    """Send HTML email to citizen. Fails silently if not configured."""
    if not MAIL_SENDER_EMAIL or not MAIL_SENDER_PASSWORD:
        return
    subject_map = {
        "In Progress": f"Update: Your Complaint #{complaint_id} is Now In Progress",
        "Resolved":    f"Resolved: Your Complaint #{complaint_id} Has Been Fixed!",
        "Rejected":    f"Notice: Your Complaint #{complaint_id} Could Not Be Processed"
    }
    html_body = f"""
    <div style="font-family:Arial,sans-serif;max-width:600px;margin:0 auto;padding:24px;">
      <div style="background:#0F6E56;padding:20px 24px;border-radius:10px 10px 0 0;">
        <h2 style="color:white;margin:0;font-size:18px;">Smart City Complaint Assistant</h2>
        <p style="color:#9FE1CB;margin:4px 0 0;font-size:13px;">SDG 11: Sustainable Cities &amp; Communities</p>
      </div>
      <div style="background:#f9f9f9;padding:24px;border:1px solid #e0e0e0;border-top:none;">
        <p style="font-size:15px;color:#333;margin-top:0;">Dear <strong>{citizen_name}</strong>,</p>
        <div style="background:white;border-left:4px solid #1D9E75;padding:16px;border-radius:0 8px 8px 0;margin:16px 0;">
          <p style="font-size:14px;color:#333;margin:0;line-height:1.7;">{ai_message}</p>
        </div>
        <div style="background:#E1F5EE;border-radius:8px;padding:14px;margin:16px 0;">
          <p style="font-size:13px;color:#085041;margin:0;">
            <strong>Complaint ID:</strong> #{complaint_id}<br>
            <strong>Current Status:</strong> {status}
          </p>
        </div>
        <p style="font-size:13px;color:#666;">Track your complaint anytime using Complaint ID <strong>#{complaint_id}</strong>.</p>
      </div>
      <div style="background:#eee;padding:12px 24px;border-radius:0 0 10px 10px;text-align:center;">
        <p style="font-size:11px;color:#888;margin:0;">Smart City Complaint Assistant &nbsp;·&nbsp; SDG 11 &nbsp;·&nbsp; AI Capstone Project</p>
      </div>
    </div>"""
    try:
        msg = MIMEMultipart("alternative")
        msg["Subject"] = subject_map.get(status, f"Update on Complaint #{complaint_id}")
        msg["From"]    = MAIL_SENDER_EMAIL
        msg["To"]      = to_email
        msg.attach(MIMEText(html_body, "html"))
        with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
            server.login(MAIL_SENDER_EMAIL, MAIL_SENDER_PASSWORD)
            server.sendmail(MAIL_SENDER_EMAIL, to_email, msg.as_string())
    except:
        pass  # Fail silently — app works even without email
 
 
 
 
# ── Citizen Auth Routes ────────────────────────────────────────────────────────
 
@app.route("/signup", methods=["GET", "POST"])
def signup():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        name     = request.form.get("name", "").strip()
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        confirm  = request.form.get("confirm", "").strip()
        if not name or not email or not password:
            error = "All fields are required."
        elif password != confirm:
            error = "Passwords do not match."
        elif len(password) < 6:
            error = "Password must be at least 6 characters."
        else:
            db = get_db()
            existing = db.execute("SELECT id FROM users WHERE email=?", (email,)).fetchone()
            if existing:
                error = "An account with this email already exists."
                db.close()
            else:
                hashed = generate_password_hash(password)
                db.execute("INSERT INTO users (name, email, password, created_at) VALUES (?,?,?,?)",
                           (name, email, hashed, datetime.now().strftime("%Y-%m-%d %H:%M")))
                db.commit()
                user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
                db.close()
                session["user_id"]   = user["id"]
                session["user_name"] = user["name"]
                session["user_email"]= user["email"]
                return redirect(url_for("index"))
    return render_template("signup.html", error=error)
 
 
@app.route("/signin", methods=["GET", "POST"])
def signin():
    if session.get("user_id"):
        return redirect(url_for("index"))
    error = None
    if request.method == "POST":
        email    = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "").strip()
        db = get_db()
        user = db.execute("SELECT * FROM users WHERE email=?", (email,)).fetchone()
        db.close()
        if not user or not check_password_hash(user["password"], password):
            error = "Invalid email or password."
        else:
            session["user_id"]    = user["id"]
            session["user_name"]  = user["name"]
            session["user_email"] = user["email"]
            return redirect(url_for("index"))
    return render_template("signin.html", error=error)
 
 
@app.route("/signout")
def signout():
    session.pop("user_id", None)
    session.pop("user_name", None)
    session.pop("user_email", None)
    return redirect(url_for("index"))
 
# ── Main Routes ────────────────────────────────────────────────────────────────
 
@app.route("/")
def index():
    db = get_db()
    recent = db.execute("SELECT * FROM complaints ORDER BY created_at DESC LIMIT 5").fetchall()
    stats  = get_stats(db)
    db.close()
    return render_template("index.html", recent=recent, stats=stats)
 
 
@app.route("/report", methods=["GET", "POST"])
@login_required
def report():
    if request.method == "POST":
        location = request.form.get("location", "").strip()
        image    = request.files.get("image")
        if not location:
            return render_template("report.html", error="Please enter your location.")
        if not image or image.filename == "":
            return render_template("report.html", error="Please upload a photo.")
        ext = image.filename.rsplit(".", 1)[-1].lower()
        if ext not in ("jpg", "jpeg", "png", "webp"):
            return render_template("report.html", error="Only JPG, PNG, or WEBP images are allowed.")
        filename  = f"{datetime.now().strftime('%Y%m%d_%H%M%S')}_{image.filename}"
        save_path = os.path.join(app.config['UPLOAD_FOLDER'], filename)
        image.save(save_path)
        result = classify_image(save_path, location)
        db = get_db()
        db.execute(
            "INSERT INTO complaints (user_id, category, severity, description, location, image_path, status, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (session["user_id"], result["category"], result["severity"], result["description"],
             location, f"static/uploads/{filename}", "Pending", datetime.now().strftime("%Y-%m-%d %H:%M"))
        )
        db.commit()
        complaint_id = db.execute("SELECT last_insert_rowid()").fetchone()[0]
        db.close()
        return redirect(url_for("complaint_detail", complaint_id=complaint_id, submitted="1"))
    return render_template("report.html")
 
 
@app.route("/complaint/<int:complaint_id>")
def complaint_detail(complaint_id):
    db = get_db()
    complaint = db.execute("SELECT * FROM complaints WHERE id=?", (complaint_id,)).fetchone()
    db.close()
    if not complaint:
        return redirect(url_for("complaints"))
    # Only owner or admin can see full detail
    # Other users see limited public view
    is_owner = session.get("user_id") and session["user_id"] == complaint["user_id"]
    submitted = request.args.get("submitted", "0") == "1"
    return render_template("detail.html", complaint=complaint, submitted=submitted, is_owner=is_owner)
 
 
@app.route("/track", methods=["GET", "POST"])
def track():
    complaint = None
    error     = None
    is_owner  = False
    if request.method == "POST":
        complaint_id = request.form.get("complaint_id", "").strip()
        if not complaint_id or not complaint_id.isdigit():
            error = "Please enter a valid complaint ID number."
        else:
            db = get_db()
            complaint = db.execute("SELECT * FROM complaints WHERE id=?", (int(complaint_id),)).fetchone()
            db.close()
            if not complaint:
                error = f"No complaint found with ID #{complaint_id}."
            else:
                is_owner = session.get("user_id") and session["user_id"] == complaint["user_id"]
    return render_template("track.html", complaint=complaint, error=error, is_owner=is_owner)
 
 
@app.route("/my-complaints")
@login_required
def my_complaints():
    db = get_db()
    complaints = db.execute(
        "SELECT * FROM complaints WHERE user_id=? ORDER BY created_at DESC",
        (session["user_id"],)
    ).fetchall()
    db.close()
    return render_template("my_complaints.html", complaints=complaints)
 
 
@app.route("/complaints")
def complaints():
    db = get_db()
    category_filter = request.args.get("category", "")
    severity_filter = request.args.get("severity", "")
    status_filter   = request.args.get("status", "")
    query  = "SELECT * FROM complaints WHERE 1=1"
    params = []
    if category_filter:
        query += " AND category=?"; params.append(category_filter)
    if severity_filter:
        query += " AND severity=?"; params.append(severity_filter)
    if status_filter:
        query += " AND status=?";   params.append(status_filter)
    query += " ORDER BY created_at DESC"
    all_complaints = db.execute(query, params).fetchall()
    stats = get_stats(db)
    db.close()
    return render_template("complaints.html", complaints=all_complaints, stats=stats,
                           categories=ISSUE_CATEGORIES,
                           selected_category=category_filter,
                           selected_severity=severity_filter,
                           selected_status=status_filter)
 
 
@app.route("/dashboard")
def dashboard():
    db = get_db()
    stats    = get_stats(db)
    cat_data = db.execute("SELECT category, COUNT(*) as count FROM complaints GROUP BY category ORDER BY count DESC").fetchall()
    weekly   = db.execute("""SELECT DATE(created_at) as day, COUNT(*) as count
                              FROM complaints WHERE created_at >= DATE('now','-7 days')
                              GROUP BY DATE(created_at) ORDER BY day""").fetchall()
    recent   = db.execute("SELECT * FROM complaints ORDER BY created_at DESC LIMIT 8").fetchall()
    db.close()
    return render_template("dashboard.html", stats=stats, cat_data=cat_data, weekly=weekly, recent=recent)
 
 
@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json()
    user_message = data.get("message", "").strip()
    if not user_message:
        return jsonify({"reply": "Please type a message."})
    db = get_db()
    stats = get_stats(db)
    db.close()
    return jsonify({"reply": chat_with_ai(user_message, stats)})
 
@app.route("/update_status/<int:complaint_id>", methods=["POST"])
def update_status(complaint_id):
    new_status = request.form.get("status")
    if new_status in ("Pending", "In Progress", "Resolved"):
        db = get_db()
        db.execute("UPDATE complaints SET status=? WHERE id=?", (new_status, complaint_id))
        db.commit()
        db.close()
    return redirect(request.referrer or url_for("complaints"))
 
 
# ── Admin Routes ───────────────────────────────────────────────────────────────
 
@app.route("/admin/login", methods=["GET", "POST"])
def admin_login():
    if session.get("admin_logged_in"):
        return redirect(url_for("admin_dashboard"))
    error = None
    if request.method == "POST":
        if request.form.get("username") == ADMIN_USERNAME and \
           request.form.get("password") == ADMIN_PASSWORD:
            session["admin_logged_in"] = True
            return redirect(url_for("admin_dashboard"))
        error = "Invalid username or password."
    return render_template("admin_login.html", error=error)
 
 
@app.route("/admin/logout")
def admin_logout():
    session.pop("admin_logged_in", None)
    return redirect(url_for("admin_login"))
 
 
@app.route("/admin")
@admin_required
def admin_dashboard():
    db = get_db()
    stats = get_stats(db)
    complaints = db.execute("""
        SELECT c.*, u.name as citizen_name, u.email as citizen_email
        FROM complaints c
        LEFT JOIN users u ON c.user_id = u.id
        ORDER BY
            CASE c.severity WHEN 'High' THEN 1 WHEN 'Medium' THEN 2 ELSE 3 END,
            CASE c.status WHEN 'Pending' THEN 1 WHEN 'In Progress' THEN 2 ELSE 3 END,
            c.created_at DESC
    """).fetchall()
    db.close()
    return render_template("admin_dashboard.html", stats=stats, complaints=complaints)
 
 
@app.route("/admin/update/<int:complaint_id>", methods=["POST"])
@admin_required
def admin_update_status(complaint_id):
    new_status       = request.form.get("status")
    rejection_reason = request.form.get("rejection_reason", "").strip()
    valid_statuses   = ("Pending", "In Progress", "Resolved", "Rejected")
 
    if new_status not in valid_statuses:
        return redirect(url_for("admin_dashboard"))
 
    db = get_db()
    # Get complaint + citizen info
    complaint = db.execute("""
        SELECT c.*, u.name as citizen_name, u.email as citizen_email
        FROM complaints c LEFT JOIN users u ON c.user_id = u.id
        WHERE c.id=?""", (complaint_id,)).fetchone()
 
    if not complaint:
        db.close()
        return redirect(url_for("admin_dashboard"))
 
    # Only generate AI message for meaningful status changes
    ai_msg = None
    if new_status in ("In Progress", "Resolved", "Rejected"):
        citizen_name = complaint["citizen_name"] or "Citizen"
        ai_msg = generate_status_message(
            dict(complaint), new_status, citizen_name,
            rejection_reason if new_status == "Rejected" else None
        )
 
    # Update complaint in DB
    if new_status == "Rejected":
        db.execute("UPDATE complaints SET status=?, rejection_reason=?, ai_message=? WHERE id=?",
                   (new_status, rejection_reason or "No reason provided.", ai_msg, complaint_id))
    else:
        db.execute("UPDATE complaints SET status=?, rejection_reason=NULL, ai_message=? WHERE id=?",
                   (new_status, ai_msg, complaint_id))
 
    # Save notification for citizen
    if ai_msg and complaint["user_id"]:
        db.execute("""INSERT INTO notifications (user_id, complaint_id, message, status, is_read, created_at)
                      VALUES (?, ?, ?, ?, 0, ?)""",
                   (complaint["user_id"], complaint_id, ai_msg, new_status,
                    datetime.now().strftime("%Y-%m-%d %H:%M")))
 
    db.commit()
 
    # Send email in background (non-blocking)
    if ai_msg and complaint["citizen_email"]:
        send_email_notification(
            complaint["citizen_email"],
            complaint["citizen_name"] or "Citizen",
            complaint_id, new_status, ai_msg
        )
 
    db.close()
    return redirect(url_for("admin_dashboard"))
 
 
@app.route("/notifications")
@login_required
def notifications():
    db = get_db()
    notifs = db.execute("""
        SELECT n.*, c.category, c.location, c.severity
        FROM notifications n
        JOIN complaints c ON n.complaint_id = c.id
        WHERE n.user_id = ?
        ORDER BY n.created_at DESC
    """, (session["user_id"],)).fetchall()
    # Mark all as read
    db.execute("UPDATE notifications SET is_read=1 WHERE user_id=?", (session["user_id"],))
    db.commit()
    unread = 0
    db.close()
    return render_template("notifications.html", notifications=notifs)
 
 
@app.route("/admin/complaint/<int:complaint_id>")
@admin_required
def admin_complaint_detail(complaint_id):
    db = get_db()
    complaint = db.execute("""
        SELECT c.*, u.name as citizen_name, u.email as citizen_email
        FROM complaints c LEFT JOIN users u ON c.user_id = u.id
        WHERE c.id=?""", (complaint_id,)).fetchone()
    db.close()
    if not complaint:
        return redirect(url_for("admin_dashboard"))
    return render_template("admin_detail.html", complaint=complaint)
 
# ── Context processor — injects unread count into every template ───────────────
 
@app.context_processor
def inject_unread_count():
    if session.get("user_id"):
        db = get_db()
        count = db.execute(
            "SELECT COUNT(*) FROM notifications WHERE user_id=? AND is_read=0",
            (session["user_id"],)
        ).fetchone()[0]
        db.close()
        return {"unread_count": count}
    return {"unread_count": 0}
 
 
# ── Helpers ────────────────────────────────────────────────────────────────────
 
def get_stats(db):
    total       = db.execute("SELECT COUNT(*) FROM complaints").fetchone()[0]
    pending     = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Pending'").fetchone()[0]
    in_progress = db.execute("SELECT COUNT(*) FROM complaints WHERE status='In Progress'").fetchone()[0]
    resolved    = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Resolved'").fetchone()[0]
    rejected    = db.execute("SELECT COUNT(*) FROM complaints WHERE status='Rejected'").fetchone()[0]
    top_row     = db.execute("SELECT category FROM complaints GROUP BY category ORDER BY COUNT(*) DESC LIMIT 1").fetchone()
    return {"total": total, "pending": pending, "in_progress": in_progress,
            "resolved": resolved, "rejected": rejected,
            "top_category": top_row[0] if top_row else "N/A"}
 
# Initialize DB and uploads folder on startup (works for both gunicorn and python app.py)
os.makedirs(app.config['UPLOAD_FOLDER'], exist_ok=True)
init_db()
 
if __name__ == "__main__":
    app.run(debug=True)