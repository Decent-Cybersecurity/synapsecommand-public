"""Fingerprints of the literals the pinned TacticalAPI contract holds only inside its comments, and
a check that none of the `tacticalapi` adapter's files repeats the comments' prose. A build-time
tool; nothing in the package imports it.

    python gates/tacticalapi_contract_comments.py > tests/tacticalapi_comment_digests.json
    python gates/tacticalapi_contract_comments.py --check-prose     # run by hand, never by CI

`tests/test_cdm_tacticalapi_contract_text.py` hashes every literal of every file `ARC_FILES` names
the same way and fails on a match, so a value copied out of a comment (an example identifier, a
reference, an address) is found in any of them, without the pinned files at hand. Moved here from
the adapter's out-of-tree project on 2026-10-06, when the adapter landed; there both checks read
every file of the project, and here they read the adapter's own files (`ARC_FILES`) and never
the whole repository, whose other files were never compared with the contract's comments and
are not this tool's to judge.

WHY DIGESTS AND NOT THE TEXT
----------------------------
No text copied from an interface definition file enters the repository (the rulings of
`docs/tacticalapi-implementation.md`, the record). A gate that compares the adapter's files with
the contract's comments needs either the comments, which may not be held here, or the pinned
files, which CI does not have (the record's §7) and which the descriptor test alone is allowed to
need. A SHA-256 of each literal is neither: it identifies the
literal and cannot be read back into it. The file records the upstream commit the digests were
taken from, and a test holds that commit to the one the codec's field table was generated from,
so a new pin cannot leave the digests behind unnoticed.

WHAT COUNTS AS A COMMENT-ONLY LITERAL
-------------------------------------
1. Each pinned file is split into comments (`//` to the end of the line, `/* ... */`) and code.
   A quoted string belongs to the code, so a `//` inside one does not start a comment, and a
   block comment counts as a space, as protoc's tokenizer counts it.
2. A literal is a run of letters, digits and underscores, or several such runs joined by single
   `-`, `.`, `:` or `/` characters. Literals are compared case-folded.
3. A literal is fingerprinted when it occurs in the comments of some pinned file and in the code
   of none (the contract's names and numbers are the adapter's to use), is at least MIN_LENGTH
   characters long and holds a digit. Shorter or digit-free literals are words, numbers and short
   designations that any text on the same subject may contain on its own; a longer one with a
   digit is an identifier, a version, a reference or an address.
4. A file's literal is matched whole and by every run of its joined parts (`runs`), so a
   fingerprinted value is found inside a longer literal too: as the adapter writes an external
   id (`<member>:<value>`), behind a URN prefix, as a file name, in a URL's path. A literal of
   the code counts with every run of its parts, so a comment literal that is a part of one of
   the contract's names is not fingerprinted and a name taken from the code is never a hit
   (both added 2026-10-04, final verification, licence-11; until then whole literals only).
5. Besides each comment-only literal, every distinctive run of its parts that is not a run of a
   code literal is fingerprinted (`fingerprinted`), so a shortened copy is found as well as a
   longer one: the path of a reference URL without its host, the first groups of an example
   identifier (added 2026-10-04, final verification, N7).

PROSE (`--check-prose`)
-----------------------
Fingerprints of literals do not cover copied prose. That check needs the comments themselves, so
it runs only where the pinned files are (by hand, with `SYNAPSE_CDM_TACTICALAPI_PROTO_DIR` set)
and stores nothing: it reads the comment text of the ten files at run time and fails when any
file `ARC_FILES` names shares a run of WINDOW (six) consecutive words with the comments of one of
them. A word is a run of letters and digits, case-folded; every other character, the underscore
included, separates words, so punctuation, case and line breaks do not hide a copied sentence.
Six words, because a shorter run is too often a common phrase of the subject (on 2026-10-04 the
out-of-tree project shared no six-word run and one coincidental five-word run). It prints the
file and line of each hit, never the words.

The pinned files are located and verified exactly as `gates/tacticalapi_field_table.py` does (all
ten SHA-256 hashes against `proto_pin.json`); protoc is not needed, since comments are not part of
the descriptor protoc prints.

HASHES GO THROUGH `synapse_cdm.evidence`
----------------------------------------
None of the adapter's files imports `hashlib`, which the package keeps to
`synapse_cdm/evidence.py`. A fingerprint is `evidence.digest` of the literal's octets, handed over
as an object whose only method is `read_bytes()`, which is all `digest` reads of its argument
(the fixture builder hashes its in-memory files the same way). The digest is the SHA-256 hex
`hashlib` would give, so the stored fingerprints are unchanged by the route.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import sys
from collections.abc import Iterable

ROOT = pathlib.Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    # Run as `python gates/tacticalapi_contract_comments.py`, the script's own directory is on the
    # path and the repository root is not; `gates.tacticalapi_field_table` is imported by its
    # package name either way.
    sys.path.insert(0, str(ROOT))

from synapse_cdm import evidence, normative_binding  # noqa: E402

from gates import tacticalapi_field_table as gen_field_table  # noqa: E402

#: The digests file the contract-text test reads, relative to the repository root.
DIGESTS = "tests/tacticalapi_comment_digests.json"

#: The adapter's own files, relative to the repository root, as glob patterns: the files the
#: prose check and the contract-text test's literal scan read (2026-10-06, the landing). A
#: pattern ending `/**/*` takes every file under its directory. The files the landing changed
#: elsewhere in the repository are read by the same two checks, fed the changed paths, at each
#: exit of the round that changes them, never by a walk of the whole tree.
ARC_FILES = (
    "packages/cdm/synapse_cdm/adapters/tacticalapi.py",
    "packages/cdm/synapse_cdm/adapters/tacticalapi_codec.py",
    "packages/cdm/synapse_cdm/fixtures/tacticalapi/**/*",
    "gates/protoc_text.py",
    "gates/tacticalapi_*.py",
    "tests/tacticalapi_*",
    "tests/test_cdm_tacticalapi_*.py",
    "docs/tacticalapi-implementation.md",
    "docs/docs/cdm/tacticalapi.mdx",
    "NOTICE",
    "packages/cdm/NOTICE",
)

LITERAL = re.compile(r"[A-Za-z0-9_]+(?:[-.:/][A-Za-z0-9_]+)*")
MIN_LENGTH = 8
_DIGIT = re.compile(r"[0-9]")
#: The characters that join the parts of a literal, kept as written when `runs` splits it.
_JOINER = re.compile(r"([-.:/])")
#: A word of prose: a run of letters and digits (the underscore separates words).
WORD = re.compile(r"[^\W_]+")
#: The length of the word run `--check-prose` refuses to find in a file of the adapter.
WINDOW = 6
#: The caches a run of the tests or the tools may leave beside the files. No scan reads them
#: (2026-10-04, final verification, licence-12).
CACHE_DIRECTORIES = ("__pycache__", ".pytest_cache")
CACHE_SUFFIX = ".pyc"


class UnreadableSource(ValueError):
    """A pinned file whose comments and strings cannot be told apart (an unterminated string or
    block comment). The tool stops rather than fingerprint a guess."""


def split(source: str) -> tuple[str, str]:
    """`(code, comments)` of one interface definition file. Comment text is joined by newlines; a
    block comment leaves a space in the code so the literals either side stay apart."""
    code: list[str] = []
    comments: list[str] = []
    at, size = 0, len(source)
    while at < size:
        if source.startswith("//", at):
            end = source.find("\n", at)
            end = size if end < 0 else end
            comments.append(source[at + 2:end])
            at = end
        elif source.startswith("/*", at):
            end = source.find("*/", at + 2)
            if end < 0:
                raise UnreadableSource(f"block comment opened at offset {at} is not closed")
            comments.append(source[at + 2:end])
            code.append(" ")
            at = end + 2
        elif source[at] in "\"'":
            end = at + 1
            while end < size and source[end] != source[at]:
                if source[end] == "\n":
                    break
                end += 2 if source[end] == "\\" else 1
            if end >= size or source[end] != source[at]:
                raise UnreadableSource(f"string opened at offset {at} is not closed on its line")
            code.append(source[at:end + 1])
            at = end + 1
        else:
            code.append(source[at])
            at += 1
    return "".join(code), "\n".join(comments)


def literals(text: str) -> set[str]:
    """Every literal of `text`, case-folded."""
    return {found.casefold() for found in LITERAL.findall(text)}


def distinctive(literal: str) -> bool:
    return len(literal) >= MIN_LENGTH and _DIGIT.search(literal) is not None


def runs(literal: str) -> set[str]:
    """The literal and every run of its consecutive parts, joined as written: `a-b:c` gives
    `a-b:c`, `a-b`, `b:c`, `a`, `b` and `c`. A run starts and ends at a joiner, so `EX-0001`
    is not a run of `EX-00011`."""
    pieces = _JOINER.split(literal)
    parts, joiners = pieces[0::2], pieces[1::2]
    found: set[str] = set()
    for first in range(len(parts)):
        text = parts[first]
        found.add(text)
        for last in range(first + 1, len(parts)):
            text += joiners[last - 1] + parts[last]
            found.add(text)
    return found


def _code_runs_and_comment_literals(sources: Iterable[str]) -> tuple[set[str], set[str]]:
    """Every run of every code literal's parts (`runs`), and every literal of the comments."""
    in_code: set[str] = set()
    in_comments: set[str] = set()
    for source in sources:
        code, comments = split(source)
        for literal in literals(code):
            in_code |= runs(literal)
        in_comments |= literals(comments)
    return in_code, in_comments


