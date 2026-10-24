# CivicConnect — Your city. Your voice. Your change.

Flask + MySQL + HTML/CSS/JS platform for transparent, trackable local governance.

## Features
- **Public (no login):** home dashboard with Open / Pending / Resolved counts, browse and filter all complaints, view photo, location map, status timeline and comments.
- **Citizen login:** raise a complaint (title, category, description, **photo required**, site address + GPS), comment on any complaint, see "My Complaints".
- **Admin / Official login:** admin dashboard, set status (Open / Pending / Resolved) with a public remark; officials' comments are badged.
- Location: browser "use my current location" button, with fallback to GPS data (EXIF) inside the uploaded photo.
- Security: hashed passwords, CSRF tokens on every POST, image validation, upload size limit.

## Setup
```bash
cd civicconnect
python -m venv venv && source venv/bin/activate     # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 1. create the database and tables
mysql -u root -p < schema.sql

# 2. configure (optional; defaults shown)
export DB_HOST=localhost DB_USER=root DB_PASSWORD=yourpassword DB_NAME=civicconnect
export SECRET_KEY="a-long-random-string"

# 3. create the first official/admin account
flask --app app create-admin

# 4. run
flask --app app run
```
Open http://127.0.0.1:5000

On Windows PowerShell use `$env:DB_PASSWORD="..."` instead of `export`.

## Pages
| URL | Access |
|---|---|
| `/` | public: dashboard + issue list |
| `/complaint/<id>` | public view; login to comment |
| `/login?role=user` / `role=admin` | two login types |
| `/register` | citizen sign-up |
| `/report`, `/dashboard` | citizen only |
| `/admin` | admin only |

## Before going live
Set a strong `SECRET_KEY`, run behind HTTPS (gunicorn + nginx), and set `SESSION_COOKIE_SECURE=True`.
