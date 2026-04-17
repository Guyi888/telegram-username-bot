#!/usr/bin/env python3
"""
Telegram Username Sniper
========================
通过并发 HTTP 请求 t.me 批量检测用户名可用性。

支持模式：
  letters   — N位纯字母（如 5 位：26^5 ≈ 1200万）
  shuangpin — 双拼靓号（小鹤/自然码，2~3音节）
  pinyin    — 常见拼音组合（单/双音节）

特性：
  · 100并发协程，速度 500~2000个/分钟
  · SQLite 断点续传，中断后从上次进度继续
  · 发现靓号写入 found.txt + 可选 Telegram Bot 推送通知
  · 自动处理频率限制（429 / 连接错误指数退避）

依赖安装：
  pip install aiohttp

用法示例：
  python username_sniper.py letters 5
  python username_sniper.py letters 4 --concurrency 150
  python username_sniper.py shuangpin --scheme xiaohe
  python username_sniper.py shuangpin 3 --scheme ziranma
  python username_sniper.py pinyin
  python username_sniper.py --token BOT_TOKEN --chat CHAT_ID letters 5
"""

import argparse
import asyncio
import itertools
import json
import logging
import signal
import sqlite3
import string
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Iterator

try:
    import aiohttp
except ImportError:
    sys.exit("请先安装依赖：pip install aiohttp")

# ── 日志 ──────────────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.WARNING,
    format="%(asctime)s %(levelname)s %(message)s",
    handlers=[logging.StreamHandler()],
)
logger = logging.getLogger(__name__)

# ── 拼音数据 ──────────────────────────────────────────────────────────────────

VALID_PINYIN: frozenset = frozenset([
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
])

# ── 双拼方案 ──────────────────────────────────────────────────────────────────

_SCHEMES = {
    "xiaohe": {
        "init": {"zh":"v","ch":"i","sh":"u",**{c:c for c in "bpmfdtnlgkhjqxrzcsyw"},"":""},
        "final": {
            "a":"a","o":"o","e":"e","i":"i","u":"u","v":"v",
            "ai":"d","ei":"w","ui":"v","uei":"v","ao":"c","ou":"z","iu":"q","iou":"q",
            "ie":"p","ve":"t","ue":"t","er":"r",
            "an":"j","en":"f","in":"b","un":"n","uen":"n","vn":"m",
            "ang":"h","eng":"g","ing":"k","ong":"s",
            "ia":"x","ua":"x","uo":"o","uai":"y",
            "iang":"l","uang":"l","iong":"s","ian":"m","uan":"r","van":"r",
        },
    },
    "ziranma": {
        "init": {"zh":"v","ch":"i","sh":"u",**{c:c for c in "bpmfdtnlgkhjqxrzcsyw"},"":""},
        "final": {
            "a":"a","o":"o","e":"e","i":"i","u":"u","v":"v",
            "ai":"l","ei":"q","ui":"v","uei":"v","ao":"k","ou":"b","iu":"r","iou":"r",
            "ie":"x","ve":"t","ue":"t","er":"j",
            "an":"j","en":"f","in":"n","un":"p","uen":"p","vn":"m",
            "ang":"h","eng":"g","ing":"y","ong":"s",
            "ia":"w","ua":"w","uo":"o","uai":"y",
            "iang":"t","uang":"d","iong":"s","ian":"m","uan":"r","van":"r",
        },
    },
}

_TWO_INITS = ("zh","ch","sh")
_ONE_INITS  = set("bpmfdtnlgkhjqxrzcsyw")

def _split(syllable: str):
    for ti in _TWO_INITS:
        if syllable.startswith(ti):
            return ti, syllable[len(ti):]
    if syllable[0] in _ONE_INITS and syllable[0] not in "yw":
        return syllable[0], syllable[1:]
    return "", syllable

def _to_code(syllable: str, scheme: str) -> str | None:
    s = _SCHEMES[scheme]
    init, final = _split(syllable)
    if init in ("","y","w"):
        fk = s["final"].get(final) or s["final"].get(final.lstrip("iuvy"))
        if fk is None:
            return None
        return syllable[0] + fk
    ik = s["init"].get(init)
    fk = s["final"].get(final)
    if ik is None or fk is None:
        return None
    return ik + fk

def _shuangpin_codes(scheme: str) -> list[str]:
    codes = set()
    for syl in VALID_PINYIN:
        c = _to_code(syl, scheme)
        if c and len(c) == 2 and c.isalpha():
            codes.add(c)
    return sorted(codes)

# ── 生成器 ────────────────────────────────────────────────────────────────────

def gen_letters(length: int) -> Iterator[str]:
    for combo in itertools.product(string.ascii_lowercase, repeat=length):
        yield "".join(combo)

