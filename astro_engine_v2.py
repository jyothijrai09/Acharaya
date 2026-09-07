"""
Astrology Engine v2
- Multi-profile storage (SQLite)
- Full natal chart (Vedic + KP planet sub-lords)
- KP cuspal sub-lords (house cusps, Placidus)
- Vimshottari Dasha/Antardasha timeline
- Live transits (current planetary positions vs natal)
- build_full_context(): assembles EVERYTHING into one data packet
  that must be passed to the AI every single time it responds —
  no shortcuts, no answering from a cached "vibe" of the chart.
"""

import swisseph as swe
import sqlite3
import json
from datetime import datetime, timedelta

swe.set_ephe_path('/usr/share/ephe')
swe.set_sid_mode(swe.SIDM_LAHIRI)

DB_PATH = "/home/claude/astro_profiles.db"

PLANETS = {
    'Sun': swe.SUN, 'Moon': swe.MOON, 'Mars': swe.MARS,
    'Mercury': swe.MERCURY, 'Jupiter': swe.JUPITER, 'Venus': swe.VENUS,
    'Saturn': swe.SATURN, 'Rahu': swe.MEAN_NODE,
}

NAKSHATRAS = [
    "Ashwini","Bharani","Krittika","Rohini","Mrigashira","Ardra",
    "Punarvasu","Pushya","Ashlesha","Magha","Purva Phalguni","Uttara Phalguni",
    "Hasta","Chitra","Swati","Vishakha","Anuradha","Jyeshtha",
    "Mula","Purva Ashadha","Uttara Ashadha","Shravana","Dhanishta","Shatabhishak",
    "Purva Bhadrapada","Uttara Bhadrapada","Revati"
]
SIGNS = ["Aries","Taurus","Gemini","Cancer","Leo","Virgo",
         "Libra","Scorpio","Sagittarius","Capricorn","Aquarius","Pisces"]
DASHA_ORDER = ["Ketu","Venus","Sun","Moon","Mars","Rahu","Jupiter","Saturn","Mercury"]
DASHA_YEARS = {"Ketu":7,"Venus":20,"Sun":6,"Moon":10,"Mars":7,"Rahu":18,"Jupiter":16,"Saturn":19,"Mercury":17}
TOTAL_YEARS = 120

# ---------------- NUMEROLOGY ----------------
# Pythagorean letter-to-number mapping (standard Western numerology, also widely used in Indian practice)
LETTER_VALUES = {
    'A':1,'J':1,'S':1, 'B':2,'K':2,'T':2, 'C':3,'L':3,'U':3, 'D':4,'M':4,'V':4,
    'E':5,'N':5,'W':5, 'F':6,'O':6,'X':6, 'G':7,'P':7,'Y':7, 'H':8,'Q':8,'Z':8, 'I':9,'R':9
}
VOWELS = set("AEIOU")
MASTER_NUMBERS = {11, 22, 33}

def reduce_number(n, keep_master=True):
    """Reduce to single digit, but preserve master numbers 11/22/33 unless told not to."""
    while n > 9 and not (keep_master and n in MASTER_NUMBERS):
        n = sum(int(d) for d in str(n))
    return n

def life_path_number(year, month, day):
    """Sum of full birth date, reduced (Vedic/Western root-number equivalent)."""
    total = reduce_number(year) if False else sum(int(d) for d in f"{year}{month:02d}{day:02d}")
    return reduce_number(total)

def birth_day_number(day):
    """Reduced day-of-month number — Vedic 'Mulank' (radical/psychic number)."""
    return reduce_number(day)

def name_number(full_name, use='destiny'):
    """
    Pythagorean name numerology.
    use='destiny'    -> all letters (Expression/Destiny number)
    use='soul_urge'  -> vowels only (Soul Urge/Heart's Desire)
    use='personality'-> consonants only (Personality number)
    """
    letters = [c.upper() for c in full_name if c.isalpha()]
    if use == 'soul_urge':
        letters = [c for c in letters if c in VOWELS]
    elif use == 'personality':
        letters = [c for c in letters if c not in VOWELS]
    total = sum(LETTER_VALUES.get(c, 0) for c in letters)
    return reduce_number(total)

def compute_numerology(year, month, day, full_name=None):
    result = {
        'life_path_number': life_path_number(year, month, day),
        'birth_day_number': birth_day_number(day),  # Mulank
    }
    if full_name:
        result['destiny_number'] = name_number(full_name, 'destiny')     # Bhagyank (name-based)
        result['soul_urge_number'] = name_number(full_name, 'soul_urge')
        result['personality_number'] = name_number(full_name, 'personality')
    return result

