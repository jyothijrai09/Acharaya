"""
Tests for planetary condition: dignity, retrogression and combustion.

Like test_navamsha.py these stub swisseph, so they run with no ephemeris.
The combustion pass inside compute_planets needs real positions, so the orb
rule itself is exercised directly against the published table.

    python test_dignity.py
"""

import sys
import types

_stub = types.ModuleType("swisseph")
_stub.set_ephe_path = lambda *a, **k: None
_stub.set_sid_mode = lambda *a, **k: None
for _name in ("SIDM_LAHIRI", "SUN", "MOON", "MARS", "MERCURY",
              "JUPITER", "VENUS", "SATURN", "MEAN_NODE", "FLG_SIDEREAL",
              "FLG_SPEED"):
    setattr(_stub, _name, 0)
sys.modules.setdefault("swisseph", _stub)

from astro_engine_v2 import (  # noqa: E402
    angular_separation, get_dignity, COMBUSTION_ORBS, SHADOW_PLANETS,
    EXALTATION, DEBILITATION, SIGNS,
)

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (label, got, want))


# ---------------------------------------------------------------
# 1. Angular separation wraps the zodiac correctly.
# ---------------------------------------------------------------
check("same point", angular_separation(100, 100), 0)
check("simple gap", angular_separation(10, 40), 30)
check("opposition", angular_separation(0, 180), 180)
check("wraps past 0 Aries", angular_separation(350, 10), 20)
check("wraps the other way", angular_separation(10, 350), 20)
check("never exceeds 180", angular_separation(0, 200), 160)
check("full circle", angular_separation(0, 360), 0)

# ---------------------------------------------------------------
# 2. Exaltation and debilitation are exact opposites, by construction.
# ---------------------------------------------------------------
for planet, sign in EXALTATION.items():
    opposite = SIGNS[(SIGNS.index(sign) + 6) % 12]
    check("%s debilitation opposes exaltation" % planet,
          DEBILITATION[planet], opposite)

check("Sun exalted in Aries", get_dignity("Sun", "Aries"), "exalted")
check("Sun debilitated in Libra", get_dignity("Sun", "Libra"), "debilitated")
check("Saturn exalted in Libra", get_dignity("Saturn", "Libra"), "exalted")
check("Mars debilitated in Cancer", get_dignity("Mars", "Cancer"), "debilitated")
check("Mercury exalted and own sign in Virgo",
      get_dignity("Mercury", "Virgo"), "exalted")   # exaltation wins over own sign
check("Venus own sign Taurus", get_dignity("Venus", "Taurus"), "own sign")
check("neutral", get_dignity("Jupiter", "Aries"), None)

# The nodes have no agreed exaltation, so they must report none rather than
# a guess. This is the same reasoning as in compute_navamsha.
for node in SHADOW_PLANETS:
    for sign in SIGNS:
        check("%s never has dignity (%s)" % (node, sign),
              get_dignity(node, sign), None)

# ---------------------------------------------------------------
# 3. The combustion orb table.
# ---------------------------------------------------------------
check("Sun is not in the orb table", "Sun" in COMBUSTION_ORBS, False)
for node in SHADOW_PLANETS:
    check("%s is not in the orb table" % node, node in COMBUSTION_ORBS, False)

check("seven combustible bodies", len(COMBUSTION_ORBS), 6)

for planet, (direct, retro) in COMBUSTION_ORBS.items():
    check("%s retrograde orb is not wider than direct" % planet,
          retro <= direct, True)
    check("%s orbs are positive" % planet, direct > 0 and retro > 0, True)

# Mercury and Venus are the two that tighten when retrograde.
check("Mercury tightens retrograde", COMBUSTION_ORBS["Mercury"], (14, 12))
check("Venus tightens retrograde", COMBUSTION_ORBS["Venus"], (10, 8))
check("Mars orb", COMBUSTION_ORBS["Mars"], (17, 17))


# ---------------------------------------------------------------
# 4. The combustion decision, as compute_planets applies it.
# ---------------------------------------------------------------
def is_combust(planet, planet_lon, sun_lon, retrograde=False):
    if planet == "Sun" or planet in SHADOW_PLANETS:
        return False
    direct, retro = COMBUSTION_ORBS[planet]
    orb = retro if retrograde else direct
    return angular_separation(planet_lon, sun_lon) <= orb


check("Mercury 5 deg from Sun is combust", is_combust("Mercury", 105, 100), True)
check("Mercury 20 deg from Sun is not", is_combust("Mercury", 120, 100), False)
check("Mercury at exactly its orb is combust", is_combust("Mercury", 114, 100), True)
check("Mercury retrograde at 13 deg escapes the tighter orb",
      is_combust("Mercury", 113, 100, retrograde=True), False)
check("Mercury direct at 13 deg is combust",
      is_combust("Mercury", 113, 100, retrograde=False), True)
check("combustion works across 0 Aries",
      is_combust("Venus", 2, 355), True)
check("Sun is never combust", is_combust("Sun", 100, 100), False)
for node in SHADOW_PLANETS:
    check("%s is never combust" % node, is_combust(node, 100, 100), False)

if failures:
    print("FAILED (%d)" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("All dignity, retrogression and combustion tests passed.")
