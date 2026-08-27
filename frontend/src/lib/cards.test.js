/* cards.js 纯函数测试 */
import { describe, it, expect } from "vitest";
import { sprintTier, sprintShareText, pkShareText, badgeShareText } from "../lib/cards";

describe("sprintTier", () => {
  it("returns 全对封神 at 100%", () => {
    expect(sprintTier(10, 10).label).toBe("全对封神");
  });
  it("returns 词力高手 at 90% boundary", () => {
    expect(sprintTier(9, 10).label).toBe("词力高手");
  });
  it("returns 稳扎稳打 at 75% boundary", () => {
    expect(sprintTier(75, 100).label).toBe("稳扎稳打");
  });
  it("returns 继续加油 at 60% boundary", () => {
    expect(sprintTier(6, 10).label).toBe("继续加油");
  });
  it("returns 明日再战 below 60%", () => {
    expect(sprintTier(1, 10).label).toBe("明日再战");
  });
  it("returns 明日再战 when total is 0", () => {
    expect(sprintTier(0, 0).label).toBe("明日再战");
  });
  it("returns 明日再战 at 0%", () => {
    expect(sprintTier(0, 100).label).toBe("明日再战");
  });
});

describe("sprintShareText", () => {
  const m = { listTitle: "CET-4", score: 8, total: 10, combo: 5, link: "https://example.com" };
  it("contains score and total", () => {
    const t = sprintShareText(m);
    expect(t).toContain("8/10");
  });
  it("contains combo", () => {
    expect(sprintShareText(m)).toContain("连击 5");
  });
  it("contains percentage", () => {
    expect(sprintShareText(m)).toContain("正确率 80%");
  });
  it("contains link", () => {
    expect(sprintShareText(m)).toContain("https://example.com");
  });
  it("contains list title", () => {
    expect(sprintShareText(m)).toContain("CET-4");
  });
});

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
