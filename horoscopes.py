"""
Daily, weekly, yearly and life horoscopes — written once, then read for free.

The whole design turns on one idea: a horoscope covers a PERIOD, so it only
needs writing once for that period. A life reading never changes and is written
once and kept; a yearly one is rewritten when the year turns; a weekly one when
the week does; a daily one the next day. Opening a tab reads what is stored and
costs nothing.

Without that, four tabs would mean four readings every time someone looked,
which is four times the cost for no more information.

`period_key()` is what makes it work — it is the cache key, and it changes
exactly when the period does.
"""

from datetime import date, datetime, timedelta

KINDS = ("daily", "weekly", "yearly", "life")

SCOPES = {
    "daily": {
        "label": "Today",
        "period": "the next twenty-four hours",
        "guidance": (
            "Write about TODAY only. Lead with the transits and the running "
            "antardasha, since nothing else moves fast enough to matter over a "
            "day. Keep it short — four or five short sections, not the full "
            "structure. Do not restate the natal chart at length; the querent "
            "has read it. Where the day is unremarkable, say so plainly rather "
            "than manufacturing significance."
        ),
    },
    "weekly": {
        "label": "This week",
        "period": "the coming seven days",
        "guidance": (
            "Write about THE WEEK AHEAD. The Moon crosses several signs in a "
            "week, so day-to-day texture belongs here; the slow movers set the "
            "background. Name the days that differ from the rest and say why. "
            "Keep it to a readable length rather than the full structure."
        ),
    },
    "yearly": {
        "label": "This year",
        "period": "the year ahead",
        "guidance": (
            "Write about THE YEAR AHEAD. The dasha and antardasha changes are "
            "the spine — give their dates. Saturn and Jupiter's movement "
            "matters; the Moon does not, at this scale. Where an antardasha "
            "changes mid-year, say what shifts and when. The full structure is "
            "appropriate here."
        ),
    },
    "life": {
        "label": "Life reading",
        "period": "the whole life",
        "guidance": (
            "Write about THE WHOLE LIFE, not a period. This is the natal chart "
            "read as a shape: the lagna and its lord, the Moon, the strongest "
            "and weakest planets, the yogas actually formed, what the D9 says "
            "about whether the promises hold, and how the mahadasha sequence "
            "lays the life out in chapters — give their dates.\n\n"
            "Do not anchor this to today's transits. They are the wrong "
            "timescale and will be wrong within a week; this reading is written "
            "once and kept.\n\n"
            "This is the longest and most careful of the four. Take the full "
            "structure. Rule 21 matters especially here — a life reading is "
            "read more than once, and it must not become something the querent "
            "measures themselves against."
        ),
    },
}


def period_key(kind, when=None, tz_offset=0.0):
    """
    The cache key for a kind of horoscope: what changes when the period does.

    'life' is constant, so a life reading is written once and never expires.
    The rest change with the day, the ISO week, or the year.

    tz_offset is hours east of UTC, and it matters more than it looks. Keyed
    on UTC, someone at UTC-4 crosses into tomorrow's key at 8pm their time:
    every evening they would be charged for a second daily reading, and on
    New Year's Eve they would buy next year's horoscope three hours early.
    A day is the querent's day.
    """
    when = when or datetime.utcnow()
    if kind == "life":
        return "life"

    local = when + timedelta(hours=tz_offset or 0.0)
    if kind == "daily":
        return local.strftime("%Y-%m-%d")
    if kind == "weekly":
        # ISO week, so the key changes on Monday rather than mid-week.
        iso = local.isocalendar()
        return "%d-W%02d" % (iso[0], iso[1])
    if kind == "yearly":
        return local.strftime("%Y")
    raise ValueError("unknown horoscope kind: %r" % kind)


def expires_at(kind, tz_offset=0.0, when=None):
    """When the current period ends, as a UTC datetime, or None for life.

    Reported to the interface so it can say how long a cached horoscope
    stays free instead of leaving that a guess.
    """
    if kind == "life":
        return None
    when = when or datetime.utcnow()
    local = when + timedelta(hours=tz_offset or 0.0)

    if kind == "daily":
        end = datetime(local.year, local.month, local.day) + timedelta(days=1)
    elif kind == "weekly":
        start = datetime(local.year, local.month, local.day) - timedelta(
            days=local.weekday())
        end = start + timedelta(days=7)
    else:   # yearly
        end = datetime(local.year + 1, 1, 1)

    return end - timedelta(hours=tz_offset or 0.0)


def is_current(kind, key, tz_offset=0.0, when=None):
    """Whether a stored horoscope still covers the period we are in.

    The lookup is already keyed on the period, so a hit is by definition
    current. This exists so the answer can be stated rather than assumed -
    and so a row written under the old UTC keying can be recognised as
    belonging to a different period than the one it claims.
    """
    return key == period_key(kind, when, tz_offset)


def build_question(kind):
    """The question put to the astrologer for this kind of horoscope."""
    scope = SCOPES[kind]
    return (
        f"Write a reading covering {scope['period']}.\n\n"
        f"{scope['guidance']}\n\n"
        "Everything you say must still come from the computed chart data "
        "provided. Do not invent a placement, a date or a transit to fill the "
        "shape of a horoscope."
    )


def describe(kind, key):
    """A human label for a cached horoscope, for the interface."""
    scope = SCOPES[kind]
    if kind == "life":
        return scope["label"]
    if kind == "daily":
        try:
            return date.fromisoformat(key).strftime("%A %d %B %Y")
        except ValueError:
            return key
    if kind == "weekly":
        return "Week " + key.split("-W")[-1] + ", " + key.split("-")[0]
    return key
