"""How the three test modules that load a fixture generator load it, and why not the obvious way.

WHAT WENT WRONG, MEASURED RATHER THAN REASONED
-----------------------------------------------
Three test modules run a `fixtures/*/spec/build_fixtures.py` — to call its `check_layouts()` from
the suite, and to assert that the octets on disk are what that generator produces. All three used
`importlib.util.spec_from_file_location` + `exec_module`, which is the ordinary SOURCE loader: it
consults `__pycache__` and it writes one.

A `.pyc` is revalidated against the source's **mtime in whole seconds and its size**. So a
same-length edit that is reverted inside one second leaves a cache that validates against a file
it was never compiled from, and the loader hands back the OLD module while the source on disk says
something else. Reproduced at the CAT034 site: a generator cached with `STATION_HEIGHT_M = -13.0`,
the source restored byte-for-byte to `-12.0`, and
`test_the_generator_is_the_only_thing_that_writes_the_octets` FAILED against a correct tree.

THE STATUS "HARMLESS IN A NORMAL RUN" WAS WRONG, AND THAT IS THE FINDING
------------------------------------------------------------------------
It was reported as reachable only by a mutation harness. Measurement says otherwise:
`git checkout -- <file>` restores a file **0.016 s** after an edit — the same integer second,
which is the granularity the `.pyc` header stores. Edit a constant, run one fast test, revert: no
mutation harness anywhere, and the second run reads bytecode compiled from the edit. A harness
makes it routine rather than lucky; it does not make it possible.

AND THE LOADER IS WRONG HERE ON ITS OWN TERMS, INDEPENDENT OF TIMING
---------------------------------------------------------------------
Which is the part that decides the fix rather than merely motivating it. These tests exist to
compare artefacts on disk against **what this source produces**. A test whose subject is a source
file must read that source file; consulting a cache compiled from some other version of it is not
a performance question, it is the test measuring the wrong thing. So all three compile in memory —
`exec(compile(path.read_text(), ...))` — which reads the source every time and writes nothing.

WHY THIS IS A GATE AND NOT A COMMENT
-------------------------------------
The three sites are fixed the same way and nothing but a check keeps them that way, because the
convenient form is the broken one and it is what anybody writing a fourth loader would reach for.
So the poisoning is performed here: a cache is planted, the source is restored at the same mtime
and size, and each loader must still return what the SOURCE says. A loader that regressed would
pass every other test in the suite.
"""
import ast
import importlib
import os
import pathlib
import shutil
import types

import pytest

import synapse_cdm

PKG = pathlib.Path(synapse_cdm.__file__).resolve().parent
REPO = PKG.parents[2]
TESTS = REPO / "tests"

#: The modules that load a generator, and the loader each exposes. Hand-written, and the closure
#: below re-derives it from the tree so that a new loader cannot arrive unlisted.
LOADERS = {
    "test_cdm_asterix_cat023_adapter": "_build_fixtures_module",
    "test_cdm_asterix_cat034_adapter": "_build_fixtures_module",
    "test_cdm_asterix_cat048_adapter": "_build_fixtures_module",
    "test_cdm_asterix_cat062_adapter": "_build_fixtures_module",
    "test_cdm_gmtif_adapter": "_spec",
    # Adapter #10's harness loads it for two reasons the others have one of each: to assert the ten
    # payloads on disk are what the generator produces, and to assert each parsed twin is the parsed
    # form of its own payload.
    "test_cdm_stanag4609_adapter": "_build_fixtures_module",
    # Adapter #15's harness loads it for the same two reasons #10's does, and for a third that is
    # this format's own: the generator is where the ENCODER lives, because the shipped codec
    # decodes only. So the assertion that the octets on disk are the generator's output is the
    # only place anything checks that this repository can still produce the bytes it reads.
    "test_cdm_stanag4586_adapter": "_build_fixtures_module",
}

#: The adapter test modules. The ones absent from `LOADERS` are the other half of the closure:
#: the shape must be absent from them, and that is derived rather than asserted.
ADAPTER_TEST_MODULES = tuple(sorted(
    p.stem for p in TESTS.glob("test_cdm_*_adapter.py")))

#: The call the fix exists to keep out. `exec_module` is the ordinary source loader and is what
#: consults and writes `__pycache__`; `module_from_spec` is harmless alone but only ever appears
#: as its other half.
BANNED_CALL = "exec_module"


