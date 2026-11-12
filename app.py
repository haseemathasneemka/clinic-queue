import secrets
from datetime import date, datetime, timedelta
from functools import wraps

import pymysql
from flask import (Flask, abort, flash, jsonify, redirect, render_template,
                   request, session, url_for)
from flask_socketio import SocketIO
from werkzeug.security import check_password_hash, generate_password_hash

from config import DB_CONFIG, DEFAULT_CONSULT_MIN, SECRET_KEY

app = Flask(__name__)
app.config["SECRET_KEY"] = SECRET_KEY
socketio = SocketIO(app, async_mode="threading")


# ---------------------------------------------------------------- database
def get_db():
    return pymysql.connect(**DB_CONFIG, cursorclass=pymysql.cursors.DictCursor)


def query(sql, args=(), one=False):
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(sql, args)
            rows = cur.fetchall()
        conn.commit()
        return (rows[0] if rows else None) if one else rows
    finally:
        conn.close()


def notify(doctor_id):
    """Tell every connected screen that this doctor's queue changed."""
    socketio.emit("queue_update", {"doctor_id": int(doctor_id)})


# ---------------------------------------------------------------- auth
def login_required(*roles):
    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if "user_id" not in session:
                if request.path.startswith("/api/"):
                    return jsonify(error="Login required"), 401
                return redirect(url_for("login", next=request.path))
            if roles and session.get("role") not in roles:
                abort(403)
            return view(*args, **kwargs)
        return wrapper
    return decorator


def can_manage(doctor_id):
    """Doctors may only control their own queue; staff can control all."""
    if session.get("role") == "doctor":
        return session.get("doctor_id") == int(doctor_id)
    return session.get("role") in ("admin", "receptionist")


# ---------------------------------------------------------------- queue logic
def issue_token(doctor_id, name, phone, source):
    """Issue the next token number for a doctor, safe under concurrent requests."""
    today, now = date.today(), datetime.now()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute("SELECT is_available FROM doctors WHERE id=%s", (doctor_id,))
            doc = cur.fetchone()
            if not doc or not doc["is_available"]:
                raise ValueError("This doctor is not available today.")

            cur.execute(
                "INSERT IGNORE INTO daily_counters (doctor_id, counter_date, last_no) VALUES (%s,%s,0)",
                (doctor_id, today),
            )
            # Row lock: a second request waits here until this transaction commits
            cur.execute(
                "SELECT last_no FROM daily_counters WHERE doctor_id=%s AND counter_date=%s FOR UPDATE",
                (doctor_id, today),
            )
            token_no = cur.fetchone()["last_no"] + 1
            cur.execute(
                "UPDATE daily_counters SET last_no=%s WHERE doctor_id=%s AND counter_date=%s",
                (token_no, doctor_id, today),
            )
            code = secrets.token_hex(4)
            cur.execute(
                """INSERT INTO tokens (public_code, doctor_id, token_date, token_no, patient_name,
                   phone, source, created_at) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)""",
                (code, doctor_id, today, token_no, name, phone, source, now),
            )
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
    notify(doctor_id)
    return code, token_no


def avg_consult_minutes(doctor_id):
    """Average consultation time today; falls back to last 7 days, then a default."""
    for days_back in (0, 7):
        row = query(
            """SELECT AVG(TIMESTAMPDIFF(SECOND, called_at, completed_at)) / 60 AS avg_min
               FROM tokens WHERE doctor_id=%s AND status='done'
               AND completed_at IS NOT NULL AND token_date >= %s""",
            (doctor_id, date.today() - timedelta(days=days_back)),
            one=True,
        )
        if row and row["avg_min"]:
            return round(float(row["avg_min"]), 1)
    return DEFAULT_CONSULT_MIN


