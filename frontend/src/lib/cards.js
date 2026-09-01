/* 社交分享卡片共享件：冲刺成绩卡 / PK 战报卡 / 成就徽章卡。
 * 三张卡共用同一画布脚手架（背景、边框、页眉页脚），色值取 lib/poster 的双主题调色板；
 * 绘制函数是数据的纯函数（同一个入参画出同一张卡），文案构造与绘制分离便于测试。 */
import { roundRect } from "./poster";

const W = 900, H = 1150;
const SITE_LINE = "mi2.cc.cd · 听清每一个词，写下每一句";

/* 卡片基座：渐变底 + 角标光晕 + 描边框；返回内部坐标系供各卡续画 */
function paintBase(g, kicker, title, subtitle, dpr, P) {
  g.setTransform(dpr, 0, 0, dpr, 0, 0);
  const grad = g.createLinearGradient(0, 0, 0, H);
  grad.addColorStop(0, P.bgTop);
  grad.addColorStop(0.55, P.bgMid);
  grad.addColorStop(1, P.bgBottom);
  g.fillStyle = grad;
  g.fillRect(0, 0, W, H);

  g.fillStyle = P.glow;
  g.beginPath();
  g.arc(W / 2, 210, 190, 0, Math.PI * 2);
  g.fill();

  g.strokeStyle = P.cardStroke;
  g.lineWidth = 3;
  roundRect(g, 26, 26, W - 52, H - 52, 36);
  g.stroke();

  g.textAlign = "center";
  g.fillStyle = P.dim;
  g.font = "600 26px 'PingFang SC',sans-serif";
  g.fillText(kicker, W / 2, 92);
  g.fillStyle = P.title;
  g.font = "700 44px 'PingFang SC',sans-serif";
  g.fillText(title, W / 2, 152);
  if (subtitle) {
    g.fillStyle = P.sub;
    g.font = "400 26px 'PingFang SC',sans-serif";
    g.fillText(subtitle, W / 2, 196);
  }
}

function paintFooter(g, dpr, P) {
  g.textAlign = "center";
  g.fillStyle = P.dim;
  g.font = "500 24px 'PingFang SC',sans-serif";
  g.fillText(SITE_LINE, W / 2, H - 60);
}

function chip(g, x, y, w, h, fill, P) {
  g.fillStyle = fill || P.cardFill;
  roundRect(g, x, y, w, h, 20);
  g.fill();
  g.strokeStyle = P.cardStroke;
  g.lineWidth = 2;
  roundRect(g, x, y, w, h, 20);
  g.stroke();
}

/* 冲刺等级口径：正确率分档，颜色随主题（dark 取暖金绿红三系） */
export function sprintTier(score, total) {
  const acc = total > 0 ? (score / total) * 100 : 0;
  if (acc >= 100) return { label: "全对封神", color: "#ffd37a" };
  if (acc >= 90)  return { label: "词力高手", color: "#3edc97" };
  if (acc >= 75)  return { label: "稳扎稳打", color: "#5fb0ff" };
  if (acc >= 60)  return { label: "继续加油", color: "#f5a83c" };
  return { label: "明日再战", color: "#ff8a9a" };
}

