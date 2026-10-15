"""
LeadWolf — lead capture, qualification, and follow-up for local service businesses.

A single-file Flask app. Run with:  python app.py
Then open: http://127.0.0.1:5000

Features:
  - Public quote-request intake form (/intake)
  - Transparent lead scoring (0-100) with a visible score breakdown
  - CRM dashboard with search, status filter, and follow-up queue
  - Per-lead detail: qualification summary, editable response draft,
    status pipeline, activity trail, delete
  - CSV export of all leads (/export.csv)
  - White-label business name in Settings (used on the intake form
    and inside response drafts)
  - JSON API at /api/leads
  - Local SQLite storage, no external services required
"""
import csv
import io
import json
import os
import re
import sqlite3
from datetime import datetime, timedelta

from flask import (
    Flask, render_template, request, redirect, url_for,
    flash, jsonify, Response,
)

APP_NAME = "LeadWolf"
TAGLINE = "Hunt every lead."
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "leadwolf.db")

app = Flask(__name__)
# In production, set FLASK_SECRET_KEY in the environment.
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")

# ---------------------------------------------------------------------------
# Scoring configuration (transparent, explainable — show the math, not magic)
# ---------------------------------------------------------------------------
BASE_SCORE = 40

URGENCY_POINTS = {
    "ASAP": 35,
    "This week": 25,
    "This month": 10,
    "Just researching": 0,
}
VALID_URGENCIES = list(URGENCY_POINTS.keys())

# Each matched keyword adds 5 points, capped at +25.
HIGH_INTENT_KEYWORDS = [
    "quote", "estimate", "book", "schedule", "repair", "replace",
    "install", "emergency", "today", "broken", "leaking",
]
KEYWORD_POINTS_EACH = 5
KEYWORD_POINTS_MAX = 25