def _loads_a_module_by_path(source: str) -> bool:
    """Does this source EXECUTE a module loaded from a path? Two idioms, and nothing else counts.

    `exec(compile(...))` is the ruled form and `exec_module` is the retired one. Referring to a
    generator's path — to assert it exists, or that it is not a fixture — is not loading it.
    """
    return "exec(compile(" in source or "spec.loader.exec_module" in source


def _module(name):
    return importlib.import_module(f"tests.{name}")


def _generator_path(name: str) -> pathlib.Path:
    module = _module(name)
    return module.FIXTURES / "spec" / "build_fixtures.py"


# ---------------------------------------------------------------- the closure, both directions


def test_exactly_the_listed_harnesses_load_a_generator_and_the_others_do_not():
    """CLOSURE, and the second half is the one that makes it total.

    One adapter test module per shipped adapter. Some load a `build_fixtures.py`; the rest never
    mention one, and that absence is DERIVED from the tree rather than taken on trust — a harness
    that starts loading a generator has to join `LOADERS` and pass the poisoning check with the
    rest.

    THE COUNT IS DERIVED FROM THE REGISTRY and used to be the literal `10`, which went stale the
    moment `cat062` and `cat023` shipped. That is `tests/test_cdm_prose_counts.py`'s defect one
    layer in — a count in a place nothing computes it — and it is the third such literal this round
    found in the suite itself.
    """
    from synapse_cdm import adapter as adapter_module
    shipped = {n for n, c in adapter_module.discover().items()
               if c.__module__.startswith("synapse_cdm.adapters.")}
    assert len(ADAPTER_TEST_MODULES) == len(shipped), (
        f"{len(ADAPTER_TEST_MODULES)} adapter test modules and {len(shipped)} shipped adapters: "
        f"{sorted(ADAPTER_TEST_MODULES)} against {sorted(shipped)}. One harness per adapter is "
        "what makes this closure total"
    )
    # LOADING is the discriminator, not MENTIONING — and the difference is a real one:
    # `test_cdm_asterix_cat021_adapter` names its generator twice, to assert the file exists and
    # to assert it is not replayed as a fixture, and it never executes it. An earlier version of
    # this sweep keyed on the filename plus `compile(`, and matched that module on its `re.compile`
    # calls. The two idioms that execute a module by path are `exec(compile(` — the ruled one —
    # and `exec_module`, the one the module above bans outright.
    loads = {name for name in ADAPTER_TEST_MODULES
             if _loads_a_module_by_path((TESTS / f"{name}.py").read_text())}
    assert loads == set(LOADERS), (
        f"the generator-loading harnesses and the list disagree:\n"
        f"  only in the list: {sorted(set(LOADERS) - loads)}\n"
        f"  only in the tree: {sorted(loads - set(LOADERS))}\n"
        "A harness that starts loading its generator joins LOADERS and is poisoned with the rest"
    )
    silent = [n for n in ADAPTER_TEST_MODULES if n not in LOADERS]
    assert silent, "every harness loads a generator, so the second half of the closure is vacuous"
    for name in silent:
        source = (TESTS / f"{name}.py").read_text()
        assert not _loads_a_module_by_path(source), (
            f"{name} executes a module by path and is not on the loader list"
        )


def test_no_test_module_anywhere_uses_the_caching_loader():
    """THE ABSENCE, swept over every test module rather than over the three that had the defect.

    `exec_module` is what consults and writes `__pycache__`. Nothing in this suite needs it: the
    only modules loaded by path are the three generators, and all three are compiled in memory.
    Swept by AST so a mention inside a docstring — this module has several — is not a hit.
    """
    offenders = []
    for path in sorted(TESTS.glob("test_cdm_*.py")):
        if path.name == pathlib.Path(__file__).name:
            continue
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and node.attr == BANNED_CALL:
                offenders.append(f"{path.name}:{node.lineno}")
    assert not offenders, (
        f"these test modules call {BANNED_CALL}(): {offenders}. It is the ordinary source loader, "
        "so it reads and writes __pycache__ — and a .pyc is revalidated on the source's mtime in "
        "whole SECONDS and its size, which a same-length edit-and-revert defeats. Compile the "
        "source in memory instead; see this module's docstring for the reproduction"
    )


# ------------------------------------------------------------------------- the poisoning


