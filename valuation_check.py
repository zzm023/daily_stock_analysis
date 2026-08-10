#!/usr/bin/env python3
"""
估值共振检查 v6 — 调试版
数据源：腾讯 qt.gtimg.cn，打印原始字段定位PE/PB索引
"""
import os
import json
import requests
import subprocess
from datetime import datetime
from pathlib import Path

STATE_FILE = Path(__file__).parent / "framework_state.json"
PUSHPLUS_TOKEN = os.environ.get("PUSHPLUS_TOKEN", "")
PUSHPLUS_TOPIC = os.environ.get("PUSHPLUS_TOPIC", "")


def get_raw(code):
    prefix = "sh" if code.startswith("6") else "sz"
    try:
        r = requests.get(f"http://qt.gtimg.cn/q={prefix}{code}", timeout=10)
        r.encoding = "gbk"
        return r.text
    except:
        return ""


def push(title, content):
    if not PUSHPLUS_TOKEN: return
    try:
        payload = {"token": PUSHPLUS_TOKEN, "title": title, "content": content, "template": "markdown"}
        if PUSHPLUS_TOPIC:
            payload["topic"] = PUSHPLUS_TOPIC
        r = requests.post("http://www.pushplus.plus/send", json=payload, timeout=10)
        print(f"[{'OK' if r.json().get('code')==200 else 'FAIL'}] PushPlus")
    except Exception as e:
        print(f"[PushPlus] {e}")


def main():
    now = datetime.now()
    print(f"[START] 估值共振检查 v6 调试 {now:%Y-%m-%d %H:%M}")

    # 调试：打印分众传媒(002027)和格力电器(000651)的原始返回
    for code in ["002027", "000651"]:
        raw = get_raw(code)
        parts = raw.split("~")
        print(f"\n=== {code} 原始字段 (共{len(parts)}个) ===")
        for i, p in enumerate(parts[:50]):
            print(f"  [{i}] = {p}")
        print(f"  ... (省略{len(parts)-50}个字段)")
    print("\n[DONE] 调试完成，请发送截图")


if __name__ == "__main__":
    main()
