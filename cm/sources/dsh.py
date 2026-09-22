#!/usr/bin/env python3
"""DeepSeek Harness(dsh):~/.dsh/sessions/<工作区槽>/session-<uuid>/session*.jsonl.zstd

这部分公开文档没写,是实测摸出来的(方法与证据见 docs/dsh.md):
- 会话是 **zstd 压缩**的 JSONL,一个 session 一个目录;同目录里可能同时有旧版
  `session.jsonl.zstd` 和新版 `session.v3.jsonl.zstd`,**以版本高的为准**。
- 用户发言取 `type == "user/message"` 且 `data.source.kind == "user"`。
  另外两个坑:
    * `agent/inbox/spliced` 事件里也带同一条消息,那是收件箱的搬运记录,会重复计数;
    * `source.kind` 还有 `plugin` / `agent-instructions` / `skill-catalog` —— 那是注入进去的
      上下文(**包括本项目自己注入的快照**),不是人说的话,必须滤掉,否则记忆会自我循环。
- 时间戳是 epoch 毫秒(`time` 字段);会话头一行 `{"type":"session", createdAt, cwd, id}`。
- 标题在 `type == "session/title"` 事件里,`data.source.kind == "provider"` 的那条比
  `fallback` 那条好(fallback 是把首句截断)。
- 解压优先级:Python 3.14 的 compression.zstd → zstandard 模块 → 系统 zstd 命令。
"""
import glob, json, os, subprocess

from . import cached_scan, since_epoch, iso, clean, is_noise
from .. import config

NAME = 'dsh'


def root(cfg):
    return config.expand(config.host_cfg(cfg, NAME).get('dir') or '~/.dsh/sessions')


def available(cfg):
    return os.path.isdir(root(cfg))


# ---------- 解压 ----------
_ZSTD = None


def _decompress(path):
    global _ZSTD
    if _ZSTD is None:
        try:
            from compression import zstd as _z      # Python 3.14+
            _ZSTD = ('stdlib', _z)
        except ImportError:
            try:
                import zstandard as _z              # pip install zstandard
                _ZSTD = ('module', _z)
            except ImportError:
                _ZSTD = ('cli', None)
    kind, mod = _ZSTD
    if kind == 'stdlib':
        with open(path, 'rb') as f:
            return mod.decompress(f.read()).decode('utf-8', 'replace')
    if kind == 'module':
        with open(path, 'rb') as f:
            return mod.ZstdDecompressor().stream_reader(f).read().decode('utf-8', 'replace')
    r = subprocess.run(['zstd', '-dc', path], capture_output=True, timeout=120)
    if r.returncode != 0:
        raise RuntimeError('解压 zstd 失败,装 `zstd` 命令或 `pip install zstandard`')
    return r.stdout.decode('utf-8', 'replace')


def _events(path):
    for line in _decompress(path).splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except Exception:
            continue


# ---------- 读取 ----------
def _iter_user_texts(path):
    for o in _events(path):
        if o.get('type') != 'user/message':
            continue
        d = o.get('data') or {}
        if ((d.get('source') or {}).get('kind')) != 'user':
            continue                                  # plugin / agent-instructions / skill-catalog = 注入的上下文
        txt = '\n'.join(c.get('text') or '' for c in (d.get('content') or [])
                        if c.get('type') in (None, 'text'))
        txt = clean(txt)
        if is_noise(txt):
            continue
        yield txt


def _version(path):
    base = os.path.basename(path)
    if base.startswith('session.v') and base[9:].split('.')[0].isdigit():
        return int(base[9:].split('.')[0])
    return 0


def _parse(path):
    sid = cwd = created = None
    ts_first = ts_last = None
    title = title_rank = None
    n = 0
    for o in _events(path):
        t = o.get('type')
        if t == 'session':
            sid, cwd, created = o.get('id'), o.get('cwd'), o.get('createdAt')
        tm = o.get('time') or created
        if tm:
            ts_first = ts_first or tm
            ts_last = tm
        if t == 'session/title':
            d = o.get('data') or {}
            rank = 2 if ((d.get('source') or {}).get('kind') == 'provider') else 1
            if title_rank is None or rank >= title_rank:
                title, title_rank = d.get('title'), rank
        if t == 'user/message' and ((o.get('data') or {}).get('source') or {}).get('kind') == 'user':
            n += 1
    if not sid:
        sid = os.path.basename(os.path.dirname(path))
    if not ts_last:
        return None
    return {'source': NAME, 'sid': sid, 'path': path, 'cwd': cwd, 'title': title,
            'ts_first': iso(ts_first or created), 'ts_last': iso(ts_last),
            'n_user_turns': n, 'ver': _version(path)}


def scan(cfg, since=None):
    paths = glob.glob(os.path.join(root(cfg), '*', 'session-*', 'session*.jsonl.zstd'))
    paths += glob.glob(os.path.join(root(cfg), 'session-*', 'session*.jsonl.zstd'))
    recs = cached_scan(NAME, paths, _parse, since_epoch(since))
    best = {}
    for r in recs:                                     # 同一 session 目录下留版本最高的那份
        cur = best.get(r['sid'])
        if not cur or r.get('ver', 0) > cur.get('ver', 0):
            best[r['sid']] = r
    return list(best.values())


def load_turns(rec):
    return list(_iter_user_texts(rec['path']))