def queue_state(doctor_id):
    doctor = query("SELECT * FROM doctors WHERE id=%s", (doctor_id,), one=True)
    if not doctor:
        return None
    tokens = query(
        """SELECT id, public_code, token_no, patient_name, phone, source, status, created_at
           FROM tokens WHERE doctor_id=%s AND token_date=%s ORDER BY token_no""",
        (doctor_id, date.today()),
    )
    for t in tokens:
        t["created_at"] = t["created_at"].strftime("%H:%M")
    serving = next((t for t in tokens if t["status"] == "serving"), None)
    avg = avg_consult_minutes(doctor_id)
    return {
        "doctor": {k: doctor[k] for k in ("id", "name", "specialization", "room")},
        "available": bool(doctor["is_available"]),
        "serving": serving,
        "waiting": [t for t in tokens if t["status"] == "waiting"],
        "absent": [t for t in tokens if t["status"] == "absent"],
        "done_count": sum(t["status"] == "done" for t in tokens),
        "avg_consult_min": avg,
    }


# ---------------------------------------------------------------- public pages
@app.route("/")
def index():
    doctors = query("SELECT * FROM doctors ORDER BY name")
    return render_template("index.html", doctors=doctors)


@app.route("/book", methods=["POST"])
def book():
    name = request.form.get("name", "").strip()
    phone = request.form.get("phone", "").strip()
    doctor_id = request.form.get("doctor_id", type=int)
    if not name or not phone.isdigit() or len(phone) != 10 or not doctor_id:
        flash("Please enter your name, a 10-digit phone number and pick a doctor.")
        return redirect(url_for("index"))
    try:
        code, _ = issue_token(doctor_id, name, phone, "online")
    except ValueError as e:
        flash(str(e))
        return redirect(url_for("index"))
    return redirect(url_for("track", code=code))


@app.route("/track/<code>")
def track(code):
    return render_template("track.html", code=code)


@app.route("/display")
def display():
    return render_template("display.html")


# ---------------------------------------------------------------- public APIs
@app.route("/api/track/<code>")
def api_track(code):
    t = query(
        """SELECT t.*, d.name AS doctor_name, d.room FROM tokens t
           JOIN doctors d ON d.id = t.doctor_id WHERE t.public_code=%s""",
        (code,), one=True,
    )
    if not t:
        return jsonify(error="Token not found"), 404
    current = query(
        "SELECT token_no FROM tokens WHERE doctor_id=%s AND token_date=%s AND status='serving'",
        (t["doctor_id"], t["token_date"]), one=True,
    )
    ahead = query(
        """SELECT COUNT(*) AS n FROM tokens WHERE doctor_id=%s AND token_date=%s
           AND status='waiting' AND token_no < %s""",
        (t["doctor_id"], t["token_date"], t["token_no"]), one=True,
    )["n"]
    avg = avg_consult_minutes(t["doctor_id"])
    people_before = ahead + (1 if current else 0)
    return jsonify(
        doctor_id=t["doctor_id"],
        token_no=t["token_no"],
        patient_name=t["patient_name"],
        doctor_name=t["doctor_name"],
        room=t["room"],
        status=t["status"],
        is_today=t["token_date"] == date.today(),
        now_serving=current["token_no"] if current else None,
        position=ahead + 1,
        est_wait_min=round(people_before * avg) if t["status"] == "waiting" else 0,
    )


@app.route("/api/display")
def api_display():
    doctors = query("SELECT id FROM doctors WHERE is_available=1 ORDER BY room")
    data = []
    for d in doctors:
        s = queue_state(d["id"])
        data.append({
            "doctor": s["doctor"],
            "now_serving": s["serving"]["token_no"] if s["serving"] else None,
            "next": [t["token_no"] for t in s["waiting"][:3]],
        })
    return jsonify(data)


# ---------------------------------------------------------------- login
@app.route("/login", methods=["GET", "POST"])
def login():
    if request.method == "POST":
        user = query("SELECT * FROM users WHERE username=%s",
                     (request.form.get("username", ""),), one=True)
        if user and check_password_hash(user["password_hash"], request.form.get("password", "")):
            session.clear()
            session.update(user_id=user["id"], username=user["username"],
                           role=user["role"], doctor_id=user["doctor_id"])
            nxt = request.args.get("next", "")
            # only allow local paths, never an outside website
            return redirect(nxt if nxt.startswith("/") and not nxt.startswith("//") else url_for("dashboard"))
        flash("Invalid username or password.")
    return render_template("login.html")


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("index"))


