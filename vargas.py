"""
Divisional charts — the shodashavarga, D1 to D60.

Each varga divides a sign into N parts and maps each part to a sign. What
differs between them is not the arithmetic but the STARTING sign: some count
from the rashi itself, some from a fixed sign, some depend on whether the sign
is odd or even, movable or fixed or dual, or on its element. Two of them are
not equal divisions at all.

That variety is the whole reason this is a table rather than one formula.
Writing D3 as a continuous count from Aries — the shortcut that happens to be
correct for D9 — puts 10° Aries in Taurus instead of Leo. The rules below are
each stated explicitly so they can be checked against a printed chart.

Where the tradition disagrees, the choice is recorded in the varga's `note`
rather than hidden:

  D30  Trimshamsha has UNEQUAL divisions and skips the luminaries entirely.
       The five parts belong to Mars, Saturn, Jupiter, Mercury and Venus, in
       one order for odd signs and the reverse for even ones.
  D60  Shashtiamsha counting is not agreed. This uses the common form —
       count the part forward from the rashi sign, for odd and even alike.
       Some schools reverse the count for even signs, which shifts nearly
       every planet, so check a printed D60 before relying on it.

Sign indices are 0-based from Aries throughout, matching SIGNS in
astro_engine_v2.
"""

# Movable (chara), fixed (sthira), dual (dwiswabhava), by 0-based sign index.
MOVABLE = {0, 3, 6, 9}      # Aries, Cancer, Libra, Capricorn
FIXED = {1, 4, 7, 10}       # Taurus, Leo, Scorpio, Aquarius
DUAL = {2, 5, 8, 11}        # Gemini, Virgo, Sagittarius, Pisces

# Elements, for D27.
FIERY = {0, 4, 8}           # Aries, Leo, Sagittarius
EARTHY = {1, 5, 9}          # Taurus, Virgo, Capricorn
AIRY = {2, 6, 10}           # Gemini, Libra, Aquarius
WATERY = {3, 7, 11}         # Cancer, Scorpio, Pisces

ARIES, TAURUS, GEMINI, CANCER = 0, 1, 2, 3
LEO, VIRGO, LIBRA, SCORPIO = 4, 5, 6, 7
SAGITTARIUS, CAPRICORN, AQUARIUS, PISCES = 8, 9, 10, 11


def _is_odd(sign):
    """Odd signs are Aries, Gemini, Leo... — 1st, 3rd, 5th and so on.
    Zero-based, that is an EVEN index. Named for the tradition, not the code."""
    return sign % 2 == 0


# --------------------------------------------------------------- starts

def _start_same(sign):
    return sign


def _start_odd_even(odd_start, even_start):
    """Start at one sign for odd rashis and another for even ones, where each
    is given relative to the rashi itself (an offset), not absolutely."""
    def start(sign):
        return (sign + (odd_start if _is_odd(sign) else even_start)) % 12
    return start


def _start_fixed_by_parity(odd_sign, even_sign):
    """Start at an absolute sign, chosen by the rashi's parity."""
    def start(sign):
        return odd_sign if _is_odd(sign) else even_sign
    return start


def _start_by_quality(movable, fixed, dual):
    """Start at an absolute sign, chosen by movable / fixed / dual."""
    def start(sign):
        if sign in MOVABLE:
            return movable
        if sign in FIXED:
            return fixed
        return dual
    return start


def _start_by_element(fiery, earthy, airy, watery):
    def start(sign):
        if sign in FIERY:
            return fiery
        if sign in EARTHY:
            return earthy
        if sign in AIRY:
            return airy
        return watery
    return start


def _start_trine(sign):
    """D3: same sign, then the 5th, then the 9th — the trines."""
    return sign


# --------------------------------------------------------------- specials

def _hora_sign(sign, deg):
    """D2. Two halves, and only two signs are ever produced: Leo (the Sun's
    hora) and Cancer (the Moon's). Odd signs give Sun then Moon; even signs
    the reverse."""
    first_half = deg < 15
    if _is_odd(sign):
        return LEO if first_half else CANCER
    return CANCER if first_half else LEO


