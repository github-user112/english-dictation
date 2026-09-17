import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { listenOnce, listenServerOnce, preferServerRecognition, speechErrorMessage } from "./speech";

const flush = async () => { for (let i = 0; i < 12; i++) await Promise.resolve(); };
let track, getUserMedia, decoded, decode, recording, request;
class Recorder {
  static isTypeSupported() { return true; }
  constructor() { recording = this; this.state = "inactive"; this.mimeType = "audio/webm"; }
  start() { this.state = "recording"; }
  stop() {
    this.state = "inactive";
    this.ondataavailable?.({ data: new Blob(["test recording"]) });
    this.onstop?.();
  }
}
class Request {
  constructor() { request = this; this.upload = {}; }
  open = vi.fn();
  setRequestHeader = vi.fn();
  send = vi.fn();
  abort = vi.fn();
  reply(status, data) { this.status = status; this.responseText = JSON.stringify(data); this.onload(); }
}
class AudioContext {
  decodeAudioData = (...args) => decode(...args);
  close = vi.fn(async () => {});
}
class OfflineContext {
  createBufferSource() { return { connect() {}, start() {} }; }
  async startRendering() { return { getChannelData: () => decoded }; }
  close() {}
}

beforeEach(() => {
  vi.useFakeTimers();
  track = { stop: vi.fn() };
  getUserMedia = vi.fn(async () => ({ getTracks: () => [track] }));
  vi.stubGlobal("navigator", { userAgent: "Android Mobile", mediaDevices: { getUserMedia } });
  vi.stubGlobal("MediaRecorder", Recorder);
  vi.stubGlobal("XMLHttpRequest", Request);
  vi.stubGlobal("AudioContext", AudioContext);
  vi.stubGlobal("OfflineAudioContext", OfflineContext);
  vi.stubGlobal("SpeechRecognition", vi.fn());
  // Audio decoding is mocked independently from jsdom's Blob implementation.
});
afterEach(() => { vi.useRealTimers(); vi.restoreAllMocks(); vi.unstubAllGlobals(); });

// Install Blob polyfill independently of browser version.
function setupAudio() {
  if (!Blob.prototype.arrayBuffer) Object.defineProperty(Blob.prototype, "arrayBuffer", {
    configurable: true, value: async () => new ArrayBuffer(8),
  });
  decoded = new Float32Array(16000).fill(0.1);
  decode = vi.fn(async () => ({ duration: 1 }));
  recording = null; request = null;
}

async function uploaded(options = {}) {
  setupAudio();
  const handle = listenServerOnce(options);
  await flush();
  handle.finish();
  await flush();
  return handle;
}

