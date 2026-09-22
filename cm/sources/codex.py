#!/usr/bin/env python3
"""Codex CLI:~/.codex/sessions/YYYY/MM/DD/rollout-*.jsonl(明文 JSONL)。

坑:`codex resume` 会产生分叉文件,文件名里的 id ≠ 真实 session_id,而且父 session 的
session_meta 会被重放进分叉文件。按文件里**最后一个** session_meta 的 id 归组,
才不会把一次续聊算成一个独立 session。
"""
import glob, json, os

from . import cached_scan, since_epoch, iso, clean, is_noise
from .. import config

NAME = 'codex'


def root(cfg):
    return config.expand(config.host_cfg(cfg, NAME).get('dir') or '~/.codex/sessions')


def available(cfg):
    return os.path.isdir(root(cfg))


def _iter_user_texts(path):
    for line in open(path, errors='replace'):
        try:
            o = json.loads(line)
        except Exception:
            continue
        p = o.get('payload') or {}
        if o.get('type') == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
            parts = [c.get('text') or c.get('input_text') or '' for c in (p.get('content') or [])]
            msg = '\n'.join(x for x in parts if x).strip()
            if is_noise(msg):
                continue
            yield clean(msg)


def _parse(path):
    sid = cwd = ts_first = ts_last = None
    n = 0
    for line in open(path, errors='replace'):
        try:
            o = json.loads(line)
        except Exception:
            continue
        ts = o.get('timestamp')
        if ts:
            ts_first = ts_first or ts
            ts_last = ts
        t, p = o.get('type'), (o.get('payload') or {})
        if t == 'session_meta':
            sid = p.get('session_id') or p.get('id') or sid
            cwd = p.get('cwd') or cwd
        elif t == 'response_item' and p.get('type') == 'message' and p.get('role') == 'user':
            parts = [c.get('text') or c.get('input_text') or '' for c in (p.get('content') or [])]
            if not is_noise('\n'.join(x for x in parts if x).strip()):
                n += 1
    if not ts_last:
        return None
    return {'source': NAME, 'sid': sid or os.path.basename(path), 'path': path, 'cwd': cwd,
            'title': None, 'ts_first': iso(ts_first), 'ts_last': iso(ts_last), 'n_user_turns': n}


def scan(cfg, since=None):
    paths = glob.glob(os.path.join(root(cfg), '*', '*', '*', 'rollout-*.jsonl'))
    paths += glob.glob(os.path.join(root(cfg), 'rollout-*.jsonl'))
    recs = cached_scan(NAME, paths, _parse, since_epoch(since))
    groups = {}
    for r in recs:
        groups.setdefault(r['sid'], []).append(r)
    out = []
    for sid, rs in groups.items():
        primary = max(rs, key=lambda r: (r['ts_last'] or '', r['n_user_turns']))
        out.append({**primary,
                    'ts_first': min((r['ts_first'] for r in rs if r['ts_first']), default=None),
                    'paths': [r['path'] for r in rs]})
    return out


def load_turns(rec):
    return list(_iter_user_texts(rec['path']))
