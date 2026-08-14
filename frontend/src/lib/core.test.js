/* 核心工具函数测试 */
import { describe, it, expect, beforeEach, vi } from "vitest";

// Mock localStorage
const localStorageMock = (() => {
  let store = {};
  return {
    getItem: vi.fn((key) => store[key] ?? null),
    setItem: vi.fn((key, value) => { store[key] = String(value); }),
    removeItem: vi.fn((key) => { delete store[key]; }),
    clear: vi.fn(() => { store = {}; }),
  };
})();
Object.defineProperty(window, "localStorage", { value: localStorageMock });

// Mock Audio
const audioMock = { preload: "", src: "", playbackRate: 1, play: vi.fn().mockResolvedValue(), pause: vi.fn() };
window.Audio = vi.fn(() => ({ ...audioMock }));

// Mock location
delete window.location;
window.location = { href: "", hash: "", search: "", pathname: "/", replaceState: vi.fn() };

// 现在导入要测试的模块
import { Settings, User, api, es, sndRight, sndWrong } from "../lib/core";

describe("Settings", () => {
  beforeEach(() => {
    localStorageMock.clear();
    Settings.set(Settings.DEFAULTS);
  });

  it("should return default values when nothing is saved", () => {
    const s = Settings.get();
    expect(s.showMeaning).toBe(true);
    expect(s.showPhonetic).toBe(true);
    expect(s.speed).toBe(1.0);
    expect(s.newPerDay).toBe(10);
    expect(s.practiceMode).toBe("assisted");
    expect(s.theme).toBe("dark");
  });

  it("should save and retrieve settings", () => {
    Settings.set({ theme: "light", speed: 0.75 });
    const s = Settings.get();
    expect(s.theme).toBe("light");
    expect(s.speed).toBe(0.75);
  });

  it("should preserve other keys when setting one", () => {
    Settings.set({ newPerDay: 20 });
    const s = Settings.get();
    expect(s.newPerDay).toBe(20);
    expect(s.showMeaning).toBe(true);
  });

  it("should migrate legacy showWord to practiceMode", () => {
    localStorageMock.setItem("dict_settings", JSON.stringify({ showWord: true }));
    const s = Settings.get();
    expect(s.practiceMode).toBe("follow");
  });

  it("should migrate legacy showWord=false to practiceMode=assisted", () => {
    localStorageMock.setItem("dict_settings", JSON.stringify({ showWord: false }));
    const s = Settings.get();
    expect(s.practiceMode).toBe("assisted");
  });
});

describe("User", () => {
  beforeEach(() => {
    localStorageMock.clear();
    window.location.search = "";
    window.location.hash = "";
  });

  it("should return empty string when no uuid is set", () => {
    expect(User.get()).toBe("");
  });

  it("should return uuid from URL", () => {
    window.location.search = "?u=testuser1234567890123456789012345678";
    expect(User.get()).toBe("testuser1234567890123456789012345678");
  });

  it("should save uuid to localStorage", () => {
    User.save("saveduser12345678901234567890123456");
    expect(localStorageMock.setItem).toHaveBeenCalledWith("dict_u", "saveduser12345678901234567890123456");
  });
});

describe("es (escape)", () => {
  it("should escape HTML special characters", () => {
    expect(es('<script>alert("xss")</script>')).toBe("&lt;script&gt;alert(&quot;xss&quot;)&lt;/script&gt;");
  });

  it("should escape ampersand", () => {
    expect(es("a & b")).toBe("a &amp; b");
  });

  it("should return empty string for empty input", () => {
    expect(es("")).toBe("");
  });
});

describe("Audio functions", () => {
  it("sndRight and sndWrong should not throw", () => {
    expect(() => { sndRight(); }).not.toThrow();
    expect(() => { sndWrong(); }).not.toThrow();
  });
});