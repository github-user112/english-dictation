"""配置：路径 / 学习参数 / 素材清单"""
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
DB = BASE / "data" / "learn.db"
AUDIO = BASE / "audio"
STATIC_DIR = BASE / "static"

COOKIE = "dict_u"

CONFIG = {
    "new_per_day": 10,
    "max_review": 30,
    "known_threshold": 3,
    "memorize_batch": 20,
    "memorize_threshold": 2,
    "memorize_review_days": 7,
}

MATERIALS = {
    "cet4": {"type": "words", "title": "CET-4 词汇"},
    "cet6": {"type": "words", "title": "CET-6 词汇"},
    "kaoyan": {"type": "words", "title": "考研词汇"},
    "tuofu": {"type": "words", "title": "托福词汇"},
    "nc1": {"type": "sentences", "title": "新概念英语1册"},
    "nc2": {"type": "sentences", "title": "新概念英语2册"},
    "nc3": {"type": "sentences", "title": "新概念英语3册"},
    "nc4": {"type": "sentences", "title": "新概念英语4册"},
    "oral900": {"type": "sentences", "title": "口语900句"},
}
