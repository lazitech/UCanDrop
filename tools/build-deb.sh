#!/usr/bin/env bash
# Build the complete native-architecture UCanDrop Debian package.
#
# The package is assembled directly with dpkg-deb so this script is usable
# from a clean checkout without a debian/ directory.  It does not need root:
# --root-owner-group records root ownership in the archive while all staging
# happens in a caller-owned temporary directory.
set -Eeuo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd -P)
BUILD_DIR=${UCANDROP_BUILD_DIR:-$ROOT/build}
OUTPUT_DIR=${UCANDROP_OUTPUT_DIR:-$ROOT/dist}
SOURCE_DATE_EPOCH=${SOURCE_DATE_EPOCH:-1791590400}
VERSION=1.1.0
PACKAGE=ucandrop

die() {
    printf 'ucandrop package: %s\n' "$*" >&2
    exit 1
}

usage() {
    cat <<'EOF'
Usage: tools/build-deb.sh [--clean] [--jobs N]

Build the native-architecture ucandrop_1.1.0_<arch>.deb.  Set
UCANDROP_BUILD_DIR or UCANDROP_OUTPUT_DIR to select caller-owned directories.
SOURCE_DATE_EPOCH defaults to the fixed 1.1.0 release epoch and may be set by
the release environment.
EOF
}

BUILD_ARGS=()
while (($#)); do
    case $1 in
        --clean|--jobs)
            BUILD_ARGS+=("$1")
            if [[ $1 == --jobs ]]; then
                (($# >= 2)) || die '--jobs needs a positive integer'
                BUILD_ARGS+=("$2")
                shift
            fi
            ;;
        --help|-h)
            usage
            exit 0
            ;;
        *) die "unknown option: $1" ;;
    esac
    shift
done

[[ ${EUID:-$(id -u)} -ne 0 ]] || die 'run as an ordinary user; packaging never needs root'
[[ $SOURCE_DATE_EPOCH =~ ^[0-9]+$ ]] || die 'SOURCE_DATE_EPOCH must be an integer'
export SOURCE_DATE_EPOCH
command -v dpkg >/dev/null 2>&1 || die 'dpkg is required'
command -v dpkg-deb >/dev/null 2>&1 || die 'dpkg-deb is required'
command -v sha256sum >/dev/null 2>&1 || die 'sha256sum is required'

mkdir -p "$BUILD_DIR" "$OUTPUT_DIR"
BUILD_DIR=$(cd -- "$BUILD_DIR" && pwd -P)
OUTPUT_DIR=$(cd -- "$OUTPUT_DIR" && pwd -P)
export UCANDROP_BUILD_DIR="$BUILD_DIR"

ARCH=$(dpkg --print-architecture)
case $ARCH in
    amd64|arm64) ;;
    *) die "unsupported native architecture: $ARCH (supported: amd64, arm64)" ;;
esac

# Contacts Only verification uses the vendored Apple root and issuing CAs;
# these are release inputs, not optional system trust-store files.
for required in \
    "$ROOT/client/bin/ucandrop" \
    "$ROOT/client/manifest.json" \
    "$ROOT/client/share/certs/apple_root_ca.pem" \
    "$ROOT/client/bin/apple-ca/apple-aai-ca.pem" \
    "$ROOT/client/bin/apple-ca/apple-aai2-ca.pem" \
    "$ROOT/client/share/ucandrop-receiver.service" \
    "$ROOT/receiver" \
    "$ROOT/radio/lib" \
    "$ROOT/vendor/owl" \
    "$ROOT/THIRD_PARTY_NOTICES.md" \
    "$ROOT/packaging/ucandrop-radio.policy" \
    "$ROOT/packaging/ucandrop-networkmanager.conf" \
    "$ROOT/packaging/control" \
    "$ROOT/packaging/copyright" \
    "$ROOT/packaging/README.Debian"; do
    [[ -e $required ]] || die "required release input is missing: $required"
done

for certificate in \
    "$ROOT/client/share/certs/apple_root_ca.pem" \
    "$ROOT/client/bin/apple-ca/apple-aai-ca.pem" \
    "$ROOT/client/bin/apple-ca/apple-aai2-ca.pem"; do
    [[ -f $certificate && -s $certificate ]] \
        || die "certificate release input is missing or empty: $certificate"
done

if ! grep -Eq '"version"[[:space:]]*:[[:space:]]*"1\.1\.0"' "$ROOT/client/manifest.json"; then
    die 'client/manifest.json must declare version 1.1.0 before packaging'
fi

"$ROOT/tools/build.sh" "${BUILD_ARGS[@]}"
OWL_BINARY=$BUILD_DIR/owl/daemon/owl
[[ -x $OWL_BINARY ]] || die "missing built OWL binary: $OWL_BINARY"