def gen_shuangpin(syllables: int, scheme: str) -> Iterator[str]:
    codes = _shuangpin_codes(scheme)
    for combo in itertools.product(codes, repeat=syllables):
        yield "".join(combo)

def gen_pinyin(max_syllables: int = 2, min_len: int = 4) -> Iterator[str]:
    syls = sorted(VALID_PINYIN)
    for s in syls:
        if len(s) >= min_len:
            yield s
    if max_syllables >= 2:
        for s1, s2 in itertools.product(syls, syls):
            combo = s1 + s2
            if min_len <= len(combo) <= 32:
                yield combo

def build_generator(mode: str, args) -> tuple[Iterator[str], int]:
    """返回 (生成器, 估计总量)"""
    if mode == "letters":
        n = args.length
        return gen_letters(n), 26 ** n
    if mode == "shuangpin":
        codes = _shuangpin_codes(args.scheme)
        n = args.syllables
        return gen_shuangpin(n, args.scheme), len(codes) ** n
    if mode == "pinyin":
        n = len(VALID_PINYIN)
        return gen_pinyin(args.max_syllables, args.min_len), n + n * n
    raise ValueError(f"未知模式: {mode}")

# ── 状态数据库 ────────────────────────────────────────────────────────────────

class StateDB:
    def __init__(self, path: str):
        self.conn = sqlite3.connect(path)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS progress (
                key   TEXT PRIMARY KEY,
                value TEXT
            )""")
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS found (
                username   TEXT PRIMARY KEY,
                found_at   TEXT
            )""")
        self.conn.commit()

    def get_offset(self, key: str) -> int:
        row = self.conn.execute(
            "SELECT value FROM progress WHERE key=?", (key,)).fetchone()
        return int(row[0]) if row else 0

    def save_offset(self, key: str, offset: int):
        self.conn.execute(
            "INSERT OR REPLACE INTO progress(key,value) VALUES(?,?)",
            (key, str(offset)))
        self.conn.commit()

    def add_found(self, username: str):
        self.conn.execute(
            "INSERT OR IGNORE INTO found(username,found_at) VALUES(?,?)",
            (username, datetime.now().isoformat()))
        self.conn.commit()

    def all_found(self) -> list[str]:
        return [r[0] for r in self.conn.execute(
            "SELECT username FROM found ORDER BY found_at")]

    def close(self):
        self.conn.close()

# ── HTTP 检测 ─────────────────────────────────────────────────────────────────

# t.me 有真实用户/频道时页面含 CDN 头像链接；无用户时只有默认 logo
_TAKEN_MARKERS = ("cdn.telegram-cdn.org", "tgme_page_photo", "tgme_page_additional_info")

async def check_one(session: aiohttp.ClientSession, sem: asyncio.Semaphore,
                    username: str, backoff: list) -> str:
    """返回 'available' | 'taken' | 'error'"""
    async with sem:
        if backoff[0] > 0:
            await asyncio.sleep(backoff[0])
        try:
            url = f"https://t.me/{username}"
            async with session.get(url, allow_redirects=True,
                                   timeout=aiohttp.ClientTimeout(total=12)) as resp:
                if resp.status == 429:
                    backoff[0] = min(backoff[0] + 5, 60)
                    logger.warning("429 rate-limit — 退避 %ds", backoff[0])
                    return "error"
                backoff[0] = max(0, backoff[0] - 1)
                html = await resp.text(encoding="utf-8", errors="ignore")
                if any(m in html for m in _TAKEN_MARKERS):
                    return "taken"
                return "available"
        except asyncio.TimeoutError:
            return "error"
        except Exception as e:
            logger.debug("check %s: %s", username, e)
            return "error"

# ── Bot 推送通知 ───────────────────────────────────────────────────────────────

async def notify_bot(session: aiohttp.ClientSession,
                     token: str, chat_id: str, usernames: list[str]):
    if not token or not chat_id:
        return
    lines = ["🎯 <b>发现可注册靓号！</b>"]
    for u in usernames:
        lines.append(f"• <code>@{u}</code>  <a href='https://t.me/{u}'>查看</a>")
    text = "\n".join(lines)
    url = f"https://api.telegram.org/bot{token}/sendMessage"
    try:
        await session.post(url, json={
            "chat_id": chat_id, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": True,
        }, timeout=aiohttp.ClientTimeout(total=10))
    except Exception as e:
        logger.warning("Bot 推送失败: %s", e)

# ── 主循环 ────────────────────────────────────────────────────────────────────