def comment_only(sources: Iterable[str]) -> set[str]:
    """The distinctive literals that occur in some source's comments and in no source's code,
    whole or as a run of a code literal's parts."""
    in_code, in_comments = _code_runs_and_comment_literals(sources)
    return {literal for literal in in_comments - in_code if distinctive(literal)}


def fingerprinted(sources: Iterable[str]) -> set[str]:
    """What the digests file fingerprints: each comment-only literal (`comment_only`) and every
    distinctive run of its parts that is not a run of a code literal. A shortened copy of a
    comment literal — a URL's path without its host, the first groups of an example identifier
    — is then found, as a longer literal holding one already is (added 2026-10-04, final
    verification). A run that is a part of one of the contract's names stays out, so a name the
    adapter takes from the code is never a hit."""
    sources = list(sources)
    in_code, _ = _code_runs_and_comment_literals(sources)
    found: set[str] = set()
    for literal in comment_only(sources):
        found |= {run for run in runs(literal) if run not in in_code and distinctive(run)}
    return found


class _Octets:
    """Octets in memory, offered to `synapse_cdm.evidence.digest`, which reads its argument with
    `read_bytes()` and nothing else. A literal has no file to give it."""

    def __init__(self, octets: bytes) -> None:
        self._octets = octets

    def read_bytes(self) -> bytes:
        return self._octets