STAGE=$(mktemp -d "${TMPDIR:-/tmp}/ucandrop-package.XXXXXX")
cleanup() {
    rm -rf -- "$STAGE"
}
trap cleanup EXIT

PKG_ROOT=$STAGE/root
DEBIAN=$PKG_ROOT/DEBIAN
CLIENT=$PKG_ROOT/usr/lib/ucandrop/client
RADIO=$PKG_ROOT/usr/lib/ucandrop/radio
RECEIVER=$PKG_ROOT/usr/lib/ucandrop/receiver
DOC=$PKG_ROOT/usr/share/doc/ucandrop
mkdir -p "$DEBIAN" "$CLIENT/bin/apple-ca" "$CLIENT/share" \
    "$RADIO" "$RECEIVER" "$DOC/licenses" "$PKG_ROOT/usr/bin"

# Copy only release inputs.  Build/dist directories and test fixtures never
# enter the package.  Require the UCanDrop CLI to avoid accidentally packaging
# a legacy entrypoint.
cp -a "$ROOT/client/bin/." "$CLIENT/bin/"
# The only public command is client/bin/ucandrop.
rm -f -- "$CLIENT/bin/omdrop"
cp -a "$ROOT/client/share/." "$CLIENT/share/"
cp -a "$ROOT/client/manifest.json" "$CLIENT/manifest.json"
cp -a "$ROOT/client/LICENSE" "$CLIENT/LICENSE"
cp -a "$ROOT/receiver/." "$RECEIVER/"
cp -a "$ROOT/radio/lib/." "$RADIO/"
install -m 0755 "$OWL_BINARY" "$RADIO/owl"

# Keep the trust material coupled to the code paths in contacts.py.  A source
# file can exist while a copy/glob change silently drops it from staging, so
# check both presence and byte-for-byte identity before building the archive.
check_staged_certificate() {
    local source=$1
    local staged=$2
    [[ -f $staged && -s $staged ]] \
        || die "certificate asset missing from package staging: $staged"
    cmp -s "$source" "$staged" \
        || die "certificate asset changed while staging: $staged"
}
check_staged_certificate \
    "$ROOT/client/share/certs/apple_root_ca.pem" \
    "$CLIENT/share/certs/apple_root_ca.pem"
check_staged_certificate \
    "$ROOT/client/bin/apple-ca/apple-aai-ca.pem" \
    "$CLIENT/bin/apple-ca/apple-aai-ca.pem"
check_staged_certificate \
    "$ROOT/client/bin/apple-ca/apple-aai2-ca.pem" \
    "$CLIENT/bin/apple-ca/apple-aai2-ca.pem"

# Source checkouts sometimes contain interpreter caches from local tests.  They
# are generated, can retain checkout strings, and have no place in a release.
find "$CLIENT" "$RADIO" "$RECEIVER" -type f \
    \( -name '*.pyc' -o -name '*.pyo' -o -name '*.tmp' -o -name '*.temp' -o -name '*~' \) -delete
find "$CLIENT" "$RADIO" "$RECEIVER" -type d \
    \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) \
    -prune -exec rm -rf -- {} +
if find "$CLIENT" "$RADIO" "$RECEIVER" -type f \
    \( -name '*.pyc' -o -name '*.pyo' -o -name '*.tmp' -o -name '*.temp' -o -name '*~' \) \
    -print -quit | grep -q .; then
    die 'generated bytecode or temporary files remained in package staging'
fi
if find "$CLIENT" "$RADIO" "$RECEIVER" -type d \
    \( -name __pycache__ -o -name .pytest_cache -o -name .mypy_cache -o -name .ruff_cache \) \
    -print -quit | grep -q .; then
    die 'generated cache directories remained in package staging'
fi

# Package the policy fragments supplied by this source tree.
install -Dm0644 "$ROOT/packaging/ucandrop-radio.policy" \
    "$PKG_ROOT/usr/share/polkit-1/actions/ucandrop-radio.policy"
install -Dm0644 "$ROOT/packaging/ucandrop-networkmanager.conf" \
    "$PKG_ROOT/usr/lib/NetworkManager/conf.d/ucandrop-networkmanager.conf"

# The public command is the new UCanDrop entrypoint.  There is intentionally
# no /usr/bin/omdrop link and no package-owned systemd enablement.
ln -s ../lib/ucandrop/client/bin/ucandrop "$PKG_ROOT/usr/bin/ucandrop"

