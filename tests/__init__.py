"""Present on purpose, not by accident: it fixes the test modules' identity.

`tests/test_cdm_harness.py` hands the harness a `module:Class` string pointing back at
itself, which is how an adapter the harness has never heard of gets resolved. Without this
file `tests` is a namespace package, so pytest imports the module as `test_cdm_harness`
while the harness imports the same file again as `tests.test_cdm_harness` — two module
objects, two class definitions, and the adapter registry rejects the second name as a
duplicate. One package, one identity.
"""
