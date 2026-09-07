"""
Planetary strength, and Saturn's long transit over the Moon.

Two things live here because both answer "how much weight does this carry",
and both are pure arithmetic over positions the engine already has.

A note on scope, because the honest answer matters more than a complete-looking
one. Shadbala is SIX strengths, and three of them — kala bala, cheshta bala and
drik bala — are built from a dozen sub-components whose definitions vary
between authorities and whose implementations disagree in practice. Producing a
number and calling it Shadbala would put a figure in front of the model that
looks authoritative and is not, which is rule 6's failure in its most
convincing form: a fabricated placement at least sounds like a placement, but a
wrong number sounds like a measurement.

So this computes the three that ARE unambiguous, names each one, and does not
add them up:

    uchcha bala      distance from the point of debilitation
    dig bala         how well the planet suits the direction of its house
    naisargika bala  the fixed natural order of the planets

`shadbala_complete` is False and stays False until the rest is done properly.
The astrologer is told so and instructed not to present these as Shadbala.
"""

# Virupas. Sixty virupas make one rupa, and one rupa is the usual pass mark.
FULL = 60.0

# Exaltation degrees. Debilitation is the exact opposite point, 180 away.
EXALTATION_DEGREE = {
    "Sun": 10.0,        # Aries 10
    "Moon": 33.0,       # Taurus 3
    "Mars": 298.0,      # Capricorn 28
    "Mercury": 165.0,   # Virgo 15
    "Jupiter": 95.0,    # Cancer 5
    "Venus": 357.0,     # Pisces 27
    "Saturn": 200.0,    # Libra 20
}

# The house each planet is strongest in. Dig bala falls off with distance from
# that house's cusp, reaching nothing at the opposite point.
DIG_BALA_HOUSE = {
    "Jupiter": 1, "Mercury": 1,     # the ascendant
    "Sun": 10, "Mars": 10,          # the midheaven
    "Saturn": 7,                    # the descendant
    "Moon": 4, "Venus": 4,          # the nadir
}

# Naisargika bala is a fixed order, brightest to dimmest. Not computed, given.
NAISARGIKA_BALA = {
    "Sun": 60.00, "Moon": 51.43, "Venus": 42.86, "Jupiter": 34.29,
    "Mercury": 25.71, "Mars": 17.14, "Saturn": 8.57,
}

# Rahu and Ketu have no shadbala in the classical scheme: the six strengths are
# defined for bodies, and the nodes are not bodies. Left out rather than given
# a made-up value.
SHADOW_PLANETS = {"Rahu", "Ketu"}

SHADBALA_COMPLETE = False


def _sep(a, b):
    d = abs(a - b) % 360
    return min(d, 360 - d)


def uchcha_bala(planet, longitude):
    """Strength by distance from the point of debilitation, 0 to 60.

    Full at exact exaltation, nothing at exact debilitation, linear between.
    """
    exalt = EXALTATION_DEGREE.get(planet)
    if exalt is None:
        return None
    debilitation = (exalt + 180) % 360
    return round(_sep(longitude, debilitation) / 180 * FULL, 2)


def dig_bala(planet, house):
    """Strength by direction, 0 to 60.

    Full in the planet's own quarter of the chart, nothing in the opposite one.
    Measured in whole houses, which is what a whole-sign chart supports; the
    classical form measures from the exact cusp.
    """
    best = DIG_BALA_HOUSE.get(planet)
    if best is None or not house:
        return None
    houses_apart = min((house - best) % 12, (best - house) % 12)
    return round((1 - houses_apart / 6) * FULL, 2)


def naisargika_bala(planet):
    return NAISARGIKA_BALA.get(planet)


def compute(planets):
    """
    The three unambiguous strengths, per planet.

    Deliberately not summed. A total would imply the other three had been
    accounted for.
    """
    out = {}
    for name, p in (planets or {}).items():
        if name in SHADOW_PLANETS:
            continue
        u = uchcha_bala(name, p.get("longitude", 0))
        d = dig_bala(name, p.get("house"))
        n = naisargika_bala(name)
        if u is None and d is None and n is None:
            continue
        out[name] = {
            "uchcha_bala": u,
            "dig_bala": d,
            "naisargika_bala": n,
            # A reader wants to know which planets carry weight, and the three
            # together give a usable ranking even though they are not Shadbala.
            "of_three": round(sum(v for v in (u, d, n) if v is not None), 2),
        }
    return {"complete": SHADBALA_COMPLETE, "planets": out}


