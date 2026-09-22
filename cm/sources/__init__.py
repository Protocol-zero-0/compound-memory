#!/usr/bin/env python3
"""各 harness 的会话读取适配器。

统一输出(一个 session 一条):
    {source, sid, path, cwd, title, ts_first, ts_last, n_user_turns}
再按需 load_turns(rec) 拿全部用户发言。

为什么分两步:扫描要便宜(每晚都跑),读原文要全(只对真正要提炼的 session 做)。
扫描结果按 (mtime, size) 缓存在 ~/.compound-memory/cache/,文件没动就不重解析。
"""
import datetime, json, os, re

from .. import config

NOISE_PREFIXES = ('<environment_context>', '<user_instructions>', '<ENVIRONMENT_CONTEXT>',
                  '<turn_aborted', '# AGENTS', '<permissions', '<app_context',
                  '<system-reminder>')

# 开局注入的快照会以用户消息的形态落进会话文件。不滤掉它,记忆就会开始自我循环:
# 快照喂进提炼 → 提炼出"他说过快照里那些话" → 写回快照。这一行是那个循环的断点。
MARKER = 'compound-memory-snapshot'

REGISTRY = {}


def register(mod):
    REGISTRY[mod.NAME] = mod
    return mod


def iso(ts):
    """把各家的时间戳统一成 'YYYY-MM-DDTHH:MM:SSZ'(UTC),好做字符串比较。"""
    if ts is None or ts == '':
        return None
    if isinstance(ts, (int, float)):
        sec = ts / 1000.0 if ts > 1e11 else float(ts)
        return datetime.datetime.fromtimestamp(sec, datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    s = str(ts)
    try:
        d = datetime.datetime.fromisoformat(s.replace('Z', '+00:00'))
        if d.tzinfo is None:
            d = d.replace(tzinfo=datetime.timezone.utc)
        return d.astimezone(datetime.timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    except ValueError:
        return s[:19] + 'Z'


def short(sid):
    """日志里用的短 id。dsh 的 sid 长成 session-<uuid>,直接截前 8 位会全是 'session-'。"""
    s = str(sid or '')
    if s.startswith('session-'):
        s = s[8:]
    return s[:8]


def clean(text):
    text = re.sub(r'\s+', ' ', text or '').strip()
    return text


def is_noise(text):
    return (not text) or text.startswith(NOISE_PREFIXES) or len(text) < 4 or MARKER in text


# ---------- 扫描缓存 ----------
def _cache_path(name):
    d = os.path.join(config.HOME, 'cache')
    os.makedirs(d, exist_ok=True)
    return os.path.join(d, f'{name}.json')


def since_epoch(since_iso, slack_days=1):
    """把窗口起点换算成文件 mtime 下界。文件最后写入时间 >= 最后一条消息时间,
    所以 mtime 早于窗口的文件一定不在窗口内 —— 这是安全的预过滤,不是用 mtime 判"有没有新内容"。"""
    if not since_iso:
        return 0.0
    d = datetime.datetime.strptime(since_iso[:19], '%Y-%m-%dT%H:%M:%S').replace(tzinfo=datetime.timezone.utc)
    return (d - datetime.timedelta(days=slack_days)).timestamp()


def cached_scan(name, paths, parse_one, mtime_floor=0.0):
    """paths: 文件路径列表;parse_one(path) -> 记录或 None。按 (mtime,size) 缓存。
    mtime_floor:早于它的文件直接跳过(见 since_epoch);已缓存的仍然沿用,不丢历史。"""
    p = _cache_path(name)
    try:
        old = json.load(open(p, encoding='utf-8'))
    except Exception:
        old = {}
    new, out, dirty = {}, [], False
    for path in paths:
        try:
            st = os.stat(path)
        except OSError:
            continue
        key = [st.st_mtime, st.st_size]
        e = old.get(path)
        if e and e.get('k') == key:
            rec = e['r']
        elif st.st_mtime < mtime_floor:
            continue
        else:
            try:
                rec = parse_one(path)
            except Exception:
                rec = None
            dirty = True
        new[path] = {'k': key, 'r': rec}
        if rec:
            out.append(rec)
    if dirty or set(new) != set(old):
        tmp = p + '.tmp'
        with open(tmp, 'w', encoding='utf-8') as f:
            json.dump(new, f, ensure_ascii=False)
        os.replace(tmp, p)
    return out


# ---------- 对外 ----------
def enabled_hosts(cfg):
    out = []
    for name, mod in REGISTRY.items():
        hc = config.host_cfg(cfg, name)
        en = hc.get('enabled', 'auto')
        if en is False or str(en).lower() in ('false', 'no', 'off'):
            continue
        if str(en).lower() == 'auto' and not mod.available(cfg):
            continue
        if en is True or str(en).lower() in ('true', 'yes', 'on') or mod.available(cfg):
            out.append(mod)
    return out


def scan_all(cfg, since=None):
    recs = []
    for mod in enabled_hosts(cfg):
        try:
            recs += mod.scan(cfg, since)
        except Exception as ex:
            print(f'  ! {mod.NAME} 扫描失败 {type(ex).__name__}: {ex}', flush=True)
    return recs


def load_turns(rec):
    mod = REGISTRY[rec['source']]
    return mod.load_turns(rec)


from . import claude, codex, dsh          # noqa: E402

for _m in (claude, codex, dsh):
    register(_m)
