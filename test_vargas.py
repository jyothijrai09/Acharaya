"""
Tests for the divisional charts, D1 to D60.

Pure arithmetic, no ephemeris and no imports from the engine.

The most valuable check here is the last one: that D9 computed by the varga
table matches D9 computed by the existing, already-verified navamsha code. If
the table were wrong in shape, that would catch it.

    python test_vargas.py
"""

import sys
import types

from vargas import (
    VARGAS, BY_KEY, MOVABLE, FIXED, DUAL, FIERY, EARTHY, AIRY, WATERY,
)

SIGNS = ["Aries", "Taurus", "Gemini", "Cancer", "Leo", "Virgo",
         "Libra", "Scorpio", "Sagittarius", "Capricorn", "Aquarius", "Pisces"]

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (label, got, want))


def sign_of(key, sign_name, deg):
    return SIGNS[BY_KEY[key].sign_for(SIGNS.index(sign_name), deg)]


# ---------------------------------------------------------------
# 1. The registry itself.
# ---------------------------------------------------------------
check("sixteen vargas", len(VARGAS), 16)
check("keys are unique", len(BY_KEY), 16)
check("expected set", sorted(v.number for v in VARGAS),
      [1, 2, 3, 4, 7, 9, 10, 12, 16, 20, 24, 27, 30, 40, 45, 60])
for v in VARGAS:
    check("%s has a start or a special" % v.key,
          bool(v._start) or bool(v._special), True)

# The quality and element groupings must partition the zodiac.
check("movable/fixed/dual partition",
      sorted(MOVABLE | FIXED | DUAL), list(range(12)))
check("elements partition",
      sorted(FIERY | EARTHY | AIRY | WATERY), list(range(12)))

# ---------------------------------------------------------------
# 2. Every varga stays inside the zodiac, everywhere in every sign.
# ---------------------------------------------------------------
for v in VARGAS:
    for s in range(12):
        for step in range(60):
            deg = step * 0.5
            idx = v.sign_for(s, deg)
            if not (0 <= idx <= 11):
                failures.append("%s out of range at sign %d deg %s -> %r"
                                % (v.key, s, deg, idx))
                break
        # 30.0 should never appear, but must not blow up if it does.
        idx = v.sign_for(s, 30.0)
        if not (0 <= idx <= 11):
            failures.append("%s out of range at exactly 30 deg" % v.key)

# ---------------------------------------------------------------
# 3. D1 is the identity.
# ---------------------------------------------------------------
for s in range(12):
    check("D1 identity %s" % SIGNS[s], sign_of("D1", SIGNS[s], 17.3), SIGNS[s])

# ---------------------------------------------------------------
# 4. D2 Hora — only ever Cancer or Leo.
# ---------------------------------------------------------------
check("D2 Aries first half is Leo", sign_of("D2", "Aries", 5), "Leo")
check("D2 Aries second half is Cancer", sign_of("D2", "Aries", 20), "Cancer")
check("D2 Taurus first half is Cancer", sign_of("D2", "Taurus", 5), "Cancer")
check("D2 Taurus second half is Leo", sign_of("D2", "Taurus", 20), "Leo")
check("D2 boundary at 15 flips", sign_of("D2", "Aries", 15), "Cancer")
for s in range(12):
    for deg in (0, 7.5, 14.9, 15, 22, 29.9):
        got = SIGNS[BY_KEY["D2"].sign_for(s, deg)]
        if got not in ("Cancer", "Leo"):
            failures.append("D2 produced %s, only Cancer/Leo are valid" % got)

# ---------------------------------------------------------------
# 5. D3 Drekkana — trines, not consecutive signs. This is the case the
#    naive continuous formula gets wrong.
# ---------------------------------------------------------------
check("D3 Aries 0-10 is Aries", sign_of("D3", "Aries", 5), "Aries")
check("D3 Aries 10-20 is Leo", sign_of("D3", "Aries", 15), "Leo")
check("D3 Aries 20-30 is Sagittarius", sign_of("D3", "Aries", 25), "Sagittarius")
check("D3 Taurus 10-20 is Virgo", sign_of("D3", "Taurus", 15), "Virgo")
# The continuous shortcut would give Taurus here; it must not.
if sign_of("D3", "Aries", 15) == "Taurus":
    failures.append("D3 used the continuous count instead of the trine rule")

# ---------------------------------------------------------------
# 6. D4 — kendras from the sign.
# ---------------------------------------------------------------
check("D4 Aries part 1", sign_of("D4", "Aries", 3), "Aries")
check("D4 Aries part 2", sign_of("D4", "Aries", 10), "Cancer")
check("D4 Aries part 3", sign_of("D4", "Aries", 18), "Libra")
check("D4 Aries part 4", sign_of("D4", "Aries", 26), "Capricorn")

