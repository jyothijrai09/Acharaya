"""
Place lookup for the birth-details form.

Turns "Jalgaon, India" into the latitude, longitude and — the part that is
easy to get wrong by hand — the UTC offset that was in force at that place on
the date of birth.

Two sources, both free and neither needing an API key:

    OpenStreetMap Nominatim  place name -> coordinates (network)
    timezonefinder           coordinates -> IANA zone   (offline)
    zoneinfo                 IANA zone + birth datetime -> offset (stdlib)

Why the offset is computed rather than typed: CLAUDE.md's convention is that
tz_offset is the offset **at the time of birth**, not the modern one for that
place. Those differ more often than people expect — Britain was on UTC+0 in
March 1984 and UTC+1 in July 1984, and India itself has changed. A person
entering their own birth details has no reliable way to know the historical
value, and an hour of error moves the ascendant by roughly fifteen degrees.
"""

import json
import os
import urllib.parse
import urllib.request
from datetime import datetime
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"

# Nominatim's usage policy requires a User-Agent identifying the application.
# Requests without one are refused, and a generic urllib default risks the
# whole IP being blocked.
USER_AGENT = os.environ.get(
    "GEOCODER_USER_AGENT",
    "Acharaya-Jyotish/1.0 (personal astrology app; github.com/jyothijrai09/Acharaya)",
)

TIMEOUT_SECONDS = 8


class GeocodeError(RuntimeError):
    """Raised with a message fit to show the person filling in the form."""


_finder = None


def _timezone_finder():
    """Loaded once and reused. Construction reads a bundled data file, which is
    slow enough to matter on a cold serverless start."""
    global _finder
    if _finder is None:
        try:
            from timezonefinder import TimezoneFinder
        except ImportError as e:
            raise GeocodeError(
                "timezonefinder is not installed. Run: pip install timezonefinder"
            ) from e
        _finder = TimezoneFinder()
    return _finder


def timezone_for(lat, lon):
    """IANA zone name for a coordinate, or None over open ocean."""
    return _timezone_finder().timezone_at(lat=lat, lng=lon)


def offset_at(zone_name, year, month, day, hour=12, minute=0):
    """
    UTC offset in hours at a place on a specific local date and time.

    Returns a float because half-hour and quarter-hour zones are common in
    exactly the part of the world this app is aimed at — India is +5.5 and
    Nepal is +5.75.
    """
    try:
        zone = ZoneInfo(zone_name)
    except (ZoneInfoNotFoundError, ValueError) as e:
        raise GeocodeError(f"Unknown time zone {zone_name!r}.") from e

    # A local wall-clock time inside a DST transition is ambiguous or does not
    # exist. fold=0 picks the first occurrence, which matches what a birth
    # certificate records: the clock reading as it was written down.
    local = datetime(year, month, day, hour, minute, fold=0, tzinfo=zone)
    return local.utcoffset().total_seconds() / 3600


def search(query, limit=5, birth=None):
    """
    Look up a place. Returns a list of candidates, best match first:

        {name, lat, lon, timezone, tz_offset, offset_is_for_birth_date}

    birth: optional (year, month, day, hour, minute). When given, tz_offset is
    the offset in force at that moment. When absent it is today's offset, and
    offset_is_for_birth_date is False so the caller can avoid presenting a
    possibly-wrong value as authoritative.
    """
    query = (query or "").strip()
    if not query:
        return []

    url = NOMINATIM_URL + "?" + urllib.parse.urlencode({
        "q": query,
        "format": "jsonv2",
        "limit": max(1, min(int(limit), 10)),
        "addressdetails": 0,
    })
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})

    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:
            raw = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code == 429:
            raise GeocodeError(
                "The place lookup is rate limited right now. Wait a moment and "
                "try again, or enter the coordinates by hand."
            ) from e
        raise GeocodeError(f"Place lookup failed ({e.code}).") from e
    except Exception as e:
        raise GeocodeError(
            "Could not reach the place lookup service. You can still enter "
            "latitude, longitude and offset by hand."
        ) from e

    results = []
    for item in raw:
        try:
            lat = float(item["lat"])
            lon = float(item["lon"])
        except (KeyError, TypeError, ValueError):
            continue

        zone = timezone_for(lat, lon)
        tz_offset = None
        offset_is_for_birth_date = False
        if zone:
            try:
                if birth:
                    tz_offset = offset_at(zone, *birth)
                    offset_is_for_birth_date = True
                else:
                    now = datetime.now(ZoneInfo(zone))
                    tz_offset = now.utcoffset().total_seconds() / 3600
            except GeocodeError:
                pass

        results.append({
            "name": item.get("display_name", query),
            "lat": round(lat, 4),
            "lon": round(lon, 4),
            "timezone": zone,
            "tz_offset": tz_offset,
            "offset_is_for_birth_date": offset_is_for_birth_date,
        })
    return results