# ---------------------------------------------------------------- staff pages
@app.route("/dashboard")
@login_required()
def dashboard():
    if session["role"] == "doctor":
        doctors = query("SELECT * FROM doctors WHERE id=%s", (session["doctor_id"],))
    else:
        doctors = query("SELECT * FROM doctors ORDER BY name")
    return render_template("dashboard.html", doctors=doctors)


@app.route("/analytics")
@login_required()
def analytics():
    return render_template("analytics.html")


@app.route("/admin/doctors", methods=["GET", "POST"])
@login_required("admin")
def admin_doctors():
    if request.method == "POST":
        f = request.form
        if not all(f.get(k, "").strip() for k in ("name", "specialization", "room", "username", "password")):
            flash("All fields are required.")
        elif query("SELECT id FROM users WHERE username=%s", (f["username"],), one=True):
            flash("That username is already taken.")
        else:
            conn = get_db()
            try:
                with conn.cursor() as cur:
                    cur.execute("INSERT INTO doctors (name, specialization, room) VALUES (%s,%s,%s)",
                                (f["name"].strip(), f["specialization"].strip(), f["room"].strip()))
                    cur.execute(
                        "INSERT INTO users (username, password_hash, role, doctor_id) VALUES (%s,%s,'doctor',%s)",
                        (f["username"].strip(), generate_password_hash(f["password"]), cur.lastrowid))
                conn.commit()
                flash("Doctor added.")
            finally:
                conn.close()
        return redirect(url_for("admin_doctors"))
    doctors = query("""SELECT d.*, u.username FROM doctors d
                       LEFT JOIN users u ON u.doctor_id = d.id ORDER BY d.name""")
    return render_template("admin_doctors.html", doctors=doctors)


@app.route("/admin/doctors/<int:doctor_id>/toggle", methods=["POST"])
@login_required("admin")
def toggle_doctor(doctor_id):
    query("UPDATE doctors SET is_available = 1 - is_available WHERE id=%s", (doctor_id,))
    notify(doctor_id)
    return redirect(url_for("admin_doctors"))


# ---------------------------------------------------------------- staff APIs
@app.route("/api/queue/<int:doctor_id>")
@login_required()
def api_queue(doctor_id):
    if not can_manage(doctor_id):
        abort(403)
    state = queue_state(doctor_id)
    return jsonify(state) if state else (jsonify(error="Doctor not found"), 404)


@app.route("/api/tokens", methods=["POST"])
@login_required("admin", "receptionist")
def api_walkin():
    data = request.get_json(force=True)
    name, phone = data.get("name", "").strip(), data.get("phone", "").strip()
    if not name or not phone.isdigit() or len(phone) != 10:
        return jsonify(error="Enter a name and a 10-digit phone number."), 400
    try:
        code, token_no = issue_token(int(data["doctor_id"]), name, phone, "walkin")
    except ValueError as e:
        return jsonify(error=str(e)), 400
    return jsonify(token_no=token_no, track_url=url_for("track", code=code, _external=True))


@app.route("/api/doctor/<int:doctor_id>/next", methods=["POST"])
@login_required()
def api_call_next(doctor_id):
    """Finish the current patient and call the next waiting token."""
    if not can_manage(doctor_id):
        abort(403)
    now, today = datetime.now(), date.today()
    conn = get_db()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """UPDATE tokens SET status='done', completed_at=%s
                   WHERE doctor_id=%s AND token_date=%s AND status='serving'""",
                (now, doctor_id, today))
            cur.execute(
                """SELECT id, token_no FROM tokens WHERE doctor_id=%s AND token_date=%s
                   AND status='waiting' ORDER BY token_no LIMIT 1 FOR UPDATE""",
                (doctor_id, today))
            nxt = cur.fetchone()
            if nxt:
                cur.execute("UPDATE tokens SET status='serving', called_at=%s WHERE id=%s",
                            (now, nxt["id"]))
        conn.commit()
    finally:
        conn.close()
    notify(doctor_id)
    return jsonify(called=nxt["token_no"] if nxt else None)