describe("mobile recording lifecycle", () => {
  it("chooses upload without trying native recognition and requests permission immediately", async () => {
    setupAudio();
    const handle = listenOnce();
    expect(handle.mode).toBe("server");
    expect(getUserMedia).toHaveBeenCalledOnce();
    expect(window.SpeechRecognition).not.toHaveBeenCalled();
    handle.abort();
    await flush();
    expect(track.stop).toHaveBeenCalled();
  });

  it("detects iPad desktop user agent", () => {
    vi.stubGlobal("navigator", { userAgent: "Macintosh", maxTouchPoints: 5 });
    expect(preferServerRecognition()).toBe(true);
  });

  it("emits real states, closes mic before upload and supplies replay blob", async () => {
    const onState = vi.fn(), onResult = vi.fn(), onRecording = vi.fn(), onEnd = vi.fn();
    await uploaded({ onState, onResult, onRecording, onEnd });
    expect(onState.mock.calls.map(([s]) => s)).toEqual([
      "requesting", "recording", "encoding", "encoding", "uploading",
    ]);
    expect(track.stop).toHaveBeenCalled();
    expect(onRecording.mock.calls[0][0]).toBeInstanceOf(Blob);
    request.upload.onload();
    expect(onState).toHaveBeenLastCalledWith("recognizing");
    request.reply(200, { text: "hello" });
    expect(onResult).toHaveBeenCalledWith(["hello"]);
    expect(onEnd).toHaveBeenCalledOnce();
  });

  it.each([
    [429, { code: "rate-limited" }, "rate-limited"],
    [429, {}, "service-busy"],
    [504, {}, "asr-timeout"],
    [413, {}, "audio-too-long"],
    [403, {}, "auth-failed"],
    [200, { text: " " }, "no-speech"],
    [200, {}, "asr-failed"],
    [502, {}, "asr-failed"],
  ])("classifies HTTP %s without producing a zero-score result", async (status, body, code) => {
    const onError = vi.fn(), onResult = vi.fn();
    await uploaded({ onError, onResult });
    request.reply(status, body);
    expect(onError).toHaveBeenCalledWith(code);
    expect(onResult).not.toHaveBeenCalled();
  });

  it.each([false, true])("distinguishes upload/recognition timeout (%s)", async (sent) => {
    const onError = vi.fn();
    await uploaded({ onError });
    if (sent) request.upload.onload();
    request.ontimeout();
    expect(onError).toHaveBeenCalledWith(sent ? "asr-timeout" : "upload-timeout");
  });

  it("cancels in-flight upload and ignores late events", async () => {
    const onResult = vi.fn(), onError = vi.fn(), onEnd = vi.fn();
    const handle = await uploaded({ onResult, onError, onEnd });
    handle.abort();
    request.reply(200, { text: "late result" });
    request.onerror();
    expect(request.abort).toHaveBeenCalledOnce();
    expect(onResult).not.toHaveBeenCalled();
    expect(onError).not.toHaveBeenCalled();
    expect(onEnd).toHaveBeenCalledOnce();
  });

  it("cancels while permission is pending and releases late stream", async () => {
    setupAudio();
    let grant;
    getUserMedia.mockImplementation(() => new Promise((resolve) => { grant = resolve; }));
    const handle = listenServerOnce();
    handle.abort();
    grant({ getTracks: () => [track] });
    await flush();
    expect(track.stop).toHaveBeenCalledOnce();
    expect(recording).toBeNull();
  });

  it("cancels during decoding without uploading", async () => {
    setupAudio();
    let resolveDecode;
    decode.mockImplementation(() => new Promise((resolve) => { resolveDecode = resolve; }));
    const handle = listenServerOnce();
    await flush(); handle.finish(); await flush(); handle.abort();
    resolveDecode({ duration: 1 });
    await flush();
    expect(request).toBeNull();
  });

  it.each([["NotAllowedError", "not-allowed"], ["NotFoundError", "audio-capture"],
    ["NotReadableError", "audio-capture"]])("classifies microphone %s", async (name, code) => {
    setupAudio();
    getUserMedia.mockRejectedValue({ name });
    const onError = vi.fn();
    listenServerOnce({ onError }); await flush();
    expect(onError).toHaveBeenCalledWith(code);
  });

  it("preserves recorded blob when decoding fails", async () => {
    setupAudio(); decode.mockRejectedValue(new Error("bad format"));
    const onError = vi.fn(), onRecording = vi.fn();
    const handle = listenServerOnce({ onError, onRecording });
    await flush(); handle.finish(); await flush();
    expect(onRecording).toHaveBeenCalledOnce();
    expect(onError).toHaveBeenCalledWith("decode-failed");
    expect(request).toBeNull();
  });

  it("rejects digital silence before calling ASR", async () => {
    setupAudio(); decoded.fill(0);
    const onError = vi.fn();
    const handle = listenServerOnce({ onError });
    await flush(); handle.finish(); await flush();
    expect(onError).toHaveBeenCalledWith("no-speech");
    expect(request).toBeNull();
  });

  it("automatically stops at 15 seconds and ignores repeated finish", async () => {
    setupAudio(); const onRecording = vi.fn();
    const handle = listenServerOnce({ onRecording });
    await flush(); await vi.advanceTimersByTimeAsync(15000);
    handle.finish(); await flush();
    expect(onRecording).toHaveBeenCalledOnce();
    handle.abort();
  });

  it("times out a stalled decoder without uploading", async () => {
    setupAudio(); decode.mockImplementation(() => new Promise(() => {}));
    const onError = vi.fn();
    const handle = listenServerOnce({ onError });
    await flush(); handle.finish(); await flush();
    await vi.advanceTimersByTimeAsync(15000);
    expect(onError).toHaveBeenCalledWith("decode-failed");
    expect(request).toBeNull();
  });

  it("releases recorder and stream on recording errors", async () => {
    setupAudio(); const onError = vi.fn(), onResult = vi.fn();
    listenServerOnce({ onError, onResult }); await flush();
    recording.onerror(); await flush();
    expect(recording.state).toBe("inactive");
    expect(track.stop).toHaveBeenCalled();
    expect(onError).toHaveBeenCalledWith("recording-failed");
    expect(onResult).not.toHaveBeenCalled();
    expect(request).toBeNull();
  });

  it("provides distinct user-facing errors", () => {
    const codes = ["not-allowed", "no-speech", "decode-failed", "service-busy", "asr-timeout"];
    expect(new Set(codes.map(speechErrorMessage)).size).toBe(codes.length);
  });
});
