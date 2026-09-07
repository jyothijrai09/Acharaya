"""
Lal Kitab remedies (upay), from a fixed table.

Why a table and not the model: Lal Kitab remedies are specific, traditional
and enumerable. Asked to recall them, a language model produces things that
sound like remedies — the register is easy to imitate — and some of what it
invents will be wrong. Rule 6 forbids the astrologer fabricating a placement;
inventing a remedy is the same failure with more consequence, because a
placement is only read while a remedy is acted on.

So the astrologer is handed these and told to use only these.

Scope, stated honestly: these are the PLANET-level remedies, which are widely
published and consistent between sources. Lal Kitab also carries remedies
specific to a planet in a particular house — 108 combinations — and those vary
considerably between editions. They are not here. `HOUSE_SPECIFIC_AVAILABLE`
is False, the astrologer is told so, and it should say the same rather than
improvise the gap.

Selection is grounded rather than general: remedies are offered for planets
this chart actually shows as afflicted — debilitated, combust, or in a
dusthana — not for all nine.

On safety. Every remedy here is inexpensive, harmless, and involves no
fasting, no medical instruction, and no payment to any person. Traditional
sources contain remedies that are none of those things; they are deliberately
excluded. A remedy is a supportive practice, not a treatment and not a
transaction, and CAUTION below is repeated to the astrologer verbatim.
"""

HOUSE_SPECIFIC_AVAILABLE = False

# Houses traditionally read as difficult. Used only to decide whether to
# OFFER a remedy, never to make a claim about the person.
DUSTHANAS = {6, 8, 12}

CAUTION = (
    "Remedies are a supportive practice within this tradition, not a treatment "
    "and not a transaction. They never replace a doctor, a lawyer or a "
    "financial adviser. Never present one as required, as urgent, or as "
    "something whose omission causes harm — that is how remedies are used to "
    "frighten people. Offer them as optional, and only when asked or when the "
    "chart genuinely warrants one."
)

# Each entry: the planet, what Lal Kitab associates it with, and remedies that
# are cheap, harmless and widely attested.
TABLE = {
    "Sun": {
        "signifies": "father, authority, health, standing, the bones and the eyes",
        "remedies": [
            "Offer water to the rising sun.",
            "Keep a good relationship with your father, or honour his memory.",
            "Donate wheat or jaggery.",
            "Avoid taking things freely from those in authority over you.",
        ],
    },
    "Moon": {
        "signifies": "the mind, the mother, sleep, water, emotional steadiness",
        "remedies": [
            "Serve your mother, or an elderly woman.",
            "Keep silver about you.",
            "Donate rice or milk.",
            "Keep a source of clean water in the house.",
        ],
    },
    "Mars": {
        "signifies": "energy, siblings, courage, disputes, blood and injury",
        "remedies": [
            "Feed birds, and put out sweet food.",
            "Keep good relations with your brothers.",
            "Donate sweets at a place of worship.",
            "Keep a vessel of honey in the house.",
        ],
    },
    "Mercury": {
        "signifies": "speech, learning, accounts, trade, the nervous system",
        "remedies": [
            "Feed green fodder to a cow.",
            "Donate green cloth or green vegetables.",
            "Keep a coin with a hole in it.",
            "Avoid speaking dishonestly in matters of money.",
        ],
    },
    "Jupiter": {
        "signifies": "wisdom, teachers, children, fortune, dharma",
        "remedies": [
            "Apply a saffron or turmeric mark on the forehead.",
            "Donate gram lentils or turmeric.",
            "Serve teachers and elders.",
            "Care for a tree, particularly a peepal.",
        ],
    },
    "Venus": {
        "signifies": "marriage, comfort, art, wealth, the senses",
        "remedies": [
            "Serve cows.",
            "Donate white cloth, curd, or rice.",
            "Keep the house clean and the kitchen in order.",
            "Keep good relations with your wife or partner.",
        ],
    },
    "Saturn": {
        "signifies": "labour, delay, endurance, servants, the old and the poor",
        "remedies": [
            "Feed dogs, particularly black ones.",
            "Feed crows.",
            "Donate mustard oil or iron.",
            "Treat those who work for you well, and pay them promptly.",
        ],
    },
    "Rahu": {
        "signifies": "sudden change, confusion, foreigners, obsession",
        "remedies": [
            "Let barley flow into running water.",
            "Keep silver about you.",
            "Feed dogs.",
            "Keep clear of intoxicants and of gambling.",
        ],
    },
    "Ketu": {
        "signifies": "detachment, loss, the unseen, spiritual leaning",
        "remedies": [
            "Feed dogs.",
            "Donate blankets, or a black-and-white blanket.",
            "Serve ascetics, or those who have withdrawn from the world.",
            "Keep good relations with your children.",
        ],
    },
}


def afflictions_for(planets):
    """
    Which planets this chart shows as under strain, and why.

    Grounded in what has already been computed — debilitation, combustion, and
    placement in a dusthana. Nothing here is inferred or guessed; if a planet
    is not marked, no reason is offered for it.
    """
    found = []
    for name, p in (planets or {}).items():
        reasons = []
        if p.get("dignity") == "debilitated":
            reasons.append("debilitated in " + p.get("sign", "its sign"))
        if p.get("combust"):
            reasons.append("combust, %s° from the Sun" % p.get("sun_distance"))
        if p.get("house") in DUSTHANAS:
            reasons.append("in the %dth house" % p["house"])
        if reasons:
            found.append({"planet": name, "reasons": reasons,
                          "house": p.get("house"), "sign": p.get("sign")})
    return found


def build(planets):
    """
    The remedy block for a chart: which planets are strained, the remedies
    Lal Kitab gives for those planets, and the caution that goes with them.

    Returns None when nothing in the chart warrants a remedy — an empty
    section is better than one invented to fill the space.
    """
    strained = afflictions_for(planets)
    if not strained:
        return None

    return {
        "caution": CAUTION,
        "house_specific_available": HOUSE_SPECIFIC_AVAILABLE,
        "planets": [
            {
                "planet": item["planet"],
                "why": item["reasons"],
                "house": item["house"],
                "sign": item["sign"],
                "signifies": TABLE[item["planet"]]["signifies"],
                "remedies": TABLE[item["planet"]]["remedies"],
            }
            for item in strained if item["planet"] in TABLE
        ],
    }


def to_prompt_lines(block):
    """Render the remedy block for the astrologer's context."""
    if not block:
        return []

    lines = ["\n-- Lal Kitab remedies (upay) for the strained planets in this chart --"]
    lines.append(
        "USE ONLY THE REMEDIES LISTED HERE. Do not recall others, do not adapt "
        "them, and do not invent one for a planet that is not listed. If a "
        "querent asks for a remedy that is not here, say it is not in the data "
        "you were given."
    )
    if not block["house_specific_available"]:
        lines.append(
            "Only planet-level remedies are available. Lal Kitab also has "
            "remedies for a planet in a particular house; those are NOT "
            "provided, so say so if asked rather than improvising."
        )
    lines.append("CAUTION: " + block["caution"])

    for p in block["planets"]:
        lines.append(
            f"\n{p['planet']} — {', '.join(p['why'])}. "
            f"Lal Kitab reads it for: {p['signifies']}."
        )
        for r in p["remedies"]:
            lines.append(f"  - {r}")
    return lines