@app.route("/api/token/<int:token_id>/<action>", methods=["POST"])
@login_required()
def api_token_action(token_id, action):
    """action = absent (patient didn't turn up) or recall (bring an absent patient back)."""
    t = query("SELECT doctor_id, status FROM tokens WHERE id=%s", (token_id,), one=True)
    if not t:
        abort(404)
    if not can_manage(t["doctor_id"]):
        abort(403)
    if action == "absent" and t["status"] in ("waiting", "serving"):
        query("UPDATE tokens SET status='absent', called_at=NULL WHERE id=%s", (token_id,))
    elif action == "recall" and t["status"] == "absent":
        query("UPDATE tokens SET status='waiting' WHERE id=%s", (token_id,))
    else:
        return jsonify(error="Action not allowed for this token."), 400
    notify(t["doctor_id"])
    return jsonify(ok=True)


@app.route("/api/analytics")
@login_required()
def api_analytics():
    since = date.today() - timedelta(days=30)
    hourly = query(
        """SELECT HOUR(created_at) AS h, COUNT(*) AS n FROM tokens
           WHERE token_date >= %s GROUP BY h ORDER BY h""", (since,))
    daily_wait = query(
        """SELECT token_date AS d, AVG(TIMESTAMPDIFF(MINUTE, created_at, called_at)) AS w
           FROM tokens WHERE token_date >= %s AND called_at IS NOT NULL
           GROUP BY token_date ORDER BY token_date""",
        (date.today() - timedelta(days=14),))
    per_doctor = query(
        """SELECT d.name, COUNT(t.id) AS total,
                  SUM(t.status='absent') AS absent,
                  AVG(CASE WHEN t.status='done'
                      THEN TIMESTAMPDIFF(SECOND, t.called_at, t.completed_at) / 60 END) AS consult
           FROM doctors d LEFT JOIN tokens t ON t.doctor_id = d.id AND t.token_date >= %s
           GROUP BY d.id, d.name ORDER BY d.name""", (since,))
    today = query(
        """SELECT COUNT(*) AS total, SUM(status='done') AS served, SUM(status='waiting') AS waiting,
                  AVG(TIMESTAMPDIFF(MINUTE, created_at, called_at)) AS avg_wait
           FROM tokens WHERE token_date=%s""", (date.today(),), one=True)
    return jsonify(
        hourly=[{"hour": r["h"], "count": r["n"]} for r in hourly],
        daily_wait=[{"date": r["d"].strftime("%d %b"), "wait": round(float(r["w"] or 0), 1)}
                    for r in daily_wait],
        per_doctor=[{
            "name": r["name"],
            "total": int(r["total"] or 0),
            "no_show_pct": round(100 * float(r["absent"] or 0) / r["total"], 1) if r["total"] else 0,
            "avg_consult": round(float(r["consult"] or 0), 1),
        } for r in per_doctor],
        today={
            "total": int(today["total"] or 0),
            "served": int(today["served"] or 0),
            "waiting": int(today["waiting"] or 0),
            "avg_wait": round(float(today["avg_wait"] or 0), 1),
        },
    )


@app.errorhandler(403)
def forbidden(_):
    return render_template("message.html", title="Not allowed",
                           text="You don't have permission to view this page."), 403


if __name__ == "__main__":
    # host 0.0.0.0 lets phones on the same Wi-Fi open http://<laptop-ip>:5000
    socketio.run(app, host="0.0.0.0", port=5000, debug=True, allow_unsafe_werkzeug=True)
