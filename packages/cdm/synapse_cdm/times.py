"""Time in the CDM: one format, one zone, one injectable clock.

FORMAT
------
RFC 3339 / ISO 8601, UTC, three decimal places, always `Z` — byte-identical to the pattern
the Track contract already pins:

    ^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\\.[0-9]{3}Z$

Fixed millisecond precision is not fussiness. Two timestamps that mean the same instant must
compare equal as STRINGS, because they are compared as strings in golden-output diffs, in
ledger hashes and in every log line an auditor greps. `...:44Z`, `...:44.0Z` and
`...:44.000000Z` are the same instant and three different strings, and a chain hash over the
second form does not match a chain hash over the third.

Timestamps are stored on the models as `datetime` and serialised through this module's
formatter, so a model built in Python and a model parsed from JSON produce the same bytes.

THE INJECTABLE CLOCK
--------------------
`received_at` is the one field an adapter cannot read from its input — it is the moment WE
took delivery. A `datetime.now()` inside an adapter would make golden-output tests impossible
(every run differs) and would make the adapter untestable at the exact moment its correctness
matters. So the clock is a constructor argument on `Adapter`, defaulting to real UTC now, and
the harness injects a frozen one. The adapter code itself never learns which it got.
"""
from __future__ import annotations

import datetime as _dt
import re
from typing import Callable

Clock = Callable[[], _dt.datetime]

TIMESTAMP_RE = re.compile(r"^[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}\.[0-9]{3}Z$")

# The frozen instant the harness uses by default. A real date, in the scenario's own window,
# so a golden file reads like something that happened rather than like 1970.
FROZEN_NOW = _dt.datetime(2026, 4, 29, 6, 15, 0, tzinfo=_dt.timezone.utc)


def utc_now() -> _dt.datetime:
    return _dt.datetime.now(tz=_dt.timezone.utc)


def frozen_clock(at: _dt.datetime = FROZEN_NOW) -> Clock:
    return lambda: at


def parse(value: str | _dt.datetime) -> _dt.datetime:
    """Accept what sources actually send; return an aware UTC datetime.

    Sources are not disciplined about this. `Z`, `+00:00`, `+02:00` and a naive local string
    all arrive in practice. A naive string is the dangerous one: it is assumed UTC here and
    that assumption is DECLARED rather than silent, because the alternative — inferring the
    host's timezone — makes the same payload parse differently on a laptop and in the enclave.
    """
    if isinstance(value, _dt.datetime):
        stamp = value
    else:
        text = value.strip()
        if text.endswith(("Z", "z")):
            text = text[:-1] + "+00:00"
        stamp = _dt.datetime.fromisoformat(text)
    if stamp.tzinfo is None:
        stamp = stamp.replace(tzinfo=_dt.timezone.utc)
    return stamp.astimezone(_dt.timezone.utc)


def parse_wire(value: str | _dt.datetime) -> _dt.datetime:
    """What a model accepts as a timestamp ON THE WIRE: the one serialised form, or a datetime.

    `parse()` above is the adapter's parser and takes what sources send. This is the JSON
    path's, since 2026-09-19 (audit F04) — `models.Timestamp` routes `model_validate_json`
    here and everything else to `parse()` — and it takes only what `render()` writes: a string
    must match `TIMESTAMP_RE` in full, the same pattern the published JSON Schema carries, so a
    document the schema refuses is not a document the Python JSON path accepts. Before this the
    JSON path took "2026-04-29T06:12:44Z", "+02:00" and a naive string through `parse()`, and
    the same bytes failed the schema's `pattern`: two validators, two languages. A `datetime`
    object is accepted and normalised to UTC, because that is Python-object coercion, not the
    wire contract.
    """
    if isinstance(value, _dt.datetime):
        return parse(value)
    if isinstance(value, str) and TIMESTAMP_RE.fullmatch(value) is not None:
        return parse(value)
    raise ValueError(
        f"a timestamp on the wire is RFC 3339 UTC with exactly three decimal places and Z, "
        f"e.g. 2026-04-29T06:12:44.000Z; got {value!r}. A source's own form is parsed with "
        "times.parse() at the adapter, and the model receives the datetime"
    )


def render(stamp: _dt.datetime) -> str:
    """The one serialised form. Truncates, never rounds.

    Rounding 23:59:59.9995 forward produces 00:00:00.000 on the NEXT DAY, which is how a
    single event lands in the wrong day's audit slice. Truncation keeps the instant inside
    the second it was measured in.
    """
    stamp = parse(stamp)
    return f"{stamp.strftime('%Y-%m-%dT%H:%M:%S')}.{stamp.microsecond // 1000:03d}Z"
