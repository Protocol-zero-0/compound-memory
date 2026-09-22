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
# 这一段的每个选择都是在 `cm eval` 的 24 道题上量过的,不是拍脑袋(数字见 docs/recall.md):
#   · 字段只取 内容 + 适用范围 —— 把原话、出处也搜进去,recall@8 从 88% 掉到 83%(出处带主题和机器名,是噪音)
#   · 不做 IDF 加权 —— @3 +4 点但 @8 -5 点,对"AI 一次读 8 条"的用法是亏的
#   · 中文按字符二元组、英文数字按词 —— @1 42%→46%(同口径消融里 @8 88%→92%);纯字符二元组在英文上是坏的,
#     两句毫不相关的英文能撞出 0.25 的相似度
_PUNCT = re.compile(r'[\s\u3000-\u303f\uff00-\uff0f\uff1a-\uff20\uff3b-\uff40\uff5b-\uff65'
                    r'!-/:-@\[-`{-~]+')
_CJK = re.compile(r'[\u4e00-\u9fff\u3040-\u30ff\uac00-\ud7af]+')
_WORD = re.compile(r'[a-z0-9]+')


def norm(s):
    """归一化:去标点空白、全角转半角、英文小写。中英混排的记忆里这三件事都会咬人。"""
    s = (s or '').translate({c: c - 0xFEE0 for c in range(0xFF01, 0xFF5F)})
    return _PUNCT.sub(' ', s).lower()


def tokens(s):
    """中文切字符二元组,英文/数字切词。混排文本(「给 README 加个 badge」)两边都照顾到。"""
    s = norm(s)
    out = set()
    for seg in _CJK.findall(s):
        out |= {seg[i:i + 2] for i in range(len(seg) - 1)} if len(seg) > 1 else {seg}
    for w in _WORD.findall(s):
        out.add(w)
        if len(w) > 6:                       # 长英文词给点前缀容错
            out |= {w[i:i + 4] for i in range(len(w) - 3)}
    return out


def haystack(m):
    return (m.get('content') or '') + ' ' + (m.get('scope') or '')


def _score(g, wmap, total):
    return sum(w for x, w in wmap.items() if x in g) / total


def _wmap(queries):
    """多个说法合成一张 token→权重 表。只有一个权重 1 的查询时,退化成最朴素的重叠率。"""
    wmap = {}
    for q, w in queries:
        for x in tokens(q):
            wmap[x] = max(wmap.get(x, 0.0), float(w))
    return wmap, (sum(wmap.values()) or 1.0)


def related(rows, query, sid=None, k=25):
    """给提炼用的"可能要被这次修订的旧记忆"。同 session 的加权重,其余按相似度。"""
    pool = live(rows)
    wmap, total = _wmap([(query, 1.0)])
    scored = []
    for m in pool:
        s = 5.0 if (sid and m.get('source_sid') == sid) else 0.0
        s += 3 * _score(tokens(haystack(m)), wmap, total)
        if s > 0:
            scored.append((s, m))
    scored.sort(key=lambda x: -x[0])
    return [m for _, m in scored[:k]]


def search(rows, queries, k=8, include_stale=False):
    """给 `cm recall` 用。queries 是字符串,或者 [(说法, 权重)] —— 后者给查询扩展留的口子。"""
    if isinstance(queries, str):
        queries = [(queries, 1.0)]
    pool = [m for m in rows if include_stale or m.get('status') != 'overturned']
    wmap, total = _wmap([(q, w) for q, w in queries if norm(q).strip()])
    if not (pool and wmap):
        return []
    out = []
    for m in pool:
        s = _score(tokens(haystack(m)), wmap, total)
        if s > 0:
            out.append((s, m))
    out.sort(key=lambda x: -x[0])
    return [m for _, m in out[:k]]
