"""
Regression tests for the D9 navamsha calculation.

Navamsha is pure longitude arithmetic, so these run without an ephemeris —
swisseph is stubbed out before the engine is imported. That keeps the test
runnable anywhere, including a machine with no pyswisseph installed:

    python test_navamsha.py
"""

import sys
import types

# Stub swisseph: the engine calls set_ephe_path / set_sid_mode at import time,
# but nothing on the navamsha path touches the ephemeris.
_stub = types.ModuleType("swisseph")
_stub.set_ephe_path = lambda *a, **k: None
_stub.set_sid_mode = lambda *a, **k: None
for _name in ("SIDM_LAHIRI", "SUN", "MOON", "MARS", "MERCURY",
              "JUPITER", "VENUS", "SATURN", "MEAN_NODE", "FLG_SIDEREAL"):
    setattr(_stub, _name, 0)
sys.modules.setdefault("swisseph", _stub)

from astro_engine_v2 import (  # noqa: E402
    SIGNS, get_navamsha_longitude, get_sign, compute_navamsha, get_dignity,
)

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (label, got, want))


# ---------------------------------------------------------------
# 1. The classical starting-sign rule, checked at 0 degrees of each sign.
#    Movable signs start their navamsha series from themselves, fixed signs
#    from the 9th sign, dual signs from the 5th.
#
#    This is also the regression guard for the floating-point boundary bug:
#    every case here sits exactly on a sign cusp, which is precisely where
#    the naive longitude // (30/9) form goes wrong.
# ---------------------------------------------------------------
MOVABLE = ["Aries", "Cancer", "Libra", "Capricorn"]
FIXED = ["Taurus", "Leo", "Scorpio", "Aquarius"]

for idx, sign in enumerate(SIGNS):
    start = get_sign(get_navamsha_longitude(idx * 30))
    if sign in MOVABLE:
        want = sign
    elif sign in FIXED:
        want = SIGNS[(idx + 8) % 12]        # 9th sign from itself
    else:
        want = SIGNS[(idx + 4) % 12]        # 5th sign from itself
    check("first navamsha of %s" % sign, start, want)

# A few boundaries spelled out explicitly, so a future reader can see the
# expected answers without re-deriving the rule.
check("0 deg Aries -> Aries", get_sign(get_navamsha_longitude(0.0)), "Aries")
check("0 deg Taurus -> Capricorn", get_sign(get_navamsha_longitude(30.0)), "Capricorn")
check("0 deg Gemini -> Libra", get_sign(get_navamsha_longitude(60.0)), "Libra")
check("0 deg Cancer -> Cancer", get_sign(get_navamsha_longitude(90.0)), "Cancer")

# ---------------------------------------------------------------
# 2. The nine navamshas of a sign run in unbroken zodiacal order.
# ---------------------------------------------------------------
for idx, sign in enumerate(SIGNS):
    first = SIGNS.index(get_sign(get_navamsha_longitude(idx * 30)))
    for part in range(9):
        lon = idx * 30 + part * (30 / 9) + 0.5      # mid-navamsha
        check("%s navamsha %d" % (sign, part + 1),
              get_sign(get_navamsha_longitude(lon)),
              SIGNS[(first + part) % 12])

# ---------------------------------------------------------------
# 3. The zodiac holds exactly 108 navamshas and the cycle closes.
# ---------------------------------------------------------------
check("navamsha count", int(360 * 9 // 30), 108)
check("cycle closes at 360", get_sign(get_navamsha_longitude(359.999)), "Pisces")

# The expanded degree must stay inside the sign at every boundary.
for idx in range(12):
    d = get_navamsha_longitude(idx * 30) % 30
    check("expanded degree in range at %d deg" % (idx * 30), 0.0 <= d < 30.0, True)

# ---------------------------------------------------------------
# 4. Reference chart (CLAUDE.md): born 2 March 1984, 06:45 IST, Jalgaon.
#    Lagna Aquarius 16.08 deg -> absolute 316.08 deg.
#    Aquarius is fixed, so its navamsha series starts at Libra; 16.08 deg
#    falls in the 5th navamsha, and Libra + 4 = Aquarius. The lagna is
#    therefore vargottama.
# ---------------------------------------------------------------
ASC = 10 * 30 + 16.08
check("reference D9 lagna", get_sign(get_navamsha_longitude(ASC)), "Aquarius")

natal = {
    "Sun":    {"longitude": ASC, "sign": "Aquarius"},
    "Saturn": {"longitude": 6 * 30 + 15.0, "sign": "Libra"},   # exalted in D1
}
d9 = compute_navamsha(natal, ASC)
check("reference D9 lagna via compute_navamsha", d9["lagna"]["sign"], "Aquarius")
check("reference D9 lagna vargottama", d9["lagna"]["vargottama"], True)
check("reference D9 lagna lord", d9["lagna"]["lord"], "Saturn")
check("Sun vargottama in D9", d9["planets"]["Sun"]["vargottama"], True)
check("Sun D9 house", d9["planets"]["Sun"]["house"], 1)

# ---------------------------------------------------------------
# 5. Dignity lookup, including the deliberate absence of node dignities.
# ---------------------------------------------------------------
check("Saturn exalted in Libra", get_dignity("Saturn", "Libra"), "exalted")
check("Saturn debilitated in Aries", get_dignity("Saturn", "Aries"), "debilitated")
check("Saturn own sign Aquarius", get_dignity("Saturn", "Aquarius"), "own sign")
check("Jupiter exalted in Cancer", get_dignity("Jupiter", "Cancer"), "exalted")
check("Jupiter debilitated in Capricorn", get_dignity("Jupiter", "Capricorn"), "debilitated")
check("Rahu has no dignity", get_dignity("Rahu", "Taurus"), None)
check("Ketu has no dignity", get_dignity("Ketu", "Scorpio"), None)
check("neutral placement", get_dignity("Sun", "Gemini"), None)

# ---------------------------------------------------------------
# 6. Houses are whole-sign from the D9 lagna and wrap correctly.
# ---------------------------------------------------------------
spread = {SIGNS[i]: {"longitude": i * 30 + 1.0, "sign": SIGNS[i]} for i in range(12)}
d9_spread = compute_navamsha(spread, 0.0)
houses = [p["house"] for p in d9_spread["planets"].values()]
check("houses stay in 1..12", all(1 <= h <= 12 for h in houses), True)

# A planet in the D9 lagna's own sign must land in house 1.
same = compute_navamsha({"X": {"longitude": 0.0, "sign": "Aries"}}, 0.0)
check("planet on D9 lagna is house 1", same["planets"]["X"]["house"], 1)

if failures:
    print("FAILED (%d)" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("All navamsha tests passed.")
