#!/usr/bin/env python3
"""后续事项:由脚本自己按条件推进,不靠任何人的记忆。

这是整个系统里最容易被忽略、却最省事的一块:"等它稳了再做 X"这种话,写进
~/.compound-memory/memory/followups.json,条件满足时脚本自己做掉并留痕,
不用你记、也不用 AI 在某个 session 里刚好想起来。

条目格式:
  {"id":"...", "when":"streak>=7 | manual", "status":"pending",
   "what":"一句话说清要做什么", "run":"可选,满足条件时执行的 shell 命令"}
"""
import json, os, subprocess, time

from . import config, llm, store

PATH = os.path.join(config.HOME, 'memory', 'followups.json')
NOTICES = os.path.join(config.HOME, 'memory', 'notices.md')

DEFAULT = [
    {'id': 'cold_backup', 'when': 'streak>=7', 'status': 'pending', 'run': '',
     'what': '提醒一次:原始语料还没有冷备份。记忆可以重算,原文丢了就真没了 —— '
             '把 session 目录加密打包放一份到别的账户下。'},
]


def load():
    if not os.path.exists(PATH):
        llm.atomic_write(PATH, json.dumps(DEFAULT, ensure_ascii=False, indent=1))
        return list(DEFAULT)
    return store.jload(PATH, list(DEFAULT))


def notice(text):
    with open(NOTICES, 'a', encoding='utf-8') as f:
        f.write(f"- {time.strftime('%Y-%m-%d %H:%M')} {text}\n")
    print(f'  · 待办:{text}', flush=True)


def met(when, meta):
    if when.startswith('streak>='):
        try:
            return meta.get('streak', 0) >= int(when.split('>=')[1])
        except ValueError:
            return False
    return False


def run(state, ok):
    meta = state.setdefault('_meta', {})
    meta['streak'] = (meta.get('streak', 0) + 1) if ok else 0
    meta['last_run'] = time.strftime('%Y-%m-%d %H:%M')
    items = load()
    changed = False
    for it in items:
        if it.get('status') != 'pending' or it.get('when') == 'manual':
            continue
        if not met(it.get('when', ''), meta):
            continue
        if it.get('run'):
            r = subprocess.run(it['run'], shell=True, capture_output=True, text=True, timeout=600)
            notice(f"{it['id']}: {it['what']}(执行 rc={r.returncode})")
        else:
            notice(f"{it['id']}: {it['what']}")
        it['status'] = f"done {time.strftime('%Y-%m-%d')}"
        changed = True
    if changed:
        llm.atomic_write(PATH, json.dumps(items, ensure_ascii=False, indent=1))
