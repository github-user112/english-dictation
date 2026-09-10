/* 跟读打分模块测试 */
import { describe, it, expect, vi, beforeEach } from "vitest";
import { scorePronunciation, bestAlternativeScore, scoreSentence, bestSentenceScore, listenOnce, speechSupported } from "../lib/speech";

describe("scorePronunciation", () => {
  it("should give 100 for exact word", () => {
    expect(scorePronunciation("hello", "hello").score).toBe(100);
  });

  it("should find the target word inside a sentence", () => {
    const r = scorePronunciation("world", "hello world");
    expect(r.score).toBe(100);
    expect(r.hit).toBe("world");
  });

  it("should ignore punctuation and case", () => {
    expect(scorePronunciation("Hello", "Hello!").score).toBe(100);
  });

  it("should give partial credit for close misspellings", () => {
    const r = scorePronunciation("apple", "appl");
    expect(r.score).toBeGreaterThanOrEqual(70);
    expect(r.score).toBeLessThan(100);
  });

  it("should credit prefix containment like accept -> accepting", () => {
    const r = scorePronunciation("accept", "accepting");
    expect(r.score).toBe(67);  // 6/9
    expect(r.hit).toBe("accepting");
  });

  it("should score unrelated words low", () => {
    expect(scorePronunciation("apple", "banana").score).toBeLessThan(40);
  });

  it("should return 0 for empty input", () => {
    expect(scorePronunciation("apple", "").score).toBe(0);
    expect(scorePronunciation("", "apple").score).toBe(0);
  });
});

describe("bestAlternativeScore", () => {
  it("should pick the best among alternatives", () => {
    const r = bestAlternativeScore("world", ["word", "hello world", "xyz"]);
    expect(r.score).toBe(100);
  });

  it("should tolerate null alternatives", () => {
    expect(bestAlternativeScore("world", null).score).toBe(0);
  });
});

describe("scoreSentence", () => {
  it("should give 100 for an exact sentence", () => {
    expect(scoreSentence("I am fine.", "I am fine").score).toBe(100);
  });

  it("should ignore case and punctuation", () => {
    expect(scoreSentence("Excuse me!", "excuse me,").score).toBe(100);
  });

  it("should penalize a missed word", () => {
    const r = scoreSentence("I am very fine", "I am fine");
    expect(r.score).toBe(75);   // 漏 1 词 / 4 词
  });

  it("should penalize extra words", () => {
    const r = scoreSentence("I am fine", "I am fine thank you");
    expect(r.score).toBe(60);   // 多 2 词 / 5 词
  });

  it("should score an unrelated sentence low", () => {
    expect(scoreSentence("I am fine", "totally different words here").score).toBeLessThan(40);
  });

  it("should return 0 for empty input", () => {
    expect(scoreSentence("hello", "").score).toBe(0);
    expect(scoreSentence("", "hello").score).toBe(0);
  });

  it("bestSentenceScore picks the best alternative", () => {
    const r = bestSentenceScore("thank you very much", ["thank very much", "thank you very much"]);
    expect(r.score).toBe(100);
    expect(bestSentenceScore("hello", null).score).toBe(0);
  });
});

describe("listenOnce", () => {
  class FakeSR {
    start() { FakeSR.lastStarted = this; }
  }
  beforeEach(() => {
    FakeSR.lastStarted = null;
    window.SpeechRecognition = FakeSR;
  });

  it("should start recognition with lang and alternatives", () => {
    const rec = listenOnce({ onResult: vi.fn(), onError: vi.fn() });
    expect(rec).toBeInstanceOf(FakeSR);
    expect(rec.lang).toBe("en-US");
    expect(rec.maxAlternatives).toBe(3);
  });

  it("should collect all alternatives from the result event", () => {
    const onResult = vi.fn();
    listenOnce({ onResult });
    const evt = { results: [[{ transcript: "word" }, { transcript: "world" }]] };
    FakeSR.lastStarted.onresult(evt);
    expect(onResult).toHaveBeenCalledWith(["word", "world"]);
  });

  it("should report errors through onError", () => {
    const onError = vi.fn();
    listenOnce({ onError });
    FakeSR.lastStarted.onerror({ error: "not-allowed" });
    expect(onError).toHaveBeenCalledWith("not-allowed");
  });

  it("should flag unsupported environments via speechSupported", () => {
    expect(speechSupported()).toBe(true);
    delete window.SpeechRecognition;
    delete window.webkitSpeechRecognition;
    expect(speechSupported()).toBe(false);
    const onError = vi.fn();
    expect(listenOnce({ onError })).toBeNull();
    expect(onError).toHaveBeenCalledWith("unsupported");
  });

  it("should surface start failures and return null", () => {
    class BoomSR { start() { throw new Error("busy"); } }
    window.SpeechRecognition = BoomSR;
    const onError = vi.fn();
    expect(listenOnce({ onError })).toBeNull();
    expect(onError).toHaveBeenCalledWith("start-failed");
  });
});
