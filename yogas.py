"""
Yogas — planetary combinations — detected from the chart, and when they fire.

Every yoga here is a structural condition: a planet in a particular kind of
house, two lords in the same sign, an exchange between two planets. That makes
them computable, and computable is the point. Asked which yogas a chart holds,
a language model will name some — the vocabulary is easy — and a few will be
wrong. "You have Raja yoga" is believed, so it has to be true.

So each yoga below is checked against the actual placements, and the
astrologer is given only what was found and told to claim nothing else.

WHAT IS CHECKED, AND WHAT IS NOT. Association between two planets is taken
here to mean conjunction (the same sign) or parivartana (each in the other's
sign). Mutual aspect — the third classical form — is NOT tested, because
graha drishti needs each planet's special aspects and would roughly double
this file for a result that is harder to verify. So a chart may hold a raja
yoga by aspect that this does not report. Absence here means "not found by
conjunction or exchange", never "not present", and the astrologer is told to
say it that way.

Activation: a yoga does not act continuously. It is read as delivering during
the dasha and antardasha of the planets that form it, so each result carries
the windows from the chart's own Vimshottari timeline.
"""

from datetime import date, datetime, timedelta

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

SIGN_LORDS = {
    "Aries": "Mars", "Taurus": "Venus", "Gemini": "Mercury", "Cancer": "Moon",
    "Leo": "Sun", "Virgo": "Mercury", "Libra": "Venus", "Scorpio": "Mars",
    "Sagittarius": "Jupiter", "Capricorn": "Saturn", "Aquarius": "Saturn",
    "Pisces": "Jupiter",
}

KENDRAS = (1, 4, 7, 10)
TRIKONAS = (1, 5, 9)
DUSTHANAS = (6, 8, 12)
DHANA_HOUSES = (2, 5, 9, 11)

# The five Mahapurusha yogas: one planet, own sign or exalted, in a kendra.
MAHAPURUSHA = {
    "Mars": ("Ruchaka", "drive, command, physical courage; a soldier's shape"),
    "Mercury": ("Bhadra", "intelligence, speech, trade; a scholar's shape"),
    "Jupiter": ("Hamsa", "wisdom, standing, dharma; a teacher's shape"),
    "Venus": ("Malavya", "beauty, comfort, refinement; an artist's shape"),
    "Saturn": ("Sasa", "endurance, authority over others, slow power"),
}

SHADOW = {"Rahu", "Ketu"}

# Vimshottari order and lengths, repeated here rather than imported so this
# module stays free of the engine and can be reasoned about on its own.
DASHA_ORDER = ["Ketu", "Venus", "Sun", "Moon", "Mars",
               "Rahu", "Jupiter", "Saturn", "Mercury"]
DASHA_YEARS = {"Ketu": 7, "Venus": 20, "Sun": 6, "Moon": 10, "Mars": 7,
               "Rahu": 18, "Jupiter": 16, "Saturn": 19, "Mercury": 17}
TOTAL_YEARS = 120

# How far ahead to subdivide antardashas into pratyantardashas. Every
# antardasha holds nine of them, so subdividing the whole 120-year cycle would
# produce 729 windows per yoga — true, and useless to read. Two years covers
# what anyone is actually planning around.
PRATYANTAR_HORIZON_DAYS = 730


def _pratyantardashas(ad_lord, start_iso, end_iso):
    """Subdivide one antardasha into its nine pratyantardashas.

    Same proportional rule as every level of Vimshottari: the sub-period runs
    from the lord of the period it sits in, and each share of the whole is that
    planet's years out of 120. These are short — weeks, not years — which is
    exactly why they are worth having: a yoga whose lords are nowhere near the
    running mahadasha still gets brief pulses inside it.
    """
    try:
        start = date.fromisoformat(start_iso)
        end = date.fromisoformat(end_iso)
    except (TypeError, ValueError):
        return []

    total_days = (end - start).days
    if total_days <= 0:
        return []

    out = []
    cursor = start
    begin = DASHA_ORDER.index(ad_lord) if ad_lord in DASHA_ORDER else 0
    for i in range(9):
        lord = DASHA_ORDER[(begin + i) % 9]
        span = total_days * DASHA_YEARS[lord] / TOTAL_YEARS
        finish = cursor + timedelta(days=span)
        out.append({
            "lord": lord,
            "start": cursor.isoformat(),
            "end": min(finish, end).isoformat(),
        })
        cursor = finish
        if cursor >= end:
            break
    return out


