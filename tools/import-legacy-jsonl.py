#!/usr/bin/env python3
"""把"中文字段名"的旧记忆 JSONL 导进 compound-memory。

用在两个地方:本项目的原型(session-index/memory/observations.jsonl),
或者任何一行一条、字段叫 内容/日期/性质/类型/时效/状态/… 的记忆文件。

它只写本地库,**不碰共享层** —— 导完自己看一眼,再 `cm distill --snapshot-only` 发出去。
同一个 记忆ID 导第二次会被跳过,重复跑安全。

    python3 tools/import-legacy-jsonl.py <旧文件.jsonl> [--dry] [--host 机器名]
"""
import argparse, json, os, sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from cm import store, lexicon as L                                    # noqa: E402

FIELDS = {'内容': 'content', '适用范围': 'scope', '有效期': 'expires', '引用': 'quote',
          '记忆ID': 'id', '批次': 'batch', '出处': 'source_label'}


def convert(o, host):
    m = {'id': o.get('记忆ID') or o.get('id') or store.new_id(),
         'date': str(o.get('日期') or o.get('date') or '')[:10],
         'nature': L.canon(o.get('性质') or o.get('nature'), L.NATURE, 'fact'),
         'kind': L.canon(o.get('类型') or o.get('kind'), L.KIND, 'event'),
         'horizon': L.canon(o.get('时效') or o.get('horizon'), L.HORIZON, 'short'),
         'status': L.canon(o.get('状态') or o.get('status'), L.STATUS, 'active'),
         'content': store.scrub(o.get('内容') or o.get('content') or ''),
         'scope': store.scrub(o.get('适用范围') or o.get('scope') or ''),
         'expires': o.get('有效期') or o.get('expires') or '',
         'quote': store.scrub(o.get('引用') or o.get('quote') or ''),
         'source': o.get('source') or 'legacy',
         'source_sid': o.get('出处_sid') or o.get('source_sid') or '',
         'host': o.get('机器') or o.get('host') or host,
         'source_label': o.get('出处') or o.get('source_label') or '',
         'revises': o.get('修订自') or o.get('revises') or None,
         'old_status': None,
         'share': bool(o.get('共享', o.get('share', False))),
         'share_reason': o.get('共享理由') or o.get('share_reason') or '',
         'batch': o.get('批次') or o.get('batch') or 'imported',
         'remote': {}}
    return m if m['content'] else None


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('path')
    ap.add_argument('--dry', action='store_true')
    ap.add_argument('--host', default=store.HOST)
    a = ap.parse_args()
    rows = store.load()
    have = {m['id'] for m in rows}
    added, skipped, bad = 0, 0, 0
    for line in open(a.path, encoding='utf-8'):
        line = line.strip()
        if not line:
            continue
        try:
            o = json.loads(line)
        except json.JSONDecodeError:
            bad += 1
            continue
        m = convert(o, a.host)
        if not m:
            bad += 1
        elif m['id'] in have:
            skipped += 1
        else:
            rows.append(m)
            have.add(m['id'])
            added += 1
    print(f'导入 {added} 条,跳过已有 {skipped} 条,读不动 {bad} 条 → 本地库共 {len(rows)} 条')
    if a.dry:
        print('(--dry,没写盘)')
        return 0
    store.save(rows)
    print(f'已写 {store.STORE}。接着跑:cm distill --snapshot-only  (发共享层 + 重写快照)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
