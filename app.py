"""
Astrology consultation app — Flask backend.

Endpoints:
  GET  /                      -> UI
  GET  /api/profiles          -> list stored profiles
  POST /api/profiles          -> create a profile
  DELETE /api/profiles/<id>   -> remove a profile
  GET  /api/chart/<id>        -> full computed context (chart, KP, dasha, numerology, transits)
  GET  /api/personas          -> available personas
  POST /api/ask               -> ask a persona a question

Run:
    pip install -r requirements.txt
    export ANTHROPIC_API_KEY=...          # or:
    export LLM_PROVIDER=gemini GEMINI_API_KEY=...
    python3 app.py
"""

import os
import traceback
from flask import Flask, request, jsonify, render_template, g
from functools import wraps

from astro_engine_v2 import (
    init_db, save_profile, list_profiles, get_profile, delete_profile,
    build_full_context, context_to_prompt_text,
)
from storage import (
    save_reading, list_readings, get_user, upsert_user, list_users,
    set_user_status, can_access_profile, adopt_orphan_profiles,
)
import auth
from astro_personas import PERSONAS, build_system_prompt, build_chart_block
from llm import generate, current_model, ProviderError, PROVIDER
import geocode

# Absolute template path: on a serverless host the working directory is not
# the repository root, so Flask's relative default fails to find them.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Exchanges of history replayed to the astrologer. One exchange is a
# question and its answer, so this is REPLAYED_TURNS * 2 messages. Three
# keeps a follow-up coherent without the prompt growing without limit.
REPLAYED_TURNS = int(os.environ.get('REPLAYED_TURNS', '3'))

app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
init_db()


# ------------------------------- auth -------------------------------

def _resolve_account():
    """Identify the caller, or return None when signed out.

    With no Supabase configured the app runs open, exactly as it did before
    sign-in existed, so `python app.py` on a laptop needs no accounts. That is
    a local-development convenience: on Vercel SUPABASE_URL is set, so this
    branch is not reachable in deployment.
    """
    if not auth.is_configured():
        return {"id": None, "email": None, "status": "admin", "open_mode": True}

    identity = auth.verify_token(auth.bearer_token(request.headers))
    record = upsert_user(identity["id"], identity["email"],
                         auth.intended_status(identity["email"]))

    # Charts saved before sign-in existed have no owner. The first admin to
    # arrive takes them, rather than leaving them permanently unreachable.
    if auth.is_admin(record):
        adopt_orphan_profiles(record["id"])
    return record


def require_user(admin_only=False):
    """Gate a route on a signed-in, approved account.

    Approval is checked on every request rather than at sign-in, so revoking
    someone takes effect immediately instead of when their token expires.
    """
    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            try:
                record = _resolve_account()
            except auth.AuthError as e:
                return jsonify({"error": str(e)}), e.status

            if not auth.may_use_app(record):
                return jsonify({
                    "error": "Your account is waiting for approval.",
                    "status": record.get("status", "pending"),
                }), 403

            if admin_only and not auth.is_admin(record):
                return jsonify({"error": "Administrators only."}), 403

            g.account = record
            g.is_admin = auth.is_admin(record)
            g.user_id = record.get("id")
            return view(*args, **kwargs)
        return wrapped
    return decorator


def _require_profile(pid):
    """403 unless the caller owns this chart, or is an admin."""
    if not can_access_profile(pid, g.user_id, g.is_admin):
        return jsonify({"error": "That chart is not yours."}), 403
    return None


@app.get("/api/config")
def api_config():
    """Public. What the browser needs to start a sign-in, nothing more.

    The publishable key is designed to ship in client code; it grants nothing
    on its own because every table has RLS on with no policies.
    """
    return jsonify({
        "replayed_turns": REPLAYED_TURNS,
        "auth_enabled": auth.is_configured(),
        "supabase_url": auth.SUPABASE_URL,
        "supabase_anon_key": auth.SUPABASE_ANON_KEY,
    })


@app.get("/api/me")
def api_me():
    """The caller's account and approval status. Used to choose which screen
    to show, so it must answer for pending accounts too, not only approved."""
    try:
        record = _resolve_account()
    except auth.AuthError as e:
        return jsonify({"error": str(e)}), e.status
    return jsonify({
        "id": record.get("id"),
        "email": record.get("email"),
        "status": record.get("status"),
        "is_admin": auth.is_admin(record),
        "open_mode": bool(record.get("open_mode")),
    })


# ------------------------------ admin -------------------------------

@app.get("/api/admin/users")
@require_user(admin_only=True)
def api_admin_users():
    return jsonify(list_users())


@app.post("/api/admin/users/<user_id>")
@require_user(admin_only=True)
def api_admin_set_status(user_id):
    status = (request.get_json(force=True) or {}).get("status")
    if str(user_id) == str(g.user_id):
        return jsonify({"error": "You cannot change your own status."}), 400
    try:
        return jsonify(set_user_status(user_id, status, approved_by=g.user_id))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400


