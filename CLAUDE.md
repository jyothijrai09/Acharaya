# Jyotish — AI astrology consultation app

## What this is

A consultation app that computes real astrological charts from ephemeris data and
delivers readings through four AI astrologer personas. Vedic (Parashari), KP
(Krishnamurti Paddhati) and numerology. Built as a Flask backend with a single-page
frontend.

## Files

| File | Role |
|---|---|
| `astro_engine_v2.py` | All chart mathematics. Do not change calculation logic without testing against the reference chart below. |
| `astro_personas.py` | The four personas and the 22 rules governing how they speak. The rules are the product — treat them as carefully as code. |
| `app.py` | Flask server. REST API plus serves the UI. |
| `templates/index.html` | The interface. Single file, no build step, vanilla JS. |
| `llm.py` | Model provider layer. Anthropic or Gemini behind one `generate()`. The only module that talks to a model API. |
| `storage.py` | Profile storage. SQLite locally, PostgreSQL when `DATABASE_URL` is set. The only module that talks to a database. |
| `supabase_schema.sql` | Authoritative Postgres schema. Run once per Supabase project. |
| `api/index.py` | Vercel entry point. Re-exports the Flask app; holds no logic. |
| `vercel.json` | Routes every path to the Flask app. |
| `astro_profiles.db` | Local SQLite, created on first run. Saved birth charts. |
| `test_navamsha.py` | D9 regression tests. Runs without an ephemeris — stubs swisseph. |
| `test_llm.py` | Provider layer tests. Runs with no API key and neither SDK installed. |

## Setup

```bash
pip install -r requirements.txt
export ANTHROPIC_API_KEY=sk-ant-...
python3 app.py          # http://localhost:5000
```

Or on Gemini's free tier:

```bash
export LLM_PROVIDER=gemini GEMINI_API_KEY=...
python3 app.py
```

With no `DATABASE_URL`, profiles go to a local SQLite file and no Postgres
driver or network is needed. Set `DATABASE_URL` to a Supabase connection
string to use Postgres instead — the same code path serves both.

`GET /api/model` reports which provider and model are actually answering.

```bash
python3 test_navamsha.py && python3 test_llm.py
```

## Architecture

```
Birth details (SQLite)
    ↓
astro_engine_v2.build_full_context(profile_id)
    ├── compute_natal_chart()    sidereal positions, whole-sign houses,
    │                            nakshatras, padas, KP star/sub lords
    ├── compute_navamsha()       D9 signs, houses, lords, dignity,
    │                            vargottama flags
    ├── compute_kp_cusps()       Placidus cusps + cusp sub-lords
    ├── compute_dasha_timeline() Vimshottari mahadasha + antardasha
    ├── compute_numerology()     Pythagorean, life path / mulank / destiny
    └── compute_transits()       live planetary positions right now
    ↓
context_to_prompt_text()         renders it all as structured text
    ↓
astro_personas.build_chart_block()   wraps in <computed_chart_data> tags
    ↓
llm.generate(system=build_system_prompt(persona), messages=...)
    └── LLM_PROVIDER selects Anthropic or Gemini
```

## The one invariant that must not be broken

**The full computed context is rebuilt from the ephemeris on every single API call**
and attached to the current question. Conversation history is stored *without* the
chart block. This is deliberate and load-bearing:

- Transits change hourly, dasha changes daily — a cached block goes stale.
- Without it the model answers from its impression of the chart three turns ago
  rather than from the data.

If you refactor `ask_astrologer()` or `/api/ask`, keep this property. Do not
"optimise" by caching the chart block into history.

## The persona rules

`SHARED_RULES` in `astro_personas.py` is 22 numbered rules in six blocks:

1. Core reasoning (1–7): full-chart reasoning every turn, cite placements,
   cross-check systems, timing from dasha not feeling, no filler, stay inside the
   data, frame honestly.
2. Response structure (A, B1–B8): summary paragraph first, then dasha (longest
   section), natal, navamsha, KP, transits, numerology, timing, verdict.
3. Language (8–11): no idioms, explain mechanism not just verdict, define terms
   in line, plain sentences.
4. Authority and care (12–15): speak from depth, never leave a hard placement
   bare, counterweights must be real, proportion.
5. Truth and closing (16–17): truth then options — and if no options, still the
   truth. Mandatory closing disclaimer, written fresh each time.
6. Warmth (18–21): maternal tone, warmth never softens truth, genuine not
   performed, do not create dependence.
7. Teaching (22): a paraphrased teaching from the Gita, Upanishads or the
   contemplative traditions, before the disclaimer.

Rules 13 and 14 are in tension by design — 13 requires a counterweight for every
hard finding, 14 requires it to be real. If readings start reaching for weak
counterweights just to satisfy 13, tighten 14 rather than loosening 13.

Rule 22 must paraphrase, never quote translated verses or published books.

## Reference chart for regression testing

Any change to `astro_engine_v2.py` should still produce these values:

