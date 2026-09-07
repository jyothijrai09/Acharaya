"""
Astrology Engine v2
- Multi-profile storage (SQLite)
- Full natal chart (Vedic + KP planet sub-lords)
- D9 Navamsha divisional chart (Parashari reckoning)
- KP cuspal sub-lords (house cusps, Placidus)
- Vimshottari Dasha/Antardasha timeline
- Live transits (current planetary positions vs natal)
- build_full_context(): assembles EVERYTHING into one data packet
  that must be passed to the AI every single time it responds —
  no shortcuts, no answering from a cached "vibe" of the chart.
"""

import os
import swisseph as swe
from datetime import datetime, timedelta

# Profile storage lives in storage.py, which speaks SQLite locally and
# PostgreSQL (Supabase) when DATABASE_URL is set. Re-exported here so that
# existing `from astro_engine_v2 import ...` imports keep working.
import hora
import vargas
from storage import (  # noqa: F401
    init_db, save_profile, list_profiles, get_profile, delete_profile, DB_PATH,
)

# Swiss Ephemeris data files. If the directory is absent - as it is on a
# serverless host - pyswisseph falls back to its built-in Moshier ephemeris,
# which needs no data files but is marginally less precise. That matters
# here: CLAUDE.md allows about two days of dasha drift against Parashara's
# Light, and the fallback eats into that budget. Ship the data files and
# point SWISSEPH_PATH at them if the drift ever grows.
EPHE_PATH = os.environ.get('SWISSEPH_PATH', '/usr/share/ephe')
if os.path.isdir(EPHE_PATH):
    swe.set_ephe_path(EPHE_PATH)

swe.set_sid_mode(swe.SIDM_LAHIRI)

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

SIGN_LORDS = {
    "Aries":"Mars", "Taurus":"Venus", "Gemini":"Mercury", "Cancer":"Moon",
    "Leo":"Sun", "Virgo":"Mercury", "Libra":"Venus", "Scorpio":"Mars",
    "Sagittarius":"Jupiter", "Capricorn":"Saturn", "Aquarius":"Saturn", "Pisces":"Jupiter"
}

# Exaltation signs. Rahu and Ketu are deliberately absent - the tradition does
# not agree on their exaltation, and guessing would put a fabricated dignity
# in front of the model.
EXALTATION = {
    "Sun":"Aries", "Moon":"Taurus", "Mars":"Capricorn", "Mercury":"Virgo",
    "Jupiter":"Cancer", "Venus":"Pisces", "Saturn":"Libra"
}
DEBILITATION = {p: SIGNS[(SIGNS.index(s) + 6) % 12] for p, s in EXALTATION.items()}
OWN_SIGNS = {
    "Sun":{"Leo"}, "Moon":{"Cancer"}, "Mars":{"Aries","Scorpio"},
    "Mercury":{"Gemini","Virgo"}, "Jupiter":{"Sagittarius","Pisces"},
    "Venus":{"Taurus","Libra"}, "Saturn":{"Capricorn","Aquarius"}
}

# Combustion orbs in degrees from the Sun (Parashari). Mercury and Venus take
# a tighter orb when retrograde, which is why the value is a pair
# (direct, retrograde) rather than a single number.
#
# These orbs vary between authorities by a degree or two. This set is the
# common Parashari one; if a reading ever disagrees with a printed chart on a
# borderline case, the orb table is the first thing to check.
COMBUSTION_ORBS = {
    "Moon": (12, 12), "Mars": (17, 17), "Mercury": (14, 12),
    "Jupiter": (11, 11), "Venus": (10, 8), "Saturn": (15, 15),
}

# Rahu and Ketu are shadow points, not bodies: they are never combust, and
# they are always retrograde, so flagging their motion says nothing useful.
SHADOW_PLANETS = {"Rahu", "Ketu"}


def angular_separation(a, b):
    """Shortest distance between two zodiacal longitudes, 0-180 degrees."""
    d = abs(a - b) % 360
    return min(d, 360 - d)
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

