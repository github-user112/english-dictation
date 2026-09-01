/* cards.js 纯函数测试 */
import { describe, it, expect } from "vitest";
import { pkShareText, badgeShareText, weeklyShareText } from "../lib/cards";

describe("pkShareText", () => {
  const m = {
    code: "ABC",
    verdict: "你赢了！",
    rows: [
      { crown: true, name: "Alice", score: 9 },
      { crown: false, name: "Bob", score: 7 },
    ],
  };
  it("contains room code", () => {
    expect(pkShareText(m)).toContain("ABC");
  });
  it("contains verdict", () => {
    expect(pkShareText(m)).toContain("你赢了！");
  });
  it("contains both player names and scores", () => {
    const t = pkShareText(m);
    expect(t).toContain("Alice");
    expect(t).toContain("9");
    expect(t).toContain("Bob");
    expect(t).toContain("7");
  });
  it("contains crown emoji for winner", () => {
    expect(pkShareText(m)).toContain("👑");
  });
});

describe("badgeShareText", () => {
  const m = { level: 5, levelTitle: "词霸", xp: 1200, streak: 30, link: "https://example.com" };
  it("contains level and title", () => {
    const t = badgeShareText(m);
    expect(t).toContain("Lv.5");
    expect(t).toContain("词霸");
  });
  it("contains xp", () => {
    expect(badgeShareText(m)).toContain("1200 XP");
  });
  it("contains streak", () => {
    expect(badgeShareText(m)).toContain("连续打卡 30 天");
  });
  it("contains link", () => {
    expect(badgeShareText(m)).toContain("https://example.com");
  });
});

describe("weeklyShareText", () => {
  const m = { name: "小鱼", weekStart: "09.01", weekEnd: "09.07", items: 120,
              accuracy: 86, accuracyDelta: 5, memorizeRight: 40, daysActive: 6,
              streak: 12, link: "https://example.com" };
  it("包含核心数据与上周增量", () => {
    const t = weeklyShareText(m);
    expect(t).toContain("120 题");
    expect(t).toContain("86%");
    expect(t).toContain("较上周 +5%");
    expect(t).toContain("打卡 6/7 天");
    expect(t).toContain("https://example.com");
  });
  it("无上周数据时不显示增量", () => {
    expect(weeklyShareText({ ...m, accuracyDelta: null })).not.toContain("较上周");
  });
});
