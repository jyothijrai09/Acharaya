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
    pip install flask anthropic pyswisseph
    export ANTHROPIC_API_KEY=...
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
    if not os.environ.get("ANTHROPIC_API_KEY"):
        return jsonify({"error": "ANTHROPIC_API_KEY is not set on the server."}), 500

    try:
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

        # Chart block is rebuilt fresh and attached to the current question
        # on every call — history is stored without it.
        messages = list(history)
        messages.append({
            "role": "user",
            "content": f"{build_chart_block(pid)}\n\nQuestion: {question}",
        })

        resp = client.messages.create(
            model=os.environ.get("ASTRO_MODEL", "claude-opus-4-6"),
            max_tokens=4000,
            system=build_system_prompt(persona),
            messages=messages,
        )
        answer = "".join(b.text for b in resp.content if b.type == "text")

        new_history = list(history) + [
            {"role": "user", "content": question},
            {"role": "assistant", "content": answer},
        ]
        return jsonify({"answer": answer, "history": new_history})

    except Exception as e:
        traceback.print_exc()
        return jsonify({"error": str(e)}), 500


@app.get("/")
def index():
    return render_template("index.html")


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000, debug=True)
