#!/usr/bin/env python
"""手动抓取一轮每日新闻素材（正常由应用内守护线程每日自动刷新）。

用法: .venv/bin/python scripts/fetch_news.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.newsfetch import refresh

print(f"新增 {refresh()} 句")
