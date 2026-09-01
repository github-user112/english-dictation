#!/usr/bin/env python
"""手动触发一轮每日目标提醒（正常情况下由应用内守护线程自动发送，此脚本仅供调试）。

用法: .venv/bin/python scripts/push_remind.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from backend.push import remind_today

if remind_today(force=True):
    print("已发送一轮提醒")
else:
    print("未发送：vapid_key.pem 缺失")
