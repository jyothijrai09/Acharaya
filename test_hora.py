"""
Tests for sunrise, sunset and the planetary hours.

No ephemeris and no network — the solar position is computed in hora.py.

The strongest check here is the last one: after twenty-four horas the sequence
must land on the NEXT weekday's lord. Twenty-four is not a multiple of seven,
so that only holds if both the Chaldean order and the weekday lords are right.
It is the property the seven-day week is named after.

    python test_hora.py
"""

import sys
from datetime import date, datetime, timedelta

from hora import (
    CHALDEAN, WEEKDAY_LORDS, sun_events, day_lord, build_horas,
    _julian_day, _from_julian_day,
)

failures = []


def check(label, got, want):
    if got != want:
        failures.append("%s: got %r, want %r" % (label, got, want))


def close(label, got, want, tol):
    if got is None or abs(got - want) > tol:
        failures.append("%s: got %r, want %r +/- %r" % (label, got, want, tol))


# ---------------------------------------------------------------
# 1. Julian day round-trips.
# ---------------------------------------------------------------
for dt in (datetime(2000, 1, 1, 12), datetime(1984, 3, 2, 1, 15),
           datetime(2026, 9, 7, 23, 59), datetime(2026, 2, 29, 6, 0)
           if False else datetime(2024, 2, 29, 6, 0)):
    back = _from_julian_day(_julian_day(dt))
    if abs((back - dt).total_seconds()) > 1:
        failures.append("julian round trip %s -> %s" % (dt, back))

check("J2000 epoch", round(_julian_day(datetime(2000, 1, 1, 12)), 1), 2451545.0)

# ---------------------------------------------------------------
# 2. Sunrise and sunset are ordered, and the day is a sane length.
# ---------------------------------------------------------------
JALGAON = (21.02, 75.57)          # the reference chart's birthplace
LONDON = (51.5, -0.12)
QUITO = (-0.18, -78.47)           # on the equator
TROMSO = (69.65, 18.96)           # inside the Arctic circle

for name, (lat, lon) in [("Jalgaon", JALGAON), ("London", LONDON),
                         ("Quito", QUITO)]:
    for d in (date(2026, 3, 20), date(2026, 6, 21),
              date(2026, 9, 22), date(2026, 12, 21)):
        rise, set_ = sun_events(d, lat, lon)
        if not rise or not set_:
            failures.append("%s %s: no sun events" % (name, d))
            continue
        if rise >= set_:
            failures.append("%s %s: sunrise not before sunset" % (name, d))
        hours = (set_ - rise).total_seconds() / 3600
        if not (5 < hours < 20):
            failures.append("%s %s: implausible day length %.2f h"
                            % (name, d, hours))

# On the equator the day is close to twelve hours all year.
for d in (date(2026, 3, 20), date(2026, 6, 21), date(2026, 12, 21)):
    rise, set_ = sun_events(d, *QUITO)
    close("Quito day length %s" % d, (set_ - rise).total_seconds() / 3600, 12.1, 0.5)

# At an equinox everywhere gets roughly twelve hours.
for name, (lat, lon) in [("Jalgaon", JALGAON), ("London", LONDON)]:
    rise, set_ = sun_events(date(2026, 3, 20), lat, lon)
    close("%s equinox day length" % name,
          (set_ - rise).total_seconds() / 3600, 12.1, 0.4)

# London's summer day is far longer than its winter one; Jalgaon's varies less.
def day_hours(d, place):
    r, s = sun_events(d, *place)
    return (s - r).total_seconds() / 3600

london_swing = day_hours(date(2026, 6, 21), LONDON) - day_hours(date(2026, 12, 21), LONDON)
jalgaon_swing = day_hours(date(2026, 6, 21), JALGAON) - day_hours(date(2026, 12, 21), JALGAON)
check("London swings more than Jalgaon", london_swing > jalgaon_swing + 4, True)

# Inside the Arctic circle at midsummer there is no sunset at all, and the
# hora division has to say so rather than invent one.
rise, set_ = sun_events(date(2026, 6, 21), *TROMSO)
check("Tromso midsummer has no sun events", (rise, set_), (None, None))

