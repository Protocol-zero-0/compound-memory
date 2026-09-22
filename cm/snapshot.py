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


RETRY_NUDGE = ('\n\n(上一次你没有按要求输出 —— 只输出 Markdown 正文,从"## A"开始;'
               '不要解释、不要调用工具、不要写文件、不要提任何文件路径。)')


def ok(body):
    """快照至少得是四节里的第一节开头。模型偶尔会返回一段"我打算怎么做"的自述。"""
    return bool(body) and '## A' in body


def pick(live, budget):
    """喂给模型的记忆也要有上限,否则记忆一多,快照必然超长、压缩轮数也压不回来。

    取舍是固定的:**「要求」和「线头·承诺」一条不删**(它们有指令效力、而且线头不按时间退出),
    其余按从新到旧填到预算为止。被挤掉的靠 `cm recall` 检索,不靠把快照写长。
    """
    keep = [m for m in live if m['nature'] == 'request' or m['kind'] == 'thread']
    rest = sorted([m for m in live if m not in keep], key=lambda m: m['date'], reverse=True)
    used = sum(len(m.get('content') or '') for m in keep)
    for m in rest:
        n = len(m.get('content') or '')
        if used + n > budget:
            continue
        keep.append(m)
        used += n
    keep.sort(key=lambda m: (m['horizon'] != 'long', m['date']))
    return keep, len(live) - len(keep)


def build(cfg, rows, sessions_done, batch):
    lang = cfg.get('language') or 'zh'
    hard = int(cfg.get('snapshot_max_chars') or 3200)
    live = store.shared(rows)
    live.sort(key=lambda m: (m['horizon'] != 'long', m['date']))
    live, dropped = pick(live, int(cfg.get('snapshot_input_budget') or hard * 8))
    if dropped:
        print(f'  · 喂给快照的记忆裁到 {len(live)} 条(略过 {dropped} 条较旧的,检索仍然找得到)', flush=True)
    mems = '\n'.join(
        f"- [{L.word(m['nature'], lang)}/{L.word(m['kind'], lang)}/{L.word(m['horizon'], lang)}/"
        f"{L.word(m['status'], lang)}, {m['date']}, "
        f"{'scope' if lang == 'en' else '范围'}:{m.get('scope') or '-'}] {m['content']}"
        for m in live)
    n_corr = sum(1 for m in rows if m['kind'] == 'correction' and m.get('batch') == batch)
    prev_path = os.path.join(config.HOME, 'memory', 'snapshot.md')
    prev = open(prev_path, encoding='utf-8').read()[:4000] if os.path.exists(prev_path) else '(none)'

    p = prompts.build('snapshot', lang, user_name=cfg.get('user_name'),
                      soft_limit=int(hard * 0.78), hard_limit=hard,
                      n_corr=n_corr, prev=prev, mems=mems)
    body = ''
    for i in range(2):                       # 一次废话就重来一次,别让整晚的提炼白跑
        body = llm.ask(p if i == 0 else p + RETRY_NUDGE, timeout=900)
        llm.log_usage('snapshot', 1)
        if ok(body):
            break
    if not ok(body):
        raise ValueError('快照输出不含 A 节:' + body[:200])
    target = int(hard * 0.85)                # 留点余量,压到刚好就容易又超
    for _ in range(3):                       # 长度是软约束:压不下去也要有快照,不能因此整晚白跑
        if len(body) <= hard:
            break
        out = llm.ask(prompts.build('compress', lang, cur=len(body), hard_limit=target, body=body),
                      timeout=900)
        llm.log_usage('snapshot-compress', 1)
        if not (ok(out) and len(out) < len(body)):
            print(f'  · 压缩没生效({len(body)} 字 / 上限 {hard}),保留上一版', flush=True)
            break
        body = out
    if len(body) > hard:
        print(f'  · 快照正文 {len(body)} 字,仍超过上限 {hard} —— 已发布,但该调小 '
              f'snapshot_input_budget 或调大 snapshot_max_chars', flush=True)

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