def fingerprint(literal: str) -> str:
    """SHA-256 of the case-folded literal's UTF-8 octets, as lowercase hex, taken through
    `synapse_cdm.evidence.digest`."""
    sha256, _ = evidence.digest(_Octets(literal.casefold().encode("utf-8")))
    return sha256


def matches(octets: bytes, digests: Iterable[str]) -> list[str]:
    """The distinctive literals, and runs of literals (`runs`), of a file's octets whose
    fingerprint is among `digests`, sorted. Octets that are not UTF-8 read as a replacement
    character, which no literal holds."""
    wanted = set(digests)
    candidates: set[str] = set()
    for literal in literals(octets.decode("utf-8", "replace")):
        candidates |= runs(literal)
    return sorted(run for run in candidates if distinctive(run) and fingerprint(run) in wanted)


def arc_files(root: pathlib.Path) -> list[pathlib.Path]:
    """Every file under `root` that `ARC_FILES` names, sorted, less the caches
    (`CACHE_DIRECTORIES`, `.pyc` files): the files the contract-text test's literal scan and the
    prose check read. Re-scoped on 2026-10-06 from every file under the project root."""
    found = {path for pattern in ARC_FILES for path in root.glob(pattern)}
    return sorted(path for path in found
                  if path.is_file() and path.suffix != CACHE_SUFFIX
                  and not set(path.relative_to(root).parts) & set(CACHE_DIRECTORIES))


