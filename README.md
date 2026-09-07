# Jyotish — AI astrology consultation app

Vedic, KP and numerology readings from real ephemeris calculations, delivered by
four AI astrologer personas.

## Files

| File | What it does |
|---|---|
| `astro_engine_v2.py` | Chart maths. Sidereal positions, whole-sign houses, nakshatras and padas, the D9 navamsha chart, KP star and sub lords, KP Placidus cusps, Vimshottari dasha timeline, numerology, live transits, SQLite profile storage. |
| `astro_personas.py` | The four personas and the 22 rules that govern how they speak. Builds the system prompt and the fresh chart block for each API call. |
| `app.py` | Flask server. REST API plus the web interface. |
| `templates/index.html` | The interface. |
| `storage.py` | Profile storage — SQLite locally, Postgres when `DATABASE_URL` is set. |
| `supabase_schema.sql` | Run once in the Supabase SQL editor to create the table. |
| `astro_profiles.db` | Created on first run locally. Your saved charts. |
| `test_navamsha.py` | D9 regression tests. `python test_navamsha.py` — no ephemeris needed. |

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python3 app.py
```

Open http://localhost:5000

Optional — choose a different model (the default is Opus, which gives the best
readings; a smaller model is cheaper for high-volume use):

```bash
export ASTRO_MODEL=claude-sonnet-4-6
```

## The personas

| Key | Name | Method |
|---|---|---|
| `vedic` | Pandit Raghav | Parashari — lagna, house lords, yogas, dignity |
| `kp` | Guruji Ramanathan | Krishnamurti Paddhati — sub-lord chains, promise or denial |
| `numerology` | Anjali | Pythagorean and Indian numerology, number to planet mapping |
| `integrated` | Acharya Devi | All three layered, reports where they disagree |

## How the readings are kept honest

The full computed context — natal chart, KP planet sub-lords, KP cusp sub-lords,
the dasha timeline, current mahadasha and antardasha, numerology and today's
transits — is **rebuilt from the ephemeris on every single API call** and attached
to the current question. Conversation history is stored without the chart block,
so nothing stale is ever carried forward. The personas cannot answer from a
summary or from what they said three turns ago.

The persona rules require every claim to be traceable to a named placement, cusp,
dasha date or number; require the layers to be cross-checked and disagreements
reported rather than smoothed over; forbid manufactured comfort; and require every
reading to end on the truth, then the options, then a teaching, then the
disclaimer that a chart is a reference and not a verdict.

## Adding a chart

You need latitude, longitude and the UTC offset **at the time of birth** — historic
time zones and daylight saving change, so check the offset for that date rather
than using today's. Birth time decides the ascendant and the house cusps; a few
minutes moves them.

## Cost

Swiss Ephemeris and Flask are free. Hosting runs on a free tier to start. The
only real cost is the API call per reading — a few cents at Opus, less at Sonnet.

## Not included

Nadi astrology. It works by matching a chart against physical palm-leaf records,
so it needs a digitised leaf archive rather than ephemeris maths. Different build
entirely.