@pytest.mark.parametrize("name", sorted(LOADERS), ids=lambda n: n.replace("test_cdm_", ""))
def test_the_loader_reads_the_source_even_with_a_poisoned_cache(name):
    """THE TEETH, and it is the check that would have caught the original defect.

    A cache is planted from a MODIFIED generator, the true source is restored byte-for-byte at the
    same mtime and size, and the loader must return what the source says. The old loader returns
    the planted value; this one cannot, because it never looks.

    The mutation is a comment appended to the generator and padded back to the original length, so
    it changes the bytecode without changing behaviour — the point is which BYTES were compiled,
    not what they do.
    """
    path = _generator_path(name)
    cache = path.parent / "__pycache__"
    original = path.read_bytes()
    stat = path.stat()
    marker = "_POISON_MARKER_" + name

    # The poisoned source APPENDS the marker rather than overwriting the tail, because a
    # same-length edit made by truncation lands mid-statement and the generator stops parsing —
    # which would test nothing but my ability to corrupt a file. The size difference is then
    # erased in the .pyc header below, which is exact rather than approximate: a timestamp .pyc
    # (PEP 552) is magic(4) + flags(4) + source mtime(4) + SOURCE SIZE(4), and those last two
    # fields are the entire validation. Writing the original's size into the header reproduces
    # precisely the state a same-length edit-and-revert leaves behind.
    poisoned = original + f"\n{marker} = 1\n".encode()

    shutil.rmtree(cache, ignore_errors=True)
    try:
        path.write_bytes(poisoned)
        os.utime(path, (stat.st_atime, stat.st_mtime))
        # Compile the poisoned source the OLD way, so a cache exists to be read.
        import importlib.util
        spec = importlib.util.spec_from_file_location(f"poison_{name}", path)
        planted = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(planted)
        assert getattr(planted, marker, None) == 1, (
            "the poisoning did not take, so this test proves nothing about the loader"
        )
        pycs = sorted(cache.glob("*.pyc")) if cache.is_dir() else []
        assert pycs, (
            "no bytecode was written, so there is no stale cache to defeat and this check is "
            "vacuous — the hazard it guards depends on exec_module writing one"
        )

        # Restore the truth, at the same mtime, and make the cache claim the restored size.
        path.write_bytes(original)
        os.utime(path, (stat.st_atime, stat.st_mtime))
        assert path.read_bytes() == original
        for pyc in pycs:
            blob = bytearray(pyc.read_bytes())
            blob[12:16] = (len(original) & 0xFFFFFFFF).to_bytes(4, "little")
            pyc.write_bytes(bytes(blob))

        module = getattr(_module(name), LOADERS[name])()
        assert not hasattr(module, marker), (
            f"{name}'s loader returned a module built from bytecode, not from the source on disk: "
            f"{marker} is present and the source does not define it. A .pyc validates on the "
            "source's mtime in whole seconds and its size, both of which are unchanged here — so "
            "this is what an edit reverted inside one second produces. Compile in memory"
        )
        assert isinstance(module, types.ModuleType)
    finally:
        path.write_bytes(original)
        os.utime(path, (stat.st_atime, stat.st_mtime))
        shutil.rmtree(cache, ignore_errors=True)


@pytest.mark.parametrize("name", sorted(LOADERS), ids=lambda n: n.replace("test_cdm_", ""))
def test_loading_a_generator_writes_no_bytecode_beside_it(name):
    """The other half: not reading a cache is worth little if the loader still writes one.

    A written `.pyc` is what the NEXT reader trips over, so a loader that ignores caches and leaves
    them behind has moved the hazard rather than removed it.
    """
    path = _generator_path(name)
    cache = path.parent / "__pycache__"
    shutil.rmtree(cache, ignore_errors=True)
    getattr(_module(name), LOADERS[name])()
    assert not cache.exists(), (
        f"loading {name}'s generator created {cache.relative_to(REPO)}. Compiling in memory writes "
        "nothing; something has gone back to the source loader"
    )


def test_the_generators_leave_no_bytecode_in_the_tree_after_a_full_run():
    """The state of the tree, checked rather than assumed, because it is what a reader sees.

    Three `__pycache__` directories sat beside these generators before the fix — gitignored, so
    invisible to `git status` and to review, which is part of why the shape survived.
    """
    stale = sorted(str(p.relative_to(REPO)) for p in (PKG / "fixtures").rglob("*.pyc"))
    assert not stale, (
        f"generator bytecode is on disk: {stale}. Nothing in this suite writes it any more, so "
        "these are either left from before the fix — delete them — or something regressed"
    )
