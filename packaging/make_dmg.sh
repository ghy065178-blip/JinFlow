#!/usr/bin/env bash
# 可选：把已构建的 .app 制作成带「应用程序」快捷方式的 DMG。
# 用法：bash packaging/make_dmg.sh dist/raw/macos-arm64/JinshujuDesktop.app dist/JinFlow-macos-arm64.dmg
set -euo pipefail

APP_PATH="${1:?usage: make_dmg.sh <path-to.app> <output.dmg>}"
OUT_DMG="${2:?usage: make_dmg.sh <path-to.app> <output.dmg>}"

if [[ "$(uname -s)" != "Darwin" ]]; then
  echo "make_dmg.sh 只能在 macOS 上运行" >&2
  exit 1
fi

STAGE="$(mktemp -d)"
cp -R "$APP_PATH" "$STAGE/"
ln -s /Applications "$STAGE/Applications"
hdiutil create -volname "JinshujuDesktop" -srcfolder "$STAGE" -ov -format UDZO "$OUT_DMG"
rm -rf "$STAGE"
echo "已生成 $OUT_DMG"
