#!/usr/bin/env python3
"""读取侧:`cm snapshot`(开局导航)与 `cm recall "话题"`(工作中按需检索)。

快照故意很短。真正的细节靠 recall 去翻 —— 加长快照会让每个 session 的开头越来越贵,
而且大部分内容当次任务根本用不上。
"""
import os, time

from . import config, llm, store, sinks, lexicon as L
from .sources import MARKER

CACHE = os.path.join(config.HOME, 'cache', 'snapshot.md')
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


def print_recall(cfg, query, k=8):
    rows = store.load()
    src = '本机全量' if (cfg.get('language') or 'zh') != 'en' else 'local store'
    if not rows:
        try:
            rows = sinks.get(cfg).fetch_memories()
            src = '共享层' if (cfg.get('language') or 'zh') != 'en' else 'shared layer'
        except Exception:
            rows = []
    lang = cfg.get('language') or 'zh'
    hits = store.search(rows, query, k)
    head = (f'【memory · {src} · "{query}" · top {k}】' if lang == 'en'
            else f'【记忆检索 · {src} · 话题「{query}」· 前 {k} 条】')
    print(head)
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
