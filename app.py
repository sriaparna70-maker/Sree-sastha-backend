import os, re, sqlite3, csv, ssl, smtplib, base64
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime

BASE_DIR = os.path.dirname(__file__)
DB_PATH  = os.path.join(BASE_DIR, "leads.db")
CSV_PATH = os.path.join(BASE_DIR, "leads.csv")

app = Flask(__name__)

# ---------- CORS ----------
# Prefer single origin FRONTEND_ORIGIN; or allow multiple with ALLOWED_ORIGINS (comma-separated)
ALLOWED_ORIGINS = [o.strip().rstrip('/') for o in os.environ.get("ALLOWED_ORIGINS", "").split(",") if o.strip()]
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "").rstrip('/')
allowed = ALLOWED_ORIGINS if ALLOWED_ORIGINS else (FRONTEND_ORIGIN or "*")

CORS(
    app,
    resources={r"/api/*": {"origins": allowed}},
    methods=["POST", "OPTIONS"],
    allow_headers=["Content-Type", "Authorization"],
    supports_credentials=False,
)

@app.after_request
def add_cors_headers(resp):
    origin = (request.headers.get("Origin") or "").rstrip('/')
    if allowed == "*" or (isinstance(allowed, list) and "*" in allowed):
        resp.headers["Access-Control-Allow-Origin"] = "*"
    elif origin and (origin == FRONTEND_ORIGIN or origin in ALLOWED_ORIGINS):
        resp.headers["Access-Control-Allow-Origin"] = origin
        resp.headers["Vary"] = "Origin"
    resp.headers["Access-Control-Allow-Methods"] = "POST, OPTIONS"
    resp.headers["Access-Control-Allow-Headers"] = "Content-Type, Authorization"
    return resp

EMAIL_REGEX = re.compile(r"^[^@]+@[^@]+\.[^@]+$")

# ---------- DB & CSV ----------
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
        )""")
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

# ---------- Email (Zoho) ----------
def send_email_via_zoho(subject: str, body: str, reply_to: str = "", attachments: list = None) -> bool:
    sender   = os.environ.get("ZOHO_EMAIL", "").strip()
    app_pass = os.environ.get("ZOHO_APP_PASSWORD", "").strip()
    to_addr  = os.environ.get("ZOHO_TO_EMAIL", sender).strip() or sender
    host     = os.environ.get("ZOHO_SMTP_HOST", "smtp.zoho.in").strip()
    port     = int(os.environ.get("ZOHO_SMTP_PORT", "465"))

    msg = MIMEMultipart()
    msg["Subject"] = subject
    msg["From"]    = sender
    msg["To"]      = to_addr
    if reply_to:
        msg["Reply-To"] = reply_to
    msg.attach(MIMEText(body, _charset="utf-8"))

    for att in (attachments or []):
        try:
            part = MIMEBase("application", "octet-stream")
            part.set_payload(base64.b64decode(att.get("b64","")))
            encoders.encode_base64(part)
            fname = att.get("filename","attachment")
            ctype = att.get("content_type","application/octet-stream")
            part.add_header("Content-Disposition", f'attachment; filename="{fname}"')
            part.add_header("Content-Type", ctype)
            msg.attach(part)
        except Exception as e:
            print("[warn] attachment failed:", e)

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

# ---------- Routes ----------
@app.route("/api/contact", methods=["POST", "OPTIONS"])
def contact():
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
    body = f"Name: {name}\nEmail: {email}\n\n{message}\n"
    sent = send_email_via_zoho(f"New website inquiry from {name}", body, reply_to=email)

    return jsonify({ "ok": True, "id": lead_id, "created_at": created_at, "email_sent": bool(sent) })

@app.route("/api/oa-inquiry", methods=["POST", "OPTIONS"])
def oa_inquiry():
    if request.method == "OPTIONS":
        return ("", 204)

    data = request.get_json(silent=True) or {}
    name  = (data.get("name") or "").strip()
    email = (data.get("email") or "").strip()
    company = (data.get("company") or "").strip()
    phone   = (data.get("phone") or "").strip()
    sanctioned = (data.get("sanctioned_load") or "").strip()
    monthly   = (data.get("monthly_kwh") or "").strip()
    callback  = bool(data.get("callback"))
    eb_bill   = data.get("eb_bill")  # {filename, content_type, b64} or None

    if not name or not EMAIL_REGEX.match(email) or not company or not sanctioned or not monthly:
        return jsonify({"ok": False, "error": "Invalid input"}), 400

    # Save concise row (so CSV/DB captures OA lead too)
    msg = (f"[Open Access Inquiry]\n"
           f"Company: {company}\nPhone: {phone}\n"
           f"Sanctioned Load (kVA): {sanctioned}\nMonthly (kWh): {monthly}\n"
           f"Callback: {'Yes' if callback else 'No'}")
    lead_id, created_at = save_lead(name, email, msg)

    email_body = (f"Name: {name}\nCompany: {company}\nEmail: {email}\nPhone: {phone}\n"
                  f"Sanctioned Load (kVA): {sanctioned}\nMonthly Consumption (kWh): {monthly}\n"
                  f"Callback: {'Yes' if callback else 'No'}\n\n"
                  f"(Lead #{lead_id} at {created_at})")

    attachments = [eb_bill] if isinstance(eb_bill, dict) and eb_bill.get("b64") else []
    sent = send_email_via_zoho("Open Access Inquiry", email_body, reply_to=email, attachments=attachments)

    return jsonify({ "ok": True, "id": lead_id, "created_at": created_at, "email_sent": bool(sent) })

# ---------- Init ----------
def _maybe_init():
    try:
        init_db()
    except Exception as e:
        print("[warn] init_db failed:", e)
_maybe_init()

if __name__ == "__main__":
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT","8080")), debug=True)
