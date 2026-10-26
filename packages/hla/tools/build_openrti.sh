#!/usr/bin/env bash
# Builds the pinned OpenRTI that the native worker links against.
#
#   bash tools/build_openrti.sh ARCHIVE /absolute/new/build-directory
#
# ARCHIVE is openrti-814a210.tar.gz of the handoff bundle (the handoff document SC HLA SPEC 001
# v1.0 and its bundle are not in this repository); its SHA-256 must be the pinned one. The
# configure, build and install commands are the bundle's tools/build_openrti.sh command (R43),
# unchanged, with these options appended:
#   -DCMAKE_POLICY_VERSION_MINIMUM=3.5  only when `cmake --version` reports 4.0 or later: CMake 4
#                                       refuses OpenRTI's own minimum version (NAT-12);
#   -DOPENRTI_INSTALL_WITH_RPATH=OFF -DCMAKE_INSTALL_RPATH=$ORIGIN/../lib (Linux) or
#   @loader_path/../lib (macOS)         a relocatable install with a relative loader path (NAT-13);
#   -DCMAKE_CXX_STANDARD=98             on macOS only, for OpenRTI only (NAT-02: the C++14 OpenRTI
#                                       client cannot connect there); the worker stays C++14, and
#                                       a build made so is development evidence, never release
#                                       evidence (CR-L04).
# Nothing is installed outside the build directory and nothing is fetched. Beside the install
# it writes build-record.txt: the exact commands, the CMake and compiler versions, the archive's
# SHA-256, which variant ran and the evidence class of the build: the reference configuration
# only on Linux x86_64 with Ubuntu 24.04, GCC 13 and CMake 3.28 to 3.31, otherwise development
# evidence of the machine it ran on.
set -euo pipefail

usage='Usage: bash tools/build_openrti.sh ARCHIVE /absolute/new/build-directory'
if [ "$#" -ne 2 ]; then echo "$usage" >&2; exit 2; fi
archive=$1
build_root=$2
case "$build_root" in /*) ;; *) echo 'Build directory must be absolute' >&2; exit 2;; esac
if [ -e "$build_root" ]; then echo 'Build directory already exists' >&2; exit 2; fi
if [ ! -f "$archive" ]; then echo 'No archive at the given path' >&2; exit 2; fi

pinned_sha256=16de11df983c8074feed252a7de1fc7c05c4e9520c050df6bcff8b3a899adb80
commit=814a210978b7faafd65affbe70a2e25679921b23
if command -v sha256sum >/dev/null 2>&1; then
  archive_sha256=$(sha256sum "$archive" | cut -d ' ' -f 1)
else
  archive_sha256=$(shasum -a 256 "$archive" | cut -d ' ' -f 1)
fi
if [ "$archive_sha256" != "$pinned_sha256" ]; then
  echo 'The archive is not the pinned OpenRTI source archive (SHA-256 differs)' >&2
  exit 2
fi

cmake_version=$(cmake --version | head -n 1)
cmake_major=$(printf '%s\n' "$cmake_version" | sed -E 's/^cmake version ([0-9]+)\..*$/\1/')
case "$cmake_major" in
  ''|*[!0-9]*) echo "Cannot read the CMake version: $cmake_version" >&2; exit 2;;
esac

added=()
policy_flag=no
if [ "$cmake_major" -ge 4 ]; then
  added+=(-DCMAKE_POLICY_VERSION_MINIMUM=3.5)
  policy_flag=yes
fi
platform=$(uname -s)
case "$platform" in
  Darwin)
    added+=(-DOPENRTI_INSTALL_WITH_RPATH=OFF '-DCMAKE_INSTALL_RPATH=@loader_path/../lib')
    added+=(-DCMAKE_CXX_STANDARD=98)
    evidence='development evidence only (macOS: OpenRTI configured as C++98, NAT-02)'
    ;;
  *)
    added+=(-DOPENRTI_INSTALL_WITH_RPATH=OFF '-DCMAKE_INSTALL_RPATH=$ORIGIN/../lib')
    evidence=''
    ;;
esac

configure=(cmake -S "$build_root/source/OpenRTI-$commit"
  -B "$build_root/build" -DCMAKE_BUILD_TYPE=Release -DCMAKE_CXX_STANDARD=14
  -DOPENRTI_ENABLE_RTI13=OFF -DOPENRTI_ENABLE_RTI1516=OFF
  -DOPENRTI_ENABLE_RTI1516E=ON -DOPENRTI_ENABLE_PYTHON_BINDINGS=OFF
  -DOPENRTI_BUILD_SHARED=ON -DCMAKE_INSTALL_PREFIX="$build_root/install" "${added[@]}")
build=(cmake --build "$build_root/build" --parallel 4)
install=(cmake --install "$build_root/build")

mkdir -p -- "$build_root/source"
tar -xzf "$archive" -C "$build_root/source"
"${configure[@]}"
"${build[@]}"
"${install[@]}"

cache="$build_root/build/CMakeCache.txt"
compiler=$(sed -n 's/^CMAKE_CXX_COMPILER:[A-Z]*=//p' "$cache")
standard=$(sed -n 's/^CMAKE_CXX_STANDARD:[A-Z]*=//p' "$cache")
# sed reads the whole output: head could close the pipe early, and under pipefail the
# compiler's SIGPIPE would end the script here.
compiler_line=$("$compiler" --version | sed -n 1p)

# The record names the reference configuration (CR-L04: Linux x86_64, Ubuntu 24.04, GCC 13,
# CMake 3.28 to 3.31) only when this machine is it; any other Linux build is development
# evidence of its own machine (CR-L21: the Linux aarch64 reference run's record claimed the
# reference configuration because this line used to be written whatever the machine was).
if [ -z "$evidence" ]; then
  machine=$(uname -m)
  reference=yes
  [ "$machine" = x86_64 ] || reference=no
  if [ ! -f /etc/os-release ] || ! grep -qx 'ID=ubuntu' /etc/os-release ||
     ! grep -qx 'VERSION_ID="24.04"' /etc/os-release; then reference=no; fi
  case "$compiler_line" in *'(Ubuntu 13.'*') 13.'*) ;; *) reference=no;; esac
  case "$cmake_version" in 'cmake version 3.'2[89].*|'cmake version 3.'3[01].*) ;; *) reference=no;; esac
  if [ "$reference" = yes ]; then
    evidence='the reference configuration: Linux x86_64, Ubuntu 24.04, GCC 13, CMake 3.28 to 3.31'
  else
    evidence="DEV-linux-$machine: development evidence only (not the reference configuration:"
    evidence="$evidence Linux x86_64, Ubuntu 24.04, GCC 13, CMake 3.28 to 3.31)"
  fi
fi
{
  echo "openrti_commit=$commit"
  echo "archive=$archive"
  echo "archive_sha256=$archive_sha256"
  echo "platform=$platform $(uname -m)"
  echo "cmake=$cmake_version"
  echo "compiler=$compiler: $compiler_line"
  echo "policy_version_minimum_added=$policy_flag"
  echo "cxx_standard_in_cache=$standard"
  echo "evidence=$evidence"
  printf 'configure='; printf '%q ' "${configure[@]}"; echo
  printf 'build='; printf '%q ' "${build[@]}"; echo
  printf 'install='; printf '%q ' "${install[@]}"; echo
} >"$build_root/build-record.txt"

echo "OpenRTI installed in $build_root/install"
echo "Build record: $build_root/build-record.txt"
if [ "$platform" = Darwin ]; then
  echo "This build is development evidence only (NAT-02, CR-L04);"
  echo "release evidence needs the reference platform."
fi
echo "Evidence: $evidence"
