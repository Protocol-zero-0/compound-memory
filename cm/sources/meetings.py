#!/usr/bin/env python3
"""会议转写:把会议当成第四种语料来源,跟 Claude Code / Codex / dsh 走同一条提炼流程。

采集不在这里做(腾讯会议等由各自的采集脚本负责),这里只读采集好的原文目录:
    <dir>/<会议ID>.json   元数据:meeting.subject / start_time / end_time,source_complete
    <dir>/<会议ID>.txt    转写,一行一句:「说话人: 内容」
只处理 source_complete 为真的会议。每句话都是一个 turn,带着说话人 —— 会议里不只是你在说话。
"""
import glob, json, os

from . import cached_scan, since_epoch, iso
from .. import config

NAME = 'meeting'


def root(cfg):
    return config.expand(config.host_cfg(cfg, NAME).get('dir') or '')


def available(cfg):
    d = root(cfg)
    return bool(d) and os.path.isdir(d)


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
            'title': m.get('subject'), 'ts_first': iso(m.get('start_time')), 'ts_last': iso(m.get('end_time') or m.get('start_time')),
            'n_user_turns': n}


def scan(cfg, since=None):
    """hosts.meeting.since:这个日期以前的会议一律不读(不论窗口多大、是不是补历史)。"""
    floor = str(config.host_cfg(cfg, NAME).get('since') or '')
    paths = glob.glob(os.path.join(root(cfg), '*.json'))
    return [r for r in cached_scan(NAME, paths, _parse, since_epoch(since))
            if r.get('ts_last') and (r.get('ts_first') or '')[:10] >= floor]


def load_turns(rec):
    return [l.strip() for l in open(rec['path'], encoding='utf-8', errors='ignore') if l.strip()]
