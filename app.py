"""CivicConnect - Your city. Your voice. Your change.

Flask + MySQL platform where citizens report local problems (with photo and
location), everyone can view open issues and statistics without logging in,
and officials (admins) update the status of each complaint.
"""
import os
import secrets
from datetime import datetime
from functools import wraps

import mysql.connector
from flask import (Flask, abort, flash, g, redirect, render_template, request,
                   session, url_for)
from PIL import Image
from PIL.ExifTags import GPSTAGS, TAGS
from werkzeug.security import check_password_hash, generate_password_hash

BASE_DIR = os.path.abspath(os.path.dirname(__file__))
UPLOAD_DIR = os.path.join(BASE_DIR, "static", "uploads")
ALLOWED_EXT = {"jpg", "jpeg", "png", "webp"}
STATUSES = ["Open", "Pending", "Resolved"]
CATEGORIES = ["Pothole / Road", "Garbage / Sanitation", "Street Light",
              "Water Supply", "Drainage / Sewage", "Electricity",
              "Public Property", "Other"]

app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.environ.get("SECRET_KEY", "change-me-in-production"),
    MAX_CONTENT_LENGTH=6 * 1024 * 1024,  # 6 MB upload limit
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

DB_CONFIG = dict(
    host=os.environ.get("DB_HOST", "localhost"),
    user=os.environ.get("DB_USER", "root"),
    password=os.environ.get("DB_PASSWORD", ""),
    database=os.environ.get("DB_NAME", "civicconnect"),
)

os.makedirs(UPLOAD_DIR, exist_ok=True)


# ---------------------------------------------------------------- database
def get_db():
    if "db" not in g:
        g.db = mysql.connector.connect(**DB_CONFIG)
    return g.db


@app.teardown_appcontext
def close_db(_exc):
    db = g.pop("db", None)
    if db is not None:
        db.close()


def query(sql, params=(), one=False):
    cur = get_db().cursor(dictionary=True)
    cur.execute(sql, params)
    rows = cur.fetchall()
    cur.close()
    return (rows[0] if rows else None) if one else rows


def execute(sql, params=()):
    db = get_db()
    cur = db.cursor()
    cur.execute(sql, params)
    db.commit()
    last_id = cur.lastrowid
    cur.close()
    return last_id


# ---------------------------------------------------------------- security
def csrf_token():
    if "_csrf" not in session:
        session["_csrf"] = secrets.token_hex(16)
    return session["_csrf"]


app.jinja_env.globals["csrf_token"] = csrf_token


@app.before_request
def protect_post():
    if request.method == "POST":
        sent = request.form.get("_csrf", "")
        if not sent or not secrets.compare_digest(sent, session.get("_csrf", "")):
            abort(400, "Invalid or missing security token. Please go back and retry.")


@app.before_request
def load_user():
    g.user = None
    uid = session.get("uid")
    if uid:
        g.user = query("SELECT id, name, email, role, locality FROM users WHERE id=%s",
                       (uid,), one=True)
        if g.user is None:
            session.clear()


def login_required(role=None):
    def deco(fn):
        @wraps(fn)
        def wrapper(*a, **kw):
            if g.user is None:
                flash("Please log in to continue.", "warn")
                return redirect(url_for("login", next=request.path))
            if role and g.user["role"] != role:
                abort(403)
            return fn(*a, **kw)
        return wrapper
    return deco


def safe_next(target):
    return target if target and target.startswith("/") and not target.startswith("//") else None


# ---------------------------------------------------------------- helpers
def _to_deg(value):
    d, m, s = (float(x) for x in value)
    return d + m / 60.0 + s / 3600.0


def extract_gps(path):
    """Try to read GPS coordinates from a photo's EXIF data."""
    try:
        with Image.open(path) as img:
            exif = img._getexif() or {}
        gps = {}
        for tag, val in exif.items():
            if TAGS.get(tag) == "GPSInfo":
                gps = {GPSTAGS.get(k, k): v for k, v in val.items()}
        if gps.get("GPSLatitude") and gps.get("GPSLongitude"):
            lat = _to_deg(gps["GPSLatitude"])
            lon = _to_deg(gps["GPSLongitude"])
            if gps.get("GPSLatitudeRef") == "S":
                lat = -lat
            if gps.get("GPSLongitudeRef") == "W":
                lon = -lon
            return round(lat, 7), round(lon, 7)
    except Exception:
        pass
    return None, None


def parse_coord(value, low, high):
    try:
        num = float(value)
        return num if low <= num <= high else None
    except (TypeError, ValueError):
        return None


def stats():
    rows = query("SELECT status, COUNT(*) AS n FROM complaints GROUP BY status")
    counts = {s: 0 for s in STATUSES}
    for r in rows:
        counts[r["status"]] = r["n"]
    counts["Total"] = sum(counts[s] for s in STATUSES)
    return counts


