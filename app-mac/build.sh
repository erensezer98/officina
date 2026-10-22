#!/bin/bash
# Build Officina.app (native window around the Officina page) into ~/Applications. Needs the Xcode command line tools (swiftc).
set -e
cd "$(dirname "$0")"
command -v swiftc >/dev/null || { echo "swiftc not found: run  xcode-select --install"; exit 1; }
swiftc -O -o Officina Officina.swift -framework Cocoa -framework WebKit
APP="$HOME/Applications/Officina.app"; mkdir -p "$APP/Contents/MacOS" "$APP/Contents/Resources"
cp Officina "$APP/Contents/MacOS/Officina"; cp Officina.icns "$APP/Contents/Resources/Officina.icns"
cat > "$APP/Contents/Info.plist" <<PL
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
<key>CFBundleName</key><string>Officina</string><key>CFBundleExecutable</key><string>Officina</string>
<key>CFBundleIdentifier</key><string>local.officina.app</string><key>CFBundleIconFile</key><string>Officina</string>
<key>CFBundlePackageType</key><string>APPL</string><key>CFBundleShortVersionString</key><string>1.0</string>
<key>LSMinimumSystemVersion</key><string>12.0</string><key>NSHighResolutionCapable</key><true/>
<key>NSAppTransportSecurity</key><dict><key>NSAllowsLocalNetworking</key><true/></dict>
</dict></plist>
PL
rm -f Officina
echo "built: $APP"
