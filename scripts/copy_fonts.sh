#!/usr/bin/env bash
# 前端本地字体装配：把设计稿用的 Noto Sans SC 可变字体与 Noto Color Emoji 复制到前端 public/。
# 这两份字体体积大（约 43MB），不入 git；需要时从 design/fonts/ 复制即可。
set -euo pipefail
cd "$(dirname "$0")/.."
mkdir -p frontend/public/fonts
cp -f design/fonts/NotoSansSC.ttf      frontend/public/fonts/
cp -f design/fonts/NotoColorEmoji.ttf  frontend/public/fonts/
echo "已复制字体 -> frontend/public/fonts/"
ls -lh frontend/public/fonts/