@app.template_filter("dt")
def fmt_dt(value):
    return value.strftime("%d %b %Y, %I:%M %p") if isinstance(value, datetime) else ""


# ---------------------------------------------------------------- public
@app.route("/")
def index():
    status = request.args.get("status", "")
    locality = request.args.get("locality", "").strip()
    q = request.args.get("q", "").strip()

    sql = ("SELECT c.*, u.name AS author, "
           "(SELECT COUNT(*) FROM comments cm WHERE cm.complaint_id=c.id) AS n_comments "
           "FROM complaints c JOIN users u ON u.id=c.user_id WHERE 1=1")
    params = []
    if status in STATUSES:
        sql += " AND c.status=%s"
        params.append(status)
    if locality:
        sql += " AND c.locality=%s"
        params.append(locality)
    if q:
        sql += " AND (c.title LIKE %s OR c.description LIKE %s)"
        params += [f"%{q}%", f"%{q}%"]
    sql += " ORDER BY c.created_at DESC LIMIT 60"

    localities = [r["locality"] for r in query(
        "SELECT DISTINCT locality FROM complaints ORDER BY locality")]
    return render_template("index.html", complaints=query(sql, params), stats=stats(),
                           localities=localities, f_status=status, f_locality=locality,
                           f_q=q, statuses=STATUSES)


@app.route("/complaint/<int:cid>")
def complaint(cid):
    c = query("SELECT c.*, u.name AS author FROM complaints c "
              "JOIN users u ON u.id=c.user_id WHERE c.id=%s", (cid,), one=True)
    if not c:
        abort(404)
    comments = query("SELECT cm.*, u.name, u.role FROM comments cm "
                     "JOIN users u ON u.id=cm.user_id WHERE cm.complaint_id=%s "
                     "ORDER BY cm.created_at ASC", (cid,))
    history = query("SELECT s.*, u.name AS admin_name FROM status_updates s "
                    "JOIN users u ON u.id=s.admin_id WHERE s.complaint_id=%s "
                    "ORDER BY s.created_at DESC", (cid,))
    return render_template("complaint.html", c=c, comments=comments, history=history,
                           statuses=STATUSES)


@app.route("/complaint/<int:cid>/comment", methods=["POST"])
@login_required()
def add_comment(cid):
    if not query("SELECT id FROM complaints WHERE id=%s", (cid,), one=True):
        abort(404)
    body = request.form.get("body", "").strip()
    if not body:
        flash("Comment cannot be empty.", "error")
    elif len(body) > 1000:
        flash("Comment is too long (max 1000 characters).", "error")
    else:
        execute("INSERT INTO comments (complaint_id, user_id, body) VALUES (%s,%s,%s)",
                (cid, g.user["id"], body))
        flash("Comment added.", "ok")
    return redirect(url_for("complaint", cid=cid) + "#comments")


# ---------------------------------------------------------------- auth
@app.route("/register", methods=["GET", "POST"])
def register():
    if g.user:
        return redirect(url_for("index"))
    if request.method == "POST":
        name = request.form.get("name", "").strip()
        email = request.form.get("email", "").strip().lower()
        locality = request.form.get("locality", "").strip()
        pw = request.form.get("password", "")
        error = None
        if not name or not email or not locality:
            error = "Name, email and locality are required."
        elif len(pw) < 6:
            error = "Password must be at least 6 characters."
        elif query("SELECT id FROM users WHERE email=%s", (email,), one=True):
            error = "An account with this email already exists."
        if error:
            flash(error, "error")
        else:
            uid = execute("INSERT INTO users (name,email,password_hash,role,locality) "
                          "VALUES (%s,%s,%s,'user',%s)",
                          (name, email, generate_password_hash(pw), locality))
            session.clear()
            session["uid"] = uid
            flash("Welcome to CivicConnect!", "ok")
            return redirect(url_for("dashboard"))
    return render_template("register.html")


@app.route("/login", methods=["GET", "POST"])
def login():
    role = request.values.get("role", "user")
    role = role if role in ("user", "admin") else "user"
    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        pw = request.form.get("password", "")
        user = query("SELECT * FROM users WHERE email=%s AND role=%s", (email, role), one=True)
        if user and check_password_hash(user["password_hash"], pw):
            session.clear()
            session["uid"] = user["id"]
            nxt = safe_next(request.args.get("next"))
            return redirect(nxt or url_for("admin_panel" if role == "admin" else "dashboard"))
        flash("Invalid email or password for this login type.", "error")
    return render_template("login.html", role=role)


@app.route("/logout", methods=["POST"])
def logout():
    session.clear()
    flash("You have been logged out.", "ok")
    return redirect(url_for("index"))


# ---------------------------------------------------------------- citizens
@app.route("/dashboard")
@login_required("user")
def dashboard():
    mine = query("SELECT c.*, (SELECT COUNT(*) FROM comments cm WHERE cm.complaint_id=c.id) "
                 "AS n_comments FROM complaints c WHERE c.user_id=%s ORDER BY c.created_at DESC",
                 (g.user["id"],))
    return render_template("dashboard.html", complaints=mine)