cp -a "$ROOT/LICENSE" "$DOC/LICENSE"
cp -a "$ROOT/README.md" "$DOC/README.md"
cp -a "$ROOT/README.zh-CN.md" "$DOC/README.zh-CN.md"
cp -a "$ROOT/CHANGELOG.md" "$DOC/CHANGELOG.md"
install -Dm0644 "$ROOT/docs/validation.md" "$DOC/docs/validation.md"
cp -a "$ROOT/THIRD_PARTY_NOTICES.md" "$DOC/THIRD_PARTY_NOTICES.md"
cp -a "$ROOT/packaging/README.Debian" "$DOC/README.Debian"
cp -a "$ROOT/packaging/copyright" "$DOC/copyright"
cp -a "$ROOT/licenses/." "$DOC/licenses/"
if [[ -f $ROOT/vendor/owl/googletest/LICENSE ]]; then
    install -m 0644 "$ROOT/vendor/owl/googletest/LICENSE" "$DOC/licenses/googletest-BSD-3-Clause.txt"
fi
if [[ -f $ROOT/vendor/owl/radiotap/COPYING ]]; then
    install -m 0644 "$ROOT/vendor/owl/radiotap/COPYING" "$DOC/licenses/radiotap-COPYING.txt"
fi

owl_source_hash=$(
    cd "$ROOT"
    find vendor/owl -type f -not -path 'vendor/owl/build/*' -not -path 'vendor/owl/.git/*' -print0 \
        | LC_ALL=C sort -z \
        | xargs -0 sha256sum \
        | sha256sum \
        | awk '{print $1}'
)
manifest_hash=$(sha256sum "$ROOT/client/manifest.json" | awk '{print $1}')
{
    printf 'source-package=%s\n' "$PACKAGE"
    printf 'source-version=%s\n' "$VERSION"
    printf 'architecture=%s\n' "$ARCH"
    printf 'source-date-epoch=%s\n' "$SOURCE_DATE_EPOCH"
    printf 'owl-vendored-tree-sha256=%s\n' "$owl_source_hash"
    printf 'client-manifest-sha256=%s\n' "$manifest_hash"
} > "$DOC/source-provenance.txt"

CONTROL_TEMPLATE=$ROOT/packaging/control
sed "s/@ARCH@/$ARCH/g; s/@VERSION@/$VERSION/g" "$CONTROL_TEMPLATE" > "$DEBIAN/control"

# Source checkouts are commonly group-writable.  Installed package content is
# root-owned and must not retain those write bits; only the public command,
# radio launcher scripts, and native binary need execute permission.
find "$PKG_ROOT" -type d -exec chmod 0755 {} +
find "$PKG_ROOT" -type f -exec chmod 0644 {} +
chmod 0755 "$CLIENT/bin/ucandrop" "$RADIO/omdrop-discoverable" \
    "$RADIO/send-to-peer" "$RADIO/owl"
if find "$PKG_ROOT" \( -type f -o -type d \) -perm /022 -print -quit | grep -q .; then
    die 'package staging contains group/world-writable files'
fi

# Make all archive timestamps stable, including directories and control files.
find "$PKG_ROOT" -exec touch --no-dereference --date="@$SOURCE_DATE_EPOCH" {} +

# Debian packages must contain root-owned files.  dpkg-deb applies that
# ownership in the archive even though the caller remains unprivileged.
OUTPUT=$OUTPUT_DIR/${PACKAGE}_${VERSION}_${ARCH}.deb
rm -f -- "$OUTPUT"
dpkg-deb --build --root-owner-group -Zxz -z9 "$PKG_ROOT" "$OUTPUT" >/dev/null

# Validate the archive before returning it.  This catches accidental checkout,
# build, or personal-home paths, and makes the no-legacy-entrypoint contract
# executable rather than a documentation promise.
LISTING=$(dpkg-deb -c "$OUTPUT")
if grep -E '/(build|dist)/|/home/|/root/|/usr/lib/omdrop|/usr/bin/omdrop|(__pycache__|\.pytest_cache|\.mypy_cache|\.ruff_cache|\.py[co]$|\.tmp$|\.temp$|~$)' <<<"$LISTING" >/dev/null; then
    die "package contains a build, personal, or legacy path"
fi
grep -q 'usr/bin/ucandrop -> ../lib/ucandrop/client/bin/ucandrop' <<<"$LISTING" \
    || die 'package is missing the ucandrop command link'
grep -q 'usr/lib/ucandrop/radio/owl$' <<<"$LISTING" \
    || die 'package is missing the native OWL binary'
for certificate in \
    'usr/lib/ucandrop/client/share/certs/apple_root_ca.pem' \
    'usr/lib/ucandrop/client/bin/apple-ca/apple-aai-ca.pem' \
    'usr/lib/ucandrop/client/bin/apple-ca/apple-aai2-ca.pem'; do
    grep -q -- "$certificate" <<<"$LISTING" \
        || die "package is missing certificate asset: $certificate"
done
if LC_ALL=C grep -aF -m1 -- "$ROOT" "$OUTPUT" >/dev/null 2>&1; then
    die 'package contains the source checkout path'
fi

printf 'built %s\n' "$OUTPUT"
