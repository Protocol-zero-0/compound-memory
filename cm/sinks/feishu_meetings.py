#!/usr/bin/env python3
"""提炼完的会议写回各自的会议表,状态改成「已入库」。零额外模型调用。

采集脚本负责建行(主题占位、参会人、逐字稿文档链接、状态「待整理」;空录制直接「需人工复核」),
这里只接手「待整理」的行:找到这场会议的提炼结果,填栏目,置「已入库」。
还没提炼的行原样不动,下一轮再来。按腾讯会议 ID 对上,幂等。

配置(sinks.feishu.meeting_tables,每个会议账号一项):
  - profile: work
    base: <Base token>
    table: <表 id>
    fields: {标题: topic, 摘要: summary+points, 决策: decisions, 待办: next, 记忆条数: n}   # 左边是你表里的栏目名
字段值的来源:topic / summary / n,或者纪要里的某一项(points、decisions、corrections…),用 + 拼接。
"""
import json

from .feishu import _one


def _value(src, st):
    parts = []
    for key in src.split('+'):
        key = key.strip()
        if key in ('topic', 'summary'):
            v = st.get(key) or ''
            parts.append(v)
        elif key == 'n':
            return int(st.get('n') or 0)
        else:
            items = (st.get('log') or {}).get(key) or []
            parts.append('\n'.join(f'· {x}' for x in items))
    return '\n'.join(p for p in parts if p)


def _rows(sink, base, table):
    out, offset = [], 0
    while True:
        args = ['base', '+record-list', '--base-token', base, '--table-id', table,
                '--field-id', '腾讯会议ID', '--field-id', '状态', '--limit', '200', '--json']
        if offset:
            args += ['--offset', str(offset)]
        d = sink._lark(args, timeout=90).get('data') or {}
        data = d.get('data') or []
        for rid, vals in zip(d.get('record_id_list') or [], data):
            out.append((rid, {k: _one(v) for k, v in zip(d.get('fields') or [], vals)}))
        if not data or not d.get('has_more'):
            return out
        offset += len(data)


def sync(cfg, sink, state, log=print):
    tables = (sink.conf or {}).get('meeting_tables') or []
    for t in tables:
        n = 0
        for rid, row in _rows(sink, t['base'], t['table']):
            if row.get('状态') != '待整理':
                continue
            ids = [x.strip() for x in str(row.get('腾讯会议ID') or '').split(',') if x.strip()]
            st = next((state.get(f'meeting:{i}') for i in ids if (state.get(f'meeting:{i}') or {}).get('topic')), None)
            if not st:
                continue                                   # 还没提炼,下一轮再来
            body = {col: _value(src, st) for col, src in (t.get('fields') or {}).items()}
            body = {k: v for k, v in body.items() if v not in ('', None)}
            body['状态'] = ['已入库']
            res = sink._lark(['base', '+record-batch-update', '--base-token', t['base'], '--table-id', t['table'],
                              '--json', json.dumps({'update_records': {rid: body}}, ensure_ascii=False)])
            if res.get('ok'):
                n += 1
            else:
                log(f"  ! 会议表写入失败 {ids}: {(res.get('error') or {}).get('message')}")
        if n:
            log(f"会议表 {t.get('profile')}:{n} 场已入库")
