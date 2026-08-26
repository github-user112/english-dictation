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
import { Settings, User, api, sndRight, sndWrong, audioEl, stopAudio } from "../lib/core";

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
    expect(s.theme).toBe("light");   // 默认亮色：暖琥珀主题
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

  it("should not persist uuid in localStorage", () => {
    expect(User.save).toBeUndefined();
    expect(localStorageMock.getItem("dict_u")).toBeNull();
  });
});

describe("Audio functions", () => {
  it("sndRight and sndWrong should not throw", () => {
    expect(() => { sndRight(); }).not.toThrow();
    expect(() => { sndWrong(); }).not.toThrow();
  });

  it("stops and clears active audio", () => {
    const pause = vi.spyOn(audioEl, "pause").mockImplementation(() => {});
    const load = vi.spyOn(audioEl, "load").mockImplementation(() => {});
    audioEl.src = "/audio/example.mp3";
    stopAudio();
    expect(pause).toHaveBeenCalled();
    expect(audioEl.getAttribute("src")).toBeNull();
    pause.mockRestore();
    load.mockRestore();
  });
});

describe("API failures", () => {

  it("should attach the browser CSRF token to API calls", async () => {
    Object.defineProperty(document, "cookie", { configurable: true, value: "dict_csrf=token-123" });
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: true, status: 200, text: async () => "{}" }));
    await api("/stats");
    expect(fetch).toHaveBeenCalledWith("/api/stats", expect.objectContaining({
      credentials: "same-origin",
      headers: expect.objectContaining({ "X-CSRF-Token": "token-123" }),
    }));
    vi.unstubAllGlobals();
  });

  it("should expose a useful message when an upstream response is not JSON", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 502, text: async () => "<html>bad gateway</html>" }));
    await expect(api("/lists")).rejects.toThrow("请求失败 (502)");
    vi.unstubAllGlobals();
  });
});
