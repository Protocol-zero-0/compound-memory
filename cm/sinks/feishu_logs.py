#!/usr/bin/env python3
"""飞书「会话记录」「每日日志」:每晚确定性填写,零模型调用。

可选功能,配置了才启用(sinks.feishu 下):
    session_table: 会话记录表 id    —— 每个 session 一行,按「会话ID」幂等
    daily_table:   每日日志表 id    —— 每天一行:会话数 + 事件清单(会话 + 会议)
    meeting_base / meeting_table:   会议表(可选),当天的会议也进事件清单
    log_tz_hours:  按哪个时区切"一天"(默认 8)

主题和概况来自提炼时顺手生成的那一句话(存在 state 里),不额外调模型。
**手写的内容不碰**:每日日志里人写的事件清单保留原样,只更新会话数;
只有空白行、或原本就是程序生成的清单(以 [Claude]/[Codex]/[dsh]/[会议] 开头)才重写。
"""
import datetime, json

from .. import sources
from .feishu import _one

AUTO_PREFIX = ('[Claude]', '[Codex]', '[dsh]', '[会议]', '·')
# 纪要四项 → 表里的栏目名(config 里 sinks.feishu.session_fields / daily_fields 可改)
SESSION_FIELDS = {'points': '讨论要点', 'next': '后续动作', 'decisions': '价值信息·决策', 'reflections': '反思·结论'}
DAILY_FIELDS = {'overview': '当日总览', 'decisions': '关键决策·结论', 'reflections': '反思'}


def _bullets(items):
    return '\n'.join(f'· {x}' for x in items)
LABEL = {'claude': 'Claude', 'codex': 'Codex', 'dsh': 'dsh'}


def _day(ts, tz):
    t = datetime.datetime.strptime(ts[:19], '%Y-%m-%dT%H:%M:%S') + datetime.timedelta(hours=tz)
    return t.strftime('%Y-%m-%d'), t.strftime('%Y-%m-%d %H:%M:%S')


def _list(sink, base, table, fields):
    out, offset = {}, 0
    while True:
        args = ['base', '+record-list', '--base-token', base, '--table-id', table, '--limit', '200', '--json']
        for f in fields:
            args += ['--field-id', f]
        if offset:
            args += ['--offset', str(offset)]
        d = sink._lark(args, timeout=90).get('data') or {}
        rows = d.get('data') or []
        for rid, vals in zip(d.get('record_id_list') or [], rows):
            out[rid] = {k: _one(v) for k, v in zip(d.get('fields') or fields, vals)}
        if not rows or not d.get('has_more'):
            return out
        offset += len(rows)


def _upsert(sink, table, body, rid=None):
    args = ['base', '+record-upsert', '--base-token', sink.base, '--table-id', table,
            '--json', json.dumps(body, ensure_ascii=False)]
    if rid:
        args += ['--record-id', rid]
    return sink._lark(args).get('ok')


def sync(cfg, sink, state, days, log=print):
    conf = sink.conf
    st_tab, dl_tab = conf.get('session_table'), conf.get('daily_table')
    if not (st_tab or dl_tab):
        return
    tz = int(conf.get('log_tz_hours', 8))
    recs = {f"{r['source']}:{r['sid']}": r for r in sources.scan_all(cfg, None)}
    n_s = n_d = 0

    if st_tab:
        have = {v.get('会话ID'): rid for rid, v in _list(sink, sink.base, st_tab, ['会话ID']).items() if v.get('会话ID')}
        for key, st in state.items():
            if key.startswith('_') or not st.get('topic') or key not in recs or key.startswith('meeting:'):
                continue                                  # 只写本系统提炼过、有主题的会话;会议有自己的会议记录表
            r = recs[key]
            if not r.get('ts_first') or _day(r['ts_first'], tz)[0] not in days:
                continue
            body = {'主题': st['topic'], '摘要': st.get('summary') or '', '日期': _day(r['ts_first'], tz)[1],
                    '来源': [LABEL.get(r['source'], r['source'])], '会话ID': r['sid']}
            sf = {**SESSION_FIELDS, **(conf.get('session_fields') or {})}
            for k, col in sf.items():
                items = (st.get('log') or {}).get(k) or []
                if items:
                    body[col] = _bullets(items)
            if _upsert(sink, st_tab, body, have.get(r['sid'])):
                n_s += 1

    if dl_tab:
        meets = {}
        if conf.get('meeting_base') and conf.get('meeting_table'):
            for v in _list(sink, conf['meeting_base'], conf['meeting_table'], ['日期', '主题']).values():
                meets.setdefault(str(v.get('日期') or '')[:10], []).append(v.get('主题'))
        df = {**DAILY_FIELDS, **(conf.get('daily_fields') or {})}
        daily = {}
        for rid, v in _list(sink, sink.base, dl_tab, ['日期', '事件清单', *df.values()]).items():
            daily.setdefault(str(v.get('日期') or '')[:10], (rid, v))
        for day in sorted(days):
            ev = []
            for key, r in sorted(recs.items(), key=lambda kv: kv[1].get('ts_first') or ''):
                if not r.get('ts_first') or r.get('n_user_turns', 0) < 2 or _day(r['ts_first'], tz)[0] != day \
                        or r['source'] == 'meeting':
                    continue                              # 会议走下面的 [会议] 行
                topic = (state.get(key) or {}).get('topic') or r.get('title') or '(未提炼)'
                ev.append(f"[{LABEL.get(r['source'], r['source'])}] {topic}({sources.short(r['sid'])},{r['n_user_turns']}轮)")
            ev += [f'[会议] {m}' for m in meets.get(day, [])]
            if not ev:
                continue
            rid, old = daily.get(day, (None, {}))
            auto = lambda col: not str(old.get(col) or '').strip() or str(old.get(col)).lstrip().startswith(AUTO_PREFIX) \
                or str(old.get(col)).startswith('(自动生成')
            body = {'会话数': len(ev)}
            if auto('事件清单'):
                body['事件清单'] = '\n'.join(ev)         # 人写的内容一律不覆盖
            logs = [(state.get(k) or {}) for k, r in recs.items()
                    if r.get('ts_first') and _day(r['ts_first'], tz)[0] == day and (state.get(k) or {}).get('topic')]
            agg = {'overview': [f"{x['topic']}:{x.get('summary') or ''}" for x in logs],
                   'decisions': [d for x in logs for d in ((x.get('log') or {}).get('decisions') or [])],
                   'reflections': [d for x in logs for d in ((x.get('log') or {}).get('reflections') or [])]}
            for k, col in df.items():
                if agg.get(k) and auto(col):
                    body[col] = _bullets(agg[k])
            if not rid:
                body['日期'] = f'{day} 12:00:00'
            if _upsert(sink, dl_tab, body, rid):
                n_d += 1
    log(f'继承表:会话记录 {n_s} 行,每日日志 {n_d} 天')
