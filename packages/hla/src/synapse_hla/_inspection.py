"""What `synapse-hla inspect` says about a capture besides its verification (OPS-26), gathered
line by line from the verified reader (round R6).

`Inspection.add` takes each line the reader verified, in order, and keeps only counts and a few
boundaries, so inspecting a capture takes memory for one line plus the counts whatever its
length. `result()` gives: the profile, declaration, mode and session of the recorded
configuration; the SHA-256 and length of the verified bytes (the whole file for a COMPLETE or
FAILED capture, the verified prefix otherwise); the frames; one span per generation (its frames,
first and last elapsed_ns, and the generation_end reason, or null when the verified prefix ends
inside it); the generation-0 frames between generations; the events by type; the reported classes
of the discoveries; the captured diagnostics by code; the time coverage (the time policy, and
under external_elapsed the epoch and the effective times of the first generation_start and the
last frame, epoch plus elapsed_ns integer-divided by 1000, CR-L05); and the footer.

Nothing here reads a file, a clock or the environment (D-08): the caller drives the reader.
Untrusted strings from the capture (reported class names) are counted as they are; whoever
prints them escapes them (R40).
"""

from __future__ import annotations

import hashlib

from synapse_hla import _utc, capture, config

_NANOSECONDS_PER_MICROSECOND = 1000


class Inspection:
    """The counts of one capture's verified lines; see the module text."""

    def __init__(self) -> None:
        self._digest = hashlib.sha256()
        self._bytes = 0
        self._header: dict | None = None
        self._frames = 0
        self._generations: dict[int, dict] = {}
        self._between = 0
        self._events = dict.fromkeys(capture.EVENT_TYPES, 0)
        self._classes: dict[str, int] = {}
        self._diagnostics: dict[str, int] = {}
        self._first_elapsed: str | None = None
        self._last_elapsed: str | None = None
        self._footer: dict | None = None

    def add(self, line: capture.VerifiedLine) -> None:
        self._digest.update(line.raw + b"\n")
        self._bytes += len(line.raw) + 1
        record = line.record
        if line.number == 1:
            self._header = record
            return
        if record["type"] == capture.FOOTER:
            self._footer = dict(record)
            return
        self._frames += 1
        event = record["event"]
        kind = event["type"]
        self._events[kind] += 1
        elapsed = record["elapsed_ns"]
        generation = record["generation"]
        if generation == 0:
            self._between += 1
        else:
            span = self._generations.setdefault(generation, {
                "generation": generation, "frames": 0, "first_elapsed_ns": elapsed,
                "last_elapsed_ns": elapsed, "end_reason": None})
            span["frames"] += 1
            span["last_elapsed_ns"] = elapsed
            if kind == capture.GENERATION_END:
                span["end_reason"] = event["reason"]
        if kind == capture.GENERATION_START and self._first_elapsed is None:
            self._first_elapsed = elapsed
        if self._first_elapsed is not None:
            self._last_elapsed = elapsed
        if kind == capture.DISCOVER:
            name = event["reported_class"]
            self._classes[name] = self._classes.get(name, 0) + 1
        elif kind == capture.DIAGNOSTIC:
            code = event["diagnostic"]["code"]
            self._diagnostics[code] = self._diagnostics.get(code, 0) + 1

    def result(self) -> dict | None:
        """The inspection, or None when not even the header verified."""
        header = self._header
        if header is None:
            return None
        session = header["config"]
        policy = session["time_policy"]
        epoch = config.epoch_microsecond(session)
        coverage = {"policy": policy["mode"],
                    "epoch": None if epoch is None else policy["epoch"],
                    "first_elapsed_ns": self._first_elapsed,
                    "last_elapsed_ns": self._last_elapsed,
                    "first_effective_at": self._effective(epoch, self._first_elapsed),
                    "last_effective_at": self._effective(epoch, self._last_elapsed)}
        return {
            "profile": header["profile"],
            "profile_declaration": session["profile_declaration"],
            "mode": session["mode"],
            "session_id": session["session_id"],
            "capture_sha256": self._digest.hexdigest(),
            "verified_bytes": self._bytes,
            "frames": self._frames,
            "generations": [dict(self._generations[g]) for g in sorted(self._generations)],
            "between_generations": self._between,
            "events": dict(self._events),
            "reported_classes": {name: self._classes[name] for name in sorted(self._classes)},
            "diagnostics": {code: self._diagnostics[code] for code in sorted(self._diagnostics)},
            "time_coverage": coverage,
            "footer": self._footer,
        }

    @staticmethod
    def _effective(epoch: int | None, elapsed: str | None) -> str | None:
        if epoch is None or elapsed is None:
            return None
        # A verified capture never passes year 9998 here (the reader refuses that, SPEC:289).
        return _utc.format_microsecond(epoch + int(elapsed) // _NANOSECONDS_PER_MICROSECOND)
