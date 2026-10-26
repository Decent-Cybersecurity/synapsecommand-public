# ctest check of the installed layout (test only), run with cmake -P:
#
#   cmake -DBUILD=<build directory> -DOUT=<new directory> -P installed.cmake
#
# Installs the build into OUT exactly as docs/installation.md installs it into the package
# directory, then checks the layout the host and the demo rely on: bin/ holds the worker, the
# publisher and rtinode and nothing else (no test program, no reference tool), lib/ the OpenRTI
# shared libraries, licences/ the texts the release carries; and the worker and the publisher
# answer --version from OUT, finding their libraries through the relative loader path alone
# (R43, NAT-13), wherever the tree is.
file(REMOVE_RECURSE "${OUT}")
execute_process(COMMAND "${CMAKE_COMMAND}" --install "${BUILD}" --prefix "${OUT}"
                RESULT_VARIABLE status OUTPUT_QUIET)
if(NOT status EQUAL 0)
  message(FATAL_ERROR "cmake --install failed: ${status}")
endif()
file(GLOB installed RELATIVE "${OUT}/bin" "${OUT}/bin/*")
list(SORT installed)
if(NOT installed STREQUAL "rtinode;sc-hla-federate;sc-hla-publisher")
  message(FATAL_ERROR "bin/ holds [${installed}]")
endif()
foreach(library OpenRTI rti1516e fedtime1516e)
  file(GLOB found "${OUT}/lib/lib${library}${CMAKE_SHARED_LIBRARY_SUFFIX}*"
                  "${OUT}/lib/lib${library}.*${CMAKE_SHARED_LIBRARY_SUFFIX}")
  if(NOT found)
    message(FATAL_ERROR "lib/ has no lib${library}")
  endif()
endforeach()
foreach(text README.md openrti/LICENSE openrti/lgpl-2.1 openrti/lgpl-3 openrti/mpl-2.0)
  if(NOT EXISTS "${OUT}/licences/${text}")
    message(FATAL_ERROR "licences/${text} was not installed")
  endif()
endforeach()
foreach(program federate publisher)
  execute_process(COMMAND "${OUT}/bin/sc-hla-${program}" --version
                  RESULT_VARIABLE status OUTPUT_VARIABLE printed)
  set(expected "{\"name\":\"sc-hla-${program}\",\"profile\":\"SC-HLA-RPR2-OBS-1\",")
  string(APPEND expected "\"version\":\"1.0.0\"}\n")
  if(NOT status EQUAL 0 OR NOT printed STREQUAL expected)
    message(FATAL_ERROR "installed ${program}: status ${status}, printed [${printed}]")
  endif()
endforeach()
message(STATUS "installed worker and publisher answer --version from ${OUT}")
