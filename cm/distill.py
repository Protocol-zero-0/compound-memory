#!/usr/bin/env python3
"""提炼:按 session 增量,把原始对话变成"关于你"的记忆。

三条不能动的设计(都是踩过坑换来的):
1. **处理单位是 session,不是日期。** 水位线 = 该 session 上次处理到的 ts_last —— 用
   "文件里最后一条消息的时间戳",不用 mtime:挂着的会话进程自己写元数据也会刷 mtime,
   按 mtime 判会天天空转烧额度。
2. **有新内容时,把整个 session 连同它以前提炼出的记忆一起重新理解。** 记忆不是追加日志,
   是可以被后来的对话修正的理解。
3. **额度纪律。** 每次运行有上限;遇到额度到顶立刻停,并且**不推进水位线**,下次接着跑。
"""
import argparse, datetime, json, os, socket, time

from . import config, llm, prompts, store, sinks, lexicon as L
from . import sources
from .snapshot import build as build_snapshot

HOST = socket.gethostname()
LOG = os.path.join(config.HOME, 'distill.log')
BATCH = None


def log(msg):
    line = f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {msg}"
    print(line, flush=True)
    os.makedirs(config.HOME, exist_ok=True)
    with open(LOG, 'a', encoding='utf-8') as f:
        f.write(line + '\n')


def cutoff(days):
    return (datetime.datetime.now(datetime.timezone.utc)
            - datetime.timedelta(days=days)).strftime('%Y-%m-%dT%H:%M:%SZ')


def candidates(cfg, state, days, limit=None):
    """挑出"有新对话、而且新得够多值得再调一次模型"的 session。"""
    since = cutoff(days)
    recs = sources.scan_all(cfg, since)
    todo = []
    for r in recs:
        if not r.get('ts_last') or r['ts_last'] < since or r.get('n_user_turns', 0) < 2:
            continue
        key = f"{r['source']}:{r['sid']}"
        st = state.get(key)
        if st and st.get('ts_last') == r['ts_last']:
            continue                                  # 最后一条消息没变 = 没有新对话
        if st and not llm.needs_resummary(st.get('turns') or 0, r.get('n_user_turns', 0)):
            continue                                  # 有新对话但不到 max(3 轮, 25%),攒着下次一起理解
        todo.append(r)
    todo.sort(key=lambda r: r['ts_last'])
    return todo[:limit] if limit else todo


def session_text(turns, budget):
    joined = '\n- '.join(turns)
    if len(joined) > budget:
        h = int(budget * 0.4)
        joined = joined[:h] + '\n…(中间省略)…\n' + joined[-(budget - h):]
    return joined


def query_of(rec, turns):
    """给"找相关旧记忆"用的检索词:标题 + 头尾几轮。不额外调模型。"""
    bits = [rec.get('title') or '']
    bits += [t[:200] for t in turns[:3]]
    bits += [t[:200] for t in turns[-3:]]
    return ' '.join(b for b in bits if b)


def fmt_related(ms, lang):
    if not ms:
        return '(none)' if lang == 'en' else '(无)'
    return '\n'.join(
        f"- [{m['id']}] ({L.word(m['nature'], lang)}/{L.word(m['kind'], lang)}/"
        f"{L.word(m['horizon'], lang)}/{L.word(m['status'], lang)}, {m['date']}) {m['content']}"
        for m in ms)


