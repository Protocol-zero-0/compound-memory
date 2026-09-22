#!/usr/bin/env python3
"""Claude Code:~/.claude/projects/<项目目录>/<session-id>.jsonl(明文 JSONL)。

每行一个事件。用户发言是 type=='user' 的行;content 可能是字符串,也可能是块数组。
含 tool_result 块的行是工具返回,不是人说的话,要跳过。
"""
import glob, json, os, re

from . import cached_scan, since_epoch, iso, clean, is_noise
from .. import config

NAME = 'claude'
_NOISE_RE = re.compile(
    r'local-command-caveat|command-name|command-message|system-reminder|'
    r'<local-command-stdout>|Caveat: The messages below', re.I)


def root(cfg):
    return config.expand(config.host_cfg(cfg, NAME).get('dir') or '~/.claude/projects')


def available(cfg):
    return os.path.isdir(root(cfg))


def _user_text(o):
    """一条 type=='user' 的事件里,人真正说的话;不是人说的返回 None。"""
    ct = (o.get('message') or {}).get('content')
    if isinstance(ct, str):
        txt = ct
    elif isinstance(ct, list):
        if any(isinstance(b, dict) and b.get('type') == 'tool_result' for b in ct):
            return None                                # 工具返回,不是人说的
        txt = ' '.join(b.get('text', '') for b in ct
                       if isinstance(b, dict) and b.get('type') == 'text')
    else:
        return None
    if not txt or _NOISE_RE.search(txt):
        return None
    txt = clean(re.sub(r'<[^>]+>', ' ', txt))
    return None if is_noise(txt) else txt


def _iter_user_texts(path):
    for line in open(path, encoding='utf-8', errors='ignore'):
        try:
            o = json.loads(line)
        except Exception:
            continue
        if o.get('type') != 'user':
            continue
        txt = _user_text(o)
        if txt:
            yield txt


def _parse(path):
    """一遍读完:标题、时间范围、真实用户轮数。几千个会话时多读一遍就是几分钟的差别。"""
    title, ts_first, ts_last, n = None, None, None, 0
    for line in open(path, encoding='utf-8', errors='ignore'):
        try:
            o = json.loads(line)
        except Exception:
            continue
        t = o.get('type')
        if t == 'custom-title':
            title = o.get('customTitle') or title
        ts = o.get('timestamp')
        if ts:
            ts_first = ts_first or ts
            ts_last = ts
        if t == 'user' and _user_text(o) is not None:
            n += 1
    if not ts_last:
        return None
    return {'source': NAME, 'sid': os.path.basename(path)[:-6], 'path': path,
            'cwd': os.path.basename(os.path.dirname(path)), 'title': title,
            'ts_first': iso(ts_first), 'ts_last': iso(ts_last), 'n_user_turns': n}


def scan(cfg, since=None):
    paths = glob.glob(os.path.join(root(cfg), '*', '*.jsonl'))
    paths += glob.glob(os.path.join(root(cfg), '*.jsonl'))
    return cached_scan(NAME, paths, _parse, since_epoch(since))


def load_turns(rec):
    return list(_iter_user_texts(rec['path']))
