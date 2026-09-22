#!/usr/bin/env python3
"""快照:开局导航,不是全部记忆。

固定四节(长时效 / 短时效 / 模式与矛盾 / 指标),正文有硬字数上限 —— 因为它要注入每一个
session 的开头。放不下的东西靠 `cm recall` 检索,不靠把快照写长。
"""
import os, time

from . import config, llm, prompts, store, lexicon as L

HOST_LINE_ZH = ('生成:{t} · 生成机器:{host} · 有效共享记忆 {n} 条 · 本批处理 {done} 个 session\n'
                '原文和完整记忆在生成机器本机;本机不可核查的细节请标注「未核实」。'
                '快照只是开局导航,工作中按任务检索。\n\n')
HOST_LINE_EN = ('generated {t} · on {host} · {n} live shared memories · {done} sessions this batch\n'
                'The transcripts and the full memory store stay on the machine that generated this. '
                'Mark anything you cannot verify locally as unverified. This snapshot is orientation, '
                'not the whole record — search for details as the task needs them.\n\n')


def build(cfg, rows, sessions_done, batch):
    lang = cfg.get('language') or 'zh'
    hard = int(cfg.get('snapshot_max_chars') or 3200)
    live = store.shared(rows)
    live.sort(key=lambda m: (m['horizon'] != 'long', m['date']))
    mems = '\n'.join(
        f"- [{L.word(m['nature'], lang)}/{L.word(m['kind'], lang)}/{L.word(m['horizon'], lang)}/"
        f"{L.word(m['status'], lang)}, {m['date']}, "
        f"{'scope' if lang == 'en' else '范围'}:{m.get('scope') or '-'}] {m['content']}"
        for m in live)
    n_corr = sum(1 for m in rows if m['kind'] == 'correction' and m.get('batch') == batch)
    prev_path = os.path.join(config.HOME, 'memory', 'snapshot.md')
    prev = open(prev_path, encoding='utf-8').read()[:4000] if os.path.exists(prev_path) else '(none)'

    body = llm.ask(prompts.build('snapshot', lang, user_name=cfg.get('user_name'),
                                 soft_limit=int(hard * 0.78), hard_limit=hard,
                                 n_corr=n_corr, prev=prev, mems=mems), timeout=900)
    llm.log_usage('snapshot', 1)
    for _ in range(2):                       # 长度是硬约束:它要进每个 session 的开头
        if len(body) <= hard:
            break
        body = llm.ask(prompts.build('compress', lang, cur=len(body), hard_limit=hard, body=body),
                       timeout=900)
        llm.log_usage('snapshot-compress', 1)
    if '## A' not in body:
        raise ValueError('快照输出不含 A 节:' + body[:200])

    head_t = HOST_LINE_EN if lang == 'en' else HOST_LINE_ZH
    title = f"# {cfg.get('user_name')} · snapshot\n\n" if lang == 'en' else f"# {cfg.get('user_name')} · 当前快照\n\n"
    head = title + head_t.format(t=time.strftime('%Y-%m-%d %H:%M'), host=store.HOST,
                                 n=len(live), done=sessions_done)
    text = head + body.strip() + baseline(cfg, lang)
    llm.atomic_write(prev_path, text)        # 本机留一份,给下一次做措辞参照,也是取不到共享层时的兜底
    return text


def baseline(cfg, lang):
    """可选的底线附录:把一个本机规则文件原样抄进来,不经模型改写。"""
    p = config.expand(cfg.get('baseline_file') or '')
    if not p or not os.path.exists(p):
        return '\n'
    body = open(p, encoding='utf-8').read().strip()
    if not body:
        return '\n'
    head = ('\n\n## E Hard limits (verbatim, applies on every machine)\n\n' if lang == 'en'
            else '\n\n## E 底线(每台机器都生效,原文照抄)\n\n')
    return head + body + '\n'
