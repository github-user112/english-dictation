/* cards.js 纯函数测试 */
import { describe, it, expect } from "vitest";
import { pkShareText, badgeShareText } from "../lib/cards";

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
