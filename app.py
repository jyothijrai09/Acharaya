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
from flask import Flask, request, jsonify, render_template

from astro_engine_v2 import (
    init_db, save_profile, list_profiles, get_profile, delete_profile,
    build_full_context, context_to_prompt_text,
)
from astro_personas import PERSONAS, build_system_prompt, build_chart_block
from llm import generate, current_model, ProviderError, PROVIDER
import geocode

# Absolute template path: on a serverless host the working directory is not
# the repository root, so Flask's relative default fails to find them.
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, template_folder=os.path.join(BASE_DIR, 'templates'))
init_db()


# ----------------------------- profiles -----------------------------

@app.get("/api/profiles")
def api_list_profiles():
    rows = list_profiles()
    return jsonify([
        {"id": r[0], "name": r[1], "place": r[2],
         "date": f"{r[5]:02d}/{r[4]:02d}/{r[3]}"}
        for r in rows
    ])


@app.post("/api/profiles")
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
        )
        return jsonify({"id": pid})
    except Exception as e:
        return jsonify({"error": str(e)}), 400


@app.delete("/api/profiles/<int:pid>")
def api_delete_profile(pid):
    delete_profile(pid)
    return jsonify({"ok": True})


# ----------------------------- chart -----------------------------

@app.get("/api/chart/<int:pid>")
def api_chart(pid):
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
def api_ask():
    d = request.get_json(force=True)
    pid = d.get("profile_id")
    question = (d.get("question") or "").strip()
    persona = d.get("persona", "integrated")
    history = d.get("history") or []

    if not pid or not question:
        return jsonify({"error": "profile_id and question are required"}), 400
    if persona not in PERSONAS:
        return jsonify({"error": f"Unknown persona: {persona}"}), 400
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

        new_history = list(history) + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        return jsonify({"answer": answer, "history": new_history})

    except ProviderError as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500
    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/api/geocode")
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
def api_model():
    """Which provider and model are actually answering. Useful when
    comparing readings between providers."""
    return jsonify({"provider": PROVIDER, "model": current_model()})


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
