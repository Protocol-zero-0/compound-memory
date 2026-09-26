#!/usr/bin/env python3
"""会议转写:第四种语料来源,跟 Claude Code / Codex / dsh 走同一条提炼流程。

采集不在这里做(由各账号的采集脚本负责),这里只读采集好的原文目录:
    <dir>/<会议ID>.json   元数据:meeting.subject / start_time / end_time,source_complete
    <dir>/<会议ID>.txt    转写,一行一句:「说话人: 内容」
只处理 source_complete 为真的会议。

可以有多个账号(profiles),各自的目录、日期下限、提示词、领域互相独立:
    hosts.meeting.profiles:
      - {name: work,    dir: ..., since: 2026-08-20, domain: work,     prompt: distill_meeting}
      - {name: personal, dir: ..., domain: personal, prompt: <你自己的提示词>}
domain: personal 的记忆只留本机、不进快照、不参与工作话题 —— 生活和工作分开。
"""
import glob, json, os

from . import cached_scan, since_epoch, iso
from .. import config

NAME = 'meeting'


def profiles(cfg):
    hc = config.host_cfg(cfg, NAME)
    ps = hc.get('profiles') or []
    if not ps and hc.get('dir'):                     # 老写法:单个目录
        ps = [{'name': 'work', 'dir': hc.get('dir'), 'since': hc.get('since') or '',
               'domain': 'work', 'prompt': 'distill_meeting'}]
    return [p for p in ps if p.get('dir') and os.path.isdir(config.expand(p['dir']))]


def available(cfg):
    return bool(profiles(cfg))


def _meta(path):
    try:
        return json.load(open(path, encoding='utf-8'))
    except Exception:
        return {}


def _parse(path):
    d = _meta(path)
    if not d.get('source_complete'):
        return None
    m = d.get('meeting') or {}
    txt = path[:-5] + '.txt'
    if not os.path.exists(txt):
        return None
    n = sum(1 for l in open(txt, encoding='utf-8', errors='ignore') if l.strip())
    return {'source': NAME, 'sid': os.path.basename(path)[:-5], 'path': txt, 'cwd': None,
            'title': m.get('subject'), 'ts_first': iso(m.get('start_time')),
            'ts_last': iso(m.get('end_time') or m.get('start_time')), 'n_user_turns': n}


def scan(cfg, since=None):
    out = []
    for p in profiles(cfg):
        floor = str(p.get('since') or '')
        paths = glob.glob(os.path.join(config.expand(p['dir']), '*.json'))
        for r in cached_scan(f"{NAME}-{p['name']}", paths, _parse, since_epoch(since)):
            if r.get('ts_last') and (r.get('ts_first') or '')[:10] >= floor:
                out.append({**r, 'profile': p['name'], 'domain': p.get('domain') or 'work',
                            'prompt': p.get('prompt') or 'distill_meeting'})
    return out


def load_turns(rec):
    return [l.strip() for l in open(rec['path'], encoding='utf-8', errors='ignore') if l.strip()]
