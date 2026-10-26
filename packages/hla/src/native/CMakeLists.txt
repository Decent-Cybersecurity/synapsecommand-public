# The native part of synapse-hla: the worker sc-hla-federate (R03, R43), the demo's synthetic
# publisher sc-hla-publisher (R38) and the two reference tools of R47, and, for tests only, the
# harness sc-hla-harness that drives the worker's callbacks directly (NAT-07) and the test
# federate sc-hla-test-federate.
#
#   cmake -S src/native -B <build directory outside the source tree> -DOPENRTI_PREFIX=<install>
#   cmake --build <build directory>
#   SYNAPSE_HLA_FOM_DIR=<directory of the five RPR FOM modules> ctest --test-dir <build directory>
#
# The harness's smoke runs create their federation from those five modules, so ctest needs
# SYNAPSE_HLA_FOM_DIR, as the Python tests do; without it each of them fails at once and says so.
#
# OPENRTI_PREFIX is the install tree of the pinned OpenRTI (tools/build_openrti.sh builds one);
# nothing is searched for anywhere else. Its shared libraries are copied into <build>/lib, so the
# build tree has the layout of the package: bin/ beside lib/, found through the relative loader
# path R43 asks for (NAT-13).
#
# The installed form (docs/installation.md): after the wheel is installed,
#
#   cmake --install <build directory> --prefix <directory of the installed synapse_hla package>
#
# puts sc-hla-federate, sc-hla-publisher and OpenRTI's rtinode into its bin/, the OpenRTI shared
# libraries into its lib/ and the licence texts of ../../licences into its licences/: the fixed
# places where the host and the demo look for them when no SYNAPSE_HLA_* variable is set
# (OPV-04, CR-R5-02, CR-L16). Nothing test-only is installed.
cmake_minimum_required(VERSION 3.28)
project(sc_hla_native LANGUAGES CXX)

set(OPENRTI_PREFIX "" CACHE PATH "Install tree of the pinned OpenRTI build")
if(NOT OPENRTI_PREFIX)
  message(FATAL_ERROR "set -DOPENRTI_PREFIX=<install tree of the pinned OpenRTI>")
endif()
set(OPENRTI_INCLUDE "${OPENRTI_PREFIX}/include/rti1516e")
if(NOT EXISTS "${OPENRTI_INCLUDE}/RTI/RTIambassador.h")
  message(FATAL_ERROR "no rti1516e headers under ${OPENRTI_PREFIX}")
endif()
if(NOT EXISTS "${OPENRTI_PREFIX}/bin/rtinode")
  message(FATAL_ERROR "no rtinode under ${OPENRTI_PREFIX}/bin")
endif()

# R43: C++14, as the rti1516e headers expect it (RTI_THROW and std::auto_ptr below C++17).
set(CMAKE_CXX_STANDARD 14)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Release)
endif()

