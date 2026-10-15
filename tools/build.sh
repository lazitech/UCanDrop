#!/usr/bin/env bash
# Build the vendored OWL radio binary for the host architecture.
#
# This script is deliberately source-only: it never downloads code, invokes
# apt, uses sudo, or writes outside the selected build directory.  The
# release builder is responsible for copying the resulting binary into a
# package staging tree.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
SOURCE_DIR=$ROOT/vendor/owl
BUILD_DIR=${UCANDROP_BUILD_DIR:-$ROOT/build}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1792022400}

die() {
    printf 'ucandrop build: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: tools/build.sh [--clean] [--jobs N]

Build the vendored OWL source into UCANDROP_BUILD_DIR (default: build/).
The build is native, offline, and unprivileged. Dependencies must already be
installed by the caller.
EOF
}

JOBS=${UCANDROP_BUILD_JOBS:-}
CLEAN=0
while (($#)); do
    case $1 in
        --clean) CLEAN=1 ;;
        --jobs)
            (($# >= 2)) || die '--jobs needs a positive integer'
            JOBS=$2
            shift
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

[[ ${EUID:-$(id -u)} -ne 0 ]] || die 'run as an ordinary user; building never needs root'
[[ $SOURCE_DATE_EPOCH =~ ^[0-9]+$ ]] || die 'SOURCE_DATE_EPOCH must be an integer'
export SOURCE_DATE_EPOCH

for command in cmake cc c++ strip; do
    command -v "$command" >/dev/null 2>&1 || die "missing build tool: $command"
done

[[ -f $SOURCE_DIR/CMakeLists.txt ]] || die "vendored OWL source is missing: $SOURCE_DIR"
[[ -f $SOURCE_DIR/daemon/CMakeLists.txt ]] || die 'vendored OWL daemon sources are incomplete'
[[ -f $SOURCE_DIR/radiotap/radiotap.c ]] || die 'vendored radiotap sources are incomplete'

if [[ -z $JOBS ]]; then
    JOBS=$(getconf _NPROCESSORS_ONLN 2>/dev/null || true)
    JOBS=${JOBS:-1}
fi
[[ $JOBS =~ ^[1-9][0-9]*$ ]] || die '--jobs must be a positive integer'

mkdir -p "$BUILD_DIR"
BUILD_DIR=$(cd -- "$BUILD_DIR" && pwd -P)
OWL_BUILD_DIR=$BUILD_DIR/owl
if (( CLEAN )); then
    rm -rf -- "$OWL_BUILD_DIR"
fi

# Keep source/build paths out of __FILE__, macro strings, and DWARF.  The
# destination names are stable release paths and contain no checkout/user
# identity.  Build paths are mapped separately because the default build is a
# child of the checkout.  CMAKE_*_FLAGS is a string parsed once more by CMake,
# so escape path separators that would otherwise split a flag when a checkout
# lives in a directory containing spaces.
cmake_flag_path() {
    local value=$1
    value=${value//\\/\\\\}
    value=${value// /\\ }
    value=${value//;/\\;}
    value=${value//\"/\\\"}
    printf '%s' "$value"
}

BUILD_FLAG_PATH=$(cmake_flag_path "$BUILD_DIR")
ROOT_FLAG_PATH=$(cmake_flag_path "$ROOT")
MAP_FLAGS="-ffile-prefix-map=$BUILD_FLAG_PATH=/usr/src/ucandrop-build -fmacro-prefix-map=$BUILD_FLAG_PATH=/usr/src/ucandrop-build -fdebug-prefix-map=$BUILD_FLAG_PATH=/usr/src/ucandrop-build -ffile-prefix-map=$ROOT_FLAG_PATH=/usr/src/ucandrop-1.2.1 -fmacro-prefix-map=$ROOT_FLAG_PATH=/usr/src/ucandrop-1.2.1 -fdebug-prefix-map=$ROOT_FLAG_PATH=/usr/src/ucandrop-1.2.1"

cmake \
    -S "$SOURCE_DIR" \
    -B "$OWL_BUILD_DIR" \
    -DCMAKE_BUILD_TYPE=Release \
    -DCMAKE_POLICY_VERSION_MINIMUM=3.5 \
    -DBUILD_TESTING=OFF \
    -DINSTALL_GTEST=OFF \
    -DCMAKE_INSTALL_PREFIX=/usr \
    "-DCMAKE_C_FLAGS=$MAP_FLAGS" \
    "-DCMAKE_CXX_FLAGS=$MAP_FLAGS"

cmake --build "$OWL_BUILD_DIR" --target owl --parallel "$JOBS"

OWL_BINARY=$OWL_BUILD_DIR/daemon/owl
[[ -x $OWL_BINARY ]] || die "OWL build did not produce $OWL_BINARY"

# Release packages do not need debug sections.  Strip only the generated
# executable, never anything in the vendored source tree.
strip --strip-unneeded "$OWL_BINARY"

# A compiler can still retain an absolute path through a new feature or a
# toolchain-specific note.  Fail now, before such bytes reach a package.
if LC_ALL=C grep -aF -m1 -- "$ROOT" "$OWL_BINARY" >/dev/null 2>&1; then
    die "built OWL contains the checkout path; inspect compiler prefix maps"
fi

printf 'built native OWL: %s\n' "$OWL_BINARY"
printf 'build directory: %s\n' "$BUILD_DIR"
printf 'source-date-epoch: %s\n' "$SOURCE_DATE_EPOCH"