```
Born 2 March 1984, 06:45 IST (UTC+5:30), Jalgaon, Maharashtra (21.02N, 75.57E)

Lagna              Aquarius 16.08°, Shatabhishak pada 3
Sun/Moon/Mercury   all Aquarius, house 1, all in Shatabhishak
Saturn             Libra, house 9, exalted, retrograde
Mars               Libra, house 9
Jupiter            Sagittarius, house 11, own sign
Venus              Capricorn, house 12
Rahu               house 4        Ketu  house 10
Saturn mahadasha   20 May 2013 – 20 May 2032
Mars antardasha    21 Nov 2025 – 31 Dec 2026
Rahu antardasha    31 Dec 2026 – 6 Nov 2029
Numerology         life path 9, mulank 2, destiny 8, soul urge 7, personality 1
D9 Lagna           Aquarius — vargottama (same sign in D1 and D9)
```

Verified against a Parashara's Light 9.0 report. Dasha dates carry roughly two
days' drift from that report — acceptable, but do not let it grow.

## Deployment

Vercel (project `acharaya`) builds from `main`; Supabase project
`AcharayaVedic` holds the profiles table.

Environment variables required on Vercel:

| Variable | Value |
|---|---|
| `DATABASE_URL` | Supabase **transaction pooler** string, port 6543 |
| `ANTHROPIC_API_KEY` | required when `LLM_PROVIDER` is `anthropic` (the default) |
| `GEMINI_API_KEY` | required when `LLM_PROVIDER=gemini` |
| `LLM_PROVIDER` | optional, `anthropic` (default) or `gemini` |
| `ASTRO_MODEL` | optional, overrides the provider's default model |
| `LLM_MAX_TOKENS` | optional, defaults to 4000 |

Use the pooler on port 6543, not the direct connection on 5432. Serverless
invocations open a connection per call, and direct connections exhaust
Postgres' connection limit under any real traffic.

Three things about this deployment are worth remembering:

- **The filesystem is ephemeral.** Anything written to disk at runtime is
  discarded. That is why `storage.py` exists: a SQLite file would appear to
  work and then silently lose every saved chart.
- **No ephemeris data files are shipped.** `swe.set_ephe_path()` is skipped
  when the directory is absent and pyswisseph falls back to its built-in
  Moshier ephemeris. Slightly less precise — watch the dasha drift budget
  below.
- **60 second function ceiling** on the Hobby plan (`vercel.json`). A full
  eight-section Opus reading can approach it. If readings start timing out,
  stream the response or move to a host without the ceiling rather than
  trimming the rules.

## Conventions

- Lahiri ayanamsa throughout (`swe.SIDM_LAHIRI`). Do not change — it is the
  standard for both Vedic and KP, and every stored chart assumes it.
- Whole-sign houses for Vedic planet placement, Placidus for KP cusps. These are
  genuinely different house systems used side by side; that is correct, not a bug.
- Time zone offsets are stored as the offset **at the time of birth**, not the
  modern offset for that location.
- All database access goes through `storage.py`, and all model calls go
  through `llm.py`. Nothing else imports `sqlite3`, `psycopg`, `anthropic`
  or `google.genai`, so the backends cannot drift apart.
- Both providers are called STATELESSLY — the whole conversation is sent
  every turn. Gemini's Interactions API offers server-side history via
  `previous_interaction_id`; do not use it. It would retain the first
  turn's chart block and break the invariant above.
- Gemini names the assistant role `model`. The translation lives in
  `llm.py`; the rest of the app speaks Anthropic's `user`/`assistant`.
- Navamsha is computed as `(longitude * 9) // 30`, never `longitude // (30/9)`.
  30/9 is not representable in binary floating point and the second form is
  wrong on every exact sign boundary — it puts 0° Gemini in Virgo instead of
  Libra. `test_navamsha.py` guards this; run it after touching D9.

## Known gaps / next steps

- **Nadi astrology** — deliberately excluded. It matches a chart against physical
  palm-leaf records, so it needs a digitised leaf archive rather than ephemeris
  maths. Different build entirely.
- **Divisional charts beyond D9** — D9 (navamsha) is computed and wired into
  the personas as section B3. D10 (dashamsha, career) and D6 are still not
  computed; the personas will correctly say so if asked. D10 is the most
  valuable next addition, and `compute_navamsha()` is the pattern to copy —
  a D10 is the same arithmetic with a different divisor and starting rule.
- **Voice mode** — speech-to-text and text-to-speech, per the original AstroSage
  reference. Not started. Gemini's Live API would be the obvious route if the
  app is already on `LLM_PROVIDER=gemini`.
- **Free-tier privacy** — Google's free tier permits using submitted content
  to improve their products. Submitted content here is birth data and personal
  questions. Use a paid tier, or Anthropic, if that matters for a given chart.
- **Billing / wallet** — per-minute metering. Not started.
- **Multi-user auth** — still single-user. Neither schema has a user column.
  Note that `profiles` holds birth dates, times and places, which is
  identifying personal data: `supabase_schema.sql` enables row level
  security with no policies and revokes the PostgREST grants, so the table
  is unreachable through the anon key. When adding auth, add a `user_id`
  column and a policy — do not disable RLS to make something work.
- **Cusp sub-lord significator chains** — KP significator tables (which planets
  signify which houses via occupancy, ownership and star lord) are computed
  implicitly by the model rather than explicitly in code. Making this explicit
  would make KP readings more reliable.

## Things to be careful about

- Birth time accuracy matters enormously — a few minutes moves the ascendant and
  every house cusp. Any UI work should make this friction visible, not hide it.
- Do not add features that encourage users to consult the chart before every
  decision. Rule 21 exists for a reason; the product should not undercut it.
