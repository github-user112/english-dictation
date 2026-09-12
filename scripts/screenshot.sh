#!/usr/bin/env bash
# 前端页面截图：对照 design/ 下的 Duolingo 设计稿检查实现效果。
# 依赖：chromium-browser（本机已有）+ nginx 的 mi2.cc.cd 站点（root 指向 static/）。
# 用法：
#   bash scripts/screenshot.sh <路由名> [输出目录]     # 单页：桌面 + 手机各一张
#   bash scripts/screenshot.sh all      [输出目录]     # 全量桌面版
# 例：
#   bash scripts/screenshot.sh catalog shots/duo
#   bash scripts/screenshot.sh word    shots/duo
set -euo pipefail
cd "$(dirname "$0")/.."

OUT="${2:-shots/duo}"
mkdir -p "$OUT"

# 先构建，nginx 直接服务 static/
(cd frontend && npx vite build >/dev/null 2>&1)
echo "build ok"

HOST="http://mi2.cc.cd"
CHROME=(--headless=new --disable-gpu --no-sandbox --hide-scrollbars
        --run-all-compositor-stages-before-draw --virtual-time-budget=4500
        --host-resolver-rules="MAP mi2.cc.cd 127.0.0.1")

shot() {
  local name="$1" route="$2" w="$3" h="$4"
  local f="$OUT/${name}.png"
  timeout 90 chromium-browser "${CHROME[@]}" --window-size="${w},${h}" --screenshot="$f" "$HOST/#/$route" >/dev/null 2>&1 || { echo "FAIL $name"; return 1; }
  printf "%-34s %s\n" "$name" "$(du -h "$f" | cut -f1)"
}

if [ "${1:-}" = "all" ]; then
  for p in catalog wrong daily tree stats word sentence memorize quiz sprint boss match arrange lists report import settings account leaderboard friends groups pk wordtest shadow; do
    shot "$p" "$p" 1440 1000 || true
  done
else
  [ -n "${1:-}" ] || { echo "用法: bash scripts/screenshot.sh <路由名|all> [输出目录]"; exit 1; }
  shot "desk-$1" "$1" 1440 1000
  shot "mob-$1"  "$1" 390 844
fi

echo "截图输出: $OUT"