def distill_session(rec, rows, cfg):
    """一个 session → (topic, summary, 新记忆列表)。一次模型调用。"""
    lang = cfg.get('language') or 'zh'
    turns = sources.load_turns(rec)
    if len(turns) < 2:
        return None, None, []
    rel = store.related(rows, query_of(rec, turns), sid=rec['sid'])
    prompt = prompts.build(
        'distill', lang, user_name=cfg.get('user_name'), src=rec['source'],
        title=rec.get('title') or '-', t0=(rec.get('ts_first') or '')[:16],
        t1=(rec.get('ts_last') or '')[:16], turns=len(turns),
        text=session_text(turns, int(cfg.get('text_budget') or 14000)),
        related=fmt_related(rel, lang), maxn=cfg.get('max_candidates') or 8)
    data = llm.ask_json(prompt, timeout=int(os.environ.get('CM_TIMEOUT', '420')))
    llm.log_usage('distill', 1)
    day = (rec.get('ts_last') or '')[:10]
    out = []
    for c in (data.get('candidates') or [])[:int(cfg.get('max_candidates') or 8)]:
        content = (c.get('content') or '').strip()
        if not content:
            continue
        out.append({
            'id': store.new_id(), 'date': day,
            'nature': L.canon(c.get('nature'), L.NATURE, 'fact'),
            'kind': L.canon(c.get('kind'), L.KIND, 'event'),
            'horizon': L.canon(c.get('horizon'), L.HORIZON, 'short'),
            'content': store.scrub(content),
            'scope': store.scrub(c.get('scope') or ''),
            'expires': c.get('expires') or '',
            'quote': store.scrub(c.get('quote') or ''),
            'source': rec['source'], 'source_sid': rec['sid'], 'host': HOST,
            'source_label': f"{HOST} · {rec['source']}:{rec['sid']} · {data.get('topic') or ''}",
            'status': 'active',
            'revises': c.get('revises') or None,
            'old_status': L.canon(c.get('old_status'), ('revised', 'overturned', 'closed'), None)
                          if c.get('old_status') else None,
            'share': bool(c.get('share')),
            'share_reason': c.get('share_reason') or '',
            'batch': BATCH, 'remote': {},
        })
    rec['_log'] = {k: [store.scrub(str(x)) for x in (((data.get('log') or {}).get(k)) or []) if str(x).strip()]
                   for k in ('points', 'next', 'decisions', 'reflections')}
    return data.get('topic'), data.get('summary'), out


def import_sources(cfg, rows):
    """每次提炼前,把别的记忆系统新产出的条目并进来(按记忆 ID 去重,重复跑安全)。
    用于跟另一套系统并行过渡:比如会议还由旧系统处理,它的新记忆每晚并进这里的快照。"""
    import importlib.util
    paths = [config.expand(p) for p in (cfg.get('import_sources') or [])]
    if not paths:
        return 0
    spec = importlib.util.spec_from_file_location('legacy', os.path.join(config.REPO, 'tools', 'import-legacy-jsonl.py'))
    mod = importlib.util.module_from_spec(spec); spec.loader.exec_module(mod)
    have, n = {m['id'] for m in rows}, 0
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in open(p, encoding='utf-8'):
            try:
                m = mod.convert(json.loads(line), HOST)
            except Exception:
                continue
            if m and m['id'] not in have:
                rows.append(m); have.add(m['id']); n += 1
    return n


