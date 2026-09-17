"""配置：路径 / 学习参数 / 素材清单"""
import os
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = Path(os.environ.get("ENGLISH_DICTATION_DB", BASE / "data" / "learn.db"))
AUDIO = BASE / "audio"
STATIC_DIR = BASE / "static"

COOKIE = "dict_u"
SESSION_COOKIE = "dict_session"
CSRF_COOKIE = "dict_csrf"


def _env_bool(name, default=False):
    return os.environ.get(name, str(default)).strip().lower() in {"1", "true", "yes", "on"}


AUTH_SESSION_DAYS = max(1, int(os.environ.get("ENGLISH_DICTATION_AUTH_SESSION_DAYS", "30")))
AUTH_COOKIE_SECURE = _env_bool("ENGLISH_DICTATION_COOKIE_SECURE")
AUTH_RATE_LIMIT_ATTEMPTS = max(1, int(os.environ.get("ENGLISH_DICTATION_AUTH_RATE_LIMIT_ATTEMPTS", "5")))
AUTH_RATE_LIMIT_SECONDS = max(60, int(os.environ.get("ENGLISH_DICTATION_AUTH_RATE_LIMIT_SECONDS", "900")))

CONFIG = {
    "new_per_day": 10,
    "max_review": 30,
    "known_threshold": 3,
    "memorize_batch": 20,
    "memorize_threshold": 2,
    "memorize_review_days": 7,
}

PRACTICE_MODES = {"pure", "assisted", "follow"}

TTS_DEFAULT_VOICE = os.environ.get("ENGLISH_DICTATION_TTS_DEFAULT_VOICE", "en-US-JennyNeural")
TTS_ALLOWED_VOICES = frozenset(filter(None, os.environ.get(
    "ENGLISH_DICTATION_TTS_ALLOWED_VOICES", "en-US-JennyNeural,en-US-GuyNeural"
).split(",")))
TTS_RATE_LIMIT_PER_HOUR = max(0, int(os.environ.get("ENGLISH_DICTATION_TTS_RATE_LIMIT_PER_HOUR", "30")))
TTS_MAX_CONCURRENCY = max(1, int(os.environ.get("ENGLISH_DICTATION_TTS_MAX_CONCURRENCY", "2")))
TTS_LAZY_MAX_FILES = max(0, int(os.environ.get("ENGLISH_DICTATION_TTS_LAZY_MAX_FILES", "5000")))
CONFIG.update({
    "tts_default_voice": TTS_DEFAULT_VOICE,
    "tts_allowed_voices": TTS_ALLOWED_VOICES,
    "tts_rate_limit_per_hour": TTS_RATE_LIMIT_PER_HOUR,
    "tts_max_concurrency": TTS_MAX_CONCURRENCY,
    "tts_lazy_max_files": TTS_LAZY_MAX_FILES,
})

# ---- 服务端 ASR（语音识别兜底）：安卓 MIUI 浏览器/Edge 的 SpeechRecognition 是空壳，
# 录音走后端转发 Cloudflare Workers AI Whisper ----
CF_ACCOUNT_ID = os.environ.get("ENGLISH_DICTATION_CF_ACCOUNT_ID", "0c4a89fdb508abf8dc2994fbf3054a06")
ASR_MODEL = os.environ.get("ENGLISH_DICTATION_ASR_MODEL", "@cf/openai/whisper-large-v3-turbo")
ASR_RATE_LIMIT_PER_HOUR = max(0, int(os.environ.get("ENGLISH_DICTATION_ASR_RATE_LIMIT_PER_HOUR", "120")))
ASR_MAX_CONCURRENCY = max(1, int(os.environ.get("ENGLISH_DICTATION_ASR_MAX_CONCURRENCY", "2")))
CONFIG.update({
    "asr_rate_limit_per_hour": ASR_RATE_LIMIT_PER_HOUR,
    "asr_max_concurrency": ASR_MAX_CONCURRENCY,
})


def cf_api_token():
    """CF API token：环境变量优先，否则读 data/cf_api_token（data/ 已 gitignore；
    本机 sudo 不可用写不了 /etc/environment，文件是次优解）。"""
    tok = os.environ.get("ENGLISH_DICTATION_CF_API_TOKEN", "").strip()
    if tok:
        return tok
    try:
        return (BASE / "data" / "cf_api_token").read_text().strip()
    except OSError:
        return ""

MATERIALS = {
    "cet4": {"type": "words", "title": "CET-4 词汇"},
    "cet6": {"type": "words", "title": "CET-6 词汇"},
    "kaoyan": {"type": "words", "title": "考研词汇"},
    "tuofu": {"type": "words", "title": "托福词汇"},
    "nce1": {"type": "words", "title": "新概念1词汇"},
    "nce2": {"type": "words", "title": "新概念2词汇"},
    "nce3": {"type": "words", "title": "新概念3词汇"},
    "nce4": {"type": "words", "title": "新概念4词汇"},
    "nc1": {"type": "sentences", "title": "新概念英语1册"},
    "nc2": {"type": "sentences", "title": "新概念英语2册"},
    "nc3": {"type": "sentences", "title": "新概念英语3册"},
    "nc4": {"type": "sentences", "title": "新概念英语4册"},
    "oral900": {"type": "sentences", "title": "口语900句"},
    "news": {"type": "sentences", "title": "每日新闻"},
}
