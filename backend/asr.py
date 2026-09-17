"""服务端语音识别（ASR）兜底：安卓 MIUI 浏览器 / Edge 的 SpeechRecognition 是空壳
（API 存在但永远 not-allowed），而 getUserMedia 录音正常。
前端录 16kHz WAV 上传 → 转发 Cloudflare Workers AI Whisper → 返回文本，
打分逻辑仍在前端。只返回识别文本、不记账——没有可伪造的成绩面。"""
import base64
import subprocess
import threading
import time
from collections import defaultdict, deque

import requests
from flask import Blueprint, jsonify, request

from .auth import get_user, resp
from .config import ASR_MODEL, CF_ACCOUNT_ID, CONFIG, cf_api_token

bp = Blueprint("asr", __name__)

_MAX_AUDIO_BYTES = 900 * 1024   # nginx client_max_body_size 是 1m，留余量
_USERS_MAX = 1024               # 限流表上限，口径同 misc.py 的 TTS 限流

_rate_lock = threading.Lock()
_requests = defaultdict(deque)
_slots = threading.BoundedSemaphore(CONFIG["asr_max_concurrency"])

_notify_lock = threading.Lock()
_last_notify = 0.0              # 企业微信告警节流：1 小时最多 1 条，防刷


def _notify_failure(detail):
    """上游（CF Whisper）失败告警。不区分额度用尽/网络故障——响应体片段会带出来，
    免费套餐超量本身就是报错（error code 在 detail 里）。"""
    global _last_notify
    now = time.monotonic()
    with _notify_lock:
        if now - _last_notify < 3600:
            return
        _last_notify = now
    try:
        subprocess.Popen(
            ["/usr/local/bin/wecom_notify", "英语听打 ASR 告警",
             f"Cloudflare Whisper 识别失败（可能额度用尽）：\n{detail[:300]}"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass   # 告警脚本缺失不影响主流程


def _allow(user):
    """滑动窗口限流（每小时 N 次/用户），与 misc._allow_tts_request 同逻辑、独立额度：
    跟读是逐句调用，频率远高于 TTS 懒生成，共用一个桶会互相挤占。"""
    limit = CONFIG["asr_rate_limit_per_hour"]
    if limit <= 0:
        return True
    now = time.monotonic()
    cutoff = now - 3600
    with _rate_lock:
        if len(_requests) >= _USERS_MAX:
            expired = [k for k, recent in _requests.items() if not recent or recent[-1] <= cutoff]
            for k in expired:
                del _requests[k]
        recent = _requests[user]
        while recent and recent[0] <= cutoff:
            recent.popleft()
        if len(recent) >= limit:
            return False
        recent.append(now)
    return True


@bp.post("/api/asr")
def api_asr():
    user = get_user()
    audio = request.get_data()
    if not audio or len(audio) < 500:
        return jsonify({"error": "录音太短", "code": "no-speech"}), 400
    if len(audio) > _MAX_AUDIO_BYTES:
        return jsonify({"error": "录音太长", "code": "audio-too-long"}), 413
    token = cf_api_token()
    if not token:
        return jsonify({"error": "语音识别服务未配置", "code": "service-unavailable"}), 503
    if not _allow(user):
        return jsonify({"error": "识别请求过于频繁，请稍后再试", "code": "rate-limited"}), 429
    if not _slots.acquire(blocking=False):
        return jsonify({"error": "识别服务忙，请稍后重试", "code": "service-busy"}), 429
    try:
        r = requests.post(
            f"https://api.cloudflare.com/client/v4/accounts/{CF_ACCOUNT_ID}/ai/run/{ASR_MODEL}",
            headers={"Authorization": f"Bearer {token}"},
            json={"audio": base64.b64encode(audio).decode()},   # turbo 只收 JSON+base64
            timeout=25,
        )
        # 先判断 HTTP 状态：上游限流可能返回非 JSON 响应体。
        if r.status_code != 200:
            _notify_failure(f"HTTP {r.status_code}: {r.text[:250]}")
            if r.status_code == 429:
                return jsonify({"error": "识别服务忙，请稍后重试", "code": "service-busy"}), 429
            return jsonify({"error": "识别失败，请重试", "code": "asr-failed"}), 502
        data = r.json()
        if data.get("success") is False:
            raise ValueError("ASR response reports failure")
        text = ((data.get("result") or {}).get("text") or "").strip()
    except requests.Timeout as e:
        _notify_failure(f"请求超时: {type(e).__name__} {e}")
        return jsonify({"error": "识别超时，请重试", "code": "asr-timeout"}), 504
    except Exception as e:
        _notify_failure(f"请求异常: {type(e).__name__} {e}")
        return jsonify({"error": "识别服务异常，请重试", "code": "asr-failed"}), 502
    finally:
        _slots.release()
    # 空文本（纯噪音/没说话）也走 200，由前端映射为"没听到声音"
    return resp({"text": text})