async def run(args):
    gen, total = build_generator(args.mode, args)
    state_key  = f"{args.mode}_{json.dumps(vars(args), sort_keys=True, default=str)[:60]}"
    db_path    = f"sniper_{args.mode}.db"
    found_path = Path("found.txt")

    db     = StateDB(db_path)
    offset = db.get_offset(state_key)

    print(f"\n{'='*55}")
    print(f"  模式: {args.mode}   预估总量: {total:,}")
    print(f"  并发: {args.concurrency}   已跳过: {offset:,}")
    print(f"  状态库: {db_path}   结果文件: found.txt")
    print(f"{'='*55}\n")

    # 跳过已检测部分
    for _ in range(offset):
        try:
            next(gen)
        except StopIteration:
            print("✅ 所有候选已检测完毕。")
            db.close()
            return

    sem     = asyncio.Semaphore(args.concurrency)
    backoff = [0]  # 共享退避计数器（列表以便协程修改）
    checked = 0
    found   = 0
    errors  = 0
    t_start = time.time()
    stop    = False

    def _sigint(_s, _f):
        nonlocal stop
        stop = True
        print("\n⏸  收到中断，正在保存进度...")

    signal.signal(signal.SIGINT, _sigint)

    conn_args = {
        "connector": aiohttp.TCPConnector(limit=args.concurrency + 10, ssl=False),
        "headers":   {"User-Agent": "Mozilla/5.0 (compatible; TelegramUsernameChecker/1.0)"},
    }

    async with aiohttp.ClientSession(**conn_args) as session:
        batch: list[str] = []

        async def flush_batch():
            nonlocal checked, found, errors
            if not batch:
                return
            tasks = [
                asyncio.create_task(check_one(session, sem, u, backoff))
                for u in batch
            ]
            results = await asyncio.gather(*tasks)
            newly_available = []
            for u, status in zip(batch, results):
                if status == "available":
                    found += 1
                    db.add_found(u)
                    with open(found_path, "a", encoding="utf-8") as f:
                        f.write(u + "\n")
                    newly_available.append(u)
                    print(f"\n🎯  可用靓号: @{u}")
                elif status == "error":
                    errors += 1
                else:
                    checked += 1
            if newly_available:
                await notify_bot(session, args.token, args.chat, newly_available)
            batch.clear()

        for username in gen:
            if stop:
                break
            batch.append(username)
            if len(batch) >= args.concurrency:
                await flush_batch()
                offset += args.concurrency
                db.save_offset(state_key, offset)

                elapsed = time.time() - t_start
                speed   = (checked + found + errors) / elapsed * 60 if elapsed > 0 else 0
                done    = checked + found + errors
                pct     = done / total * 100 if total > 0 else 0
                eta_min = (total - done) / speed if speed > 0 else float("inf")
                eta_str = f"{eta_min:.0f}分钟" if eta_min < 60*24 else f"{eta_min/60:.1f}小时"

                print(
                    f"\r  已检: {done:>9,}  速度: {speed:>6.0f}/min"
                    f"  靓号: {found}  进度: {pct:.2f}%  剩余: {eta_str}    ",
                    end="", flush=True,
                )

        await flush_batch()  # 收尾
        db.save_offset(state_key, offset + len(batch))

    db.close()
    total_done = checked + found + errors
    print(f"\n\n{'='*55}")
    print(f"  完成！共检测 {total_done:,} 个，发现靓号 {found} 个")
    if found:
        print(f"  靓号列表已保存至 {found_path}")
        for u in db.all_found()[-10:]:
            print(f"    @{u}")
    print(f"{'='*55}\n")

# ── 命令行参数 ────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Telegram 靓号用户名检测工具",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument("mode", choices=["letters","shuangpin","pinyin"],
                        help="检测模式")
    parser.add_argument("extra", nargs="?", type=int,
                        help="letters: 位数(默认5)  shuangpin: 音节数(默认2)")
    parser.add_argument("--length",        type=int, default=5,  help="letters 位数")
    parser.add_argument("--syllables",     type=int, default=2,  help="shuangpin 音节数(2=4字符,3=6字符)")
    parser.add_argument("--scheme",        default="xiaohe",     help="双拼方案: xiaohe(小鹤) / ziranma(自然码)")
    parser.add_argument("--max-syllables", dest="max_syllables", type=int, default=2, help="pinyin 最大音节数")
    parser.add_argument("--min-len",       dest="min_len",       type=int, default=4, help="pinyin 最短长度")
    parser.add_argument("--concurrency",   type=int, default=100, help="并发协程数(默认100)")
    parser.add_argument("--token",         default="",   help="Bot Token，用于推送通知")
    parser.add_argument("--chat",          default="",   help="推送通知的 Chat ID")

    args = parser.parse_args()

    # 处理位置参数 extra（如 `letters 4` 或 `shuangpin 3`）
    if args.extra is not None:
        if args.mode == "letters":
            args.length = args.extra
        elif args.mode == "shuangpin":
            args.syllables = args.extra

    if args.scheme not in _SCHEMES:
        sys.exit(f"❌ 未知双拼方案: {args.scheme}，可选: {', '.join(_SCHEMES)}")

    asyncio.run(run(args))

if __name__ == "__main__":
    main()
