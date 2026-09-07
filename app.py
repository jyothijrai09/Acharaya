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
    build_full_context, context_to_prompt_text, compute_here_now,
)
from storage import (
    save_reading, list_readings, get_user, upsert_user, list_users,
    set_user_status, can_access_profile, adopt_orphan_profiles,
    count_readings_today, usage_summary, spend_today,
    get_horoscope, save_horoscope, delete_horoscope,
)
import horoscopes
import auth
from astro_personas import PERSONAS, build_system_prompt, build_chart_block
from llm import (
    generate, current_model, ProviderError, PROVIDER, available_choices,
    LAST_USAGE, cost_of,
)
import geocode

# Absolute template path: on a serverless host the working directory is not
# the repository root, so Flask's relative default fails to find them.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# Exchanges of history replayed to the astrologer. One exchange is a
# question and its answer, so this is REPLAYED_TURNS * 2 messages. Three
# keeps a follow-up coherent without the prompt growing without limit.
REPLAYED_TURNS = int(os.environ.get('REPLAYED_TURNS', '3'))

# Readings one account may ask for per day. This is the only limit that
# stops a runaway BEFORE it reaches a provider - a spend cap at Anthropic or
# a quota at Google both fire after the request has already been made and
# paid for. Set to 0 to remove the cap.
DAILY_READING_LIMIT = int(os.environ.get('DAILY_READING_LIMIT', '25'))

# Dollars the whole app may spend per day, across every account. Global
# rather than per-account because this caps the BILL, and the bill does
# not care who ran it up. Readings on a free tier cost nothing and never
# consume it. Set to 0 to remove the cap.
DAILY_BUDGET_USD = float(os.environ.get('DAILY_BUDGET_USD', '2.00'))

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
        "daily_limit": DAILY_READING_LIMIT,
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


@app.get("/api/admin/usage")
@require_user(admin_only=True)
def api_admin_usage():
    """Who is spending the API budget, before the bill says so."""
    return jsonify({
        "daily_limit": DAILY_READING_LIMIT,
        "daily_budget": DAILY_BUDGET_USD,
        "spent_today": round(spend_today(), 4),
        "replayed_turns": REPLAYED_TURNS,
        "provider": PROVIDER,
        "model": current_model(),
        "users": usage_summary(),
        "last_call": dict(LAST_USAGE),
    })


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
        ctx = build_full_context(pid, here=_here_from_request())
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

    # Checked before the model is called, not after: the point is to stop
    # the spend, and an answer that is discarded has already been paid for.
    # Admins are exempt, so a cap can never lock out the person who sets it.
    # The budget binds admins too. A spending cap that the person most
    # likely to be testing can ignore is not a spending cap.
    if DAILY_BUDGET_USD:
        spent = spend_today()
        if spent >= DAILY_BUDGET_USD:
            return jsonify({
                "error": f"Today's budget of ${DAILY_BUDGET_USD:.2f} is spent "
                         f"(${spent:.2f} so far). It resets at midnight UTC. "
                         f"Readings on Gemini's free tier still work.",
                "budget": DAILY_BUDGET_USD,
                "spent": round(spent, 4),
            }), 429

    if DAILY_READING_LIMIT and not g.is_admin:
        used = count_readings_today(g.user_id)
        if used >= DAILY_READING_LIMIT:
            return jsonify({
                "error": f"You have used all {DAILY_READING_LIMIT} readings for "
                         f"today. The count resets at midnight UTC.",
                "limit": DAILY_READING_LIMIT,
                "used": used,
            }), 429
    try:
        # Chart block is rebuilt fresh and attached to the current question
        # on every call — history is stored without it.
        messages = list(history)
        messages.append({
            "role": "user",
            "content": f"{build_chart_block(pid, here=_here_from_request())}"
                       f"\n\nQuestion: {question}",
        })

        answer = generate(
            system=build_system_prompt(persona),
            messages=messages,
            model=d.get("model"),
        )

        # Recorded after the answer exists, so a failed call leaves no
        # row. A storage failure must not lose a reading the querent is
        # already reading, so it is logged rather than raised.
        # Priced from the tokens the provider actually reported, not
        # estimated: an estimate that drifts low would let the budget be
        # passed without ever showing it.
        used_model = d.get("model") or current_model()
        call_cost = cost_of(used_model, LAST_USAGE)
        try:
            save_reading(pid, question, answer, persona=persona,
                         provider=PROVIDER, model=used_model,
                         cost_usd=call_cost)
        except Exception:
            traceback.print_exc()

        new_history = (list(history) + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ])[-(REPLAYED_TURNS * 2):]
        remaining = None
        if DAILY_READING_LIMIT and not g.is_admin:
            remaining = max(0, DAILY_READING_LIMIT - count_readings_today(g.user_id))
        return jsonify({"answer": answer, "history": new_history,
                        "remaining_today": remaining,
                        "cost_usd": call_cost,
                        "budget_left": (round(max(0.0, DAILY_BUDGET_USD - spend_today()), 4)
                                        if DAILY_BUDGET_USD else None)})

    except ProviderError as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/horoscope/<int:pid>/<kind>")
