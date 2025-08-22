import os, re, sqlite3, csv, ssl, smtplib
from email.mime.text import MIMEText
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

# ---------- Paths ----------
BASE_DIR  = os.path.dirname(__file__)
DB_PATH   = os.path.join(BASE_DIR, "leads.db")
CSV_PATH  = os.path.join(BASE_DIR, "leads.csv")

app = Flask(__name__)

# ---------- CORS ----------
# While testing you can use "*", but in production set this to your Pages origin:
# e.g. https://sriaparna70-maker.github.io  (no trailing slash)
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")

CORS(
    app,
    resources={r"/api/*": {"origins": FRONTEND_ORIGIN}},
    methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    supports_credentials=False,
)

@app.after_request
def add_cors_headers(resp):
    # Guarantee headers on every response (incl. errors)
    resp.headers["Access-Control-Allow-Origin"] = FRONTEND_ORIGIN
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

# ---------- DB ----------
def init_db():
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS leads (
              id INTEGER PRIMARY KEY AUTOINCREMENT,
              name TEXT,
              email TEXT,
              message TEXT,
              created_at TEXT
            )
            """
        )
        con.commit()
    if not os.path.exists(CSV_PATH):
        with open(CSV_PATH, "w", newline="", encoding="utf-8") as f:
            csv.writer(f).writerow(["id", "name", "email", "message", "created_at"])

def save_lead(name, email, message):
    now = datetime.utcnow().isoformat(timespec="seconds") + "Z"
    with sqlite3.connect(DB_PATH) as con:
        cur = con.cursor()
        cur.execute(
            "INSERT INTO leads (name,email,message,created_at) VALUES (?,?,?,?)",
            (name, email, message, now),
        )
        lead_id = cur.lastrowid
    with open(CSV_PATH, "a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow([lead_id, name, email, message, now])
    return lead_id, now

# ---------- Email (Zoho SMTP) ----------
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

# ---------- API ----------
@app.route("/api/contact", methods=["POST", "OPTIONS"])
def contact():
    # CORS preflight
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    name = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    message = (data.get("message") or "").strip()

    if not name or not EMAIL_REGEX.match(email) or not message:
        return jsonify({"ok": False, "error": "Invalid input"}), 400

    if len(name) > 120 or len(email) > 200 or len(message) > 5000:
        return jsonify({"ok": False, "error": "Input too long"}), 413

    lead_id, created_at = save_lead(name, email, message)
    sent = send_email_via_zoho(name, email, message)

    return jsonify({"ok": True, "id": lead_id, "created_at": created_at, "email_sent": bool(sent)})

# Ensure DB exists on startup
init_db()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", "8080")), debug=True)
