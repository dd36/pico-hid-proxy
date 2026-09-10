#!/bin/bash
set -e

PROJECT_DIR="$(cd "$(dirname "$0")" && pwd)"
BOARD="${BOARD:-RPI_PICO2_W}"
IMAGE_TAG="pico-firmware-build"
OUT_DIR="$PROJECT_DIR/firmware"

# --clean forces a full rebuild, bypassing Docker layer cache.
BUILD_ARGS=()
for arg in "$@"; do
    case "$arg" in
        --clean) BUILD_ARGS+=(--no-cache) ;;
        *) echo "Unknown option: $arg (supported: --clean)" >&2; exit 2 ;;
    esac
done

# Version the build so images stay traceable to a commit. A "-dirty" suffix
# means it was built from uncommitted changes, which is worth knowing before
# you flash something you cannot reproduce.
VERSION="$(git -C "$PROJECT_DIR" describe --tags --always --dirty 2>/dev/null \
    || date +%Y%m%d-%H%M%S)"
BOARD_SLUG="$(echo "$BOARD" | tr '[:upper:]' '[:lower:]')"

VERSIONED="$OUT_DIR/pico-hid-proxy-$BOARD_SLUG-$VERSION.uf2"
# Stable name kept for the README and .github/workflows/release.yml.
STABLE="$OUT_DIR/pico_hid_firmware.uf2"

echo "=== Building MicroPython firmware (Docker) ==="
echo "Board:   $BOARD"
echo "Version: $VERSION"
echo ""

docker build \
    "${BUILD_ARGS[@]}" \
    --build-arg BOARD="$BOARD" \
    -t "$IMAGE_TAG" \
    "$PROJECT_DIR"

mkdir -p "$OUT_DIR"

# Extract to a temp file first so a failed build cannot clobber the previous
# image -- that copy may be the only way back from bad firmware.
TMP="$(mktemp)"
trap 'rm -f "$TMP"' EXIT
docker run --rm "$IMAGE_TAG" cat /firmware.uf2 > "$TMP"

# A UF2 starts with magic 0x0A324655 (bytes 55 46 32 0a). Catch a truncated or
# empty extraction here rather than after dragging it onto the Pico.
MAGIC="$(head -c 4 "$TMP" | xxd -p)"
if [ "$MAGIC" != "5546320a" ]; then
    echo "ERROR: output is not a UF2 image (magic '$MAGIC', expected '5546320a')" >&2
    exit 1
fi

mv "$TMP" "$VERSIONED"
trap - EXIT
chmod 644 "$VERSIONED"   # mktemp gives 600; these are meant to be shareable
cp "$VERSIONED" "$STABLE"

SIZE="$(wc -c < "$VERSIONED" | tr -d ' ')"
echo ""
echo "=== Success! ==="
echo "Versioned: $VERSIONED"
echo "Latest:    $STABLE"
echo "Size:      $SIZE bytes"
echo ""
echo "To flash: hold BOOTSEL, plug in Pico, copy either .uf2 to the drive"
echo "(the filename is irrelevant - the bootloader reads the UF2 header)"
