/* 趣味玩法的纯函数：幽灵竞速配速、每日挑战分享文本。
   等级/树的数值全部由 /api/profile 给出，前端不做二次推导。 */

/** 幽灵竞速：个人最佳成绩按均匀配速换算到已进行时间的期望分 */
export function ghostScore(bestScore, remainSec, duration = 60) {
  if (!(bestScore > 0)) return 0;
  const elapsed = Math.min(Math.max(duration - remainSec, 0), duration);
  return Math.round((bestScore * elapsed) / duration);
}

/** 每日挑战答题明细 → Wordle 式 emoji 网格（🟩 对 / 🟥 错） */
export function dailyEmojiGrid(detail) {
  return (detail || []).map((d) => (d.right ? "🟩" : "🟥")).join("");
}

/** 分享文本：纯文本进剪贴板，不做任何 HTML 拼接 */
export function shareGridText({ day, listTitle, score = 0, total = 0, streak = 0, detail }) {
  return [
    `英语听打 · 每日挑战 ${String(day || "").slice(5)} ${(listTitle || "").trim()}`.trimEnd(),
    `${score}/${total} 🔥 连续打卡 ${streak || 0} 天`,
    dailyEmojiGrid(detail),
    "mi2.cc.cd",
  ].join("\n");
}