def _house_of(planets, name):
    p = planets.get(name)
    return p.get("house") if p else None


def _sign_of(planets, name):
    p = planets.get(name)
    return p.get("sign") if p else None


def _lord_of_house(lagna_sign, house):
    """Which planet rules the nth house, counting whole signs from the lagna."""
    idx = (SIGNS.index(lagna_sign) + house - 1) % 12
    return SIGN_LORDS[SIGNS[idx]]


def _houses_between(from_house, to_house):
    """How many houses `to` is from `from`, counted inclusively as astrology
    does — the same house is 1, not 0."""
    return (to_house - from_house) % 12 + 1


def _find(planets, lagna_sign):
    """Every yoga this chart holds, by the forms described in the docstring."""
    found = []

    def add(name, sanskrit, planets_involved, houses, what, caveat=None):
        found.append({
            "name": name, "sanskrit": sanskrit,
            "planets": planets_involved, "houses": houses,
            "what": what, "caveat": caveat,
        })

    # ---- Pancha Mahapurusha ----
    for planet, (sanskrit, meaning) in MAHAPURUSHA.items():
        p = planets.get(planet)
        if not p:
            continue
        house = p.get("house")
        dignity = p.get("dignity")
        if house in KENDRAS and dignity in ("own sign", "exalted"):
            add(f"{sanskrit} Yoga", sanskrit, [planet], [house],
                f"{planet} is {dignity} in the {house}th, a kendra. "
                f"One of the five Mahapurusha yogas: {meaning}.")

    # ---- Gaja Kesari: Jupiter in a kendra from the Moon ----
    moon_house, jup_house = _house_of(planets, "Moon"), _house_of(planets, "Jupiter")
    if moon_house and jup_house:
        distance = _houses_between(moon_house, jup_house)
        if distance in KENDRAS:
            add("Gaja Kesari Yoga", "Gajakesari", ["Jupiter", "Moon"],
                [jup_house, moon_house],
                f"Jupiter stands in the {distance}th from the Moon, a kendra. "
                "Read for standing, judgement and a reputation that outlasts "
                "the circumstances that made it.")

    # ---- Budhaditya: Sun and Mercury in one sign ----
    sun_sign, mer_sign = _sign_of(planets, "Sun"), _sign_of(planets, "Mercury")
    if sun_sign and sun_sign == mer_sign:
        combust = (planets.get("Mercury") or {}).get("combust")
        add("Budhaditya Yoga", "Budhaditya", ["Sun", "Mercury"],
            [_house_of(planets, "Sun")],
            f"Sun and Mercury together in {sun_sign}. Read for intelligence "
            "applied to whatever that house governs.",
            caveat=("Mercury is combust here, which many authorities hold "
                    "weakens or cancels this yoga. Say so rather than "
                    "claiming it plainly.") if combust else None)

    # ---- Chandra Mangala: Moon with Mars ----
    moon_sign, mars_sign = _sign_of(planets, "Moon"), _sign_of(planets, "Mars")
    if moon_sign and moon_sign == mars_sign:
        add("Chandra Mangala Yoga", "Chandra-Mangala", ["Moon", "Mars"],
            [moon_house],
            f"Moon and Mars together in {moon_sign}. Read for earning "
            "capacity driven by effort, and for a temper that has to be spent "
            "somewhere.")

    # ---- Parivartana: two planets in each other's signs ----
    seen = set()
    for a, pa in planets.items():
        if a in SHADOW:
            continue
        sign_a = pa.get("sign")
        if not sign_a:
            continue
        lord_of_a = SIGN_LORDS.get(sign_a)
        if not lord_of_a or lord_of_a == a or lord_of_a in seen:
            continue
        pb = planets.get(lord_of_a)
        if not pb:
            continue
        if SIGN_LORDS.get(pb.get("sign")) == a:
            seen.add(a)
            add("Parivartana Yoga (exchange)", "Parivartana", [a, lord_of_a],
                [pa.get("house"), pb.get("house")],
                f"{a} and {lord_of_a} sit in each other's signs. An exchange "
                "ties the two houses together: what happens in one is felt in "
                "the other.")

    # ---- Raja yoga: a kendra lord and a trikona lord conjunct ----
    kendra_lords = {_lord_of_house(lagna_sign, h) for h in KENDRAS}
    trikona_lords = {_lord_of_house(lagna_sign, h) for h in TRIKONAS}
    for k in sorted(kendra_lords):
        for t in sorted(trikona_lords):
            if k == t or k in SHADOW or t in SHADOW:
                continue
            if _sign_of(planets, k) and _sign_of(planets, k) == _sign_of(planets, t):
                add("Raja Yoga", "Raja", [k, t],
                    [_house_of(planets, k)],
                    f"{k} rules a kendra and {t} a trikona, and they meet in "
                    f"{_sign_of(planets, k)}. The classical combination for "
                    "rise in standing.",
                    caveat="Only conjunction and exchange are tested. A raja "
                           "yoga formed by mutual aspect would not appear here.")

    # ---- Dhana yoga: lords of the wealth houses conjunct ----
    dhana_lords = {h: _lord_of_house(lagna_sign, h) for h in DHANA_HOUSES}
    pairs = []
    houses_list = list(DHANA_HOUSES)
    for i, h1 in enumerate(houses_list):
        for h2 in houses_list[i + 1:]:
            l1, l2 = dhana_lords[h1], dhana_lords[h2]
            if l1 == l2 or l1 in SHADOW or l2 in SHADOW:
                continue
            if _sign_of(planets, l1) and _sign_of(planets, l1) == _sign_of(planets, l2):
                pairs.append((h1, h2, l1, l2))
    for h1, h2, l1, l2 in pairs:
        add("Dhana Yoga", "Dhana", [l1, l2], [h1, h2],
            f"The lords of the {h1}th and {h2}th ({l1} and {l2}) meet in "
            f"{_sign_of(planets, l1)}. Read for accumulation rather than "
            "income.")

    # ---- Vipreet Raja yoga: a dusthana lord in another dusthana ----
    for h in DUSTHANAS:
        lord = _lord_of_house(lagna_sign, h)
        if lord in SHADOW:
            continue
        lord_house = _house_of(planets, lord)
        if lord_house in DUSTHANAS and lord_house != h:
            add("Vipreet Raja Yoga", "Viparita Raja", [lord], [h, lord_house],
                f"{lord}, lord of the {h}th, sits in the {lord_house}th — one "
                "difficult house undoing another. Read as gain arriving "
                "through trouble rather than in spite of it.")

    # ---- Kemadruma: the Moon with no company ----
    if moon_house:
        neighbours = {(moon_house % 12) + 1, ((moon_house - 2) % 12) + 1}
        company = [n for n, p in planets.items()
                   if n not in ("Moon", "Sun") and n not in SHADOW
                   and p.get("house") in (neighbours | {moon_house})]
        if not company:
            add("Kemadruma Yoga", "Kemadruma", ["Moon"], [moon_house],
                "No planet stands with the Moon or on either side of it. Read "
                "as a mind that carries itself without support.",
                caveat="This is a difficult yoga and is very often cancelled — "
                       "by a kendra from the Moon, by aspects to it, and by "
                       "other conditions not tested here. Do not present it as "
                       "settled; say it is present and that cancellations "
                       "exist which have not been checked.")

    return found


