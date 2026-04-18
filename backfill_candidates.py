#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
一次性补录脚本：把 found.txt 里的历史用户名写入 candidates 表
found_at 统一设为 2026-01-01（确保30天后首次重扫时全部到期）
运行：python3 backfill_candidates.py
"""

import sqlite3
from pathlib import Path

DB_FILE    = "sniper_state.db"
FOUND_FILE = "found.txt"

if not Path(FOUND_FILE).exists():
    print("found.txt 不存在，退出。")
    exit(1)

conn = sqlite3.connect(DB_FILE)
conn.execute("""
    CREATE TABLE IF NOT EXISTS candidates (
        username TEXT PRIMARY KEY,
        found_at TEXT,
        status   TEXT DEFAULT 'pending'
    )
""")
conn.commit()

with open(FOUND_FILE, "r") as f:
    usernames = [line.strip() for line in f if line.strip()]

inserted = 0
skipped  = 0
for u in usernames:
    cur = conn.execute(
        "INSERT OR IGNORE INTO candidates(username, found_at, status) VALUES(?, '2026-01-01 00:00:00', 'pending')",
        (u,)
    )
    if cur.rowcount:
        inserted += 1
    else:
        skipped += 1

conn.commit()
conn.close()

print("完成！插入：{} 条，已存在跳过：{} 条，合计：{} 条".format(inserted, skipped, inserted + skipped))