set(CMAKE_RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin")
if(APPLE)
  set(SC_HLA_LOADER_PATH "@loader_path/../lib")
else()
  set(SC_HLA_LOADER_PATH "$ORIGIN/../lib")
endif()
# One loader path, relative, in the build tree and in the installed tree alike (NAT-13).
set(CMAKE_BUILD_WITH_INSTALL_RPATH ON)
set(CMAKE_INSTALL_RPATH "${SC_HLA_LOADER_PATH}")

# The OpenRTI libraries beside bin/, symbolic links kept as links.
file(GLOB SC_HLA_OPENRTI_LIBRARIES
  "${OPENRTI_PREFIX}/lib/*${CMAKE_SHARED_LIBRARY_SUFFIX}*")
if(NOT SC_HLA_OPENRTI_LIBRARIES)
  message(FATAL_ERROR "no shared libraries under ${OPENRTI_PREFIX}/lib")
endif()
file(COPY ${SC_HLA_OPENRTI_LIBRARIES} DESTINATION "${CMAKE_BINARY_DIR}/lib")

add_library(openrti_rti1516e INTERFACE)
# The RTI headers are someone else's: their warnings are not ours to fail on (SYSTEM).
target_include_directories(openrti_rti1516e SYSTEM INTERFACE "${OPENRTI_INCLUDE}")
target_link_directories(openrti_rti1516e INTERFACE "${CMAKE_BINARY_DIR}/lib")
target_link_libraries(openrti_rti1516e INTERFACE rti1516e fedtime1516e)

# Our sources fail on any warning. The two deprecation groups are the API's own: R43's C++14
# headers declare dynamic exception specifications and hand out std::auto_ptr, and every
# override of a callback must repeat that specification.
set(SC_HLA_WARNINGS -Wall -Wextra -Werror -Wno-deprecated -Wno-deprecated-declarations)

add_library(sc_hla_worker STATIC
  worker/channels.cpp
  worker/observer.cpp
  worker/process.cpp
  worker/record.cpp
  worker/text.cpp)
target_include_directories(sc_hla_worker PUBLIC "${CMAKE_CURRENT_SOURCE_DIR}/worker")
target_compile_options(sc_hla_worker PRIVATE ${SC_HLA_WARNINGS})
target_link_libraries(sc_hla_worker PUBLIC openrti_rti1516e)
find_package(Threads REQUIRED)
target_link_libraries(sc_hla_worker PUBLIC Threads::Threads)

add_executable(sc-hla-federate worker/main.cpp)
target_compile_options(sc-hla-federate PRIVATE ${SC_HLA_WARNINGS})
target_link_libraries(sc-hla-federate PRIVATE sc_hla_worker)
install(TARGETS sc-hla-federate RUNTIME DESTINATION bin)

# The demo's synthetic publisher (R38, R39, CR-L16): its sources are under tools/publisher; it
# shares the worker's helpers for argument values, text and its output channel.
set(SC_HLA_TOOLS "${CMAKE_CURRENT_SOURCE_DIR}/../../tools")
add_executable(sc-hla-publisher
  "${SC_HLA_TOOLS}/publisher/publisher.cpp"
  "${SC_HLA_TOOLS}/publisher/sha256.cpp")
target_include_directories(sc-hla-publisher PRIVATE "${SC_HLA_TOOLS}/publisher")
target_compile_options(sc-hla-publisher PRIVATE ${SC_HLA_WARNINGS})
target_link_libraries(sc-hla-publisher PRIVATE sc_hla_worker)
install(TARGETS sc-hla-publisher RUNTIME DESTINATION bin)

# The rest of the runtime the two need, beside them: the OpenRTI libraries (symbolic links kept),
# the demo's rtinode (its own loader path is relative too when OpenRTI was built by
# tools/build_openrti.sh, NAT-13) and the licence texts the release carries (NAT-14).
install(DIRECTORY "${CMAKE_BINARY_DIR}/lib/" DESTINATION lib USE_SOURCE_PERMISSIONS)
install(PROGRAMS "${OPENRTI_PREFIX}/bin/rtinode" DESTINATION bin)
install(DIRECTORY "${SC_HLA_TOOLS}/../licences/" DESTINATION licences)

# The reference tools of R47 and REFERENCE-CHECKS, vendored byte for byte from the handoff
# bundle under tools/reference (their pins are in tests/contract/vendored-pins.json). They are
# someone else's sources, compiled as the bundle's own commands compile them (C++14 with the two
# deprecation groups silenced, no -Werror), and never installed: reference evidence, not product.
add_executable(sc-hla-reference-encode "${SC_HLA_TOOLS}/reference/reference_encode.cpp")
target_compile_options(sc-hla-reference-encode PRIVATE -Wno-deprecated
                       -Wno-deprecated-declarations)
target_link_libraries(sc-hla-reference-encode PRIVATE openrti_rti1516e)
add_executable(sc-hla-reference-fom-check "${SC_HLA_TOOLS}/reference/reference_fom_check.cpp")
target_compile_options(sc-hla-reference-fom-check PRIVATE -Wno-deprecated
                       -Wno-deprecated-declarations)
target_link_libraries(sc-hla-reference-fom-check PRIVATE openrti_rti1516e)

# Test only: never installed.
add_executable(sc-hla-harness
  tests/harness.cpp
  tests/recording_ambassador.cpp
  tests/test_time.cpp)
target_compile_options(sc-hla-harness PRIVATE ${SC_HLA_WARNINGS})
target_link_libraries(sc-hla-harness PRIVATE sc_hla_worker)

# Test only, never installed: a federate that creates a federation from the module files it is
# given and joins it under a name it is given, then holds until told to go (A-MISSING-FOM with a
# reduced module set, A-NAME-CONFLICT with the observer's own federate name). The publisher never
# does either.
add_executable(sc-hla-test-federate tests/test_federate.cpp)
target_compile_options(sc-hla-test-federate PRIVATE ${SC_HLA_WARNINGS})
target_link_libraries(sc-hla-test-federate PRIVATE sc_hla_worker)

enable_testing()
include(tests/smoke.cmake)
