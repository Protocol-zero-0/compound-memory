#!/usr/bin/env python3
"""读取侧:`cm snapshot`(开局导航)与 `cm recall "话题"`(工作中按需检索)。

快照故意很短。真正的细节靠 recall 去翻 —— 加长快照会让每个 session 的开头越来越贵,
而且大部分内容当次任务根本用不上。
"""
import json, os, time

from . import config, llm, prompts, store, sinks, lexicon as L
from .sources import MARKER

CACHE = os.path.join(config.HOME, 'cache', 'snapshot.md')
QCACHE = os.path.join(config.HOME, 'cache', 'queries.json')
LOCAL = os.path.join(config.HOME, 'memory', 'snapshot.md')


def _fresh(path, seconds):
    try:
        return os.path.getsize(path) > 0 and (time.time() - os.path.getmtime(path)) < seconds
    except OSError:
        return False


def snapshot_text(cfg, refresh=False):
    """共享层优先(跨机器),取不到就用本机副本。任何异常都不能让开局失败。"""
    ttl = int(cfg.get('snapshot_cache_seconds') or 3600)
    if not refresh and _fresh(CACHE, ttl):
        return open(CACHE, encoding='utf-8').read(), 'cache'
    text, src = None, None
    try:
        text = sinks.get(cfg).fetch_snapshot()
        src = 'shared'
    except Exception:
        text = None
    if not text and os.path.exists(LOCAL):
        text, src = open(LOCAL, encoding='utf-8').read(), 'local'
    if text:
        os.makedirs(os.path.dirname(CACHE), exist_ok=True)
        llm.atomic_write(CACHE, text)
    return text, src


def print_snapshot(cfg, refresh=False):
    text, src = snapshot_text(cfg, refresh)
    if not text:
        return 0                          # 还没提炼过:安静退出,别把 harness 的开局搞崩
    where = {'shared': '共享层', 'local': '本机副本', 'cache': '本机缓存'}.get(src, src)
    if (cfg.get('language') or 'zh') == 'en':
        print(f'<{MARKER} source="{src}"> Long-term memory about '
              f'{cfg.get("user_name")}, injected automatically. Orientation only — '
              f'search with `cm recall "<topic>"` for details.')
    else:
        print(f'<{MARKER} source="{src}">【关于 {cfg.get("user_name")} 的长期记忆 · 自动注入 · '
              f'来源 {where}】这只是开局导航,细节用 `cm recall "话题"` 检索。')
    print(text)
    print(f'</{MARKER}>')
    return 0


# ---------- 查询扩展 ----------
def _qcache():
    try:
        return json.load(open(QCACHE, encoding='utf-8'))
    except Exception:
        return {}


def expand(cfg, query):
    """把问题扩成几个"记忆里可能真出现的说法"。一次便宜调用,结果永久缓存。

    **默认开着,但这个默认值换过两次,过程值得记下来**(完整数字见 docs/recall.md):

    - 二十多条记忆的小库上测:@8 88% → 88%,逐题 5 好 4 差 —— 看起来是噪音,于是我关掉了它。
    - 一百多条记忆的库上再测:@8 **75% → 92%**,逐题 7 好 1 差 —— 于是又打开。

    小库上测不出来不是因为扩展没用,是因为**只有二十多条时 @8 本来就到顶了**,
    没有给它留下可改进的空间。小样本会把真效应盖掉,这是教训不是数字。

    代价:一个没见过的问题多 ~20 秒;结果按问题永久缓存,同一个问题第二次 0.1 秒。
    要快就 `cm recall --fast` 或 `recall.expand: false`。
    """
    rc = cfg.get('recall') or {}
    cache = _qcache()
    key = store.norm(query)
    if key in cache:
        return cache[key]
    n = int(rc.get('terms') or 6)
    try:
        out = llm.ask(prompts.build('recall', cfg.get('language') or 'zh',
                                    user_name=cfg.get('user_name'), query=query, n=n),
                      timeout=int(rc.get('timeout') or 45),
                      model=rc.get('model') or None, effort=rc.get('effort') or 'low')
    except Exception:
        return []                                   # 扩展是锦上添花,失败就退回字面匹配
    terms, seen = [], {key}
    for line in (out or '').splitlines():
        t = line.strip().lstrip('-*0123456789.、) ').strip(' "\'「」')
        if not t or len(t) > 24 or store.norm(t) in seen:
            continue
        seen.add(store.norm(t))
        terms.append(t)
        if len(terms) >= n:
            break
    cache[key] = terms
    if len(cache) > 500:                            # 缓存不用无限长,丢最早的一半
        cache = dict(list(cache.items())[-250:])
    os.makedirs(os.path.dirname(QCACHE), exist_ok=True)
    llm.atomic_write(QCACHE, json.dumps(cache, ensure_ascii=False, indent=1))
    return terms


def find(cfg, query, k=8, fast=None, include_stale=False):
    """返回 (命中列表, 用过的说法, 记忆来源)。"""
    rows = store.load()
    src = 'local'
    if not rows:
        try:
            rows = sinks.get(cfg).fetch_memories()
            src = 'shared'
        except Exception:
            rows = []
    # fast=None 听配置;命令行的 --expand / --fast 覆盖配置
    skip = (not (cfg.get('recall') or {}).get('expand', False)) if fast is None else fast
    terms = [] if skip else expand(cfg, query)
    weight = float((cfg.get('recall') or {}).get('expanded_weight') or 0.7)
    queries = [(query, 1.0)] + [(t, weight) for t in terms]
    return store.search(rows, queries, k, include_stale), terms, src


def print_recall(cfg, query, k=8, fast=None, include_stale=False):
    lang = cfg.get('language') or 'zh'
    hits, terms, src = find(cfg, query, k, fast, include_stale)
    where = ({'local': 'local store', 'shared': 'shared layer'} if lang == 'en'
             else {'local': '本机全量', 'shared': '共享层'}).get(src, src)
    head = (f'【memory · {where} · "{query}" · top {k}】' if lang == 'en'
            else f'【记忆检索 · {where} · 话题「{query}」· 前 {k} 条】')
    print(head)
    if terms:
        print(('  also searched: ' if lang == 'en' else '  一并搜了:') + ' / '.join(terms))
    if not hits:
        print('(no match)' if lang == 'en' else '(没有匹配的记忆)')
        return 0
    for m in hits:
        tags = '/'.join(L.word(m.get(f), lang) for f in ('nature', 'kind', 'horizon', 'status')
                        if m.get(f))
        print(f"- [{tags} {m.get('date','')}] {m.get('content')}")
        origin = m.get('source_label') or f"{m.get('host')} · {m.get('source')}:{m.get('source_sid')}"
        print(f"    {'from' if lang == 'en' else '出处'}:{origin}")
    return 0
