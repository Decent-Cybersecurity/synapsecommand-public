#!/bin/sh
# ctest smoke run of one harness scenario (test only).
#
#   sh smoke.sh HARNESS SCENARIO EXPECTED_STATUS WORK_DIR [READ_DELAY_SECONDS [CLOSE]]
#
# Runs the scenario with --stop-when-ready, its status channel (fd 3) on a pipe to a file and
# its frames on a FIFO whose reader starts reading only after READ_DELAY_SECONDS (a host that
# does not read, for the queue-overflow scenarios). CLOSE, frames:N or status:N, makes that
# channel's reader stop and close its end after N lines (a reader that goes away, for the
# broken-channel scenarios). Passes when the harness exits with EXPECTED_STATUS and its channels
# say what that status means: a failure record for 1, the orderly stop's disconnect for 0, no
# failure record for 71. The assertions on content are the Python tests'.
set -u
harness=$1
scenario=$2
expected=$3
work=$4
delay=${5:-0}
close=${6:-}
fom=${SYNAPSE_HLA_FOM_DIR:?SYNAPSE_HLA_FOM_DIR must name the directory of the RPR FOM modules}

frames_reader="cat"
status_reader="cat"
case "$close" in
  frames:*) frames_reader="head -n ${close#frames:}" ;;
  status:*) status_reader="head -n ${close#status:}" ;;
  "") ;;
  *) echo "unknown CLOSE $close" >&2; exit 1 ;;
esac

dir="$work/$scenario"
rm -rf "$dir"
mkdir -p "$dir"
mkfifo "$dir/frames.fifo"
# The reader opens its end at once (so the harness's open does not wait) and reads later.
# shellcheck disable=SC2086
( exec 5<"$dir/frames.fifo"; sleep "$delay"; exec $frames_reader <&5 >"$dir/frames" ) &
reader=$!
# shellcheck disable=SC2086
{
  "$harness" --scenario="$scenario" --fom-dir="$fom" --log="$dir/log" --stop-when-ready \
    --endpoint=rti://127.0.0.1:1 --federation-name=SC_SMOKE --federate-name=SC_OBSERVER \
    3>&1 1>"$dir/frames.fifo"
  echo $? >"$dir/status-code"
} | $status_reader >"$dir/status"
wait "$reader"

status=$(cat "$dir/status-code")
if [ "$status" != "$expected" ]; then
  echo "scenario $scenario: exit status $status, expected $expected" >&2
  exit 1
fi
case "$expected" in
  0) grep -q '"stage":"disconnect"' "$dir/status" || { echo "no orderly stop" >&2; exit 1; } ;;
  1) grep -q '"type":"failure"' "$dir/status" || { echo "no failure record" >&2; exit 1; } ;;
  71) ! grep -q '"type":"failure"' "$dir/status" || { echo "a failure record" >&2; exit 1; } ;;
esac
echo "scenario $scenario: exit status $status"
