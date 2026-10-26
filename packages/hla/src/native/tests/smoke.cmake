# The ctest smoke runs (test only): the worker's start, its installed layout, and one run of
# every harness scenario with the exit status the scenario ends with. 0 is the orderly stop, 1 a
# terminal condition reported on fd 3, 71 a channel the reader closed, 134 the abort of the
# recording decorator (SIGABRT). Each run has a time limit, so a scenario that hangs fails.
set(SC_HLA_SMOKE_DIR "${CMAKE_BINARY_DIR}/smoke")
set(SC_HLA_TESTS "${CMAKE_CURRENT_SOURCE_DIR}/tests")

add_test(NAME worker-start
         COMMAND /bin/sh "${SC_HLA_TESTS}/worker_smoke.sh" $<TARGET_FILE:sc-hla-federate>
                 "${SC_HLA_SMOKE_DIR}")
add_test(NAME worker-installed
         COMMAND "${CMAKE_COMMAND}" "-DBUILD=${CMAKE_BINARY_DIR}"
                 "-DOUT=${SC_HLA_SMOKE_DIR}/installed" -P "${SC_HLA_TESTS}/installed.cmake")

# scenario, exit status, seconds before the frame reader starts reading, and optionally the
# channel its reader closes after so many lines (frames:N or status:N)
set(SC_HLA_SCENARIOS
    "idle 0 0" "bytes 0 0" "limit-value 1 0" "limit-tag-reflect 1 0" "limit-tag-remove 1 0"
    "limit-time 1 0" "limit-name 1 0" "limit-attributes 1 0" "unsubscribed 0 0" "retract 0 0"
    "retraction-request 1 0" "empty 0 0" "reuse 0 0" "requests 0 0" "name-surrogate 1 0"
    "name-beyond 1 0" "name-text 0 0" "attribute-name-refused 1 0" "attribute-name-long 1 0"
    "attribute-name-128 0 0" "attribute-name-invalid 1 0" "attribute-name-collision 1 0"
    "time-name-long 1 0" "time-name-invalid 1 0" "class-other 1 0" "order-invalid 1 0"
    "connection-lost 1 0" "overflow-count 1 0" "overflow-bytes 1 0" "overflow-stalled 1 3"
    "tokens 1 0" "live 0 0" "rediscover-changed 0 0" "stop-mid-batch 0 0" "missing-name 1 0"
    "parent-rule 0 0"
    "decorator-forbidden 134 0" "decorator-arguments 134 0"
    "after-overflow-bytes 1 0" "after-overflow-frames 1 3" "after-limit-value 1 0"
    "after-limit-tag 1 0" "after-limit-name 1 0"
    "precedence-count-order 1 0" "precedence-value-time-name 1 0" "precedence-tag-transport 1 0"
    "precedence-time-length-name 1 0" "precedence-order-queue 1 0" "precedence-class-name 1 0"
    "precedence-name-queue 1 0" "precedence-remove-tag-order 1 0"
    "precedence-remove-order-queue 1 0" "precedence-order-token 1 0"
    "precedence-token-queue 1 0" "naming-then-limit 1 0" "limit-then-naming 1 0"
    "transport-invalid 1 0" "received-order-invalid 1 0" "remove-order-invalid 1 0"
    "time-encode-refused 1 0" "time-encode-short 1 0" "callback-no-memory 1 0"
    "callback-other-exception 1 0" "overflow-bytes-exact 1 0" "overflow-bytes-over 1 0"
    "stream-frames 71 0 frames:3" "stream-objects 71 0 status:8" "name-in-use 1 0"
    "fault-connect-stop 0 0" "fault-join-stop 0 0" "fault-join-time-factory 1 0"
    "fault-join-inconsistent-fdd 1 0" "fault-join-error-reading-fdd 1 0"
    "fault-join-could-not-open-fdd 1 0" "fault-join-other 1 0" "fault-class-name 1 0"
    "fault-attribute-other 1 0" "fault-subscribe-class 1 0" "fault-subscribe-attribute 1 0"
    "fault-subscribe-other 1 0" "fault-evoke 1 0" "fault-request-attribute 1 0"
    "fault-request-other 1 0" "fault-resign-after-stop 1 0" "fault-disconnect-after-stop 1 0"
    "fault-resign-after-condition 1 0" "fault-disconnect-after-condition 1 0"
    "overflow-bytes-time-exact 1 0" "overflow-bytes-time-over 1 0"
    "overflow-bytes-remove-exact 1 0" "overflow-bytes-remove-over 1 0"
    "token-bound-discover 1 0" "token-bound-discover-queue 1 0" "token-bound-remove 1 0"
    "token-bound-remove-order 1 0" "token-bound-remove-queue 1 0" "fault-create 1 0"
    "real-rti 1 0")
foreach(entry IN LISTS SC_HLA_SCENARIOS)
  separate_arguments(fields UNIX_COMMAND "${entry}")
  list(GET fields 0 scenario)
  list(GET fields 1 status)
  list(GET fields 2 delay)
  list(LENGTH fields count)
  set(close "")
  if(count GREATER 3)
    list(GET fields 3 close)
  endif()
  add_test(NAME harness-${scenario}
           COMMAND /bin/sh "${SC_HLA_TESTS}/smoke.sh" $<TARGET_FILE:sc-hla-harness> ${scenario}
                   ${status} "${SC_HLA_SMOKE_DIR}" ${delay} ${close})
  set_tests_properties(harness-${scenario} PROPERTIES TIMEOUT 300)
endforeach()