@app.route("/report", methods=["GET", "POST"])
@login_required("user")
def report():
    if request.method == "POST":
        title = request.form.get("title", "").strip()
        desc = request.form.get("description", "").strip()
        category = request.form.get("category", "")
        locality = request.form.get("locality", "").strip()
        address = request.form.get("address", "").strip()
        lat = parse_coord(request.form.get("latitude"), -90, 90)
        lon = parse_coord(request.form.get("longitude"), -180, 180)
        photo = request.files.get("photo")

        error = None
        if not (title and desc and locality and address):
            error = "Please fill in title, description, locality and site address."
        elif category not in CATEGORIES:
            error = "Please choose a category."
        elif len(desc) > 2000:
            error = "Description is too long (max 2000 characters)."
        elif not photo or not photo.filename:
            error = "A photo of the problem is required."
        else:
            ext = photo.filename.rsplit(".", 1)[-1].lower() if "." in photo.filename else ""
            if ext not in ALLOWED_EXT:
                error = "Photo must be a JPG, PNG or WEBP image."

        if error:
            flash(error, "error")
            return render_template("report.html", categories=CATEGORIES, form=request.form), 400

        filename = f"{secrets.token_hex(12)}.{ext}"
        path = os.path.join(UPLOAD_DIR, filename)
        photo.save(path)
        try:  # make sure the file is really an image
            with Image.open(path) as im:
                im.verify()
        except Exception:
            os.remove(path)
            flash("That file is not a valid image.", "error")
            return render_template("report.html", categories=CATEGORIES, form=request.form), 400

        if lat is None or lon is None:  # fall back to the photo's EXIF GPS data
            lat, lon = extract_gps(path)

        cid = execute("INSERT INTO complaints (user_id,title,description,category,locality,"
                      "address,latitude,longitude,photo) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s)",
                      (g.user["id"], title, desc, category, locality, address, lat, lon, filename))
        flash("Your complaint has been raised and is now visible to everyone.", "ok")
        return redirect(url_for("complaint", cid=cid))
    return render_template("report.html", categories=CATEGORIES, form={})


# ---------------------------------------------------------------- admin
@app.route("/admin")
@login_required("admin")
def admin_panel():
    status = request.args.get("status", "")
    sql = ("SELECT c.*, u.name AS author FROM complaints c JOIN users u ON u.id=c.user_id")
    params = []
    if status in STATUSES:
        sql += " WHERE c.status=%s"
        params.append(status)
    sql += " ORDER BY FIELD(c.status,'Open','Pending','Resolved'), c.created_at DESC"
    return render_template("admin.html", complaints=query(sql, params), stats=stats(),
                           statuses=STATUSES, f_status=status)


@app.route("/admin/complaint/<int:cid>/status", methods=["POST"])
@login_required("admin")
def set_status(cid):
    status = request.form.get("status", "")
    remark = request.form.get("remark", "").strip()[:500]
    if status not in STATUSES:
        abort(400)
    if not query("SELECT id FROM complaints WHERE id=%s", (cid,), one=True):
        abort(404)
    execute("UPDATE complaints SET status=%s WHERE id=%s", (status, cid))
    execute("INSERT INTO status_updates (complaint_id, admin_id, status, remark) "
            "VALUES (%s,%s,%s,%s)", (cid, g.user["id"], status, remark or None))
    flash(f"Complaint #{cid} marked as {status}.", "ok")
    return redirect(request.form.get("back") if safe_next(request.form.get("back"))
                    else url_for("admin_panel"))


# ---------------------------------------------------------------- errors / cli
@app.errorhandler(403)
@app.errorhandler(404)
@app.errorhandler(400)
@app.errorhandler(413)
def error_page(err):
    code = getattr(err, "code", 500)
    msg = {403: "You don't have access to this page.",
           404: "We couldn't find that page.",
           413: "That file is too large (max 6 MB)."}.get(code, getattr(err, "description", "Bad request."))
    return render_template("error.html", code=code, message=msg), code


@app.cli.command("create-admin")
def create_admin():
    """Create an official/admin account:  flask --app app create-admin"""
    import getpass
    name = input("Admin name: ").strip()
    email = input("Admin email: ").strip().lower()
    pw = getpass.getpass("Password (min 6 chars): ")
    if len(pw) < 6:
        print("Password too short.")
        return
    with app.app_context():
        execute("INSERT INTO users (name,email,password_hash,role) VALUES (%s,%s,%s,'admin')",
                (name, email, generate_password_hash(pw)))
    print("Admin created. Log in via the 'Admin' tab.")


if __name__ == "__main__":
    app.run(debug=os.environ.get("FLASK_DEBUG") == "1")