STATUSES = ["New", "Contacted", "Qualified", "Appointment Set", "Won", "Lost"]
TERMINAL_STATUSES = ("Won", "Lost")


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------
def db():
    """Open a new SQLite connection with dict-like rows."""
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    """Create tables if they don't exist. Safe to run on every start."""
    conn = db()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS leads (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            created_at TEXT NOT NULL,
            name TEXT NOT NULL,
            phone TEXT,
            email TEXT,
            service TEXT NOT NULL,
            details TEXT,
            urgency TEXT NOT NULL,
            score INTEGER NOT NULL,
            score_breakdown TEXT,
            status TEXT NOT NULL DEFAULT 'New',
            ai_summary TEXT,
            response_draft TEXT,
            followup_at TEXT,
            source TEXT DEFAULT 'Website'
        );
        CREATE TABLE IF NOT EXISTS activity (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            lead_id INTEGER NOT NULL,
            created_at TEXT NOT NULL,
            activity_type TEXT NOT NULL,
            note TEXT,
            FOREIGN KEY (lead_id) REFERENCES leads(id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        """
    )
    # Seed the white-label business name if it was never set.
    row = conn.execute(
        "SELECT value FROM settings WHERE key='business_name'"
    ).fetchone()
    if not row:
        conn.execute(
            "INSERT INTO settings (key, value) VALUES ('business_name', 'Your Business')"
        )

    # Backfill: older databases won't have score_breakdown — add it.
    cols = [r["name"] for r in conn.execute("PRAGMA table_info(leads)")]
    if "score_breakdown" not in cols:
        conn.execute("ALTER TABLE leads ADD COLUMN score_breakdown TEXT")

    conn.commit()
    conn.close()


def get_setting(key, default=""):
    conn = db()
    row = conn.execute(
        "SELECT value FROM settings WHERE key=?", (key,)
    ).fetchone()
    conn.close()
    return row["value"] if row else default


def set_setting(key, value):
    conn = db()
    conn.execute(
        "INSERT INTO settings (key, value) VALUES (?, ?) "
        "ON CONFLICT(key) DO UPDATE SET value=excluded.value",
        (key, value),
    )
    conn.commit()
    conn.close()


# ---------------------------------------------------------------------------
# Scoring — transparent and explainable
# ---------------------------------------------------------------------------
def qualify_lead(service, details, urgency, business_name):
    """Score a lead 0-100 and return (score, breakdown_dict, summary, draft).

    The breakdown dict is stored as JSON so the UI can show exactly
    why a lead got its score.
    """
    text = f"{service} {details}".lower()

    base = BASE_SCORE
    urgency_pts = URGENCY_POINTS.get(urgency, 0)

    matched = [kw for kw in HIGH_INTENT_KEYWORDS if kw in text]
    keyword_pts = min(KEYWORD_POINTS_MAX, KEYWORD_POINTS_EACH * len(matched))

    score = max(0, min(100, base + urgency_pts + keyword_pts))

    if score >= 80:
        priority = "Hot"
    elif score >= 60:
        priority = "Warm"
    else:
        priority = "Normal"

    breakdown = {
        "base": base,
        "urgency_label": urgency,
        "urgency_points": urgency_pts,
        "keywords_matched": matched,
        "keyword_points": keyword_pts,
        "total": score,
        "priority": priority,
    }

    summary = f"{priority} lead for {service}. Urgency: {urgency}."
    if details:
        clipped = details.strip().replace("\n", " ")[:180]
        summary += f" Customer says: {clipped}"

    draft = (
        f"Hi {{first_name}}, thanks for reaching out to {business_name} "
        f"about {service.lower()}. "
        f"We received your request and we can help. "
        f"The next step is a quick call or appointment so we can confirm "
        f"the details and give you an accurate quote. "
        f"What time works best for you?"
    )
    return score, breakdown, summary, draft


def first_name_of(full_name):
    """Return the first token of a name, or the full string if no spaces."""
    parts = (full_name or "").strip().split()
    return parts[0] if parts else full_name


def render_draft(draft_template, full_name):
    """Replace {first_name} with the lead's actual first name."""
    return draft_template.replace("{first_name}", first_name_of(full_name))


# ---------------------------------------------------------------------------
# Validation
# ---------------------------------------------------------------------------
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def validate_intake(form):
    """Return (cleaned_dict, errors_list) for the intake form."""
    name = form.get("name", "").strip()
    phone = form.get("phone", "").strip()
    email = form.get("email", "").strip()
    service = form.get("service", "").strip()
    details = form.get("details", "").strip()
    urgency = form.get("urgency", "This month").strip()

    errors = []
    if len(name) < 2:
        errors.append("Please enter your name.")
    if not service:
        errors.append("Please tell us what you need help with.")
    if email and not EMAIL_RE.match(email):
        errors.append("That email address doesn't look valid.")
    if urgency not in VALID_URGENCIES:
        urgency = "This month"  # fail safe, never crash on bad input

    cleaned = {
        "name": name, "phone": phone, "email": email,
        "service": service, "details": details, "urgency": urgency,
    }
    return cleaned, errors


def log_activity(conn, lead_id, activity_type, note):
    conn.execute(
        "INSERT INTO activity (lead_id, created_at, activity_type, note)"
        " VALUES (?, ?, ?, ?)",
        (lead_id, datetime.now().isoformat(timespec="seconds"),
         activity_type, note),
    )


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------
@app.route("/")
def dashboard():
    """CRM dashboard with search, status filter, stats, and follow-up queue."""
    q = request.args.get("q", "").strip()
    status_filter = request.args.get("status", "").strip()

    conn = db()
    where = []
    params = []
    if q:
        where.append("(name LIKE ? OR service LIKE ? OR details LIKE ?"
                     " OR phone LIKE ? OR email LIKE ?)")
        like = f"%{q}%"
        params.extend([like] * 5)
    if status_filter and status_filter in STATUSES:
        where.append("status = ?")
        params.append(status_filter)
    where_sql = f"WHERE {' AND '.join(where)}" if where else ""

    leads = conn.execute(
        f"SELECT * FROM leads {where_sql} ORDER BY datetime(created_at) DESC",
        params,
    ).fetchall()

    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
        "new": conn.execute(
            "SELECT COUNT(*) FROM leads WHERE status='New'").fetchone()[0],
        "hot": conn.execute(
            "SELECT COUNT(*) FROM leads WHERE score >= 80"
            " AND status NOT IN ('Won','Lost')").fetchone()[0],
        "won": conn.execute(
            "SELECT COUNT(*) FROM leads WHERE status='Won'").fetchone()[0],
    }
    due = conn.execute(
        "SELECT * FROM leads WHERE followup_at IS NOT NULL"
        " AND datetime(followup_at) <= datetime(?)"
        " AND status NOT IN ('Won','Lost')"
        " ORDER BY datetime(followup_at)",
        (datetime.now().isoformat(timespec="seconds"),),
    ).fetchall()
    conn.close()

    return render_template(
        "dashboard.html", app_name=APP_NAME, tagline=TAGLINE,
        leads=leads, stats=stats, due=due,
        q=q, status_filter=status_filter, statuses=STATUSES,
    )


@app.route("/intake", methods=["GET", "POST"])
def intake():
    """Customer-facing quote request form (embed this on a business site)."""
    business_name = get_setting("business_name", "Your Business")
    if request.method == "POST":
        cleaned, errors = validate_intake(request.form)
        if errors:
            for e in errors:
                flash(e)
            # Re-render with their values preserved so nothing is lost.
            return render_template(
                "intake.html", app_name=APP_NAME, tagline=TAGLINE,
                business_name=business_name, form=cleaned,
                urgencies=VALID_URGENCIES,
            ), 400

        score, breakdown, summary, draft_template = qualify_lead(
            cleaned["service"], cleaned["details"],
            cleaned["urgency"], business_name,
        )
        # The stored draft has the real first name baked in.
        draft = render_draft(draft_template, cleaned["name"])

        now = datetime.now()
        followup = now + timedelta(hours=2 if score >= 80 else 24)
        conn = db()
        cur = conn.execute(
            """INSERT INTO leads
            (created_at, name, phone, email, service, details, urgency,
             score, score_breakdown, status, ai_summary, response_draft,
             followup_at, source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                now.isoformat(timespec="seconds"),
                cleaned["name"], cleaned["phone"], cleaned["email"],
                cleaned["service"], cleaned["details"], cleaned["urgency"],
                score, json.dumps(breakdown), "New", summary, draft,
                followup.isoformat(timespec="seconds"), "Website",
            ),
        )
        lead_id = cur.lastrowid
        log_activity(conn, lead_id, "Lead captured",
                     f"Auto-qualified at {score}/100 ({breakdown['priority']})")
        conn.commit()
        conn.close()
        return redirect(url_for("thanks", lead_id=lead_id))

    return render_template(
        "intake.html", app_name=APP_NAME, tagline=TAGLINE,
        business_name=business_name, form={}, urgencies=VALID_URGENCIES,
    )


@app.route("/thanks/<int:lead_id>")
def thanks(lead_id):
    conn = db()
    lead = conn.execute(
        "SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    if not lead:
        return "Lead not found", 404
    return render_template(
        "thanks.html", app_name=APP_NAME, tagline=TAGLINE, lead=lead,
        business_name=get_setting("business_name", "Your Business"),
    )


@app.route("/lead/<int:lead_id>", methods=["GET", "POST"])
def lead_detail(lead_id):
    conn = db()
    lead = conn.execute(
        "SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        return "Lead not found", 404

    if request.method == "POST":
        status = request.form.get("status", lead["status"])
        if status not in STATUSES:
            status = lead["status"]  # ignore tampered values
        response_draft = request.form.get(
            "response_draft", lead["response_draft"])
        followup_raw = (request.form.get("followup_at") or "").strip()
        followup_at = followup_raw or None
        conn.execute(
            "UPDATE leads SET status=?, response_draft=?, followup_at=?"
            " WHERE id=?",
            (status, response_draft, followup_at, lead_id),
        )
        log_activity(conn, lead_id, "Lead updated", f"Status: {status}")
        conn.commit()
        conn.close()
        flash("Lead updated.")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    activity = conn.execute(
        "SELECT * FROM activity WHERE lead_id=?"
        " ORDER BY datetime(created_at) DESC",
        (lead_id,),
    ).fetchall()
    conn.close()

    try:
        breakdown = json.loads(lead["score_breakdown"]) if lead["score_breakdown"] else None
    except (json.JSONDecodeError, TypeError):
        breakdown = None

    return render_template(
        "lead.html", app_name=APP_NAME, tagline=TAGLINE,
        lead=lead, activity=activity, breakdown=breakdown,
        statuses=STATUSES,
    )


@app.route("/lead/<int:lead_id>/mark-contacted", methods=["POST"])
def mark_contacted(lead_id):
    """Mark the response as sent; push follow-up to tomorrow."""
    conn = db()
    exists = conn.execute(
        "SELECT 1 FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not exists:
        conn.close()
        return "Lead not found", 404
    followup = (datetime.now() + timedelta(days=1)).isoformat(timespec="seconds")
    conn.execute(
        "UPDATE leads SET status='Contacted', followup_at=? WHERE id=?",
        (followup, lead_id),
    )
    log_activity(conn, lead_id, "Contacted", "Response marked as sent")
    conn.commit()
    conn.close()
    flash("Marked as contacted — follow-up set for tomorrow.")
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.route("/lead/<int:lead_id>/delete", methods=["POST"])
def delete_lead(lead_id):
    """Permanently delete a lead and its activity trail."""
    conn = db()
    lead = conn.execute(
        "SELECT name FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        return "Lead not found", 404
    conn.execute("DELETE FROM activity WHERE lead_id=?", (lead_id,))
    conn.execute("DELETE FROM leads WHERE id=?", (lead_id,))
    conn.commit()
    conn.close()
    flash(f"Deleted lead: {lead['name']}.")
    return redirect(url_for("dashboard"))


@app.route("/export.csv")
def export_csv():
    """Download every lead as CSV."""
    conn = db()
    rows = conn.execute(
        "SELECT id, created_at, name, phone, email, service, details,"
        " urgency, score, status, followup_at, source"
        " FROM leads ORDER BY datetime(created_at) DESC"
    ).fetchall()
    conn.close()

    buf = io.StringIO()
    writer = csv.writer(buf)
    writer.writerow(["id", "created_at", "name", "phone", "email", "service",
                     "details", "urgency", "score", "status",
                     "followup_at", "source"])
    for r in rows:
        writer.writerow([r["id"], r["created_at"], r["name"], r["phone"],
                         r["email"], r["service"], r["details"], r["urgency"],
                         r["score"], r["status"], r["followup_at"],
                         r["source"]])
    return Response(
        buf.getvalue(),
        mimetype="text/csv",
        headers={"Content-Disposition": "attachment; filename=leadwolf-leads.csv"},
    )


@app.route("/settings", methods=["GET", "POST"])
def settings():
    """White-label settings — business name used on the intake form & drafts."""
    if request.method == "POST":
        business_name = request.form.get("business_name", "").strip()
        if len(business_name) < 2:
            flash("Business name must be at least 2 characters.")
        else:
            set_setting("business_name", business_name)
            flash("Settings saved.")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html", app_name=APP_NAME, tagline=TAGLINE,
        business_name=get_setting("business_name", "Your Business"),
    )


@app.route("/api/leads")
def api_leads():
    """JSON API — newest leads first."""
    conn = db()
    rows = conn.execute(
        "SELECT id, created_at, name, phone, email, service, details,"
        " urgency, score, score_breakdown, status, ai_summary,"
        " followup_at, source"
        " FROM leads ORDER BY datetime(created_at) DESC"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0",
            port=int(os.environ.get("PORT", 5000)),
            debug=True)
