#!/usr/bin/env python3
"""`cm eval` —— 检索的尺子。

为什么需要它:README 里写着"提示词是最该你自己调的东西",却不给人判断改好改坏的办法,
那是耍流氓。检索更是如此 —— "换个说法找不到"这种话很容易说,但到底多严重、改完有没有
变好,只能测。

怎么测:
  1. 从记忆库里随机抽 N 条当"标准答案"。
  2. 让模型**只看这一条**,写一个真人会问的问题,且**不许照抄里面的说法** —— 不这么限制,
     题目会跟原文字面重合,测出来的全是虚高。
  3. 把每道题丢进检索,看标准答案排第几。报 recall@1/@3/@8。
  4. 题目存盘。改提示词、换模型之后用**同一套题**再跑一遍,数字才可比。

这是"有没有变好"的最低配对照,不是排行榜。样本小,差几个点不算数;看的是方向。
"""
import json, os, random, statistics, time
from concurrent.futures import ThreadPoolExecutor

from . import config, llm, recall, store

EVAL_DIR = os.path.join(config.HOME, 'eval')

GEN_ZH = """下面是一条"关于 {user_name} 的记忆"。请写一个真人可能会问的问题,它的答案正好是这条记忆。

要求:
- **不许照抄这条记忆里的说法**。同义词、上位词、口语化的问法都行,但关键名词要换一种说法。
  (照抄的话这道题就白出了 —— 我们要测的正是"换个说法还能不能找到"。)
- 一句话,不超过 20 字,像工作中随口问 AI 的那种。
- 只输出问题本身,不要解释、不要引号。

记忆:{content}"""

GEN_EN = """Below is one memory about {user_name}. Write a question a real person might ask whose
answer is exactly this memory.

Rules:
- **Do not reuse the memory's own wording.** Synonyms, hypernyms, colloquial phrasing are all
  fine, but the key nouns must be said a different way. (Reusing them makes the item useless —
  what we are measuring is exactly "phrased differently, can it still be found".)
- One short line, the way you would ask an AI in passing.
- Output the question only. No explanation, no quotes.

Memory: {content}"""


def _gen_one(cfg, m):
    tmpl = GEN_EN if (cfg.get('language') or 'zh') == 'en' else GEN_ZH
    try:
        q = llm.ask(tmpl.format(user_name=cfg.get('user_name'), content=(m.get('content') or '')[:600]),
                    timeout=120, model=(cfg.get('recall') or {}).get('model') or None, effort='low')
    except Exception as ex:
        return None
    q = (q or '').strip().splitlines()[0].strip(' "\'「」') if q else ''
    return {'q': q, 'gold': m['id']} if q else None


def build_set(cfg, n, seed=0):
    rows = [m for m in store.load() if m.get('status') != 'overturned' and m.get('content')]
    if len(rows) < n:
        n = len(rows)
    random.Random(seed).shuffle(rows)
    picked = rows[:n]
    with ThreadPoolExecutor(max_workers=4) as ex:      # 都是等子进程,不吃 CPU
        items = list(ex.map(lambda m: _gen_one(cfg, m), picked))
    return [it for it in items if it]


def rank_of(hits, gold):
    for i, m in enumerate(hits):
        if m.get('id') == gold:
            return i + 1
    return None


def run_arm(cfg, items, fast, k=8):
    def one(it):
        t = time.time()
        hits, terms, _ = recall.find(cfg, it['q'], k, fast=fast)
        return rank_of(hits, it['gold']), time.time() - t, terms
    with ThreadPoolExecutor(max_workers=4) as ex:
        out = list(ex.map(one, items))
    ranks = [r for r, _, _ in out]
    n = len(ranks) or 1
    return {
        'recall@1': sum(1 for r in ranks if r == 1) / n,
        'recall@3': sum(1 for r in ranks if r and r <= 3) / n,
        'recall@8': sum(1 for r in ranks if r and r <= 8) / n,
        'median_rank': statistics.median([r for r in ranks if r]) if any(ranks) else None,
        'seconds': statistics.mean([s for _, s, _ in out]),
        'ranks': ranks,
        'terms': [t for _, _, t in out],
    }


def main(argv=None):
    import argparse
    ap = argparse.ArgumentParser(prog='cm eval', description='量一量检索到底行不行')
    ap.add_argument('--n', type=int, default=20, help='出多少道题')
    ap.add_argument('--seed', type=int, default=0)
    ap.add_argument('--set', default='', help='用已有的题目文件(改了提示词之后要用同一套题)')
    ap.add_argument('--arms', default='literal,expand', help='测哪几路:literal(纯字面) / expand(带查询扩展)')
    a = ap.parse_args(argv)
    cfg = config.load()
    os.makedirs(EVAL_DIR, exist_ok=True)
    if a.set:
        items = json.load(open(a.set, encoding='utf-8'))
        print(f'用已有题目 {a.set}:{len(items)} 道')
    else:
        print(f'出题中({a.n} 道,每道一次小模型调用)…', flush=True)
        items = build_set(cfg, a.n, a.seed)
        p = os.path.join(EVAL_DIR, f"{time.strftime('%Y%m%d-%H%M%S')}-n{len(items)}.json")
        llm.atomic_write(p, json.dumps(items, ensure_ascii=False, indent=1))
        print(f'题目存到 {p}(下次 --set 它,数字才可比)')
    if not items:
        print('出不了题 —— 记忆库是空的?'); return 1
    res = {}
    for arm in [x.strip() for x in a.arms.split(',') if x.strip()]:
        print(f'跑 {arm} …', flush=True)
        res[arm] = run_arm(cfg, items, fast=(arm != 'expand'))
    print()
    print(f"{'':10}{'recall@1':>10}{'recall@3':>10}{'recall@8':>10}{'中位名次':>10}{'每题秒':>9}")
    for arm, r in res.items():
        print(f"{arm:10}{r['recall@1']:>10.0%}{r['recall@3']:>10.0%}{r['recall@8']:>10.0%}"
              f"{str(r['median_rank']):>10}{r['seconds']:>9.1f}")
    if len(res) == 2 and 'literal' in res and 'expand' in res:
        f, e = res['literal'], res['expand']
        better = sum(1 for x, y in zip(f['ranks'], e['ranks'])
                     if (y or 99) < (x or 99))
        worse = sum(1 for x, y in zip(f['ranks'], e['ranks'])
                    if (y or 99) > (x or 99))
        print(f"\n逐题配对:扩展让 {better} 道变好、{worse} 道变差、{len(items)-better-worse} 道不变")
        print('(样本这么小,只看方向;变好不显著就别把它当默认)')
    return 0
