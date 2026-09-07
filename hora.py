"""
Planetary hours (hora) for where you are now.

A hora is one of twenty-four unequal hours: the daylight from sunrise to
sunset divided into twelve, and the night from sunset to the next sunrise
divided into twelve. They are rarely sixty minutes each — in Jalgaon in June a
day hora runs over an hour and a night hora under it.

Each is ruled by a planet, and the sequence is fixed: the Chaldean order,
descending by apparent speed — Saturn, Jupiter, Mars, Sun, Venus, Mercury,
Moon — cycling continuously. The first hora after sunrise belongs to the lord
of the weekday, which is what ties the two systems together and, not by
coincidence, is why the days are named as they are.

Why this needs a location rather than a birthplace: sunrise is a local event.
The chart is cast for where someone was born, but the hora running right now
depends on where they are standing right now, and the two are often nowhere
near each other.

Sunrise and sunset are computed here rather than through the ephemeris. The
NOAA solar-position algorithm is accurate to about a minute, which is far
finer than a division roughly an hour long needs, and unlike a Swiss Ephemeris
rise/set call it can be tested with no ephemeris installed.
"""

import math
from datetime import datetime, timedelta

# Descending apparent speed, the order the horas run in.
CHALDEAN = ["Saturn", "Jupiter", "Mars", "Sun", "Venus", "Mercury", "Moon"]

# Weekday lords. Python's weekday() is Monday=0.
WEEKDAY_LORDS = ["Moon", "Mars", "Mercury", "Jupiter", "Venus", "Saturn", "Sun"]

# Standard refraction-and-semidiameter allowance: the Sun's upper limb touches
# the horizon while its centre is still this far below it.
SUN_ALTITUDE_AT_RISE = -0.833

OBLIQUITY = 23.4397

# What each planet's hora is traditionally suited to. Kept short and plain,
# and deliberately not predictive — a hora colours a moment, it does not
# decide an outcome.
HORA_NATURE = {
    "Sun": "authority, official matters, dealing with those in charge",
    "Moon": "the mind and the home, anything nurturing, water, travel by sea",
    "Mars": "effort, disputes, surgery, anything needing force",
    "Mercury": "study, writing, negotiation, accounts, short journeys",
    "Jupiter": "learning, counsel, money, ceremonies, anything auspicious",
    "Venus": "relationships, art, comfort, purchases, celebration",
    "Saturn": "labour, endings, repair, the slow and the durable",
}

BENEFIC = {"Jupiter", "Venus", "Mercury", "Moon"}


def _julian_day(dt_utc):
    """Julian day for a UTC datetime. Valid for the Gregorian calendar."""
    y, m = dt_utc.year, dt_utc.month
    d = (dt_utc.day + dt_utc.hour / 24 + dt_utc.minute / 1440
         + dt_utc.second / 86400)
    if m <= 2:
        y -= 1
        m += 12
    a = y // 100
    b = 2 - a + a // 4
    return (int(365.25 * (y + 4716)) + int(30.6001 * (m + 1))
            + d + b - 1524.5)


def _from_julian_day(jd):
    """UTC datetime from a Julian day."""
    jd = jd + 0.5
    z = int(jd)
    f = jd - z
    if z < 2299161:
        a = z
    else:
        alpha = int((z - 1867216.25) / 36524.25)
        a = z + 1 + alpha - alpha // 4
    b = a + 1524
    c = int((b - 122.1) / 365.25)
    d = int(365.25 * c)
    e = int((b - d) / 30.6001)
    day = b - d - int(30.6001 * e) + f
    month = e - 1 if e < 14 else e - 13
    year = c - 4716 if month > 2 else c - 4715
    whole = int(day)
    seconds = round((day - whole) * 86400)
    return datetime(year, month, whole) + timedelta(seconds=seconds)