export function paintSprintCard(cv, m, dpr, P) {
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext("2d");
  const tier = sprintTier(m.score, m.total);
  paintBase(g, "LIMITED SPRINT · 限时冲刺",
            `${m.name} 的冲刺成绩`, `${m.listTitle} · 共 ${m.total} 词`, dpr, P);

  chip(g, (W - 520) / 2, 320, 520, 300, P.cardFill, P);
  g.fillStyle = P.big;
  g.font = "700 150px 'Avenir Next','PingFang SC',sans-serif";
  g.fillText(String(m.score), W / 2, 480);
  g.fillStyle = P.label;
  g.font = "500 28px 'PingFang SC',sans-serif";
  g.fillText("答对词数", W / 2, 546);

  const stats = [
    ["连击", m.combo], ["词汇总数", m.total],
    ["正确率", `${Math.round((m.score / Math.max(1, m.total)) * 100)}%`],
  ];
  stats.forEach(([lab, val], i) => {
    const bw = 250, gap = 30;
    const x = (W - bw * 3 - gap * 2) / 2 + i * (bw + gap);
    chip(g, x, 668, bw, 130, P.cardFill, P);
    g.textAlign = "center";
    g.fillStyle = P.num;
    g.font = "700 44px 'Avenir Next','PingFang SC',sans-serif";
    g.fillText(String(val), x + bw / 2, 726);
    g.fillStyle = P.label;
    g.font = "400 24px 'PingFang SC',sans-serif";
    g.fillText(lab, x + bw / 2, 768);
  });

  const bw2 = 420;
  chip(g, (W - bw2) / 2, 856, bw2, 96, "rgba(0,0,0,.001)", P);
  g.fillStyle = tier.color;
  g.font = "700 40px 'PingFang SC',sans-serif";
  g.fillText(tier.label, W / 2, 916);
  paintFooter(g, dpr, P);
}

export function paintPkCard(cv, m, dpr, P) {
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext("2d");
  paintBase(g, "REALTIME BATTLE · 实时对战",
            `${m.verdict}`, `${m.listTitle} · 房间口令 ${m.code}`, dpr, P);

  const rowH = 200, rowW = 620;
  m.rows.forEach((p, i) => {
    const x = (W - rowW) / 2, y = 300 + i * (rowH + 40);
    chip(g, x, y, rowW, rowH, P.cardFill, P);
    g.textAlign = "left";
    g.fillStyle = p.crown ? P.big : P.num;
    g.font = "600 34px 'PingFang SC',sans-serif";
    g.fillText(`${p.crown ? "👑 " : ""}${p.name}`, x + 40, y + 72);
    g.textAlign = "right";
    g.fillStyle = p.crown ? P.big : P.label;
    g.font = "700 76px 'Avenir Next',sans-serif";
    g.fillText(String(p.score), x + rowW - 40, y + 128);
    g.textAlign = "center";
    g.fillStyle = P.dim;
    g.font = "400 22px 'PingFang SC',sans-serif";
    g.fillText(p.finished ? "已交卷" : "未完赛", x + 110, y + rowH - 32);
  });
  // 中央 VS 徽章压在两行之间
  const cy = 300 + rowH + 20;
  g.fillStyle = P.bgTop;
  g.beginPath();
  g.arc(W / 2, cy, 46, 0, Math.PI * 2);
  g.fill();
  g.strokeStyle = P.cardStroke;
  g.lineWidth = 3;
  g.stroke();
  g.fillStyle = P.title;
  g.font = "700 34px 'Avenir Next',sans-serif";
  g.fillText("VS", W / 2, cy + 12);
  paintFooter(g, dpr, P);
}

export function paintBadgeCard(cv, m, dpr, P) {
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext("2d");
  paintBase(g, "ACHIEVEMENT · 成就徽章",
            `${m.name} 的学习勋章`, `累计经验 ${m.xp} XP`, dpr, P);

  // 徽章主体：圆环 + 等级数字
  const cx = W / 2, cyc = 470;
  g.strokeStyle = P.big;
  g.lineWidth = 14;
  g.beginPath();
  g.arc(cx, cyc, 170, 0, Math.PI * 2);
  g.stroke();
  g.strokeStyle = P.cardStroke;
  g.lineWidth = 3;
  g.beginPath();
  g.arc(cx, cyc, 200, 0, Math.PI * 2);
  g.stroke();
  g.fillStyle = P.big;
  g.font = "700 130px 'Avenir Next',sans-serif";
  g.fillText(`Lv.${m.level}`, cx, cyc + 30);

  chip(g, (W - 500) / 2, 748, 500, 96, P.cardFill, P);
  g.fillStyle = P.num;
  g.font = "700 42px 'PingFang SC',sans-serif";
  g.fillText(m.levelTitle, W / 2, 808);

  const stats = [["连续打卡", `${m.streak} 天`], ["累计经验", `${m.xp} XP`]];
  stats.forEach(([lab, val], i) => {
    const bw = 360, gap = 30;
    const x = (W - bw * 2 - gap) / 2 + i * (bw + gap);
    chip(g, x, 890, bw, 120, P.cardFill, P);
    g.fillStyle = P.num;
    g.font = "700 38px 'Avenir Next','PingFang SC',sans-serif";
    g.fillText(val, x + bw / 2, 946);
    g.fillStyle = P.label;
    g.font = "400 24px 'PingFang SC',sans-serif";
    g.fillText(lab, x + bw / 2, 984);
  });
  paintFooter(g, dpr, P);
}

