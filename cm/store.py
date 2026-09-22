#!/usr/bin/env python3
"""本地全量记忆库:observations.jsonl(一行一条)+ state.json(每个 session 的水位线)。

原则:**原始语料是资产,记忆是可重算的缓存。** 所以这里存的每条都带出处(哪台机器、
哪个 harness、哪个 session)和批次号,任何时候都能丢掉重跑。
"""
import json, os, random, re, socket, string, time

from . import config, llm

HOME = config.HOME
STORE = os.path.join(HOME, 'memory', 'observations.jsonl')
STATE = os.path.join(HOME, 'memory', 'state.json')
HOST = socket.gethostname()

# 出机前的最后一道模式清洗。它是闸门,不是第一道防线 —— 该不该共享由提炼时逐条判断。
SECRET_RE = re.compile(
    r'(sk-[A-Za-z0-9_\-]{16,}|ghp_[A-Za-z0-9]{20,}|gho_[A-Za-z0-9]{20,}|AKIA[A-Z0-9]{12,}|'
    r'xox[bpa]-[A-Za-z0-9\-]{10,}|Bearer\s+[A-Za-z0-9._\-]{16,}|'
    r'(?:token|secret|password|passwd|api[_-]?key)\s*[=:]\s*\S{8,}|'
    r'-----BEGIN [A-Z ]*PRIVATE KEY-----|[A-Fa-f0-9]{40,}|[A-Za-z0-9+/]{48,}={0,2})')
REDACTED = '[redacted]'


def scrub(text):
    return SECRET_RE.sub(REDACTED, text or '')


def new_id():
    return 'm-' + time.strftime('%Y%m%d') + '-' + ''.join(
        random.choices(string.ascii_lowercase + string.digits, k=5))


def jload(path, default):
    try:
        return json.load(open(path, encoding='utf-8'))
    except (FileNotFoundError, json.JSONDecodeError):
        return default


def load():
    if not os.path.exists(STORE):
        return []
    out = []
    for line in open(STORE, encoding='utf-8'):
        line = line.strip()
        if line:
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return out


def save(rows):
    llm.atomic_write(STORE, ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in rows))


def load_state():
    return jload(STATE, {})


def save_state(state):
    llm.atomic_write(STATE, json.dumps(state, ensure_ascii=False, indent=1))


def live(rows):
    return [m for m in rows if m.get('status') in ('active', 'uncertain')]


def shared(rows):
    return [m for m in live(rows) if m.get('share')]


# ---------- 检索 ----------
def grams(s, n=2):
    s = re.sub(r'\s+', '', s or '')
    return {s[i:i + n] for i in range(len(s) - n + 1)}


def related(rows, query, sid=None, k=25):
    """给提炼用的"可能要被这次修订的旧记忆"。二元组重叠 + 同 session 加权,够用且零成本。"""
    q = grams(query)
    scored = []
    for m in live(rows):
        s = 0.0
        if sid and m.get('source_sid') == sid:
            s += 5
        g = grams(m.get('content'))
        if q and g:
            s += 3 * len(q & g) / len(q | g)
        if s > 0:
            scored.append((s, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:k]]


def search(rows, query, k=8):
    """给 `cm recall` 用:按话题找记忆,已推翻的不返回。"""
    q = grams(query)
    out = []
    for m in rows:
        if m.get('status') == 'overturned':
            continue
        g = grams((m.get('content') or '') + (m.get('scope') or ''))
        s = len(q & g) / (len(q) or 1)
        if s > 0:
            out.append((s, m))
    out.sort(key=lambda x: -x[0])
    return [m for _, m in out[:k]]