def _words(text: str) -> list[tuple[str, int]]:
    """Each word of `text`, case-folded, with the 1-based line it is on."""
    found: list[tuple[str, int]] = []
    line, seen = 1, 0
    for match in WORD.finditer(text):
        line += text.count("\n", seen, match.start())
        seen = match.start()
        found.append((match.group().casefold(), line))
    return found


def comment_windows(sources: Iterable[str]) -> set[tuple[str, ...]]:
    """Every run of WINDOW consecutive words of each source's comment text."""
    windows: set[tuple[str, ...]] = set()
    for source in sources:
        words = [word for word, _ in _words(split(source)[1])]
        windows |= {tuple(words[at:at + WINDOW]) for at in range(len(words) - WINDOW + 1)}
    return windows


def shared_windows(octets: bytes, windows: set[tuple[str, ...]]) -> list[int]:
    """The lines, sorted, on which a run of WINDOW words of the file's text that is also a run of
    comment words begins. Octets that are not UTF-8 read as a replacement character, which
    separates words."""
    words = _words(octets.decode("utf-8", "replace"))
    return sorted({words[at][1] for at in range(len(words) - WINDOW + 1)
                   if tuple(word for word, _ in words[at:at + WINDOW]) in windows})


def pinned_sources(environ=None) -> tuple[str, list[str]]:
    """(upstream commit, the text of the ten pinned files), verified against the pin. Raises
    `NormativeBindingBlocked` when the pin does not verify."""
    resource = gen_field_table.resolve_pin(environ)
    sources = [(resource.directory / name).read_text(encoding="utf-8")
               for name in gen_field_table.PINNED_FILES]
    return gen_field_table.pin_commit(resource.record), sources


def check_prose(root: pathlib.Path, environ=None) -> list[str]:
    """One line per file of `arc_files(root)` and line where a run of WINDOW words of the pinned
    files' comments recurs; empty when none does."""
    _, sources = pinned_sources(environ)
    windows = comment_windows(sources)
    return [f"{path.relative_to(root).as_posix()}:{line}"
            for path in arc_files(root)
            for line in shared_windows(path.read_bytes(), windows)]


def render(commit: str, found: Iterable[str]) -> str:
    """The digests file: the upstream commit and the sorted fingerprints, nothing else."""
    record = {"commit": commit, "sha256": sorted({fingerprint(literal) for literal in found})}
    return json.dumps(record, indent=2) + "\n"


def generate(environ=None) -> str:
    """The digests file for the pin `environ` (default `os.environ`) names. Raises
    `NormativeBindingBlocked` when the pin does not verify; that is BLOCKED_EXTERNAL_EVIDENCE,
    never a file."""
    commit, sources = pinned_sources(environ)
    return render(commit, fingerprinted(sources))


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    if argv not in ([], ["--check-prose"]):
        print("usage: tacticalapi_contract_comments.py [--check-prose]", file=sys.stderr)
        return 2
    try:
        if argv:
            hits = check_prose(ROOT, os.environ)
        else:
            text = generate(os.environ)
    except normative_binding.NormativeBindingBlocked as blocked:
        print(f"{normative_binding.BLOCKED_STATUS}: {blocked}", file=sys.stderr)
        return 3
    if not argv:
        sys.stdout.write(text)
        return 0
    for hit in hits:
        print(f"{hit}: a run of {WINDOW} words here is also a run of the pinned files' comments")
    if hits:
        return 1
    print(f"prose: {len(arc_files(ROOT))} files of the adapter share no run of {WINDOW} words "
          "with the pinned files' comments")
    return 0


if __name__ == "__main__":
    sys.exit(main())