@require_user()
def api_horoscope(pid, kind):
    """A horoscope for one chart and one period.

    Served from the cache when one exists, which is the normal case and
    costs nothing. A model is called only on a miss - or when refresh=1
    is passed, which is the querent explicitly choosing to pay again.

    A life reading has the period key 'life', so it is written once and
    then read forever."""
    if kind not in horoscopes.KINDS:
        return jsonify({"error": f"Unknown horoscope kind: {kind}"}), 400

    denied = _require_profile(pid)
    if denied:
        return denied

    key = horoscopes.period_key(kind)
    refresh = request.args.get("refresh") in ("1", "true", "yes")

    if refresh:
        delete_horoscope(pid, kind, key)
    else:
        cached = get_horoscope(pid, kind, key)
        if cached:
            return jsonify({
                "kind": kind, "period_key": key, "cached": True,
                "label": horoscopes.describe(kind, key),
                "content": cached["content"],
                "model": cached["model"],
                "created_at": str(cached["created_at"]),
            })

    # A miss costs money, so it is subject to the same budget as a
    # question. Without this, four tabs would be four ways around the cap.
    if DAILY_BUDGET_USD:
        spent = spend_today()
        if spent >= DAILY_BUDGET_USD:
            return jsonify({
                "error": f"Today's budget of ${DAILY_BUDGET_USD:.2f} is spent "
                         f"(${spent:.2f}). This horoscope has not been written "
                         f"yet, and writing it costs. It resets at midnight UTC.",
            }), 429

    persona = request.args.get("persona", "integrated")
    if persona not in PERSONAS:
        persona = "integrated"

    try:
        chart = build_chart_block(pid, here=_here_from_request())
        model = request.args.get("model") or None
        answer = generate(
            system=build_system_prompt(persona),
            messages=[{"role": "user",
                       "content": f"{chart}\n\n{horoscopes.build_question(kind)}"}],
            model=model,
        )
        used_model = model or current_model()
        cost = cost_of(used_model, LAST_USAGE)
        saved = save_horoscope(pid, kind, key, answer, persona=persona,
                               provider=PROVIDER, model=used_model,
                               cost_usd=cost)
        return jsonify({
            "kind": kind, "period_key": key, "cached": False,
            "label": horoscopes.describe(kind, key),
            "content": (saved or {}).get("content", answer),
            "model": used_model, "cost_usd": cost,
            "created_at": str((saved or {}).get("created_at", "")),
        })
    except ProviderError as e:
        return jsonify({"error": str(e)}), 502
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


def _here_from_request():
    """The querent's CURRENT location, if the browser sent one.

    Never defaults to the birthplace. A rising sign or a hora for a
    place someone is not standing in is worse than none at all, because
    it looks like an answer.
    """
    args = request.args if request.method == "GET" else (request.get_json(silent=True) or {})
    lat, lon = args.get("lat"), args.get("lon")
    if lat in (None, "") or lon in (None, ""):
        return None
    try:
        return {"lat": float(lat), "lon": float(lon),
                "tz_offset": float(args.get("tz_offset") or 0),
                "place": args.get("place")}
    except (TypeError, ValueError):
        return None


@app.get("/api/now")
@require_user()
def api_now():
    """The rising sign and the planetary hour where the querent is now.

    Independent of any chart: it answers about a place and a moment, not
    about a person."""
    here = _here_from_request()
    if not here:
        return jsonify({"error": "A latitude and longitude are needed to say what is rising and which hora is running."}), 400
    try:
        result = compute_here_now(here["lat"], here["lon"], here["tz_offset"])
        result["place"] = here.get("place")
        return jsonify(result)
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/models")
@require_user()
def api_models():
    """Models this deployment can actually serve. Only providers whose
    key is set are offered — listing one we cannot reach would just
    produce a confusing failure when it was picked."""
    return jsonify(available_choices())


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
