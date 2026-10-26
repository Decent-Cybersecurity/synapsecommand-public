"""The fixed limits of profile SC-HLA-RPR2-OBS-1, version 1, in one frozen object.

WHY ONE OBJECT AND NO KNOBS
---------------------------
The table at SPEC:217-231 calls these values "fixed v1", and the profile's evidence argument
depends on that word: a capture that stopped with E_LIMIT is complete evidence only if the limit
it hit is the one every other session of the profile would have hit. So the numbers live here
once, as `V1`, and nowhere else in the package defines a limit number (a test holds that). No
configuration key, environment variable or command-line option reaches them. Three of them
cannot be reached through valid input at their real values (OPS-21), so the components that
enforce them take a `Limits` as a keyword-only seam that only tests replace; the host's seam
object (OPS-21's `HostSeams`) carries one.

Units are in the field names. "MiB" and "GiB" in the table are binary multiples, and "KiB" in
R07 is too: 16 MiB is 16 * 1024 * 1024 bytes. A byte limit on a name counts UTF-8 bytes, not
characters (SPEC:289).

The first sixteen fields are the table row by row (the queue and dependency-XML rows each hold
two numbers). The rest are bounds that other paragraphs fix and that would otherwise be written
as bare numbers at their point of use: the configuration file size of R07, the capture reserve
of SPEC:293, the diagnostic message bound of R37, the two RSS ceilings of R41, and the exception
message bounds of lead ruling CR-L01.
"""

from __future__ import annotations

from dataclasses import dataclass

_KIB = 1024
_MIB = 1024 * _KIB
_GIB = 1024 * _MIB


@dataclass(frozen=True)
class Limits:
    """Every fixed v1 limit. Construct only `V1`, or a test's variant of it via `replace`."""

    # --- the table at SPEC:217-231, in its order ---
    #: Active objects including incomplete and quarantined, per generation.
    active_objects_per_generation: int
    #: Total distinct object tokens per session (distinct (generation, token) pairs, RED-12).
    object_tokens_per_session: int
    #: Supplied attributes per reflection.
    attributes_per_reflection: int
    #: One attribute value, checked before copying.
    attribute_value_bytes: int
    #: User tag.
    user_tag_bytes: int
    #: Object name, UTF-8 bytes.
    object_name_utf8_bytes: int
    #: Reported class name, UTF-8 bytes.
    class_name_utf8_bytes: int
    #: Encoded logical time.
    logical_time_bytes: int
    #: One worker frame or capture line, excluding its LF.
    line_bytes: int
    #: Worker callback queue: frames, and bytes; whichever fills first.
    queue_frames: int
    queue_bytes: int
    #: Cached raw attribute bytes per generation.
    cached_attribute_bytes_per_generation: int
    #: Capture file, inclusive.
    capture_file_bytes: int
    #: Input records per session.
    frames_per_session: int
    #: Dependency XML: bytes per file, and element depth. No external references is a rule, not
    #: a number, and lives with the parser.
    dependency_xml_bytes: int
    dependency_xml_depth: int

    # --- bounds fixed by other paragraphs ---
    #: R07: a configuration file larger than 64 KiB is refused.
    config_file_bytes: int
    #: SPEC:293: the part of the capture budget kept for a terminal diagnostic, generation_end
    #: and footer.
    capture_reserve_bytes: int
    #: R37: a diagnostic message, UTF-8 bytes.
    diagnostic_message_utf8_bytes: int
    #: R41: the external RSS supervisor's ceilings for the worker and for the host.
    worker_rss_bytes: int
    host_rss_bytes: int
    #: CR-L01: an exception message, characters, and the most input it may quote.
    error_message_chars: int
    error_message_input_chars: int

    def __post_init__(self) -> None:
        # A test variant built with `dataclasses.replace` goes through here too, so a limit of
        # zero, a negative one, a float or a bool (an int subclass) is refused at construction
        # rather than discovered as an off-by-one in whatever enforces it.
        for name, value in vars(self).items():
            if type(value) is not int or value < 1:
                raise ValueError(f"limit {name} must be a positive int")


#: The values of profile SC-HLA-RPR2-OBS-1, version 1.
V1 = Limits(
    active_objects_per_generation=10_000,
    object_tokens_per_session=100_000,
    attributes_per_reflection=4,
    attribute_value_bytes=4096,
    user_tag_bytes=4096,
    object_name_utf8_bytes=1024,
    class_name_utf8_bytes=1024,
    logical_time_bytes=256,
    line_bytes=65_536,
    queue_frames=4096,
    queue_bytes=16 * _MIB,
    cached_attribute_bytes_per_generation=32 * _MIB,
    capture_file_bytes=1 * _GIB,
    frames_per_session=10_000_000,
    dependency_xml_bytes=2 * _MIB,
    dependency_xml_depth=64,
    config_file_bytes=64 * _KIB,
    capture_reserve_bytes=65_536,
    diagnostic_message_utf8_bytes=1024,
    worker_rss_bytes=512 * _MIB,
    host_rss_bytes=512 * _MIB,
    error_message_chars=256,
    error_message_input_chars=64,
)