# Jalgaon sunrise in September is early morning local time (UTC+5:30).
rise, set_ = sun_events(date(2026, 9, 7), *JALGAON)
local_rise = (rise + timedelta(hours=5.5)).hour + (rise + timedelta(hours=5.5)).minute / 60
close("Jalgaon September sunrise (IST)", local_rise, 6.4, 0.5)

# ---------------------------------------------------------------
# 3. Weekday lords.
# ---------------------------------------------------------------
check("seven lords", len(WEEKDAY_LORDS), 7)
check("seven planets in the Chaldean order", len(CHALDEAN), 7)
check("same seven planets", sorted(CHALDEAN), sorted(WEEKDAY_LORDS))

# 2026-09-07 is a Monday.
check("Monday belongs to the Moon", day_lord(date(2026, 9, 7)), "Moon")
check("Sunday belongs to the Sun", day_lord(date(2026, 9, 6)), "Sun")
check("Saturday belongs to Saturn", day_lord(date(2026, 9, 5)), "Saturn")

# ---------------------------------------------------------------
# 4. The hora table.
# ---------------------------------------------------------------
now = datetime(2026, 9, 7, 8, 0)          # 13:30 IST, mid-morning in Jalgaon
h = build_horas(now, JALGAON[0], JALGAON[1], tz_offset=5.5)

check("available", h["available"], True)
check("twenty-four horas", len(h["horas"]), 24)
check("twelve of them by day", sum(1 for x in h["horas"] if x["is_day"]), 12)
check("day lord is the weekday lord", h["day_lord"], "Moon")
check("first hora belongs to the day lord", h["horas"][0]["ruler"], "Moon")

# Exactly one hora is current, and it contains the moment asked about.
current = [x for x in h["horas"] if x["current"]]
check("exactly one current hora", len(current), 1)
check("current is reported", h["current"]["index"], current[0]["index"])

# The horas tile the whole cycle with no gap and no overlap.
for a, b in zip(h["horas"], h["horas"][1:]):
    if a["end_utc"] != b["start_utc"]:
        failures.append("gap between hora %d and %d" % (a["index"], b["index"]))
        break

# Day and night horas are not sixty minutes, and not equal to each other,
# except at an equinox. In September in Jalgaon they still differ.
check("day and night horas differ",
      h["day_hora_minutes"] != h["night_hora_minutes"], True)
close("day hora is about an hour", h["day_hora_minutes"], 60, 12)

# ---------------------------------------------------------------
# 5. The property the week is named for: twenty-four horas on, the sequence
#    lands on the NEXT day's lord. Twenty-four is not a multiple of seven, so
#    this only holds if both tables are correct.
# ---------------------------------------------------------------
for offset in range(7):
    d = date(2026, 9, 7) + timedelta(days=offset)
    start = CHALDEAN.index(day_lord(d))
    twenty_fifth = CHALDEAN[(start + 24) % 7]
    check("%s + 24 horas is %s's lord" % (d.strftime("%A"),
                                          (d + timedelta(days=1)).strftime("%A")),
          twenty_fifth, day_lord(d + timedelta(days=1)))

# ---------------------------------------------------------------
# 6. Before sunrise we are still in the previous day's cycle. This is the
#    usual off-by-one in hora tables.
# ---------------------------------------------------------------
pre_dawn = datetime(2026, 9, 7, 22, 0)     # 03:30 IST on the 8th, before sunrise
h2 = build_horas(pre_dawn, JALGAON[0], JALGAON[1], tz_offset=5.5)
check("pre-dawn still belongs to the previous weekday", h2["day_lord"], "Moon")
check("pre-dawn is in a night hora",
      h2["current"]["is_day"] if h2["current"] else None, False)

# And a polar location reports itself unavailable rather than guessing.
h3 = build_horas(datetime(2026, 6, 21, 12), TROMSO[0], TROMSO[1], tz_offset=2)
check("polar day has no horas", h3["available"], False)
check("polar day explains itself", bool(h3.get("reason")), True)

if failures:
    print("FAILED (%d)" % len(failures))
    for f in failures:
        print("  -", f)
    sys.exit(1)

print("All hora and sunrise tests passed.")
