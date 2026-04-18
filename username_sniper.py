#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
Telegram Username Sniper — Bot 控制版
通过 Bot 指令切换模式、查看进度、暂停恢复。

Bot 命令：
  /mode letters 5         — 切换到5位纯字母
  /mode letters 4         — 切换到4位纯字母
  /mode shuangpin         — 小鹤双拼2音节(4字符)
  /mode shuangpin 3       — 小鹤双拼3音节(6字符)
  /mode shuangpin 2 ziranma — 自然码双拼
  /mode pinyin            — 拼音组合
  /status                 — 当前进度/速度/已发现数
  /stop                   — 暂停扫描
  /resume                 — 继续扫描
  /found                  — 查看已发现的靓号

依赖：pip3 install aiohttp
"""

import asyncio
import itertools
import json
import logging
import sqlite3
import string
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    import aiohttp
except ImportError:
    sys.exit("请安装依赖：pip3 install aiohttp")

BOT_TOKEN   = "8690075574:AAE2QCYhb08SXET1ukWWXxePPsJFaZM5KVg"  # 控制Bot（接命令+发通知）
CHAT_ID     = "877532"
CONFIG_FILE = "sniper_config.json"
DB_FILE     = "sniper_state.db"

# ── 多 Token 池（用于 getChat 检测，越多速度越快）────────────────────────────
# 每个 Token 独立限速，8 个并发/Token
# 在这里添加更多 Bot Token：
SNIPER_TOKENS = [
    "8690075574:AAE2QCYhb08SXET1ukWWXxePPsJFaZM5KVg",          # Bot 1（主）
    "8766221920:AAHg62TK5rt2PDKlpMwnZmN_UOeTvRiIC94",          # Bot 2
    "8685117355:AAFf-w2gZ_NRPoEduR_ibufALsg9iTosUAI",          # Bot 3
]
CONCURRENCY = len(SNIPER_TOKENS) * 5  # 每个Token 5并发

logging.basicConfig(level=logging.WARNING, format="%(asctime)s %(message)s")
logger = logging.getLogger(__name__)

# ── 拼音 & 双拼 ───────────────────────────────────────────────────────────────

VALID_PINYIN = [
    "a","o","e","ai","ei","ao","ou","an","en","ang","eng","er",
    "ba","bo","bi","bu","bai","bei","bao","ban","ben","bin","bing","bang","beng","bian","biao","bie",
    "pa","po","pi","pu","pai","pei","pao","pou","pan","pen","pin","ping","pang","peng","pian","piao","pie",
    "ma","mo","me","mi","mu","mai","mei","mao","mou","man","men","min","ming","mang","meng","mian","miao","mie","miu",
    "fa","fo","fu","fei","fan","fen","fang","feng",
    "da","de","di","du","dai","dao","dou","dan","den","ding","dang","deng","dian","diao","die","diu","dong","duan","dui","dun",
    "ta","te","ti","tu","tai","tao","tou","tan","tang","teng","tian","tiao","tie","tong","tuan","tui","tun",
    "na","ne","ni","nu","nv","nai","nei","nao","nou","nan","nen","nin","ning","nang","neng","nian","niao","nie","niu","nong","nuan","nve","nun",
    "la","le","li","lu","lv","lai","lei","lao","lou","lan","lin","ling","lang","leng","lian","liao","lie","liu","long","luan","lun","lve",
    "ga","ge","gu","gai","gei","gao","gou","gan","gen","gang","geng","gong","gua","guai","guan","gui","gun","guang",
    "ka","ke","ku","kai","kei","kao","kou","kan","ken","kang","keng","kong","kua","kuai","kuan","kui","kun","kuang",
    "ha","he","hu","hai","hei","hao","hou","han","hen","hang","heng","hong","hua","huai","huan","hui","hun","huang",
    "ji","ju","jia","jie","jiu","jin","jing","jian","jiao","jiang","jiong","jue","jun","juan",
    "qi","qu","qia","qie","qiu","qin","qing","qian","qiao","qiang","qiong","que","qun","quan",
    "xi","xu","xia","xie","xiu","xin","xing","xian","xiao","xiang","xiong","xue","xun","xuan",
    "zha","zhe","zhi","zhu","zhai","zhao","zhou","zhan","zhen","zhun","zhang","zheng","zhong","zhua","zhuai","zhuan","zhui","zhuang",
    "cha","che","chi","chu","chai","chao","chou","chan","chen","chun","chang","cheng","chong","chuai","chuan","chui","chuang",
    "sha","she","shi","shu","shai","shao","shou","shan","shen","shun","shang","sheng","shua","shuai","shuan","shui","shuang",
    "re","ri","ru","rao","rou","ran","ren","run","rang","reng","rong","ruan","rui",
    "za","ze","zi","zu","zai","zao","zou","zan","zen","zun","zang","zeng","zong","zuan","zui",
    "ca","ce","ci","cu","cai","cao","cou","can","cen","cun","cang","ceng","cong","cuan","cui",
    "sa","se","si","su","sai","sao","sou","san","sen","sun","sang","seng","song","suan","sui",
    "ya","ye","yi","yo","yu","yao","you","yan","yin","yun","yue","yuan","yang","ying","yong",
    "wa","wo","wu","wai","wei","wan","wen","wang","weng",
]

_SCHEMES = {
    "xiaohe": {
        "init":  {"zh":"v","ch":"i","sh":"u","b":"b","p":"p","m":"m","f":"f","d":"d","t":"t","n":"n","l":"l","g":"g","k":"k","h":"h","j":"j","q":"q","x":"x","r":"r","z":"z","c":"c","s":"s","y":"y","w":"w","":""},
        "final": {"a":"a","o":"o","e":"e","i":"i","u":"u","v":"v","ai":"d","ei":"w","ui":"v","uei":"v","ao":"c","ou":"z","iu":"q","iou":"q","ie":"p","ve":"t","ue":"t","er":"r","an":"j","en":"f","in":"b","un":"n","uen":"n","vn":"m","ang":"h","eng":"g","ing":"k","ong":"s","ia":"x","ua":"x","uo":"o","uai":"y","iang":"l","uang":"l","iong":"s","ian":"m","uan":"r","van":"r"},
    },
    "ziranma": {
        "init":  {"zh":"v","ch":"i","sh":"u","b":"b","p":"p","m":"m","f":"f","d":"d","t":"t","n":"n","l":"l","g":"g","k":"k","h":"h","j":"j","q":"q","x":"x","r":"r","z":"z","c":"c","s":"s","y":"y","w":"w","":""},
        "final": {"a":"a","o":"o","e":"e","i":"i","u":"u","v":"v","ai":"l","ei":"q","ui":"v","uei":"v","ao":"k","ou":"b","iu":"r","iou":"r","ie":"x","ve":"t","ue":"t","er":"j","an":"j","en":"f","in":"n","un":"p","uen":"p","vn":"m","ang":"h","eng":"g","ing":"y","ong":"s","ia":"w","ua":"w","uo":"o","uai":"y","iang":"t","uang":"d","iong":"s","ian":"m","uan":"r","van":"r"},
    },
}

def _split(syllable):
    for ti in ("zh","ch","sh"):
        if syllable.startswith(ti):
            return ti, syllable[len(ti):]
    if syllable[0] in set("bpmfdtnlgkhjqxrzcsyw") and syllable[0] not in "yw":
        return syllable[0], syllable[1:]
    return "", syllable

def _shuangpin_codes(scheme):
    s = _SCHEMES[scheme]
    codes = set()
    for syl in VALID_PINYIN:
        init, final = _split(syl)
        if init in ("","y","w"):
            fk = s["final"].get(final) or s["final"].get(final.lstrip("iuvy"))
            if fk:
                codes.add(syl[0] + fk)
        else:
            ik = s["init"].get(init)
            fk = s["final"].get(final)
            if ik and fk:
                codes.add(ik + fk)
    return sorted(codes)

# ── 生成器 ────────────────────────────────────────────────────────────────────

def make_generator(cfg):
    mode   = cfg["mode"]
    params = cfg.get("params", {})
    if mode == "letters":
        length = params.get("length", 5)
        return itertools.product(string.ascii_lowercase, repeat=length), 26**length
    if mode == "shuangpin":
        syllables = params.get("syllables", 2)
        scheme    = params.get("scheme", "xiaohe")
        codes = _shuangpin_codes(scheme)
        return itertools.product(codes, repeat=syllables), len(codes)**syllables
    if mode == "pinyin":
        min_len = params.get("min_len", 5)
        syls = sorted(VALID_PINYIN)
        def _gen():
            for s in syls:
                if len(s) >= min_len:
                    yield s
            for s1, s2 in itertools.product(syls, syls):
                c = s1 + s2
                if min_len <= len(c) <= 32:
                    yield c
        n = len(syls)
        return _gen(), n + n*n
    return iter([]), 0

def combo_to_str(combo):
    return "".join(combo) if isinstance(combo, tuple) else combo

def valid_tg(u):
    return 4 <= len(u) <= 32 and u[0].isalpha() and all(c.isalnum() or c == "_" for c in u)

# ── 可读性过滤 & 实用性评分 ───────────────────────────────────────────────────

_VOWELS = set("aeiou")

def is_pronounceable(s):
    """字母模式过滤：至少含1个元音，连续辅音不超过3个"""
    if not any(c in _VOWELS for c in s):
        return False
    streak = 0
    for c in s:
        if c not in _VOWELS:
            streak += 1
            if streak > 3:
                return False
        else:
            streak = 0
    return True

def score_username(username):
    """实用性评分，返回 (score, stars字符串)"""
    u = username.lower()
    score = 0
    # 越短越好
    score += max(0, 10 - len(u))
    # 元音比例越高越易读
    vowel_ratio = sum(1 for c in u if c in _VOWELS) / max(len(u), 1)
    score += int(vowel_ratio * 4)
    # 无连续重复字符加分
    if not any(u[i] == u[i + 1] for i in range(len(u) - 1)):
        score += 2
    stars = min(5, max(1, score // 2))
    return score, "⭐" * stars

# ── 状态 DB ───────────────────────────────────────────────────────────────────

class StateDB:
    def __init__(self):
        self.conn = sqlite3.connect(DB_FILE)
        self.conn.execute("CREATE TABLE IF NOT EXISTS progress (key TEXT PRIMARY KEY, value TEXT)")
        self.conn.execute("CREATE TABLE IF NOT EXISTS found (username TEXT PRIMARY KEY, found_at TEXT)")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS candidates (
                username TEXT PRIMARY KEY,
                found_at TEXT,
                status   TEXT DEFAULT 'pending'
            )
        """)
        self.conn.commit()

    def get_offset(self, key):
        row = self.conn.execute("SELECT value FROM progress WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def save_offset(self, key, n):
        self.conn.execute("INSERT OR REPLACE INTO progress(key,value) VALUES(?,?)", (key, str(n)))
        self.conn.commit()

    def add_found(self, username):
        self.conn.execute("INSERT OR IGNORE INTO found(username,found_at) VALUES(?,?)",
                          (username, datetime.now().strftime("%Y-%m-%d %H:%M:%S")))
        self.conn.commit()

    def all_found(self):
        return [r[0] for r in self.conn.execute("SELECT username FROM found ORDER BY found_at DESC")]

    # ── 冷冻期候选 ──────────────────────────────────────────────────────────
    def add_candidate(self, username):
        self.conn.execute(
            "INSERT OR IGNORE INTO candidates(username,found_at,status) VALUES(?,?,'pending')",
            (username, datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
        )
        self.conn.commit()

    def get_due_candidates(self, days=30):
        """返回发现满 days 天且仍 pending 的用户名"""
        rows = self.conn.execute("""
            SELECT username FROM candidates
            WHERE status='pending'
              AND julianday('now') - julianday(found_at) >= ?
            ORDER BY found_at
        """, (days,)).fetchall()
        return [r[0] for r in rows]

    def update_candidate(self, username, status):
        self.conn.execute("UPDATE candidates SET status=? WHERE username=?", (status, username))
        self.conn.commit()

    def all_candidates(self):
        return self.conn.execute(
            "SELECT username, found_at, status FROM candidates ORDER BY found_at DESC"
        ).fetchall()

# ── 配置 ──────────────────────────────────────────────────────────────────────

def load_config():
    if Path(CONFIG_FILE).exists():
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    return {"mode": "letters", "params": {"length": 5}, "running": True}

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, ensure_ascii=False, indent=2)

def config_key(cfg):
    return json.dumps({"mode": cfg["mode"], "params": cfg.get("params", {})}, sort_keys=True)

# ── Bot API ───────────────────────────────────────────────────────────────────

API = "https://api.telegram.org/bot" + BOT_TOKEN

async def bot_send(session, text):
    try:
        await session.post(API + "/sendMessage", json={
            "chat_id": CHAT_ID, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logger.warning("bot_send: %s", e)

async def bot_get_updates(session, offset):
    try:
        async with session.get(API + "/getUpdates", params={
            "offset": offset, "timeout": 20, "allowed_updates": ["message"],
        }, timeout=aiohttp.ClientTimeout(total=30)) as r:
            d = await r.json()
            return d.get("result", [])
    except Exception:
        return []

# ── 检测 ──────────────────────────────────────────────────────────────────────

async def check_one(session, username, token):
    """
    三步检测（t.me 与 Fragment 并行）：
      1. Bot API getChat      → taken / 继续
      2. t.me + Fragment 并行 → taken / nft / available
    """
    # ── 第一步：Bot API getChat ────────────────────────────────────────────
    try:
        async with session.get(
            "https://api.telegram.org/bot{}/getChat".format(token),
            params={"chat_id": "@" + username},
            timeout=aiohttp.ClientTimeout(total=8),
        ) as resp:
            if resp.status == 429:
                return "error"
            data = await resp.json()
            if data.get("ok"):
                return "taken"
            if "chat not found" not in data.get("description", "").lower():
                return "error"
    except Exception:
        return "error"

    # ── 第二步：t.me 与 Fragment 并行检测 ─────────────────────────────────
    async def _tme():
        try:
            async with session.get(
                "https://t.me/" + username,
                headers={"User-Agent": "Mozilla/5.0"},
                allow_redirects=True,
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                html = await r.text(encoding="utf-8", errors="ignore")
                return "taken" if "tgme_page_title" in html else None
        except Exception:
            return None

    async def _fragment():
        try:
            async with session.get(
                "https://fragment.com/username/" + username,
                headers={"User-Agent": "Mozilla/5.0"},
                timeout=aiohttp.ClientTimeout(total=5),
            ) as r:
                if r.status == 200:
                    html = await r.text(encoding="utf-8", errors="ignore")
                    return "nft" if ("collectible" in html or "tm-status-" in html) else None
        except Exception:
            return None

    tme, frag = await asyncio.gather(_tme(), _fragment())
    if tme == "taken":
        return "taken"
    if frag == "nft":
        return "nft"
    return "available"

# ── 扫描循环（滑动窗口，完成一个立刻补一个）─────────────────────────────────

async def run_sniper(state, db, session):
    cfg   = state["cfg"]
    key   = config_key(cfg)
    offset = db.get_offset(key)

    gen, total = make_generator(cfg)
    for _ in range(offset):
        try:
            next(gen)
        except StopIteration:
            await bot_send(session, "✅ 当前模式已全部检测完毕。")
            state["cfg"]["running"] = False
            return

    checked    = 0
    found      = 0
    t_start    = time.time()
    init_offset = offset  # 本次启动的起始位置，用于计算实际迭代速度
    n_tok   = len(SNIPER_TOKENS)
    gen_idx = offset          # 绝对索引，用于轮询 token
    pending = {}              # task → (abs_idx, username)
    newly   = []

    state["stats"] = {"checked": 0, "found": 0, "speed": 0.0, "total": total, "offset": offset}

    mode = cfg["mode"]

    def _should_check(u):
        if not valid_tg(u):
            return False
        if mode == "letters" and not is_pronounceable(u):
            return False
        return True

    def _submit(abs_idx, username):
        tok  = SNIPER_TOKENS[abs_idx % n_tok]
        task = asyncio.ensure_future(check_one(session, username, tok))
        pending[task] = (abs_idx, username)

    # 预填窗口
    for combo in gen:
        u = combo_to_str(combo)
        if _should_check(u):
            _submit(gen_idx, u)
        gen_idx += 1
        if len(pending) >= CONCURRENCY:
            break

    while pending:
        # 暂停支持
        while not cfg.get("running"):
            await asyncio.sleep(0.5)
            if state.get("restart"):
                break

        # 模式切换支持
        if state.get("restart"):
            for t in list(pending):
                t.cancel()
            await asyncio.gather(*list(pending), return_exceptions=True)
            state["restart"] = False
            return

        done_set, _ = await asyncio.wait(list(pending.keys()), return_when=asyncio.FIRST_COMPLETED)

        for task in done_set:
            abs_idx, username = pending.pop(task)
            try:
                st = task.result()
            except Exception:
                st = "error"

            offset = abs_idx + 1

            if st == "available":
                found   += 1
                checked += 1
                db.add_found(username)
                db.add_candidate(username)      # 加入冷冻期重扫队列
                with open("found.txt", "a") as f:
                    f.write(username + "\n")
                newly.append(username)
            elif st in ("taken", "nft"):
                checked += 1

            # 立刻补一个新任务
            for combo in gen:
                u = combo_to_str(combo)
                gen_idx += 1
                if _should_check(u):
                    _submit(gen_idx - 1, u)
                    break

        # 持久化进度
        db.save_offset(key, offset)

        # 推送通知（含实用性评分）
        if newly:
            lines = ["🔍 <b>疑似可用靓号</b>（可能在冷冻期，30天后 /candidates 确认）"]
            for u in newly:
                _, stars = score_username(u)
                lines.append("• <code>@{0}</code> {1}  <a href='https://t.me/{0}'>查看</a>".format(u, stars))
            await bot_send(session, "\n".join(lines))
            newly = []

        # 更新统计（用迭代速度算 ETA，与 offset 量纲一致）
        elapsed    = time.time() - t_start
        iter_done  = offset - init_offset
        iter_speed = iter_done / elapsed * 60 if elapsed > 0 else 0
        speed      = checked / elapsed * 60 if elapsed > 0 else 0
        state["stats"] = {
            "checked": checked, "found": found,
            "speed": speed, "iter_speed": iter_speed,
            "total": total, "offset": offset,
        }

    await bot_send(session, "✅ 当前模式全部检测完毕，共发现 {} 个靓号。".format(found))

# ── 指令处理 ──────────────────────────────────────────────────────────────────

async def handle_cmd(text, state, db, session):
    parts = text.strip().split()
    cmd   = parts[0].lower().lstrip("/").split("@")[0]

    if cmd == "start":
        await bot_send(session,
            "🤖 <b>Username Sniper 运行中</b>\n\n"
            "/mode letters 5 — 5位纯字母（过滤不可读组合）\n"
            "/mode letters 4 — 4位纯字母\n"
            "/mode shuangpin — 小鹤双拼2音节\n"
            "/mode shuangpin 3 — 3音节双拼\n"
            "/mode shuangpin 2 ziranma — 自然码\n"
            "/mode pinyin — 拼音组合\n"
            "/status — 查看进度\n"
            "/stop — 暂停\n"
            "/resume — 继续\n"
            "/found — 已发现靓号\n"
            "/candidates — 冷冻期候选列表"
        )

    elif cmd == "mode":
        if len(parts) < 2:
            await bot_send(session, "用法：/mode letters 5 / shuangpin / pinyin")
            return
        mode   = parts[1].lower()
        params = {}
        if mode == "letters":
            params["length"] = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 5
        elif mode == "shuangpin":
            params["syllables"] = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 2
            params["scheme"]    = parts[3].lower() if len(parts) > 3 else "xiaohe"
            if params["scheme"] not in _SCHEMES:
                await bot_send(session, "⚠️ 可用方案：xiaohe / ziranma")
                return
        elif mode == "pinyin":
            params["min_len"] = int(parts[2]) if len(parts) > 2 and parts[2].isdigit() else 4
        else:
            await bot_send(session, "⚠️ 可用模式：letters / shuangpin / pinyin")
            return

        state["cfg"]["mode"]    = mode
        state["cfg"]["params"]  = params
        state["cfg"]["running"] = True
        save_config(state["cfg"])
        state["restart"] = True
        await bot_send(session, "🔄 切换模式：<code>{} {}</code>\n扫描重新开始。".format(
            mode, json.dumps(params, ensure_ascii=False)))

    elif cmd == "status":
        s   = state.get("stats", {})
        cfg = state["cfg"]
        running_str = "运行中 ▶" if cfg.get("running") else "已暂停 ⏸"
        speed      = s.get("speed", 0.0)
        iter_speed = s.get("iter_speed", speed)
        total      = s.get("total", 0)
        offset     = s.get("offset", 0)
        pct        = offset / total * 100 if total > 0 else 0
        eta        = (total - offset) / iter_speed if iter_speed > 0 else 0
        eta_str    = "{:.0f}分钟".format(eta) if eta < 1440 else "{:.1f}小时".format(eta / 60)
        await bot_send(session,
            "📊 <b>扫描状态</b>\n\n"
            "状态：{}\n"
            "模式：{} {}\n"
            "速度：{:.0f} 个/分钟\n"
            "已迭代：{:,} / {:,}\n"
            "已发现靓号：{}\n"
            "进度：{:.2f}%\n"
            "预计剩余：{}".format(
                running_str,
                cfg["mode"], json.dumps(cfg.get("params", {}), ensure_ascii=False),
                iter_speed, offset, total, s.get("found", 0), pct, eta_str,
            )
        )

    elif cmd == "stop":
        state["cfg"]["running"] = False
        save_config(state["cfg"])
        await bot_send(session, "⏸ 已暂停。发送 /resume 继续。")

    elif cmd == "resume":
        state["cfg"]["running"] = True
        save_config(state["cfg"])
        await bot_send(session, "▶ 已继续扫描。")

    elif cmd == "found":
        usernames = db.all_found()
        if not usernames:
            await bot_send(session, "📭 暂未发现可用靓号。")
        else:
            lines = ["🎯 <b>已发现靓号（共{}个）</b>".format(len(usernames))]
            for u in usernames[:30]:
                _, stars = score_username(u)
                lines.append("• <code>@{0}</code> {1}  <a href='https://t.me/{0}'>查看</a>".format(u, stars))
            if len(usernames) > 30:
                lines.append("…还有{}个，查看 found.txt 获取完整列表".format(len(usernames) - 30))
            await bot_send(session, "\n".join(lines))

    elif cmd == "candidates":
        rows = db.all_candidates()
        confirmed = [(u, d) for u, d, s in rows if s == "confirmed"]
        pending   = [(u, d) for u, d, s in rows if s == "pending"]
        if not rows:
            await bot_send(session, "📋 暂无候选用户名。")
            return
        lines = ["📋 <b>冷冻期候选用户名</b>\n"]
        if confirmed:
            lines.append("🔓 已过冷冻期可注册（{}个）：".format(len(confirmed)))
            for u, d in confirmed[:20]:
                _, stars = score_username(u)
                lines.append("• <code>@{}</code> {}".format(u, stars))
            lines.append("")
        lines.append("⏳ 待满30天重扫（{}个）：".format(len(pending)))
        for u, d in pending[:15]:
            lines.append("• <code>@{}</code>  发现于 {}".format(u, d[:10]))
        await bot_send(session, "\n".join(lines))

# ── 冷冻期重扫（每24小时检查一次满30天的候选）────────────────────────────────

async def run_recheck(db, session):
    await asyncio.sleep(3600)          # 启动1小时后首次运行
    while True:
        due = db.get_due_candidates(days=30)
        if due:
            confirmed = []
            for username in due:
                result = await check_one(session, username, SNIPER_TOKENS[0])
                if result == "available":
                    db.update_candidate(username, "confirmed")
                    confirmed.append(username)
                else:
                    db.update_candidate(username, "taken")
                await asyncio.sleep(0.2)
            if confirmed:
                lines = ["🔓 <b>冷冻期已过，确认可注册！</b>"]
                for u in confirmed:
                    _, stars = score_username(u)
                    lines.append("• <code>@{0}</code> {1}  <a href='https://t.me/{0}'>查看</a>".format(u, stars))
                await bot_send(session, "\n".join(lines))
        await asyncio.sleep(86400)     # 24小时后再次运行

# ── Bot 轮询 ──────────────────────────────────────────────────────────────────

async def run_bot(state, db, session):
    offset = 0
    while True:
        updates = await bot_get_updates(session, offset)
        for upd in updates:
            offset = upd["update_id"] + 1
            msg     = upd.get("message", {})
            text    = msg.get("text", "")
            chat_id = str(msg.get("chat", {}).get("id", ""))
            if text.startswith("/") and chat_id == CHAT_ID:
                try:
                    await handle_cmd(text, state, db, session)
                except Exception as e:
                    await bot_send(session, "❌ 出错：{}".format(e))
        await asyncio.sleep(0.5)

# ── 主入口 ────────────────────────────────────────────────────────────────────

async def main():
    db    = StateDB()
    cfg   = load_config()
    state = {"cfg": cfg, "restart": False, "stats": {}}

    connector = aiohttp.TCPConnector(limit=CONCURRENCY + 20, ssl=False)
    session   = aiohttp.ClientSession(
        connector=connector,
        headers={"User-Agent": "Mozilla/5.0"},
    )

    await bot_send(session,
        "🚀 Username Sniper 已启动\n"
        "当前模式：{} {}\n"
        "发送 /start 查看全部命令".format(
            cfg["mode"], json.dumps(cfg.get("params", {}), ensure_ascii=False)
        )
    )

    asyncio.ensure_future(run_bot(state, db, session))
    asyncio.ensure_future(run_recheck(db, session))

    while True:
        if state["cfg"]["running"]:
            await run_sniper(state, db, session)
        else:
            await asyncio.sleep(1)

if __name__ == "__main__":
    loop = asyncio.get_event_loop()
    loop.run_until_complete(main())
