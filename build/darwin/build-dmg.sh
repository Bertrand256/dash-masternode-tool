#!/bin/bash
set -e

# This script builds the DMG file for macOS.
# It takes one argument: architecture (x64 or arm64).

ARCH=$1
if [ -z "$ARCH" ]; then
    # Try to detect architecture if not provided
    ARCH_RAW=$(machine)
    if [[ "$ARCH_RAW" == "arm64" ]]; then
        ARCH="arm64"
    else
        ARCH="x64"
    fi
fi

echo "Building DMG for architecture: $ARCH"

# Get version from version.txt
VERSION=$(cat version.txt | grep version_str | cut -d"'" -f2)

DMG_FILE_NAME="DashMasternodeTool_$VERSION.mac-$ARCH.dmg"
DMG_TMP_DIR="dist/mac_dmg_$ARCH"
DIST_DIR="dist/darwin"
ALL_DIR="dist/all"

rm -rf "$DMG_TMP_DIR"
mkdir -p "$DMG_TMP_DIR"
mkdir -p "$ALL_DIR"

# Copy .app to temporary directory
cp -R "$DIST_DIR/DashMasternodeTool.app" "$DMG_TMP_DIR/"

# Get the project root directory (one level up from build/darwin)
# We use BASH_SOURCE to be more robust when the script is sourced or called via bash
PRJ_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"

if [ ! -f "$PRJ_DIR/img/mac-dmg-back.png" ]; then
    # Try relative to current directory as fallback
    if [ -f "img/mac-dmg-back.png" ]; then
        PRJ_DIR="$(pwd)"
    else
        echo "ERROR: Background file NOT found at $PRJ_DIR/img/mac-dmg-back.png"
        exit 1
    fi
fi

# Create DMG
create-dmg \
--volname "DMT $VERSION" \
--window-size 500 400 \
--text-size 12 \
--icon-size 72 \
--icon "DashMasternodeTool.app" 100 160 \
--app-drop-link 330 160 \
--background "$PRJ_DIR/img/mac-dmg-back.png" \
"$ALL_DIR/$DMG_FILE_NAME" \
"$DMG_TMP_DIR"

rm -rf "$DMG_TMP_DIR"

echo "DMG created: $ALL_DIR/$DMG_FILE_NAME"