def _activation(yoga, timeline, current, today=None):
    """When this yoga's planets rule, from the chart's own dasha timeline.

    A yoga is not read as acting continuously; it delivers during the periods
    of the planets that form it. That is the difference between a chart having
    a yoga and the yoga mattering this year.
    """
    involved = set(yoga["planets"])
    today = today or datetime.utcnow().date().isoformat()
    windows = []
    for md in timeline or []:
        md_is = md["mahadasha"] in involved
        for ad in md.get("antardashas", []):
            if md_is or ad["antardasha"] in involved:
                windows.append({
                    "mahadasha": md["mahadasha"],
                    "antardasha": ad["antardasha"],
                    "start": ad["start"], "end": ad["end"],
                    "both": md_is and ad["antardasha"] in involved,
                    "running": (md["mahadasha"] == (current or {}).get("mahadasha")
                                and ad["antardasha"] == (current or {}).get("antardasha")),
                })
    for w in windows:
        w["past"] = w["end"] < today
        w["future"] = w["start"] > today

    # What a querent wants from a yoga is when it NEXT acts. Sorting by
    # strength alone buried the coming windows under ones that closed years
    # ago, which is the wrong answer to the only question being asked.
    # Running first, then future in order, then past most-recent first.
    def order(w):
        if w["running"]:
            return (0, w["start"])
        if w["future"]:
            return (1, w["start"])
        return (2, [-ord(c) for c in w["start"]])

    windows.sort(key=order)

    # Keep every future window - a yoga may not act again for decades and
    # that is worth seeing - but only a couple of past ones for context.
    upcoming = [w for w in windows if not w["past"]]
    past = [w for w in windows if w["past"]][:2]
    return (upcoming + past)[:10]