# ---------------- DB SETUP ----------------

def init_db():
    conn = sqlite3.connect(DB_PATH)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            full_birth_name TEXT,
            year INTEGER, month INTEGER, day INTEGER,
            hour INTEGER, minute INTEGER,
            tz_offset REAL, lat REAL, lon REAL, place TEXT,
            created_at TEXT
        )
    """)
    # Migration safety: add full_birth_name if the table pre-existed without it
    cols = [r[1] for r in conn.execute("PRAGMA table_info(profiles)")]
    if 'full_birth_name' not in cols:
        conn.execute("ALTER TABLE profiles ADD COLUMN full_birth_name TEXT")
    conn.commit()
    conn.close()

def save_profile(name, year, month, day, hour, minute, tz_offset, lat, lon, place, full_birth_name=None):
    conn = sqlite3.connect(DB_PATH)
    cur = conn.execute("""
        INSERT INTO profiles (name, full_birth_name, year, month, day, hour, minute, tz_offset, lat, lon, place, created_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (name, full_birth_name or name, year, month, day, hour, minute, tz_offset, lat, lon, place, datetime.utcnow().isoformat()))
    conn.commit()
    profile_id = cur.lastrowid
    conn.close()
    return profile_id

def list_profiles():
    conn = sqlite3.connect(DB_PATH)
    rows = conn.execute("SELECT id, name, place, year, month, day FROM profiles").fetchall()
    conn.close()
    return rows

def get_profile(profile_id):
    conn = sqlite3.connect(DB_PATH)
    row = conn.execute("SELECT * FROM profiles WHERE id=?", (profile_id,)).fetchone()
    cols = [d[0] for d in conn.execute("SELECT * FROM profiles").description]
    conn.close()
    return dict(zip(cols, row)) if row else None

# ---------------- CORE ASTRO MATH ----------------

def julian_day(dt_utc):
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day,
                       dt_utc.hour + dt_utc.minute/60 + dt_utc.second/3600)

