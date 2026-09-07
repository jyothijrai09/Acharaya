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


def _activation(yoga, timeline, current):
    """When this yoga's planets rule, from the chart's own dasha timeline.

    A yoga is not read as acting continuously; it delivers during the periods
    of the planets that form it. That is the difference between a chart having
    a yoga and the yoga mattering this year.
    """
    involved = set(yoga["planets"])
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
    # The strongest windows are those where mahadasha AND antardasha both
    # belong to the yoga; they are worth surfacing first.
    windows.sort(key=lambda w: (not w["both"], w["start"]))
    return windows[:6]


def build(planets, lagna_sign, timeline=None, current_dasha=None):
    """Every yoga found, each with the periods that activate it."""
    if not planets or not lagna_sign:
        return None
    found = _find(planets, lagna_sign)
    for y in found:
        y["activation"] = _activation(y, timeline, current_dasha)
    return {
        "yogas": found,
        "forms_checked": "conjunction and parivartana (exchange) only; "
                         "mutual aspect is not tested",
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
        if y.get("activation"):
            lines.append("  Activates during:")
            for w in y["activation"]:
                mark = "  <- running now" if w["running"] else (
                    "  (both periods belong to the yoga)" if w["both"] else "")
                lines.append(f"    {w['mahadasha']}/{w['antardasha']}: "
                             f"{w['start']} to {w['end']}{mark}")
    return lines