def sidereal_longitude_and_speed(jd, planet_id):
    """Longitude plus daily motion. Negative motion is retrograde.

    Retrogression is not cosmetic: a retrograde planet is read as holding its
    significations back or turning them inward, and the reference chart's
    Saturn is both exalted AND retrograde, which pull in opposite directions.
    The model cannot infer this from a longitude, so it has to be computed.
    """
    result = swe.calc_ut(jd, planet_id, swe.FLG_SIDEREAL | swe.FLG_SPEED)
    return result[0][0], result[0][3]

def compute_planets(jd, asc_lon):
    data = {}
    for name, pid in PLANETS.items():
        lon_p, speed = sidereal_longitude_and_speed(jd, pid)
        sign = get_sign(lon_p)
        nak, pada = get_nakshatra_pada(lon_p)
        star_lord, sub_lord = get_kp_lords(lon_p)
        house = (int(lon_p//30) - int(asc_lon//30)) % 12 + 1
        data[name] = {
            'longitude': round(lon_p,2), 'sign': sign, 'degree': round(lon_p % 30,2),
            'nakshatra': nak, 'pada': pada, 'house': house,
            'star_lord': star_lord, 'sub_lord': sub_lord,
            'dignity': get_dignity(name, sign),
            'retrograde': (speed < 0) and name not in SHADOW_PLANETS,
            'speed': round(speed, 4),
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
        'star_lord': star_lord, 'sub_lord': sub_lord,
        'dignity': None, 'retrograde': False, 'speed': round(-data['Rahu']['speed'], 4),
    }

    # Combustion needs every planet placed first, because it is measured from
    # the Sun. Done in a second pass for that reason.
    sun_lon = data['Sun']['longitude']
    for name, p in data.items():
        p['combust'] = False
        p['sun_distance'] = round(angular_separation(p['longitude'], sun_lon), 2)
        if name == 'Sun' or name in SHADOW_PLANETS:
            continue
        direct_orb, retro_orb = COMBUSTION_ORBS[name]
        orb = retro_orb if p['retrograde'] else direct_orb
        p['combust'] = p['sun_distance'] <= orb

    return data

NAVAMSHA_SPAN = 30.0 / 9   # 3 degrees 20 minutes

def get_navamsha_longitude(longitude):
    """
    Map a D1 longitude to its D9 (navamsha) longitude, Parashari reckoning.

    Each 30 degree sign divides into nine parts of 3 deg 20 min, giving 108
    navamshas around the zodiac. Numbering those parts continuously from
    0 Aries and taking the result modulo 12 reproduces the classical rule
    exactly, with no special-casing:

        movable signs (Aries, Cancer, Libra, Capricorn) start from themselves
        fixed signs   (Taurus, Leo, Scorpio, Aquarius)  start from the 9th sign
        dual signs    (Gemini, Virgo, Sagittarius, Pisces) start from the 5th

    The degree within the navamsha is expanded by 9 so it fills the 30 degree
    D9 sign. Only the sign placement is doctrinally fixed; the expanded degree
    is a display convention, and is deliberately not used for nakshatra or
    lordship anywhere.

    The arithmetic is deliberately written as (longitude * 9) // 30 rather than
    the more obvious longitude // (30 / 9). The span 30/9 is not representable
    in binary floating point - it rounds to just above 10/3 - so the obvious
    form undershoots by one navamsha at every exact sign boundary, putting
    0 deg Gemini in Virgo instead of Libra. Multiplying first keeps every sign
    boundary exact. Do not "simplify" this back.
    """
    # Multiplying first fixes the boundaries between SIGNS. It does not fix
    # the boundaries between navamshas inside a sign, which fall on thirds of
    # a degree and are equally unrepresentable: 23°20' of Taurus is 160/3
    # absolute, and (160/3) * 9 / 30 is exactly 16, but in floating point it
    # comes out a hair under, flooring to 15 and putting the planet in Cancer
    # instead of Leo. The epsilon corrects that.
    #
    # 1e-9 of a navamsha is well under a thousandth of an arcsecond, far below
    # any precision the ephemeris offers, so it can only ever repair this
    # rounding and never shift a genuine placement. test_vargas.py cross-checks
    # this against the varga table, which is how the discrepancy surfaced.
    part = int(longitude * 9 / 30 + 1e-9)           # 0..107 around the zodiac
    sign_idx = part % 12

    # Clamped because the epsilon above can select the part whose boundary the
    # longitude sits a fraction below, making this subtraction very slightly
    # negative. Left unclamped, the returned longitude falls just under the
    # start of its own sign, and get_sign() then reports the PREVIOUS sign —
    # the exact wrong placement the epsilon was added to prevent.
    offset = max(0.0, longitude * 9 - part * 30)    # 0..30 within the D9 sign
    return sign_idx * 30 + offset

def get_dignity(planet, sign):
    """Exaltation / debilitation / own sign for a planet in a given sign.
    Returns None for the nodes and for neutral placements."""
    if EXALTATION.get(planet) == sign:
        return "exalted"
    if DEBILITATION.get(planet) == sign:
        return "debilitated"
    if sign in OWN_SIGNS.get(planet, ()):
        return "own sign"
    return None

def compute_navamsha(planets, asc_lon):
    """
    D9 navamsha chart: the divisional chart for marriage and partnership,
    for dharma, and for the underlying strength of every planet.

    Houses are whole-sign from the D9 lagna, matching the D1 convention.

    A planet holding the same sign in D1 and D9 is vargottama - it repeats
    across both charts and is read as markedly strengthened. That flag is the
    single most useful thing D9 adds to a reading, so it is computed here
    rather than left for the model to work out.
    """
    d9_asc_lon = get_navamsha_longitude(asc_lon)
    d9_asc_sign = get_sign(d9_asc_lon)
    d9_asc_idx = SIGNS.index(d9_asc_sign)

    d9_planets = {}
    for name, p in planets.items():
        d9_lon = get_navamsha_longitude(p['longitude'])
        d9_sign = get_sign(d9_lon)
        d9_planets[name] = {
            'sign': d9_sign,
            'degree': round(d9_lon % 30, 2),
            'house': (SIGNS.index(d9_sign) - d9_asc_idx) % 12 + 1,
            'lord': SIGN_LORDS[d9_sign],
            'dignity': get_dignity(name, d9_sign),
            'vargottama': d9_sign == p['sign'],
        }

    return {
        'lagna': {
            'sign': d9_asc_sign,
            'degree': round(d9_asc_lon % 30, 2),
            'lord': SIGN_LORDS[d9_asc_sign],
            'vargottama': d9_asc_sign == get_sign(asc_lon),
        },
        'planets': d9_planets,
    }

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
    navamsha = compute_navamsha(planets, asc_lon)

    # Every divisional chart, computed once with the rest of the natal
    # chart. This is pure arithmetic over positions already in hand — no
    # ephemeris call and no model call — so computing all sixteen costs
    # effectively nothing and saves recomputing one when it is asked for.
    divisional = vargas.compute_all(
        planets, asc_lon, SIGNS, SIGN_LORDS, get_dignity)
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
        'navamsha': navamsha,
        'divisional': divisional,
        'kp_cusps': kp_cusps,
        'dasha_timeline': dasha_timeline,
        'current_dasha': {'mahadasha': current_md, 'antardasha': current_ad},
        'numerology': numerology,
        'natal_asc_lon': asc_lon,
    }

def compute_here_now(lat, lon, tz_offset=0.0):
    """
    What the sky is doing at a place right now: the rising sign there, and the
    planetary hour running.

    Separate from the natal chart on purpose. A chart is cast for where someone
    was born; the ascendant rising this minute and the hora now in force depend
    on where they are standing today, and the two are usually nowhere near each
    other. Passing the birthplace here would answer a question nobody asked.
    """
    now_utc = datetime.utcnow()
    jd = julian_day(now_utc)

    houses = swe.houses_ex(jd, lat, lon, b'W', flags=swe.FLG_SIDEREAL)
    asc_lon = houses[1][0]
    asc_nak, asc_pada = get_nakshatra_pada(asc_lon)
    star_lord, sub_lord = get_kp_lords(asc_lon)

    return {
        'as_of_utc': now_utc.isoformat(),
        'lat': lat,
        'lon': lon,
        'tz_offset': tz_offset,
        'ascendant': {
            'sign': get_sign(asc_lon),
            'degree': round(asc_lon % 30, 2),
            'lord': SIGN_LORDS[get_sign(asc_lon)],
            'nakshatra': asc_nak,
            'pada': asc_pada,
            'star_lord': star_lord,
            'sub_lord': sub_lord,
        },
        'hora': hora.build_horas(now_utc, lat, lon, tz_offset),
    }


# ---------------- FULL CONTEXT FOR AI ----------------

def build_full_context(profile_id, here=None):
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

    context = {
        'natal_chart': natal,
        'live_transits': {
            'as_of_utc': transit_time.isoformat(),
            'positions': transits
        }
    }

    # Only when the querent has told us where they are. Guessing, or
    # falling back to the birthplace, would put a rising sign and a hora
    # in front of the model for a place the person is not standing in.
    if here and here.get('lat') is not None and here.get('lon') is not None:
        try:
            context['here_now'] = compute_here_now(
                float(here['lat']), float(here['lon']),
                float(here.get('tz_offset') or 0))
            context['here_now']['place'] = here.get('place')
        except Exception:
            pass   # a bad coordinate must not cost the whole reading

    return context

def context_to_prompt_text(context):
    """Renders the full context as structured text to inject into the AI system/user prompt."""
    n = context['natal_chart']
    lines = []
    lines.append(f"=== NATAL CHART: {n['profile_name']} ===")
    lines.append(f"Born: {n['birth_local']} | Place: {n['place']}")
    lines.append(f"Lagna: {n['lagna']['sign']} {n['lagna']['longitude']%30:.2f}° | Nakshatra: {n['lagna']['nakshatra']} Pada {n['lagna']['pada']}")
    lines.append("\n-- Planets (Vedic sign/house + KP star/sub lord) --")
    for name, p in n['planets'].items():
        marks = []
        if p.get('dignity'):
            marks.append(p['dignity'].upper())
        if p.get('retrograde'):
            marks.append('RETROGRADE')
        if p.get('combust'):
            marks.append(f"COMBUST ({p['sun_distance']}° from Sun)")
        suffix = (' | ' + ' | '.join(marks)) if marks else ''
        lines.append(f"{name}: {p['sign']} {p['degree']}° | House {p['house']} | {p['nakshatra']} Pada {p['pada']} | Star Lord: {p['star_lord']} | Sub Lord: {p['sub_lord']}{suffix}")
    d9 = n['navamsha']
    lines.append("\n-- D9 Navamsha (marriage, partnership, dharma, inner planetary strength) --")
    lines.append(f"D9 Lagna: {d9['lagna']['sign']} {d9['lagna']['degree']}° | Lord: {d9['lagna']['lord']}"
                 + (" | VARGOTTAMA" if d9['lagna']['vargottama'] else ""))
    for name, p in d9['planets'].items():
        extras = []
        if p['dignity']:
            extras.append(p['dignity'].upper())
        if p['vargottama']:
            extras.append("VARGOTTAMA")
        suffix = (" | " + " | ".join(extras)) if extras else ""
        lines.append(f"{name}: {p['sign']} {p['degree']}° | D9 House {p['house']} | Lord: {p['lord']}{suffix}")
    vargottama = [k for k, v in d9['planets'].items() if v['vargottama']]
    lines.append("Vargottama planets (same sign in D1 and D9, markedly strengthened): "
                 + (", ".join(vargottama) if vargottama else "none"))

    div = n.get('divisional') or {}
    for key in ("D10", "D30"):
        v = div.get(key)
        if not v:
            continue
        lines.append(f"\n-- {key} {v['name']} ({v['meaning']}) --")
        lines.append(f"{key} Lagna: {v['lagna']['sign']} | Lord: {v['lagna']['lord']}")
        for name, p in v["planets"].items():
            marks = []
            if p.get("dignity"):
                marks.append(p["dignity"].upper())
            if p.get("vargottama"):
                marks.append("VARGOTTAMA")
            suffix = (" | " + " | ".join(marks)) if marks else ""
            lines.append(f"{name}: {p['sign']} | House {p['house']} | Lord: {p['lord']}{suffix}")
        if v.get("note"):
            lines.append(f"Note: {v['note']}")

    others = [k for k in div if k not in ("D1", "D9", "D10", "D30")]
    if others:
        lines.append("\n-- Other divisional charts computed and available --")
        lines.append(", ".join(
            f"{k} ({div[k]['name']}: {div[k]['meaning']})" for k in others))
        lines.append("These are computed but not printed above to keep this "
                     "block short. If a question turns on one of them, say "
                     "which and that it can be shown \u2014 do not guess at "
                     "placements you have not been given.")

    lines.append("\n-- KP House Cusps (Placidus) --")
    for house, c in n['kp_cusps'].items():
        lines.append(f"Cusp {house}: {c['sign']} {c['longitude']%30:.2f}° | {c['nakshatra']} | Star Lord: {c['star_lord']} | Sub Lord: {c['sub_lord']}")
    lines.append(f"\n-- Current Dasha --\nMahadasha: {n['current_dasha']['mahadasha']} | Antardasha: {n['current_dasha']['antardasha']}")
    lines.append("\n-- Numerology --")
    num = n['numerology']
    lines.append(f"Life Path Number: {num['life_path_number']} | Birth Day Number (Mulank): {num['birth_day_number']}")
    if 'destiny_number' in num:
        lines.append(f"Destiny/Expression Number: {num['destiny_number']} | Soul Urge: {num['soul_urge_number']} | Personality: {num['personality_number']}")
    hn = context.get('here_now')
    if hn:
        where = hn.get('place') or f"{hn['lat']:.2f}, {hn['lon']:.2f}"
        a = hn['ascendant']
        lines.append(f"\n-- Where the querent is RIGHT NOW: {where} --")
        lines.append("This is their CURRENT location, not their birthplace. Use it "
                     "for what is rising now and for the hora; the natal chart above "
                     "still belongs to the birth place and time.")
        lines.append(f"Rising there now: {a['sign']} {a['degree']}° | Lord: {a['lord']} "
                     f"| {a['nakshatra']} pada {a['pada']} | Sub Lord: {a['sub_lord']}")
        h = hn.get('hora') or {}
        if h.get('available'):
            cur = h.get('current') or {}
            lines.append(f"Weekday: {h['weekday']}, ruled by {h['day_lord']}. "
                         f"Sunrise {h['sunrise_local']}, sunset {h['sunset_local']} local.")
            if cur:
                lines.append(f"Hora running now: {cur['ruler']} "
                             f"({cur['start_local']}–{cur['end_local']} local), "
                             f"suited to {cur['suited_to']}.")
                upcoming = [x for x in h['horas']
                            if x['start_utc'] > cur['start_utc']][:4]
                if upcoming:
                    lines.append("Next horas: " + ", ".join(
                        f"{x['ruler']} {x['start_local']}–{x['end_local']}"
                        for x in upcoming))
        elif h.get('reason'):
            lines.append(f"Hora unavailable: {h['reason']}")

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

    out = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                       "sample_context.txt")
    with open(out, "w", encoding="utf-8") as f:
        f.write(prompt_text)
    print("\nWrote", out)
