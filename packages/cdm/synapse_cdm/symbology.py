"""MIL-STD-2525 standard identity, and the wire vocabularies that carry it.

The CDM's `affiliation` is four members wide (§enums.Affiliation) and the formats it must
speak are wider. This module holds the mappings in ONE place so that twelve adapters cannot
grow twelve slightly different opinions about what CoT's `a-s-` prefix means.

MIL-STD-2525D SIDC, 20 digits, positions that concern us (1-indexed as the standard numbers
them):

    1-2    version
    3      standard identity (context)          — 0 reality, 1 exercise, 2 simulation
    4      standard identity (affiliation)      — the digit this module maps
    5-6    symbol set
    7      status
    ...

Position 4 is the affiliation digit. Position 3 is the CONTEXT digit, and it matters here for
a reason the CDM already cares about: an exercise or simulated object is marked as such in its
own symbol code, so a synthetic entity should not render identically to a live one. That is
the same distinction `SourceRef.synthetic` carries, and `sidc_from_affiliation()` takes it as
an argument rather than defaulting it, for the same reason SourceRef.synthetic has no default.
"""
from __future__ import annotations

from synapse_cdm.enums import Affiliation

# 2525D position 4. The three members the CDM does not carry (PENDING 0, ASSUMED_FRIEND 2,
# SUSPECT 5) are absent on purpose: they are fusion judgements, not facts on a wire.
STANDARD_IDENTITY: dict[Affiliation, str] = {
    Affiliation.UNKNOWN: "1",
    Affiliation.FRIENDLY: "3",
    Affiliation.NEUTRAL: "4",
    Affiliation.HOSTILE: "6",
}

# 2525D position 3.
CONTEXT_REALITY = "0"
CONTEXT_EXERCISE = "1"
CONTEXT_SIMULATION = "2"

# Cursor-on-Target `type` affiliation letter (field 2 of e.g. "a-f-G-U-C") -> CDM affiliation.
#
# The lossy directions are recorded rather than smoothed over. CoT's ASSUMED_FRIEND (a),
# SUSPECT (s), JOKER (j) and FAKER (k) have no CDM member, and each collapses to the nearest
# member that does not overstate what is known: an assumed friend is not a friend, and a
# suspect is not hostile. An adapter using this table MUST also park the original letter in
# `attributes` — the collapse is recoverable only if the source value survives.
AFFILIATION_FROM_COT: dict[str, Affiliation] = {
    "f": Affiliation.FRIENDLY,
    "h": Affiliation.HOSTILE,
    "n": Affiliation.NEUTRAL,
    "u": Affiliation.UNKNOWN,
    "p": Affiliation.UNKNOWN,   # pending — not yet judged
    "a": Affiliation.UNKNOWN,   # assumed friend — an assumption, not a fact
    "s": Affiliation.UNKNOWN,   # suspect — not HOSTILE; suspicion is not identification
    "j": Affiliation.HOSTILE,   # joker: friendly acting hostile in exercise — treated hostile
    "k": Affiliation.HOSTILE,   # faker: same, and both are exercise-only
    "o": Affiliation.UNKNOWN,   # other
    "x": Affiliation.UNKNOWN,   # unspecified
}

# The reverse, for egress. Only the four the CDM can state — deriving 'a' or 's' on the way
# out would be the adapter inventing a judgement it was never given.
COT_FROM_AFFILIATION: dict[Affiliation, str] = {
    Affiliation.FRIENDLY: "f",
    Affiliation.HOSTILE: "h",
    Affiliation.NEUTRAL: "n",
    Affiliation.UNKNOWN: "u",
}


def standard_identity(affiliation: Affiliation) -> str:
    """The 2525D position-4 digit for a CDM affiliation."""
    return STANDARD_IDENTITY[Affiliation(affiliation)]


def affiliation_from_cot(cot_type: str) -> Affiliation:
    """Read the affiliation out of a CoT `type` string, e.g. 'a-f-G-U-C' -> FRIENDLY.

    An unrecognised or malformed type yields UNKNOWN rather than raising. This is the one
    place in the package where permissiveness is right: a CoT feed carrying a type the table
    does not know is still a real contact at a real position, and refusing the whole event
    would lose a track to defend a taxonomy. The original string rides in `attributes`.
    """
    parts = (cot_type or "").split("-")
    if len(parts) < 2:
        return Affiliation.UNKNOWN
    return AFFILIATION_FROM_COT.get(parts[1].lower(), Affiliation.UNKNOWN)


def sidc_from_affiliation(affiliation: Affiliation, *, synthetic: bool,
                          symbol_set: str = "00", entity_code: str = "000000",
                          status: str = "0") -> str:
    """Build a minimal, valid 20-digit 2525D SIDC from what the CDM actually knows.

    Used only when a source states an affiliation and no symbol. The result is deliberately
    generic — symbol set 00, entity code 000000 — because the CDM knows the standard identity
    and nothing else about the glyph, and a specific-looking symbol we guessed is worse than a
    generic one we can defend.

    `synthetic` is keyword-only and required: it selects the CONTEXT digit, so an exercise
    object cannot silently render as a real-world one on a commander's map.
    """
    context = CONTEXT_SIMULATION if synthetic else CONTEXT_REALITY
    # 2525D digit positions, spelled out so the count is checkable by eye rather than by
    # running it: version(2) context(1) affiliation(1) symbol_set(2) status(1)
    # hq_tf_dummy(1) amplifier(2) entity(6) modifiers(4) = 20.
    hq_tf_dummy = "0"
    amplifier = "00"
    modifiers = "0000"
    sidc = (f"10{context}{standard_identity(affiliation)}{symbol_set}{status}"
            f"{hq_tf_dummy}{amplifier}{entity_code}{modifiers}")
    if not (len(sidc) == 20 and sidc.isdigit()):  # pragma: no cover - construction invariant
        raise AssertionError(f"constructed SIDC is malformed: {sidc!r} (length {len(sidc)})")
    return sidc