export function paintWeeklyCard(cv, m, dpr, P) {
  cv.width = W * dpr;
  cv.height = H * dpr;
  const g = cv.getContext("2d");
  paintBase(g, "WEEKLY REPORT · 学习周报",
            `${m.name} 的一周`, `${m.weekStart} ~ ${m.weekEnd}`, dpr, P);

  chip(g, (W - 520) / 2, 300, 520, 280, P.cardFill, P);
  g.fillStyle = P.big;
  g.font = "700 140px 'Avenir Next','PingFang SC',sans-serif";
  g.fillText(String(m.items), W / 2, 450);
  g.fillStyle = P.label;
  g.font = "500 28px 'PingFang SC',sans-serif";
  g.fillText("本周听写（题）", W / 2, 512);

  const delta = m.accuracyDelta == null ? "" :
    (m.accuracyDelta >= 0 ? ` ↑${m.accuracyDelta}` : ` ↓${Math.abs(m.accuracyDelta)}`);
  const stats = [
    ["首答正确率", `${m.accuracy}%${delta}`],
    ["背词答对", m.memorizeRight],
    ["打卡天数", `${m.daysActive}/7`],
    ["连续打卡", `${m.streak} 天`],
  ];
  stats.forEach(([lab, val], i) => {
    const bw = 300, gap = 24;
    const x = (W - bw * 2 - gap) / 2 + (i % 2) * (bw + gap);
    const y = 640 + Math.floor(i / 2) * (140 + gap);
    chip(g, x, y, bw, 140, P.cardFill, P);
    g.textAlign = "center";
    g.fillStyle = P.num;
    g.font = "700 42px 'Avenir Next','PingFang SC',sans-serif";
    g.fillText(String(val), x + bw / 2, y + 66);
    g.fillStyle = P.label;
    g.font = "400 23px 'PingFang SC',sans-serif";
    g.fillText(lab, x + bw / 2, y + 106);
  });
  paintFooter(g, dpr, P);
}

/* ---- 分享文案：纯字符串拼接，与画布内容一致 ---- */

export function sprintShareText(m) {
  const pct = Math.round((m.score / Math.max(1, m.total)) * 100);
  return `⏱ 我在「${m.listTitle}」限时冲刺拿下 ${m.score}/${m.total} 词，连击 ${m.combo}，正确率 ${pct}%！来和我比比谁听得准 → ${m.link}`;
}

export function pkShareText(m) {
  const line = m.rows.map((p) => `${p.crown ? "👑" : "　"}${p.name} ${p.score}`).join("\n");
  return `⚔️ 实时对战战报（房间 ${m.code}）\n${line}\n${m.verdict}\n${SITE_LINE}`;
}

export function badgeShareText(m) {
  return `🎖 我的听写勋章：Lv.${m.level} ${m.levelTitle}（${m.xp} XP，连续打卡 ${m.streak} 天）！一起坚持听清每一个词 → ${m.link}`;
}

export function weeklyShareText(m) {
  const delta = m.accuracyDelta == null ? "" :
    `（较上周 ${m.accuracyDelta >= 0 ? "+" : ""}${m.accuracyDelta}%）`;
  return `📅 我的听写周报（${m.weekStart}~${m.weekEnd}）\n听写 ${m.items} 题 · 首答正确率 ${m.accuracy}%${delta} · 背词答对 ${m.memorizeRight} 个 · 打卡 ${m.daysActive}/7 天\n一起来听清每一个词 → ${m.link}`;
}