# D30. Unequal spans, and the luminaries own none of them.
_TRIMSHAMSHA_ODD = [(5, ARIES), (10, AQUARIUS), (18, SAGITTARIUS),
                    (25, GEMINI), (30, LIBRA)]
_TRIMSHAMSHA_EVEN = [(5, TAURUS), (12, VIRGO), (20, PISCES),
                     (25, CAPRICORN), (30, SCORPIO)]


def _trimshamsha_sign(sign, deg):
    table = _TRIMSHAMSHA_ODD if _is_odd(sign) else _TRIMSHAMSHA_EVEN
    for upper, result in table:
        if deg < upper:
            return result
    return table[-1][1]


def _drekkana_sign(sign, deg):
    """D3. The three parts fall on the sign, the 5th from it and the 9th —
    trines, not consecutive signs."""
    part = int(deg // 10)
    return (sign + [0, 4, 8][min(part, 2)]) % 12


def _chaturthamsha_sign(sign, deg):
    """D4. The four parts fall on the kendras: the sign, the 4th, 7th, 10th."""
    part = int(deg // 7.5)
    return (sign + [0, 3, 6, 9][min(part, 3)]) % 12


# --------------------------------------------------------------- registry

class Varga:
    def __init__(self, key, number, name, meaning, start=None, special=None,
                 note=None):
        self.key = key
        self.number = number
        self.name = name
        self.meaning = meaning
        self._start = start
        self._special = special
        self.note = note

    def sign_for(self, sign, deg):
        """The varga sign for a planet in `sign` at `deg` degrees into it."""
        if self._special:
            return self._special(sign, deg)
        # The epsilon is not decoration. A degree that sits exactly on a part
        # boundary is usually not representable in binary floating point:
        # 23°20' of Taurus is 70/3, which stores as 23.333333333333332, and
        # 23.333333333333332 * 9 / 30 comes out as 6.999999999999999. Without
        # the nudge that floors to part 6 instead of 7, putting the planet one
        # varga sign back — a real disagreement with the navamsha the engine
        # computes from absolute longitude, which test_vargas.py catches.
        #
        # 1e-9 of a part is about a hundred-thousandth of an arcsecond for D9,
        # far below any precision an ephemeris offers, so it can only ever
        # correct this rounding and never move a genuine placement.
        part = int(deg * self.number / 30 + 1e-9)
        part = min(part, self.number - 1)          # guard deg == 30.0 exactly
        return (self._start(sign) + part) % 12


VARGAS = [
    Varga("D1", 1, "Rashi", "the body, and life as it is actually lived",
          start=_start_same),
    Varga("D2", 2, "Hora", "wealth and what sustains you",
          special=_hora_sign,
          note="Only ever Cancer or Leo — the Moon's hora and the Sun's."),
    Varga("D3", 3, "Drekkana", "siblings, courage, initiative",
          special=_drekkana_sign,
          note="Parts fall on the trines: the sign, the 5th, the 9th."),
    Varga("D4", 4, "Chaturthamsha", "home, land, fixed assets",
          special=_chaturthamsha_sign,
          note="Parts fall on the kendras: the sign, the 4th, 7th, 10th."),
    Varga("D7", 7, "Saptamsha", "children and lineage",
          start=_start_odd_even(0, 6),
          note="Odd signs start from themselves, even signs from the 7th."),
    # D9's start rule is attached below, where the equivalence between the
    # classical rule and the continuous count can be explained.
    Varga("D9", 9, "Navamsha", "marriage, dharma, the strength behind a promise"),
    Varga("D10", 10, "Dashamsha", "career, standing, action in the world",
          start=_start_odd_even(0, 8),
          note="Odd signs start from themselves, even signs from the 9th."),
    Varga("D12", 12, "Dwadashamsha", "parents and ancestry",
          start=_start_same,
          note="Always counted from the sign itself."),
    Varga("D16", 16, "Shodashamsha", "vehicles, comforts, pleasures",
          start=_start_by_quality(ARIES, LEO, SAGITTARIUS)),
    Varga("D20", 20, "Vimshamsha", "spiritual practice and worship",
          start=_start_by_quality(ARIES, SAGITTARIUS, LEO)),
    Varga("D24", 24, "Chaturvimshamsha", "learning and education",
          start=_start_fixed_by_parity(LEO, CANCER)),
    Varga("D27", 27, "Bhamsha", "strength and weakness of the body",
          start=_start_by_element(ARIES, CANCER, LIBRA, CAPRICORN),
          note="Start depends on the element: fiery Aries, earthy Cancer, "
               "airy Libra, watery Capricorn."),
    Varga("D30", 30, "Trimshamsha", "misfortune, and where harm comes from",
          special=_trimshamsha_sign,
          note="UNEQUAL divisions of 5/5/8/7/5 degrees, reversed for even "
               "signs. The Sun and Moon own no trimshamsha."),
    Varga("D40", 40, "Khavedamsha", "auspicious and inauspicious inheritance",
          start=_start_fixed_by_parity(ARIES, LIBRA)),
    Varga("D45", 45, "Akshavedamsha", "general character and conduct",
          start=_start_by_quality(ARIES, LEO, SAGITTARIUS)),
    Varga("D60", 60, "Shashtiamsha", "the sum of past karma; finest distinctions",
          start=_start_same,
          note="Counting is not agreed between schools. This counts forward "
               "from the rashi for odd and even signs alike; some reverse it "
               "for even signs, which moves nearly every planet."),
]

# D9 is the continuous count from Aries, which is equivalent to the classical
# movable/fixed/dual rule. Expressed here rather than in the constructor so
# the equivalence is stated where someone will read it.
def _navamsha_start(sign):
    if sign in MOVABLE:
        return sign
    if sign in FIXED:
        return (sign + 8) % 12      # the 9th from it
    return (sign + 4) % 12          # the 5th from it


for _v in VARGAS:
    if _v.key == "D9":
        _v._start = _navamsha_start
        _v.note = ("Movable signs start from themselves, fixed from the 9th, "
                   "dual from the 5th — equivalent to counting continuously "
                   "from 0 Aries.")

BY_KEY = {v.key: v for v in VARGAS}


def compute_all(planets, asc_lon, signs, sign_lords, dignity_for):
    """
    Every varga for every planet, plus each varga's lagna.

    Takes its helpers as arguments rather than importing astro_engine_v2, so
    this module has no circular import and can be tested on its own.

    Returns {varga_key: {name, meaning, note, lagna: {...}, planets: {...}}}
    """
    out = {}
    for varga in VARGAS:
        asc_sign_idx = int(asc_lon // 30)
        asc_deg = asc_lon % 30
        lagna_idx = varga.sign_for(asc_sign_idx, asc_deg)
        lagna_sign = signs[lagna_idx]

        entry = {
            "name": varga.name,
            "meaning": varga.meaning,
            "note": varga.note,
            "lagna": {
                "sign": lagna_sign,
                "lord": sign_lords[lagna_sign],
                "vargottama": lagna_idx == asc_sign_idx,
            },
            "planets": {},
        }

        for name, p in planets.items():
            rashi_idx = int(p["longitude"] // 30)
            idx = varga.sign_for(rashi_idx, p["longitude"] % 30)
            sign = signs[idx]
            entry["planets"][name] = {
                "sign": sign,
                "house": (idx - lagna_idx) % 12 + 1,
                "lord": sign_lords[sign],
                "dignity": dignity_for(name, sign),
                # Vargottama proper means the same sign as the rashi. It is
                # meaningful in any varga, not only D9.
                "vargottama": idx == rashi_idx,
            }
        out[varga.key] = entry
    return out