def get_nakshatra_pada(longitude):
    nak_span = 360 / 27
    idx = int(longitude // nak_span)
    pada = int((longitude % nak_span) // (nak_span/4)) + 1
    return NAKSHATRAS[idx], pada

def get_sign(longitude):
    return SIGNS[int(longitude // 30)]

def get_kp_lords(longitude):
    """Returns (star_lord, sub_lord) for any longitude."""
    nak_span = 360/27
    idx = int(longitude // nak_span)
    star_lord = DASHA_ORDER[idx % 9]
    pos = longitude % nak_span
    start_idx = DASHA_ORDER.index(star_lord)
    cumulative = 0.0
    for i in range(9):
        lord = DASHA_ORDER[(start_idx+i) % 9]
        span = (DASHA_YEARS[lord]/TOTAL_YEARS) * nak_span
        if pos < cumulative + span:
            return star_lord, lord
        cumulative += span
    return star_lord, star_lord

def sidereal_longitude(jd, planet_id):
    result = swe.calc_ut(jd, planet_id, swe.FLG_SIDEREAL)
    return result[0][0]

def compute_planets(jd, asc_lon):
    data = {}
    for name, pid in PLANETS.items():
        lon_p = sidereal_longitude(jd, pid)
        sign = get_sign(lon_p)
        nak, pada = get_nakshatra_pada(lon_p)
        star_lord, sub_lord = get_kp_lords(lon_p)
        house = (int(lon_p//30) - int(asc_lon//30)) % 12 + 1
        data[name] = {
            'longitude': round(lon_p,2), 'sign': sign, 'degree': round(lon_p % 30,2),
            'nakshatra': nak, 'pada': pada, 'house': house,
            'star_lord': star_lord, 'sub_lord': sub_lord
        }
    # Ketu
    rahu_lon = data['Rahu']['longitude']
    ketu_lon = (rahu_lon + 180) % 360
    nak, pada = get_nakshatra_pada(ketu_lon)
    star_lord, sub_lord = get_kp_lords(ketu_lon)
    house = (int(ketu_lon//30) - int(asc_lon//30)) % 12 + 1
    data['Ketu'] = {
        'longitude': round(ketu_lon,2), 'sign': get_sign(ketu_lon), 'degree': round(ketu_lon % 30,2),
        'nakshatra': nak, 'pada': pada, 'house': house,
        'star_lord': star_lord, 'sub_lord': sub_lord
    }
    return data

def compute_kp_cusps(jd, lat, lon):
    """KP uses Placidus house cusps (unlike whole-sign for planet houses).
    Returns cusp longitude + star/sub lord for each of 12 houses."""
    houses = swe.houses_ex(jd, lat, lon, b'P', flags=swe.FLG_SIDEREAL)
    cusps = houses[0]  # 12 cusp longitudes (index 0-11 = house 1-12)
    cusp_data = {}
    for i in range(12):
        c_lon = cusps[i]
        sign = get_sign(c_lon)
        nak, pada = get_nakshatra_pada(c_lon)
        star_lord, sub_lord = get_kp_lords(c_lon)
        cusp_data[i+1] = {
            'longitude': round(c_lon,2), 'sign': sign,
            'nakshatra': nak, 'pada': pada,
            'star_lord': star_lord, 'sub_lord': sub_lord
        }
    return cusp_data

def compute_dasha_timeline(moon_longitude, birth_dt_utc, levels=2):
    """Vimshottari Mahadasha + Antardasha timeline from Moon's nakshatra."""
    nak_span = 360/27
    idx = int(moon_longitude // nak_span)
    star_lord = DASHA_ORDER[idx % 9]
    pos_in_nak = moon_longitude % nak_span
    balance_fraction = 1 - (pos_in_nak / nak_span)

    start_idx = DASHA_ORDER.index(star_lord)
    timeline = []
    first_lord = DASHA_ORDER[start_idx]
    first_years = DASHA_YEARS[first_lord] * balance_fraction
    cursor = birth_dt_utc
    end = cursor + timedelta(days=first_years*365.25)
    timeline.append({'mahadasha': first_lord, 'start': cursor.date().isoformat(), 'end': end.date().isoformat()})
    cursor = end

    for i in range(1, 9):
        lord = DASHA_ORDER[(start_idx+i) % 9]
        years = DASHA_YEARS[lord]
        end = cursor + timedelta(days=years*365.25)
        timeline.append({'mahadasha': lord, 'start': cursor.date().isoformat(), 'end': end.date().isoformat()})
        cursor = end

    if levels >= 2:
        for md in timeline:
            md_start = datetime.fromisoformat(md['start'])
            md_lord = md['mahadasha']
            md_years = DASHA_YEARS[md_lord]
            md_idx = DASHA_ORDER.index(md_lord)
            sub_cursor = md_start
            antardashas = []
            for j in range(9):
                sub_lord = DASHA_ORDER[(md_idx+j) % 9]
                sub_years = md_years * (DASHA_YEARS[sub_lord] / TOTAL_YEARS)
                sub_end = sub_cursor + timedelta(days=sub_years*365.25)
                antardashas.append({'antardasha': sub_lord,
                                     'start': sub_cursor.date().isoformat(),
                                     'end': sub_end.date().isoformat()})
                sub_cursor = sub_end
            md['antardashas'] = antardashas

    return timeline

def get_current_mahadasha_antardasha(timeline, as_of=None):
    as_of = as_of or datetime.utcnow()
    for md in timeline:
        if datetime.fromisoformat(md['start']) <= as_of <= datetime.fromisoformat(md['end']):
            current_md = md['mahadasha']
            for ad in md.get('antardashas', []):
                if datetime.fromisoformat(ad['start']) <= as_of <= datetime.fromisoformat(ad['end']):
                    return current_md, ad['antardasha']
            return current_md, None
    return None, None

def compute_transits(natal_asc_lon):
    """Current planetary positions (transits), houses relative to natal Lagna."""
    now_utc = datetime.utcnow()
    jd_now = julian_day(now_utc)
    transit_data = compute_planets(jd_now, natal_asc_lon)
    return now_utc, transit_data

# ---------------- FULL NATAL CHART ----------------

def compute_natal_chart(profile):
    local_dt = datetime(profile['year'], profile['month'], profile['day'],
                         profile['hour'], profile['minute'])
    utc_dt = local_dt - timedelta(hours=profile['tz_offset'])
    jd = julian_day(utc_dt)

    houses = swe.houses_ex(jd, profile['lat'], profile['lon'], b'W', flags=swe.FLG_SIDEREAL)
    asc_lon = houses[1][0]
    asc_sign = get_sign(asc_lon)
    asc_nak, asc_pada = get_nakshatra_pada(asc_lon)

    planets = compute_planets(jd, asc_lon)
    kp_cusps = compute_kp_cusps(jd, profile['lat'], profile['lon'])
    dasha_timeline = compute_dasha_timeline(planets['Moon']['longitude'], utc_dt, levels=2)
    current_md, current_ad = get_current_mahadasha_antardasha(dasha_timeline)
    numerology = compute_numerology(profile['year'], profile['month'], profile['day'],
                                     profile.get('full_birth_name') or profile['name'])

    return {
        'profile_name': profile['name'],
        'birth_local': local_dt.isoformat(),
        'birth_utc': utc_dt.isoformat(),
        'place': profile['place'],
        'lagna': {'sign': asc_sign, 'longitude': round(asc_lon,2), 'nakshatra': asc_nak, 'pada': asc_pada},
        'planets': planets,
        'kp_cusps': kp_cusps,
        'dasha_timeline': dasha_timeline,
        'current_dasha': {'mahadasha': current_md, 'antardasha': current_ad},
        'numerology': numerology,
        'natal_asc_lon': asc_lon,
    }

# ---------------- FULL CONTEXT FOR AI ----------------

def build_full_context(profile_id):
    """
    Assembles the COMPLETE data packet the AI must reason over every time
    it responds for this profile: full natal chart, KP cusps, dasha timeline,
    current dasha, and live transits. This is passed fresh on every single
    AI call — never cached into a short summary, never skipped.
    """
    profile = get_profile(profile_id)
    if not profile:
        raise ValueError(f"No profile found with id {profile_id}")

    natal = compute_natal_chart(profile)
    transit_time, transits = compute_transits(natal['natal_asc_lon'])

    return {
        'natal_chart': natal,
        'live_transits': {
            'as_of_utc': transit_time.isoformat(),
            'positions': transits
        }
    }

def context_to_prompt_text(context):
    """Renders the full context as structured text to inject into the AI system/user prompt."""
    n = context['natal_chart']
    lines = []
    lines.append(f"=== NATAL CHART: {n['profile_name']} ===")
    lines.append(f"Born: {n['birth_local']} | Place: {n['place']}")
    lines.append(f"Lagna: {n['lagna']['sign']} {n['lagna']['longitude']%30:.2f}° | Nakshatra: {n['lagna']['nakshatra']} Pada {n['lagna']['pada']}")
    lines.append("\n-- Planets (Vedic sign/house + KP star/sub lord) --")
    for name, p in n['planets'].items():
        lines.append(f"{name}: {p['sign']} {p['degree']}° | House {p['house']} | {p['nakshatra']} Pada {p['pada']} | Star Lord: {p['star_lord']} | Sub Lord: {p['sub_lord']}")
    lines.append("\n-- KP House Cusps (Placidus) --")
    for house, c in n['kp_cusps'].items():
        lines.append(f"Cusp {house}: {c['sign']} {c['longitude']%30:.2f}° | {c['nakshatra']} | Star Lord: {c['star_lord']} | Sub Lord: {c['sub_lord']}")
    lines.append(f"\n-- Current Dasha --\nMahadasha: {n['current_dasha']['mahadasha']} | Antardasha: {n['current_dasha']['antardasha']}")
    lines.append("\n-- Numerology --")
    num = n['numerology']
    lines.append(f"Life Path Number: {num['life_path_number']} | Birth Day Number (Mulank): {num['birth_day_number']}")
    if 'destiny_number' in num:
        lines.append(f"Destiny/Expression Number: {num['destiny_number']} | Soul Urge: {num['soul_urge_number']} | Personality: {num['personality_number']}")
    lines.append("\n-- Live Transits (as of now) --")
    for name, p in context['live_transits']['positions'].items():
        lines.append(f"{name}: {p['sign']} {p['degree']}° | Transit House (from natal Lagna): {p['house']} | {p['nakshatra']}")
    return "\n".join(lines)


if __name__ == "__main__":
    init_db()

    if not list_profiles():
        save_profile("Jyoti Rai", 1984, 3, 2, 6, 45, 5.5, 21.02, 75.57, "Jalgaon, Maharashtra, India",
                     full_birth_name="Jyoti Rai")

    profiles = list_profiles()
    print("Stored profiles:", profiles)

    pid = profiles[0][0]
    ctx = build_full_context(pid)
    prompt_text = context_to_prompt_text(ctx)
    print("\n" + prompt_text)

    with open("/home/claude/sample_context.txt", "w") as f:
        f.write(prompt_text)