# ----------------------------- profiles -----------------------------

@app.get("/api/profiles")
@require_user()
def api_list_profiles():
    rows = list_profiles(user_id=g.user_id, include_all=g.is_admin)
    return jsonify([
        {"id": r[0], "name": r[1], "place": r[2],
         "date": f"{r[5]:02d}/{r[4]:02d}/{r[3]}"}
        for r in rows
    ])


@app.post("/api/profiles")
@require_user()
def api_create_profile():
    d = request.get_json(force=True)
    required = ["name", "year", "month", "day", "hour", "minute", "tz_offset", "lat", "lon", "place"]
    missing = [k for k in required if d.get(k) in (None, "")]
    if missing:
        return jsonify({"error": f"Missing: {', '.join(missing)}"}), 400
    try:
        pid = save_profile(
            d["name"], int(d["year"]), int(d["month"]), int(d["day"]),
            int(d["hour"]), int(d["minute"]), float(d["tz_offset"]),
            float(d["lat"]), float(d["lon"]), d["place"],
            full_birth_name=d.get("full_birth_name") or d["name"],
            user_id=g.user_id,
        )
        return jsonify({"id": pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.delete("/api/profiles/<int:pid>")
@require_user()
def api_delete_profile(pid):
    denied = _require_profile(pid)
    if denied:
        return denied
    delete_profile(pid)
    return jsonify({"ok": True})


# ----------------------------- chart -----------------------------

@app.get("/api/chart/<int:pid>")
@require_user()
def api_chart(pid):
    denied = _require_profile(pid)
    if denied:
        return denied
    try:
        ctx = build_full_context(pid)
        return jsonify({
            "raw": ctx,
            "text": context_to_prompt_text(ctx),
        })
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 400


# ----------------------------- personas -----------------------------

@app.get("/api/personas")
def api_personas():
    return jsonify([
        {"key": k, "name": p["name"], "specialty": p["specialty"]}
        for k, p in PERSONAS.items()
    ])


@app.post("/api/ask")
@require_user()
def api_ask():
    d = request.get_json(force=True)
    pid = d.get("profile_id")
    question = (d.get("question") or "").strip()
    persona = d.get("persona", "integrated")
    history = d.get("history") or []

    # Cap what is replayed to the model. Left unbounded, a long chat
    # re-sends every previous reading on every question: by the tenth turn
    # that is nine full readings of input, and the cost of asking anything
    # grows with how long you have been talking.
    #
    # Enforced here rather than in the browser because the browser's copy is
    # advisory — a stale tab, or anything else posting to this endpoint,
    # could send the whole transcript. This also makes a live chat behave
    # the same as one resumed after a reload, which previously differed.
    history = history[-(REPLAYED_TURNS * 2):]

    if not pid or not question:
        return jsonify({"error": "profile_id and question are required"}), 400
    if persona not in PERSONAS:
        return jsonify({"error": f"Unknown persona: {persona}"}), 400

    denied = _require_profile(pid)
    if denied:
        return denied
    try:
        # Chart block is rebuilt fresh and attached to the current question
        # on every call — history is stored without it.
        messages = list(history)
        messages.append({
            "role": "user",
            "content": f"{build_chart_block(pid)}\n\nQuestion: {question}",
        })

        answer = generate(
            system=build_system_prompt(persona),
            messages=messages,
        )

        # Recorded after the answer exists, so a failed call leaves no
        # row. A storage failure must not lose a reading the querent is
        # already reading, so it is logged rather than raised.
        try:
            save_reading(pid, question, answer, persona=persona,
                         provider=PROVIDER, model=current_model())
        except Exception:
            traceback.print_exc()

        new_history = (list(history) + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])[-(REPLAYED_TURNS * 2):]
        return jsonify({"answer": answer, "history": new_history})

    except ProviderError as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/readings/<int:pid>")
@require_user()
def api_readings(pid):
    """Past questions and answers for one chart, newest first."""
    denied = _require_profile(pid)
    if denied:
        return denied
    try:
        return jsonify(list_readings(pid))
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/geocode")
@require_user()
def api_geocode():
    """Place name -> coordinates and the UTC offset in force at birth.

    The birth date is optional but worth sending: time zone offsets are
    historical, and the offset that applied in 1984 is often not the one
    that applies today."""
    query = request.args.get("q", "")

    birth = None
    year, month, day = (request.args.get(k) for k in ("year", "month", "day"))
    if year and month and day:
        try:
            birth = (int(year), int(month), int(day),
                     int(request.args.get("hour") or 12),
                     int(request.args.get("minute") or 0))
        except ValueError:
            birth = None   # partial or nonsense date: fall back to today's offset

    try:
        return jsonify(geocode.search(query, birth=birth))
    except geocode.GeocodeError as e:
        return jsonify({"error": str(e)}), 502


@app.get("/api/model")
@require_user()
def api_model():
    """Which provider and model are actually answering. Useful when
    comparing readings between providers."""
    return jsonify({"provider": PROVIDER, "model": current_model()})


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