def sun_events(date, lat, lon):
    """
    Sunrise and sunset as UTC datetimes for a calendar date at a place.

    lon is east-positive. Returns (sunrise, sunset), either of which is None
    inside a polar day or night, where the Sun does not cross the horizon and
    the hora division has no meaning.
    """
    # Days since J2000, corrected for the observer's longitude so the cycle is
    # anchored to local rather than Greenwich noon.
    jd = _julian_day(datetime(date.year, date.month, date.day, 12))
    n = round(jd - 2451545.0 + 0.0008)
    west = -lon
    mean_solar_noon = n + west / 360.0

    # Solar mean anomaly, then the equation of centre.
    M = (357.5291 + 0.98560028 * mean_solar_noon) % 360
    Mr = math.radians(M)
    C = (1.9148 * math.sin(Mr) + 0.0200 * math.sin(2 * Mr)
         + 0.0003 * math.sin(3 * Mr))

    ecliptic_longitude = (M + C + 180 + 102.9372) % 360
    Lr = math.radians(ecliptic_longitude)

    transit = (2451545.0 + mean_solar_noon + 0.0053 * math.sin(Mr)
               - 0.0069 * math.sin(2 * Lr))

    declination = math.asin(math.sin(Lr) * math.sin(math.radians(OBLIQUITY)))

    phi = math.radians(lat)
    numerator = (math.sin(math.radians(SUN_ALTITUDE_AT_RISE))
                 - math.sin(phi) * math.sin(declination))
    denominator = math.cos(phi) * math.cos(declination)
    if denominator == 0:
        return None, None
    cos_hour_angle = numerator / denominator
    if cos_hour_angle > 1 or cos_hour_angle < -1:
        # Polar night or midnight sun: no rise or set on this date.
        return None, None

    hour_angle = math.degrees(math.acos(cos_hour_angle))
    return (_from_julian_day(transit - hour_angle / 360.0),
            _from_julian_day(transit + hour_angle / 360.0))


def day_lord(local_date):
    """The planet ruling a weekday.

    The Vedic day begins at sunrise, not midnight, so between midnight and
    sunrise the governing day is still the previous one. build_horas() handles
    that; this function answers only for the calendar date it is given.
    """
    return WEEKDAY_LORDS[local_date.weekday()]


def build_horas(now_utc, lat, lon, tz_offset=0.0):
    """
    The twenty-four horas covering the moment `now_utc` at a place.

    tz_offset is hours east of UTC, used only to present local clock times and
    to decide which local day it is. The astronomy is done in UTC throughout.

    Returns a dict with the sunrise and sunset that bound the current cycle,
    the ruling weekday lord, the full list of horas, and which one is running.
    """
    local_now = now_utc + timedelta(hours=tz_offset)
    local_date = local_now.date()

    sunrise, sunset = sun_events(local_date, lat, lon)
    if not sunrise or not sunset:
        return {"available": False,
                "reason": "The Sun does not rise or set here on this date, "
                          "so the day cannot be divided into horas."}

    # The hora day runs sunrise to sunrise. Before today's sunrise we are still
    # in last night's cycle, which belongs to the previous weekday — the usual
    # source of an off-by-one-day error in hora tables.
    if now_utc < sunrise:
        local_date = local_date - timedelta(days=1)
        sunrise, sunset = sun_events(local_date, lat, lon)
        if not sunrise or not sunset:
            return {"available": False,
                    "reason": "No sunrise or sunset for the previous day here."}

    next_sunrise, _ = sun_events(local_date + timedelta(days=1), lat, lon)
    if not next_sunrise:
        return {"available": False,
                "reason": "No sunrise tomorrow here, so the night cannot be "
                          "divided."}

    lord = day_lord(local_date)
    start_index = CHALDEAN.index(lord)

    day_part = (sunset - sunrise) / 12
    night_part = (next_sunrise - sunset) / 12

    horas = []
    for i in range(24):
        if i < 12:
            start = sunrise + day_part * i
            end = start + day_part
        else:
            start = sunset + night_part * (i - 12)
            end = start + night_part
        ruler = CHALDEAN[(start_index + i) % 7]
        horas.append({
            "index": i + 1,
            "ruler": ruler,
            "is_day": i < 12,
            "benefic": ruler in BENEFIC,
            "suited_to": HORA_NATURE[ruler],
            "start_utc": start.isoformat(),
            "end_utc": end.isoformat(),
            "start_local": (start + timedelta(hours=tz_offset)).strftime("%H:%M"),
            "end_local": (end + timedelta(hours=tz_offset)).strftime("%H:%M"),
            "current": start <= now_utc < end,
        })

    current = next((h for h in horas if h["current"]), None)
    return {
        "available": True,
        "day_lord": lord,
        "weekday": local_date.strftime("%A"),
        "sunrise_local": (sunrise + timedelta(hours=tz_offset)).strftime("%H:%M"),
        "sunset_local": (sunset + timedelta(hours=tz_offset)).strftime("%H:%M"),
        "next_sunrise_local": (next_sunrise + timedelta(hours=tz_offset)).strftime("%H:%M"),
        "day_hora_minutes": round(day_part.total_seconds() / 60, 1),
        "night_hora_minutes": round(night_part.total_seconds() / 60, 1),
        "current": current,
        "horas": horas,
    }