def _pulses(yoga, timeline, current, today=None, horizon_days=None):
    """Short pratyantardasha windows for this yoga, in the near future.

    A yoga whose planets do not rule the running mahadasha or antardasha
    looks dormant for years at the top two levels. It is not: the third
    level cycles all nine planets inside every antardasha, so its lords come
    round for weeks at a time. Those pulses are brief and real, and they are
    the answer to 'when does this act NEXT' when the big windows are distant.

    Bounded to the near future on purpose - subdividing the whole cycle gives
    729 windows per yoga, which is true and unreadable.
    """
    involved = set(yoga["planets"])
    today = today or datetime.utcnow().date().isoformat()
    horizon = (date.fromisoformat(today)
               + timedelta(days=horizon_days or PRATYANTAR_HORIZON_DAYS)).isoformat()

    out = []
    for md in timeline or []:
        if md["end"] < today or md["start"] > horizon:
            continue
        for ad in md.get("antardashas", []):
            if ad["end"] < today or ad["start"] > horizon:
                continue
            for pd in _pratyantardashas(ad["antardasha"], ad["start"], ad["end"]):
                if pd["lord"] not in involved:
                    continue
                if pd["end"] < today or pd["start"] > horizon:
                    continue
                out.append({
                    "mahadasha": md["mahadasha"],
                    "antardasha": ad["antardasha"],
                    "pratyantardasha": pd["lord"],
                    "start": pd["start"], "end": pd["end"],
                    "running": pd["start"] <= today <= pd["end"],
                    # All three levels belonging to the yoga is the strongest
                    # thing this level can say.
                    "all_three": (md["mahadasha"] in involved
                                  and ad["antardasha"] in involved),
                })
    out.sort(key=lambda w: (not w["running"], w["start"]))
    return out[:8]


def build(planets, lagna_sign, timeline=None, current_dasha=None):
    """Every yoga found, each with the periods that activate it."""
    if not planets or not lagna_sign:
        return None
    found = _find(planets, lagna_sign)
    for y in found:
        y["activation"] = _activation(y, timeline, current_dasha)
        y["pulses"] = _pulses(y, timeline, current_dasha)
    return {
        "yogas": found,
        "forms_checked": "conjunction and parivartana (exchange) only; "
                         "mutual aspect is not tested",
        "levels_scanned": "all nine mahadashas of the 120-year cycle at "
                          "mahadasha and antardasha level, plus "
                          "pratyantardasha for the next two years",
    }


def to_prompt_lines(block):
    if not block:
        return []

    lines = ["\n-- Yogas found in this chart --"]
    lines.append(
        "These were DETECTED from the placements, not recalled. Name only "
        "these. Do not add a yoga you remember, and do not claim a chart has "
        "one that is not listed. Checked forms: " + block["forms_checked"] +
        " — so absence here means 'not found by those forms', never 'not "
        "present', and it should be said that way if asked."
    )

    if not block["yogas"]:
        lines.append("No yoga was found by the forms checked. Say that plainly "
                     "rather than reaching for one.")
        return lines

    for y in block["yogas"]:
        lines.append(f"\n{y['name']} — {', '.join(y['planets'])}, "
                     f"house{'s' if len(set(y['houses'])) > 1 else ''} "
                     f"{', '.join(str(h) for h in sorted(set(h for h in y['houses'] if h)))}")
        lines.append(f"  {y['what']}")
        if y.get("caveat"):
            lines.append(f"  CAVEAT: {y['caveat']}")
        if y.get("pulses"):
            lines.append("  Short pratyantardasha pulses in the next two years:")
            for w in y["pulses"]:
                mark = "  <- RUNNING NOW" if w["running"] else (
                    "  (all three levels belong to the yoga)" if w["all_three"] else "")
                lines.append(
                    f"    {w['mahadasha']}/{w['antardasha']}/"
                    f"{w['pratyantardasha']}: {w['start']} to {w['end']}{mark}")
        if y.get("activation"):
            lines.append("  Activates during (coming windows first):")
            for w in y["activation"]:
                if w["running"]:
                    mark = "  <- RUNNING NOW"
                elif w.get("past"):
                    mark = "  (already passed)"
                elif w["both"]:
                    mark = "  (upcoming; both periods belong to the yoga)"
                else:
                    mark = "  (upcoming)"
                lines.append(f"    {w['mahadasha']}/{w['antardasha']}: "
                             f"{w['start']} to {w['end']}{mark}")
    return lines
