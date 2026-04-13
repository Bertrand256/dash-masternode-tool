#!/bin/bash
set -e

APP_DIR="build/linux/AppDir"
DIST_DIR="dist/linux"
ALL_DIR="dist/all"
EXE_NAME="DashMasternodeTool"

echo "Building AppImage..."

# Create AppDir structure
mkdir -p "$APP_DIR/usr/bin"
mkdir -p "$APP_DIR/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$APP_DIR/usr/share/applications"

# Copy executable
cp "$DIST_DIR/$EXE_NAME" "$APP_DIR/usr/bin/"

# Fix executable stack on libpython if it exists in the distribution (for newer Linux versions)
# This is often needed for Fedora 42/43 or newer kernels that block executable stack by default
if [ -d "$DIST_DIR/_internal" ]; then
    find "$DIST_DIR/_internal" -name "libpython*.so*" -exec execstack -c {} +
else
    execstack -c "$DIST_DIR/$EXE_NAME" || true
fi

# Copy icon
cp "img/dmt.png" "$APP_DIR/usr/share/icons/hicolor/256x256/apps/dmt.png"
cp "img/dmt.png" "$APP_DIR/dmt.png"

# Create .desktop file
cat > "$APP_DIR/$EXE_NAME.desktop" <<EOF
[Desktop Entry]
Type=Application
Name=Dash Masternode Tool
Exec=$EXE_NAME
Icon=dmt
Categories=Office;Finance;
Comment=Dash Masternode Tool
Terminal=false
EOF

# Link desktop file to share
cp "$APP_DIR/$EXE_NAME.desktop" "$APP_DIR/usr/share/applications/"

# Create AppRun
cat > "$APP_DIR/AppRun" <<EOF
#!/bin/sh
SELF=\$(readlink -f "\$0")
HERE=\$(dirname "\$SELF")
export PATH="\$HERE/usr/bin:\$PATH"
exec "$EXE_NAME" "\$@"
EOF
chmod +x "$APP_DIR/AppRun"

# Read version
VERSION=$(cat version.txt | grep version_str | cut -d"'" -f2)

# Create AppImage
# Use ARCH=x86_64 for appimagetool
export ARCH=x86_64
APPIMAGE_FILE="DashMasternodeTool_$VERSION.AppImage"
appimagetool --appimage-extract-and-run "$APP_DIR" "$ALL_DIR/$APPIMAGE_FILE"

echo "AppImage created: $ALL_DIR/$APPIMAGE_FILE"
