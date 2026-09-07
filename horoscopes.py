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

from datetime import date, datetime

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


def period_key(kind, when=None):
    """
    The cache key for a kind of horoscope: what changes when the period does.

    'life' is constant, so a life reading is written once and never expires.
    The rest change with the day, the ISO week, or the year.
    """
    when = when or datetime.utcnow()
    if kind == "life":
        return "life"
    if kind == "daily":
        return when.strftime("%Y-%m-%d")
    if kind == "weekly":
        # ISO week, so the key changes on Monday rather than mid-week.
        iso = when.isocalendar()
        return "%d-W%02d" % (iso[0], iso[1])
    if kind == "yearly":
        return when.strftime("%Y")
    raise ValueError("unknown horoscope kind: %r" % kind)


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
