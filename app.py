import os, re, sqlite3, csv, ssl, smtplib
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

DB_PATH = os.path.join(os.path.dirname(__file__), "leads.db")
CSV_PATH = os.path.join(os.path.dirname(__file__), "leads.csv")

app = Flask(__name__)
# Allow only your GitHub Pages domain in production; use * while testing
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")
CORS(app, resources={r"/api/*": {"origins": FRONTEND_ORIGIN}})

EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

def init_db():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT,
            email TEXT,
            message TEXT,
            created_at TEXT
        )
        """)
        con.commit()
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["id","name","email","message","created_at"])

def save_lead(name, email, message):
    now = datetime.utcnow().isoformat(timespec="seconds")+"Z"
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute("INSERT INTO leads (name,email,message,created_at) VALUES (?,?,?,?)",
                    (name, email, message, now))
        lead_id = cur.lastrowid
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([lead_id, name, email, message, now])
    return lead_id, now

def send_email_via_zoho(name: str, visitor_email: str, message: str) -> bool:
    sender   = os.environ.get("ZOHO_EMAIL", "").strip()
    app_pass = os.environ.get("ZOHO_APP_PASSWORD", "").strip()
    to_addr  = os.environ.get("ZOHO_TO_EMAIL", sender).strip() or sender
    host     = os.environ.get("ZOHO_SMTP_HOST", "smtp.zoho.in").strip()
    port     = int(os.environ.get("ZOHO_SMTP_PORT", "465"))

    subject = f"New website inquiry from {name}"
    body    = f"Name: {name}\nEmail: {visitor_email}\n\n{message}\n"

    msg = MIMEText(body, _charset="utf-8")
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = to_addr
    if visitor_email:
        msg["Reply-To"] = visitor_email

    if not sender or not app_pass:
        print("[warn] Missing ZOHO_EMAIL / ZOHO_APP_PASSWORD; skipping SMTP send")
        return False

    try:
        ctx = ssl.create_default_context()
        with smtplib.SMTP_SSL(host, port, context=ctx) as s:
            s.login(sender, app_pass)
            s.send_message(msg)
        return True
    except Exception as e:
        print("[error] SMTP send failed:", e)
        return False

@app.post("/api/contact")
def contact():
    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not EMAIL_REGEX.match(email) or not message:
        return jsonify({ "ok": False, "error": "Invalid input" }), 400

    if len(name) > 120 or len(email) > 200 or len(message) > 5000:
        return jsonify({ "ok": False, "error": "Input too long" }), 413

    lead_id, created_at = save_lead(name, email, message)
    sent = send_email_via_zoho(name, email, message)

    return jsonify({ "ok": True, "id": lead_id, "created_at": created_at, "email_sent": bool(sent) })

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True)
