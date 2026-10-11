#!/usr/bin/env bash
# Check or install UCanDrop without running setup or enabling receiving.
#
# The build always happens as the invoking user.  Only the final apt install,
# and the optional explicit build-dependency install, use sudo.  This keeps
# root from interpreting checkout-controlled shell code.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
VERSION=1.1.0
OUTPUT_DIR=${UCANDROP_OUTPUT_DIR:-$ROOT/dist}

BUILD_DEPS=(
    binutils cmake dpkg-dev g++ gcc libev-dev libnl-3-dev libnl-genl-3-dev
    libnl-route-3-dev libpcap-dev pkg-config python3
)
RUNTIME_DEPS=(
    bash bluez ca-certificates coreutils dbus desktop-file-utils ethtool
    iproute2 iw keyutils libnotify-bin libev4t64 libnl-3-200 libnl-genl-3-200
    libnl-route-3-200 libpcap0.8t64 network-manager openssl pkexec polkitd
    python3 python3-dbus python3-gi python3-ifaddr python3-libarchive-c
    python3-pil python3-zeroconf shared-mime-info systemd util-linux xdg-user-dirs
    xdg-utils
)

die() {
    printf 'ucandrop install: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage:
  tools/install.sh --check
  tools/install.sh --install [--install-build-deps]

--check                  read-only platform, dependency, and source check
--install                build as the current user, then sudo apt install the
                         resulting local package; it never runs setup or on
--install-build-deps     with --install, explicitly install build dependencies
                         through apt before building
EOF
}

MODE=
INSTALL_BUILD_DEPS=0
while (($#)); do
    case $1 in
        --check|--install)
            [[ -z $MODE ]] || die 'choose exactly one of --check or --install'
            MODE=${1#--}
            ;;
        --install-build-deps)
            INSTALL_BUILD_DEPS=1
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done
[[ -n $MODE ]] || { usage >&2; exit 2; }
[[ $EUID -ne 0 ]] || die 'run this script as an ordinary user; it uses sudo only for apt'
[[ $INSTALL_BUILD_DEPS -eq 0 || $MODE == install ]] \
    || die '--install-build-deps requires --install'

need_command() {
    command -v "$1" >/dev/null 2>&1 || die "missing command: $1"
}

for command in awk dpkg dpkg-query; do
    need_command "$command"
done
need_command python3
python3 - <<'PY' || die 'Python 3.11 or newer is required'
import sys
raise SystemExit(0 if sys.version_info >= (3, 11) else 1)
PY

read_os_value() {
    local key=$1 value
    value=$(awk -F= -v key="$key" '$1 == key {gsub(/^"|"$/, "", $2); print $2; exit}' /etc/os-release 2>/dev/null || true)
    printf '%s' "$value"
}

OS_ID=$(read_os_value ID)
OS_VERSION=$(read_os_value VERSION_ID)
[[ $OS_ID == ubuntu ]] || die "UCanDrop 1.1.0 targets Ubuntu 26.04; detected ${OS_ID:-unknown}"
[[ $OS_VERSION == 26.04 ]] || die "UCanDrop 1.1.0 targets Ubuntu 26.04; detected ${OS_VERSION:-unknown}"

ARCH=$(dpkg --print-architecture)
case $ARCH in
    amd64|arm64) ;;
    *) die "unsupported native architecture: $ARCH (supported: amd64, arm64)" ;;
esac

for input in \
    "$ROOT/tools/build.sh" "$ROOT/tools/build-deb.sh" \
    "$ROOT/client/manifest.json" "$ROOT/vendor/owl/CMakeLists.txt" \
    "$ROOT/packaging/control"; do
    [[ -e $input ]] || die "missing release input: $input"
done
grep -Eq '"version"[[:space:]]*:[[:space:]]*"1\.1\.0"' "$ROOT/client/manifest.json" \
    || die 'client/manifest.json must declare version 1.1.0'

missing_tools=()
for command in cmake cc c++ strip dpkg-deb sha256sum; do
    command -v "$command" >/dev/null 2>&1 || missing_tools+=("$command")
done
if ((${#missing_tools[@]})); then
    printf 'missing build tools: %s\n' "${missing_tools[*]}" >&2
fi

missing_packages=()
for package in "${RUNTIME_DEPS[@]}"; do
    if ! dpkg-query -W -f='${Status}\n' "$package" 2>/dev/null \
        | grep -qx 'install ok installed'; then
        missing_packages+=("$package")
    fi
done
if ((${#missing_packages[@]})); then
    printf 'runtime dependencies not installed (apt will resolve them): %s\n' \
        "${missing_packages[*]}" >&2
fi

if [[ $MODE == check ]]; then
    if ((${#missing_tools[@]} || ${#missing_packages[@]})); then
        exit 1
    fi
    printf 'platform and installed runtime dependencies are ready (%s, %s)\n' "$OS_ID" "$ARCH"
    printf 'check is read-only; receiving remains untouched\n'
    exit 0
fi

if (( INSTALL_BUILD_DEPS )); then
    need_command sudo
    need_command apt-get
    sudo -- apt-get install --no-install-recommends -y "${BUILD_DEPS[@]}"
fi

for command in cmake cc c++ strip dpkg-deb sha256sum; do
    need_command "$command"
done

# build-deb refuses root and performs all source operations before this point.
"$ROOT/tools/build-deb.sh"
PACKAGE=$OUTPUT_DIR/ucandrop_${VERSION}_${ARCH}.deb
[[ -f $PACKAGE ]] || die "package builder did not produce $PACKAGE"

need_command sudo
need_command apt
sudo -- apt install --no-install-recommends -y "$PACKAGE"

cat <<'EOF'
UCanDrop is installed with receiving disabled.

As the normal desktop user, complete setup and then choose a bounded receive
window explicitly:

  ucandrop setup
  ucandrop on

The package does not enable or start a user/system service during installation.
EOF
