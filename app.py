"""
CTM Softphone Web App — desk mode
----------------------------------
Two-panel layout: CTM phone embed (left) + activity log (right).
Phone embed authenticates via /ctm-phone-access using identity from .env
or a one-time login form.
"""

import os
import uuid
import base64
import functools
import subprocess
import tempfile
import requests

from flask import (
    Flask, session, request, redirect, url_for,
    render_template, jsonify, Response
)
from dotenv import load_dotenv

load_dotenv()

app = Flask(__name__)
app.secret_key = os.environ["FLASK_SECRET_KEY"]

CTM_API_KEY    = os.environ.get("CTM_API_KEY", "")
CTM_API_SECRET = os.environ.get("CTM_API_SECRET", "")
CTM_ACCOUNT_ID = os.environ.get("DEFAULT_ACCOUNT_ID", "")
CTM_BASE       = "https://app.calltrackingmetrics.com/api/v1"

# Optional: pre-configure user identity so no login form is needed
CTM_USER_EMAIL = os.environ.get("CTM_USER_EMAIL", "")
CTM_USER_FIRST = os.environ.get("CTM_USER_FIRST", "")
CTM_USER_LAST  = os.environ.get("CTM_USER_LAST", "")


def login_required(f):
    @functools.wraps(f)
    def wrapper(*args, **kwargs):
        _auto_login()
        if "email" not in session:
            return redirect(url_for("login"))
        return f(*args, **kwargs)
    return wrapper


def _auto_login():
    """If identity is pre-configured in .env, skip the login form."""
    if "email" not in session and CTM_USER_EMAIL and CTM_USER_FIRST and CTM_USER_LAST:
        session["email"]      = CTM_USER_EMAIL
        session["first_name"] = CTM_USER_FIRST
        session["last_name"]  = CTM_USER_LAST
        session["session_id"] = str(uuid.uuid4())


def ctm_get(path, params=None):
    r = requests.get(
        f"{CTM_BASE}{path}",
        params=params,
        auth=(CTM_API_KEY, CTM_API_SECRET),
        timeout=15,
    )
    r.raise_for_status()
    return r.json()


# ── Pages ────────────────────────────────────────────────────────────────────

@app.get("/login")
def login():
    _auto_login()
    if "email" in session:
        return redirect(url_for("index"))
    return render_template("login.html", error=None)


@app.post("/login")
def login_post():
    email      = request.form.get("email", "").strip()
    first_name = request.form.get("first_name", "").strip()
    last_name  = request.form.get("last_name", "").strip()
    if not all([email, first_name, last_name]):
        return render_template("login.html", error="All fields are required.")
    session.clear()
    session["email"]      = email
    session["first_name"] = first_name
    session["last_name"]  = last_name
    session["session_id"] = str(uuid.uuid4())
    return redirect(url_for("index"))


@app.get("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.get("/")
@login_required
def index():
    return render_template("phone.html",
                           user_name=f"{session['first_name']} {session['last_name']}")


# ── Phone embed auth ─────────────────────────────────────────────────────────

@app.post("/ctm-phone-access")
@login_required
def ctm_phone_access():
    payload = {
        "email":      session["email"],
        "first_name": session["first_name"],
        "last_name":  session["last_name"],
        "session_id": session["session_id"],
    }
    try:
        r = requests.post(
            f"{CTM_BASE}/accounts/{CTM_ACCOUNT_ID}/phone_access",
            json=payload,
            auth=(CTM_API_KEY, CTM_API_SECRET),
            timeout=10,
        )
        r.raise_for_status()
        data = r.json()
    except requests.RequestException as exc:
        app.logger.error("CTM phone_access error: %s", exc)
        return jsonify({"status": "error", "message": str(exc)}), 502

    data.update({
        "sessionId":  session["session_id"],
        "email":      session["email"],
        "first_name": session["first_name"],
        "last_name":  session["last_name"],
        "session_id": session["session_id"],
    })
    return jsonify(data)


@app.post("/ctm-phone-refresh")
@login_required
def ctm_phone_refresh():
    return ctm_phone_access()


# ── Data proxies ─────────────────────────────────────────────────────────────

@app.get("/ctm/calls")
@login_required
def ctm_calls():
    try:
        data  = ctm_get(f"/accounts/{CTM_ACCOUNT_ID}/calls.json", {"per_page": 50})
        calls = data.get("calls", data.get("data", []))
        error = None
    except Exception as exc:
        calls, error = [], str(exc)
    return render_template("data/calls.html", calls=calls, error=error)


@app.get("/ctm/messages")
@login_required
def ctm_messages():
    try:
        data     = ctm_get(f"/accounts/{CTM_ACCOUNT_ID}/messages.json", {"per_page": 50})
        messages = data.get("messages", data.get("data", []))
        error    = None
    except Exception as exc:
        messages, error = [], str(exc)
    return render_template("data/messages.html", messages=messages, error=error)


# ── Account Assessment ───────────────────────────────────────────────────────

ASSESSMENT_SCRIPT = os.path.expanduser(
    "~/Scripts/ctm-account-assessment/src/ctm_account_asses.py"
)
ASSESSMENT_PYTHON = os.path.expanduser(
    "~/Scripts/ctm-account-assessment/venv/bin/python"
)

@app.get("/assessment")
@login_required
def assessment():
    """Run the CTM account assessment and stream the HTML report back."""

    # The assessment script sends Authorization: Basic <value> directly,
    # so it needs the standard base64(key:secret) encoding.
    basic_token = base64.b64encode(
        f"{CTM_API_KEY}:{CTM_API_SECRET}".encode()
    ).decode()

    def generate():
        yield "<p style='padding:20px;font-family:sans-serif'>⏳ Running account assessment — this takes ~30–60 seconds…</p>"

        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                result = subprocess.run(
                    [
                        ASSESSMENT_PYTHON,
                        ASSESSMENT_SCRIPT,
                        "--account-id", CTM_ACCOUNT_ID,
                        "--api-key",    basic_token,
                        "--out-dir",    tmpdir,
                        "--calls-limit","200",
                    ],
                    capture_output=True,
                    text=True,
                    timeout=180,
                )
            except subprocess.TimeoutExpired:
                yield "<p style='color:red;padding:20px'>Assessment timed out after 3 minutes.</p>"
                return
            except Exception as exc:
                yield f"<p style='color:red;padding:20px'>Error running assessment: {exc}</p>"
                return

            if result.returncode != 0:
                yield (
                    f"<p style='color:red;padding:20px'>Assessment failed:<br>"
                    f"<pre>{result.stderr[:2000]}</pre></p>"
                )
                return

            html_path = os.path.join(
                tmpdir, f"ctm_account_assessment_{CTM_ACCOUNT_ID}.html"
            )
            if not os.path.exists(html_path):
                yield "<p style='color:red;padding:20px'>Assessment ran but no HTML file was produced.</p>"
                return

            with open(html_path, encoding="utf-8") as f:
                yield f.read()

    return Response(generate(), mimetype="text/html")


# ── Run ──────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    port  = int(os.environ.get("PORT", 8080))
    debug = os.environ.get("FLASK_DEBUG", "1") == "1"
    app.run(host="0.0.0.0", port=port, debug=debug)