# ---------------------------------------------------------------
# 7. D7 — odd from itself, even from the 7th.
# ---------------------------------------------------------------
check("D7 Aries starts Aries", sign_of("D7", "Aries", 1), "Aries")
check("D7 Taurus starts Scorpio", sign_of("D7", "Taurus", 1), "Scorpio")

# ---------------------------------------------------------------
# 8. D9 must agree with the classical movable/fixed/dual rule, and with the
#    continuous count from 0 Aries that astro_engine_v2 uses.
# ---------------------------------------------------------------
for s in range(12):
    start = BY_KEY["D9"].sign_for(s, 0.0)
    if s in MOVABLE:
        want = SIGNS[s]
    elif s in FIXED:
        want = SIGNS[(s + 8) % 12]
    else:
        want = SIGNS[(s + 4) % 12]
    check("D9 start for %s" % SIGNS[s], SIGNS[start], want)

# Call the engine itself rather than a copy of its formula — a copy drifts,
# and the point of this check is that the two implementations agree. swisseph
# is stubbed because the engine imports it at module load; nothing on the
# navamsha path touches the ephemeris.
_stub = types.ModuleType("swisseph")
_stub.set_ephe_path = lambda *a, **k: None
_stub.set_sid_mode = lambda *a, **k: None
for _n in ("SIDM_LAHIRI", "SUN", "MOON", "MARS", "MERCURY", "JUPITER",
           "VENUS", "SATURN", "MEAN_NODE", "FLG_SIDEREAL", "FLG_SPEED"):
    setattr(_stub, _n, 0)
sys.modules.setdefault("swisseph", _stub)

from astro_engine_v2 import get_navamsha_longitude  # noqa: E402

for s in range(12):
    for step in range(90):
        deg = step / 3.0
        lon = s * 30 + deg
        engine = int(get_navamsha_longitude(lon) // 30)
        table = BY_KEY["D9"].sign_for(s, deg)
        if engine != table:
            failures.append(
                "D9 disagrees with the engine at %s %.4f: table %s, engine %s"
                % (SIGNS[s], deg, SIGNS[table], SIGNS[engine]))
            break

# ---------------------------------------------------------------
# 9. D10 — odd from itself, even from the 9th.
# ---------------------------------------------------------------
check("D10 Aries starts Aries", sign_of("D10", "Aries", 1), "Aries")
check("D10 Taurus starts Capricorn", sign_of("D10", "Taurus", 1), "Capricorn")

# ---------------------------------------------------------------
# 10. D12 — always from the sign itself.
# ---------------------------------------------------------------
for s in range(12):
    check("D12 starts at itself (%s)" % SIGNS[s],
          BY_KEY["D12"].sign_for(s, 0.5), s)

# ---------------------------------------------------------------
# 11. D30 Trimshamsha — unequal spans, and no luminary signs.
# ---------------------------------------------------------------
check("D30 Aries 0-5 Mars", sign_of("D30", "Aries", 2), "Aries")
check("D30 Aries 5-10 Saturn", sign_of("D30", "Aries", 7), "Aquarius")
check("D30 Aries 10-18 Jupiter", sign_of("D30", "Aries", 14), "Sagittarius")
check("D30 Aries 18-25 Mercury", sign_of("D30", "Aries", 20), "Gemini")
check("D30 Aries 25-30 Venus", sign_of("D30", "Aries", 27), "Libra")

check("D30 Taurus 0-5 Venus", sign_of("D30", "Taurus", 2), "Taurus")
check("D30 Taurus 5-12 Mercury", sign_of("D30", "Taurus", 8), "Virgo")
check("D30 Taurus 12-20 Jupiter", sign_of("D30", "Taurus", 15), "Pisces")
check("D30 Taurus 20-25 Saturn", sign_of("D30", "Taurus", 22), "Capricorn")
check("D30 Taurus 25-30 Mars", sign_of("D30", "Taurus", 28), "Scorpio")

# Cancer and Leo are the Moon's and Sun's; the trimshamsha belongs to the five
# other planets only, so those two signs must never be produced.
for s in range(12):
    for step in range(120):
        got = SIGNS[BY_KEY["D30"].sign_for(s, step * 0.25)]
        if got in ("Cancer", "Leo"):
            failures.append("D30 produced %s — the luminaries own no "
                            "trimshamsha" % got)
            break

# ---------------------------------------------------------------
# 12. Boundary sanity: the first part of every equal-division varga starts at
#     its declared start sign, and 0 degrees never lands off by one.
# ---------------------------------------------------------------
for v in VARGAS:
    if v._special:
        continue
    for s in range(12):
        check("%s at 0 deg of %s is its start" % (v.key, SIGNS[s]),
              v.sign_for(s, 0.0), v._start(s) % 12)

if failures:
    print("FAILED (%d)" % len(failures))
    for f in failures[:25]:
        print("  -", f)
    if len(failures) > 25:
        print("  ... and %d more" % (len(failures) - 25))
    sys.exit(1)

print("All %d divisional charts pass (%d checks)." % (len(VARGAS), 12))