def run(cfg, days=None, limit=None, dry=False, no_snapshot=False, snapshot_only=False, days_backfill=0):
    global BATCH
    if not llm.try_lock('distill'):
        log('另一个提炼正在跑,退出'); return 1
    BATCH = time.strftime('%Y%m%d-%H%M')
    days = days or int(cfg.get('window_days') or 7)
    limit = limit if limit is not None else int(cfg.get('nightly_limit') or 20)
    state = store.load_state()
    rows = store.load()
    n_imp = import_sources(cfg, rows)
    if n_imp:
        store.save(rows)
        log(f'从 import_sources 并入 {n_imp} 条新记忆')
    by_id = {m['id']: m for m in rows}
    done, errors, hit_limit = 0, [], False

    if not snapshot_only:
        todo = candidates(cfg, state, days, limit or None)
        log(f'batch={BATCH} model={llm.MODEL} effort={llm.EFFORT} 待处理 session {len(todo)} 个(窗口 {days} 天)')
        if dry:
            for r in todo:
                print(f"  {r['source']:7} {sources.short(r['sid'])} turns={r.get('n_user_turns'):<4} "
                      f"{r.get('ts_last','')[:10]}  {r.get('title') or ''}")
            return 0
        for r in todo:
            try:
                topic, summary, new = distill_session(r, rows, cfg)
            except llm.UsageLimit as ex:
                log(f'  !! 额度到顶,本次停止,未处理的留到下次(水位线未动):{str(ex)[:120]}')
                hit_limit = True
                break
            except Exception as ex:
                log(f"  ! {r['source']}:{sources.short(r['sid'])} 提炼失败 {type(ex).__name__}: {str(ex)[:160]}")
                errors.append(r['sid'])
                continue
            for m in new:
                old = by_id.get(m['revises']) if m.get('revises') else None
                if old and m.get('old_status'):
                    old['status'] = m['old_status']    # 只有"取代"才改旧条状态
                rows.append(m)
                by_id[m['id']] = m
            state[f"{r['source']}:{r['sid']}"] = {
                'ts_last': r['ts_last'], 'turns': r.get('n_user_turns'), 'batch': BATCH,
                'n': len(new), 'topic': topic, 'summary': summary, 'log': r.get('_log') or {}}
            store.save(rows)
            store.save_state(state)
            done += 1
            log(f"  ✓ {r['source']:7} {sources.short(r['sid'])} {topic or ''} → {len(new)} 条"
                f"(共享 {sum(1 for m in new if m['share'])})")

    sink = sinks.get(cfg)
    if done or snapshot_only:
        try:
            n = sink.publish_memories(rows)
            store.save(rows)                          # 共享层回执(remote)写回
            log(f'共享层 {sink.describe()}:{n} 条')
        except Exception as ex:
            log(f'  ! 写共享层失败 {type(ex).__name__}: {str(ex)[:200]}')
            errors.append('sink')

    if (cfg.get('sink') or '') == 'feishu' and (done or snapshot_only or days_backfill):
        try:
            from .sinks.feishu_logs import sync as sync_logs
            tz = int(((cfg.get('sinks') or {}).get('feishu') or {}).get('log_tz_hours', 8))
            today = datetime.datetime.utcnow() + datetime.timedelta(hours=tz)
            days_set = {(today - datetime.timedelta(days=i)).strftime('%Y-%m-%d') for i in range(max(2, days_backfill or 0))}
            sync_logs(cfg, sink, state, days_set, log)
        except Exception as ex:
            log(f'  ! 填会话记录/每日日志失败 {type(ex).__name__}: {str(ex)[:160]}')

    if not no_snapshot and (done or snapshot_only):
        try:
            text = build_snapshot(cfg, rows, done, BATCH)
            where = sink.publish_snapshot(text)
            log(f'快照已发布 {len(text)} 字 → {where}')
        except llm.UsageLimit as ex:
            log(f'  !! 生成快照时额度到顶,保留上一版:{str(ex)[:120]}')
            hit_limit = True
        except Exception as ex:
            log(f'  ! 快照失败 {type(ex).__name__}: {str(ex)[:200]}')
            errors.append('snapshot')

    left = candidates(cfg, state, days)
    log(f'覆盖核对:窗口内仍未处理到最新的 session {len(left)} 个')
    if not (dry or snapshot_only):
        from .followups import run as run_followups
        run_followups(state, ok=(done > 0 and not errors and not hit_limit))
        store.save_state(state)
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog='cm distill', description='按 session 增量提炼记忆')
    ap.add_argument('--days', type=int, default=None, help='只看最近多少天有新对话的 session')
    ap.add_argument('--limit', type=int, default=None, help='本次最多处理几个 session(0=不限)')
    ap.add_argument('--dry', action='store_true', help='只列要处理的 session,不调模型')
    ap.add_argument('--no-snapshot', action='store_true')
    ap.add_argument('--snapshot-only', action='store_true', help='不提炼,只用现有记忆重写快照')
    ap.add_argument('--logs-backfill', type=int, default=0, help='飞书会话记录/每日日志往回补几天')
    a = ap.parse_args(argv)
    cfg = config.load()
    return run(cfg, a.days, a.limit, a.dry, a.no_snapshot, a.snapshot_only, a.logs_backfill)


if __name__ == '__main__':
    raise SystemExit(main())
