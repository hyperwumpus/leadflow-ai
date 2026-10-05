import os
import sqlite3
from datetime import datetime, timedelta
from flask import Flask, render_template, request, redirect, url_for, flash, jsonify

APP_NAME = "LeadFlow AI"
DB_PATH = os.path.join(os.path.dirname(__file__), "leadflow.db")

app = Flask(__name__)
app.secret_key = os.environ.get("FLASK_SECRET_KEY", "dev-secret-change-me")


def db():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
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
        """
    )
    conn.commit()
    conn.close()


def qualify_lead(service, details, urgency):
    text = f"{service} {details}".lower()
    score = 45
    if urgency == "ASAP":
        score += 30
    elif urgency == "This week":
        score += 20
    elif urgency == "This month":
        score += 10

    high_intent = ["quote", "estimate", "book", "schedule", "repair", "replace", "install", "emergency", "today"]
    score += min(25, 5 * sum(1 for phrase in high_intent if phrase in text))
    score = max(0, min(score, 100))

    if score >= 80:
        priority = "Hot"
    elif score >= 60:
        priority = "Warm"
    else:
        priority = "Normal"

    summary = f"{priority} lead for {service}. Urgency: {urgency}."
    if details:
        clipped = details.strip().replace("\n", " ")[:180]
        summary += f" Customer says: {clipped}"

    draft = (
        f"Hi {{first_name}}, thanks for reaching out about {service.lower()}. "
        f"We received your request and can help. "
        f"The next step is a quick call or appointment so we can confirm the details and give you an accurate quote. "
        f"What time works best for you?"
    )
    return score, summary, draft


@app.route("/")
def dashboard():
    conn = db()
    leads = conn.execute("SELECT * FROM leads ORDER BY datetime(created_at) DESC").fetchall()
    stats = {
        "total": conn.execute("SELECT COUNT(*) FROM leads").fetchone()[0],
        "new": conn.execute("SELECT COUNT(*) FROM leads WHERE status='New'").fetchone()[0],
        "hot": conn.execute("SELECT COUNT(*) FROM leads WHERE score>=80 AND status NOT IN ('Won','Lost')").fetchone()[0],
        "won": conn.execute("SELECT COUNT(*) FROM leads WHERE status='Won'").fetchone()[0],
    }
    due = conn.execute(
        "SELECT * FROM leads WHERE followup_at IS NOT NULL AND datetime(followup_at) <= datetime(?) AND status NOT IN ('Won','Lost') ORDER BY datetime(followup_at)",
        (datetime.now().isoformat(timespec="seconds"),),
    ).fetchall()
    conn.close()
    return render_template("dashboard.html", app_name=APP_NAME, leads=leads, stats=stats, due=due)


@app.route("/intake", methods=["GET", "POST"])
def intake():
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        phone = request.form.get("phone", "").strip()
        email = request.form.get("email", "").strip()
        service = request.form.get("service", "").strip()
        details = request.form.get("details", "").strip()
        urgency = request.form.get("urgency", "This month").strip()
        if not name or not service:
            flash("Name and service are required.")
            return redirect(url_for("intake"))

        score, summary, draft = qualify_lead(service, details, urgency)
        now = datetime.now()
        followup = now + timedelta(hours=2 if score >= 80 else 24)
        conn = db()
        cur = conn.execute(
            """INSERT INTO leads
            (created_at,name,phone,email,service,details,urgency,score,status,ai_summary,response_draft,followup_at,source)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (now.isoformat(timespec="seconds"), name, phone, email, service, details, urgency, score, "New", summary, draft, followup.isoformat(timespec="seconds"), "Website"),
        )
        lead_id = cur.lastrowid
        conn.execute(
            "INSERT INTO activity (lead_id,created_at,activity_type,note) VALUES (?,?,?,?)",
            (lead_id, now.isoformat(timespec="seconds"), "Lead captured", f"Auto-qualified at {score}/100"),
        )
        conn.commit()
        conn.close()
        return redirect(url_for("thanks", lead_id=lead_id))
    return render_template("intake.html", app_name=APP_NAME)


@app.route("/thanks/<int:lead_id>")
def thanks(lead_id):
    conn = db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    conn.close()
    if not lead:
        return "Lead not found", 404
    return render_template("thanks.html", app_name=APP_NAME, lead=lead)


@app.route("/lead/<int:lead_id>", methods=["GET", "POST"])
def lead_detail(lead_id):
    conn = db()
    lead = conn.execute("SELECT * FROM leads WHERE id=?", (lead_id,)).fetchone()
    if not lead:
        conn.close()
        return "Lead not found", 404

    if request.method == "POST":
        status = request.form.get("status", lead["status"])
        response_draft = request.form.get("response_draft", lead["response_draft"])
        followup_at = request.form.get("followup_at") or None
        conn.execute(
            "UPDATE leads SET status=?, response_draft=?, followup_at=? WHERE id=?",
            (status, response_draft, followup_at, lead_id),
        )
        conn.execute(
            "INSERT INTO activity (lead_id,created_at,activity_type,note) VALUES (?,?,?,?)",
            (lead_id, datetime.now().isoformat(timespec="seconds"), "Lead updated", f"Status: {status}"),
        )
        conn.commit()
        conn.close()
        flash("Lead updated.")
        return redirect(url_for("lead_detail", lead_id=lead_id))

    activity = conn.execute("SELECT * FROM activity WHERE lead_id=? ORDER BY datetime(created_at) DESC", (lead_id,)).fetchall()
    conn.close()
    return render_template("lead.html", app_name=APP_NAME, lead=lead, activity=activity)


@app.route("/lead/<int:lead_id>/mark-contacted", methods=["POST"])
def mark_contacted(lead_id):
    conn = db()
    conn.execute("UPDATE leads SET status='Contacted', followup_at=? WHERE id=?", ((datetime.now()+timedelta(days=1)).isoformat(timespec="seconds"), lead_id))
    conn.execute("INSERT INTO activity (lead_id,created_at,activity_type,note) VALUES (?,?,?,?)", (lead_id, datetime.now().isoformat(timespec="seconds"), "Contacted", "Response marked as sent"))
    conn.commit()
    conn.close()
    return redirect(url_for("lead_detail", lead_id=lead_id))


@app.route("/api/leads")
def api_leads():
    conn = db()
    rows = conn.execute("SELECT * FROM leads ORDER BY datetime(created_at) DESC").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])


if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=True)
