import { describe, expect, it } from "vitest";
import { dailyEmojiGrid, ghostScore, shareGridText } from "./progress";

describe("ghostScore", () => {
  it("开局为 0，结束时追平个人最佳", () => {
    expect(ghostScore(80, 60)).toBe(0);
    expect(ghostScore(80, 0)).toBe(80);
  });

  it("按均匀配速取整推进", () => {
    expect(ghostScore(80, 30)).toBe(40);
    expect(ghostScore(50, 45)).toBe(Math.round((50 * 15) / 60));
  });

  it("钳制越界时间并忽略非法最佳分", () => {
    expect(ghostScore(80, -5)).toBe(80);     // 超时按整局计
    expect(ghostScore(80, 90)).toBe(0);      // 未开跑
    expect(ghostScore(0, 10)).toBe(0);
    expect(ghostScore(undefined, 10)).toBe(0);
  });
});

describe("dailyEmojiGrid", () => {
  it("对错映射为绿红方块", () => {
    expect(dailyEmojiGrid([{ right: true }, { right: false }, { right: true }]))
      .toBe("🟩🟥🟩");
  });

  it("空明细返回空串", () => {
    expect(dailyEmojiGrid([])).toBe("");
    expect(dailyEmojiGrid(null)).toBe("");
  });
});

describe("shareGridText", () => {
  it("输出四行纯文本：标题 / 战绩 / 网格 / 域名", () => {
    const text = shareGridText({
      day: "2026-08-26", listTitle: "CET-4", score: 8, total: 10, streak: 3,
      detail: [{ right: true }, { right: false }],
    });
    const lines = text.split("\n");
    expect(lines).toEqual([
      "英语听打 · 每日挑战 08-26 CET-4",
      "8/10 🔥 连续打卡 3 天",
      "🟩🟥",
      "mi2.cc.cd",
    ]);
  });

  it("缺失字段时给出安全回退且不抛错", () => {
    const text = shareGridText({});
    expect(text.split("\n")[1]).toBe("0/0 🔥 连续打卡 0 天");
    expect(text.endsWith("mi2.cc.cd")).toBe(true);
  });
});
