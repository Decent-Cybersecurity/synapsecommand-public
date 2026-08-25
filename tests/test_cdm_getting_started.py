"""The documented install sequence, checked against the packaging that has to make it work.

WHY THIS EXISTS
---------------
`README.md` told a first-time reader to run two commands:

    pip install -e packages/cdm
    pytest -q

The first does not install `pytest`. `synapse_cdm`'s runtime dependencies are `pydantic` and
`jsonschema` and nothing else — deliberately, and enforced by `tests/test_cdm_boundary.py` — so
the second command exits `command not found` on the fresh clone the sequence is written for. A
`[test]` extra declaring `pytest>=8.0` had existed in `pyproject.toml` since the package was
lifted out, and no document mentioned it.

Nothing could have caught that from inside a development environment, which is the whole shape of
the defect: `pytest` is already on the maintainer's path, so the sequence "works" for the one
person who never has to run it. It is the same class as the floor gate keying its exclusions on
the name `.venv` — a check that passes because of a local accident. The repair for both is to
assert the property rather than to trust the environment.

WHAT IT CHECKS, AND WHAT IT DELIBERATELY CANNOT
-----------------------------------------------
It does **not** run `pip`. A test that installed something would need a network, would be slow,
and would fail for every outsider behind a proxy — the same objection `tests/test_cdm_publication.py`
makes to a test that would need a GitHub token. What it checks is the agreement between three
sites that must not drift:

* every `pip install` of this package in `README.md` and `CONTRIBUTING.md` names an extra;
* that extra is one `pyproject.toml` actually declares;
* the extra supplies `pytest`, because the next line of both documents runs `pytest`.

The end-to-end claim — that the sequence works on a fresh anonymous clone — was verified by
running exactly these commands in a clean environment, and re-verifying it is a protocol act like
the pin sweep, not something the suite can do for itself.
"""
import pathlib
import re
import tomllib

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
PYPROJECT = REPO / "packages" / "cdm" / "pyproject.toml"

#: The documents that tell somebody how to get the suite running. Both carry the sequence and both
#: were wrong in the same way, which is what a copied instruction does.
SITES = ("README.md", "CONTRIBUTING.md")

#: An editable install of this package, with or without an extra — the extra is CAPTURED and not
#: required by the pattern, because the defect was its ABSENCE and a pattern that demanded one
#: would simply have found no commands to check.
INSTALL = re.compile(r"""pip install -e ["']?packages/cdm(?:\[(?P<extra>[^\]]*)\])?["']?""")


def declared_extras() -> dict[str, list[str]]:
    data = tomllib.loads(PYPROJECT.read_text())
    return data.get("project", {}).get("optional-dependencies", {})


def test_every_documented_install_of_this_package_names_a_declared_extra():
    """The agreement, at every site that states the command."""
    extras = declared_extras()
    found = 0
    for rel in SITES:
        text = (REPO / rel).read_text()
        for match in INSTALL.finditer(text):
            found += 1
            extra = match.group("extra")
            assert extra, (
                f"{rel} documents `{match.group(0)}` with no extra. The next line of that block "
                "runs `pytest`, which a bare install does not provide — `synapse_cdm` depends on "
                "`pydantic` and `jsonschema` and nothing else. Use the `[test]` extra, which has "
                "been declared in pyproject.toml since the package was lifted out"
            )
            assert extra in extras, (
                f"{rel} documents the extra `[{extra}]` and pyproject.toml declares "
                f"{sorted(extras)}. `pip` fails an undeclared extra with a warning and installs "
                "the package anyway, so this reads as a working command and leaves the reader "
                "without whatever the extra was for"
            )
    assert found >= 2, (
        f"the install pattern matched {found} command(s) across {SITES}. Both documents state the "
        "sequence and a pattern that stops matching is a FAILURE, not a pass — re-anchor it "
        "deliberately if the command was rewritten"
    )


def test_the_extra_the_documents_name_is_the_one_that_supplies_pytest():
    """The reason the extra is named at all, asserted against the requirement it carries.

    Anchored on the distribution name rather than on the exact specifier, so raising the floor
    from `pytest>=8.0` is an ordinary edit and removing `pytest` is not.
    """
    extras = declared_extras()
    for rel in SITES:
        for match in INSTALL.finditer((REPO / rel).read_text()):
            extra = match.group("extra")
            requirements = extras.get(extra, [])
            assert any(re.match(r"pytest\b", req) for req in requirements), (
                f"{rel} points a reader at `[{extra}]` and that extra declares {requirements}, "
                "which does not include pytest. The command after it in the same block is "
                "`pytest -q`"
            )


def test_the_install_pattern_can_see_the_command_that_was_wrong():
    """A pattern matching nothing would report every site correct.

    Two directions: it must recognise the bare form that shipped — otherwise the assertion above
    is unfailable — and it must capture an extra when one is present.
    """
    bare = INSTALL.search("run `pip install -e packages/cdm` first")
    assert bare and bare.group("extra") is None, (
        "the pattern no longer recognises the extra-less install, which is the exact command "
        "this module exists to forbid"
    )
    quoted = INSTALL.search('pip install -e "packages/cdm[test]"')
    assert quoted and quoted.group("extra") == "test", (
        "the pattern no longer captures the extra, so every documented command would read as "
        "extra-less and the check would fail for the wrong reason"
    )
    assert "test" in declared_extras(), (
        "pyproject.toml no longer declares a `[test]` extra. Both documents send readers to it; "
        "if the extra was renamed, rename it at all three sites in the same commit"
    )
