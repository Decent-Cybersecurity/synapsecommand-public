#!/bin/sh
# ctest smoke runs of the worker's start (test only): what it does before any RTI call.
#
#   sh worker_smoke.sh WORKER WORK_DIR
#
# --version prints exactly the host's VERSION_LINE (CR-R5-02); an argument vector that is not
# the three tokens of OPS-08 exits 64; without a pipe on fd 3 it exits 70 (NAT-09). The Python
# tests hold the same and more; this keeps a plain `ctest` honest.
set -u
worker=$1
work=$2
dir="$work/worker"
rm -rf "$dir"
mkdir -p "$dir"
fail() { echo "$*" >&2; exit 1; }

printf '%s\n' '{"name":"sc-hla-federate","profile":"SC-HLA-RPR2-OBS-1","version":"1.0.0"}' \
  >"$dir/expected-version"
"$worker" --version >"$dir/version" 3>&- || fail "--version exited $?"
cmp -s "$dir/expected-version" "$dir/version" || fail "--version printed something else"

valid="--endpoint=rti://127.0.0.1:1 --federation-name=SC_SMOKE --federate-name=SC_OBSERVER"
for arguments in "" "--help" "--version --version" \
    "--federation-name=SC_SMOKE --endpoint=rti://127.0.0.1:1 --federate-name=SC_OBSERVER" \
    "--endpoint=--help --federation-name=SC_SMOKE --federate-name=SC_OBSERVER" \
    "$valid --extra"; do
  # shellcheck disable=SC2086
  "$worker" $arguments </dev/null >/dev/null 2>&1 3>&-
  status=$?
  [ "$status" = 64 ] || fail "arguments [$arguments]: exit $status, expected 64"
done

# shellcheck disable=SC2086
"$worker" $valid </dev/null >/dev/null 2>&1 3>&-
status=$?
[ "$status" = 70 ] || fail "fd 3 closed: exit $status, expected 70"
# shellcheck disable=SC2086
"$worker" $valid </dev/null >/dev/null 2>&1 3>"$dir/regular-file"
status=$?
[ "$status" = 70 ] || fail "fd 3 a regular file: exit $status, expected 70"
echo "worker start: ok"