# --------------------------------------------------------------- sade sati

# Saturn takes roughly two and a half years to cross a sign, so the whole
# passage over the three signs runs about seven and a half years.
YEARS_PER_SIGN = 2.5

PHASES = {
    -1: ("rising", "Saturn is in the sign before your Moon. The first phase is "
                   "usually felt as pressure building — obligations arriving, "
                   "sleep and health becoming harder to take for granted."),
    0: ("peak", "Saturn is on your Moon itself. This is the middle and the "
                "heaviest phase, felt in the mind more than in events."),
    1: ("setting", "Saturn is in the sign after your Moon. The last phase "
                   "usually eases, and what was carried through tends to "
                   "consolidate rather than continue."),
}


def sade_sati(moon_sign_index, saturn_sign_index):
    """
    Whether Saturn is in its seven-and-a-half-year passage over the Moon.

    Sade sati runs while Saturn occupies the sign before the Moon's, the Moon's
    own sign, or the sign after. Both arguments are 0-based sign indices.

    Also reports the two shorter transits that are not sade sati and are often
    confused with it: dhaiyya, Saturn in the 4th or 8th from the Moon.
    """
    if moon_sign_index is None or saturn_sign_index is None:
        return None

    offset = (saturn_sign_index - moon_sign_index) % 12
    signed = offset if offset <= 6 else offset - 12   # -5..6, relative position

    if signed in PHASES:
        phase, description = PHASES[signed]
        return {
            "active": True,
            "kind": "sade sati",
            "phase": phase,
            "description": description,
            "houses_from_moon": offset + 1,
            "approx_years_remaining": round(
                YEARS_PER_SIGN * (1 - signed) if signed < 1 else YEARS_PER_SIGN, 1),
            "note": "Timing is approximate: it assumes Saturn takes about two "
                    "and a half years per sign and ignores its retrogrades, "
                    "which can move a boundary by months.",
        }

    if offset in (3, 7):
        return {
            "active": False,
            "kind": "dhaiyya",
            "phase": "small panoti",
            "description": ("Saturn is in the %dth from your Moon — the shorter "
                            "two-and-a-half-year transit, not sade sati."
                            % (offset + 1)),
            "houses_from_moon": offset + 1,
        }

    return {
        "active": False,
        "kind": None,
        "houses_from_moon": offset + 1,
        "description": "Saturn is in the %dth from your Moon. Neither sade "
                       "sati nor dhaiyya is running." % (offset + 1),
    }


def to_prompt_lines(strengths, sadesati, signs):
    """Render both for the astrologer's context."""
    lines = []

    if strengths and strengths.get("planets"):
        lines.append("\n-- Planetary strength (PARTIAL - this is NOT Shadbala) --")
        lines.append(
            "Three of the six strengths are given, each computed and named "
            "separately: uchcha bala (distance from debilitation), dig bala "
            "(suitability of the house's direction), naisargika bala (the fixed "
            "natural order). Kala, cheshta and drik bala are NOT computed. Do "
            "not add these into a Shadbala total, do not call the result "
            "Shadbala, and say so plainly if asked for one. Each is out of 60."
        )
        for name, s in strengths["planets"].items():
            parts = [f"{k.replace('_', ' ')} {v}"
                     for k, v in (("uchcha_bala", s["uchcha_bala"]),
                                  ("dig_bala", s["dig_bala"]),
                                  ("naisargika_bala", s["naisargika_bala"]))
                     if v is not None]
            lines.append(f"{name}: " + ", ".join(parts) +
                         f" (these three sum to {s['of_three']} of a possible 180)")

    if sadesati:
        lines.append("\n-- Saturn over the Moon --")
        lines.append(sadesati["description"])
        if sadesati.get("active"):
            lines.append(
                f"Phase: {sadesati['phase']}. Roughly "
                f"{sadesati['approx_years_remaining']} years of this phase remain. "
                f"{sadesati['note']}"
            )
            lines.append(
                "Treat this carefully. Sade sati is the single most frightening "
                "term in popular astrology and the one most used to sell "
                "remedies. Say what it is, say what the chart actually shows, "
                "and do not inflate it."
            )
    return lines
