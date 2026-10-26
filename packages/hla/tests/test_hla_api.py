"""The public surface (CR-L02) and the distribution's declaration (D-01, D-17, D-18).

`__all__` is held to the CR-L02 list exactly: round R4 implemented the last two functions
(`reduce_frame`, `replay`), so the subset the earlier rounds checked is now an equality.
"""

import pathlib
import sys
import tomllib
import types

import synapse_hla
from hla_support import PACKAGE_ROOT
from synapse_hla import errors

#: CR-L02, verbatim.
CR_L02 = {"validate_config", "decode_attribute", "reduce_frame", "project_state", "replay",
          "verify_capture", "HlaError", "__version__", "PROFILE"}

PYPROJECT = tomllib.loads((PACKAGE_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
REPO = PACKAGE_ROOT.parent.parent


def test_version_and_profile():
    assert synapse_hla.__version__ == "1.0.0"
    assert synapse_hla.PROFILE == "SC-HLA-RPR2-OBS-1"


def test_the_exception_is_the_one_type_of_the_error_module():
    assert synapse_hla.HlaError is errors.HlaError


def test_all_is_exactly_cr_l02_and_names_what_exists():
    assert len(synapse_hla.__all__) == len(set(synapse_hla.__all__))
    assert set(synapse_hla.__all__) == CR_L02
    for name in synapse_hla.__all__:
        assert hasattr(synapse_hla, name), name


def test_each_public_function_is_exported_from_its_module():
    """CR-L02: `synapse_hla` exports each public function under its name, and it is the module's
    own function, not a copy or a wrapper (review finding R3-r1-F3). The package attribute
    `replay` is the function, which shadows the module of the same name, so the module is taken
    from `sys.modules`."""
    from synapse_hla import capture, codec, config, projector, reducer
    replay_module = sys.modules["synapse_hla.replay"]
    implemented = {
        "decode_attribute": codec.decode_attribute,       # R1
        "validate_config": config.validate_config,        # R2
        "verify_capture": capture.verify_capture,         # R2
        "project_state": projector.project_state,         # R3
        "reduce_frame": reducer.reduce_frame,             # R4
        "replay": replay_module.replay,                   # R4
    }
    assert set(implemented) | {"HlaError", "__version__", "PROFILE"} == CR_L02
    for name, function in implemented.items():
        assert name in synapse_hla.__all__, name
        assert getattr(synapse_hla, name) is function, name


def test_nothing_public_is_exported_beyond_all():
    """Submodules are reachable as attributes once imported; anything else public must be listed."""
    public = {n for n, v in vars(synapse_hla).items()
              if not n.startswith("_") and not isinstance(v, types.ModuleType)}
    assert public <= set(synapse_hla.__all__), sorted(public - set(synapse_hla.__all__))


def test_the_distribution_declaration():
    project = PYPROJECT["project"]
    assert project["name"] == "synapse-hla"
    assert project["version"] == synapse_hla.__version__ == "1.0.0"
    assert project["requires-python"] == ">=3.11"
    # D-28: the floor is the CDM the package was landed and tested on, below the next major.
    assert project["dependencies"] == ["synapse-cdm>=3.8.0,<4"]
    assert project["optional-dependencies"] == {"test": ["pytest==9.1.1"]}
    assert project["license"] == "Apache-2.0"
    # The repository's two files, and the two OpenRTI texts that carry a copyright line (NAT-14;
    # the repository admits such a line only in a declared licence file).
    assert project["license-files"] == ["LICENSE", "NOTICE", "licences/openrti/lgpl-2.1",
                                        "licences/openrti/lgpl-3"]
    # The console script of the command line (round R6), and no other entry point: in
    # particular no synapse_cdm.adapters entry point, since this is not a registered CDM adapter
    # (R03).
    assert project["scripts"] == {"synapse-hla": "synapse_hla.cli:main"}
    assert "entry-points" not in project and "gui-scripts" not in project
    versions = {c.rsplit(" :: ", 1)[1] for c in project["classifiers"]
                if c.startswith("Programming Language :: Python :: 3.")}
    assert versions == {"3.11", "3.12"}
    # Beta, never Production/Stable while release gates read BLOCKED (CR-L04); no OS classifier.
    assert [c for c in project["classifiers"] if c.startswith("Development Status")] == [
        "Development Status :: 4 - Beta"]
    assert not [c for c in project["classifiers"] if c.startswith("Operating System")]
    assert "under construction" not in project["description"]
    assert PYPROJECT["build-system"]["requires"] == ["setuptools>=77"]


def test_the_package_data_ships_the_vendored_contract():
    st = PYPROJECT["tool"]["setuptools"]
    assert st["packages"]["find"] == {"where": ["src"], "include": ["synapse_hla*"]}
    assert st["package-data"] == {
        "synapse_hla": ["pins.json", "schemas/*.json", "local_schemas/*.json", "fixtures/*"]}


def test_the_test_configuration_declares_the_three_groups():
    ini = PYPROJECT["tool"]["pytest"]["ini_options"]
    assert ini["testpaths"] == ["tests"]
    assert ini["pythonpath"] == ["src", "tests"]
    names = {m.split(":", 1)[0] for m in ini["markers"]}
    assert names == {"rti", "perf", "reference", "hla_case"}
    assert "--strict-markers" in ini["addopts"]


def test_the_lint_configuration_is_the_repositorys():
    ruff = PYPROJECT["tool"]["ruff"]
    assert ruff["line-length"] == 100
    assert ruff["target-version"] == "py311"
    assert ruff["lint"]["select"] == ["E9", "F", "E7", "W"]


def test_licence_and_notice_are_byte_copies_of_the_repository_root():
    for name in ("LICENSE", "NOTICE"):
        assert (PACKAGE_ROOT / name).read_bytes() == (REPO / name).read_bytes(), name


def test_the_package_lives_in_a_src_layout():
    src = pathlib.Path(synapse_hla.__file__).resolve().parent
    assert src == PACKAGE_ROOT / "src" / "synapse_hla"
