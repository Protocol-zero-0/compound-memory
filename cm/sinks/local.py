#!/usr/bin/env python3
"""local:共享层就是本机一个目录。零账号、零网络,单机用户的默认选择。

想跨机器共享时,把这个目录放进任何同步盘(iCloud / Dropbox / syncthing / NFS)即可;
要走 git 就用 github sink。
"""
import json, os, time

from .. import config, llm, store
from . import Sink, remote_set

README = """# compound-memory 共享层

这个目录由 `cm distill` 自动重写,**不要手工改**。

- `snapshot.md` —— 当前快照,开局注入给 AI 读的那一份。
- `memories.jsonl` —— 判定为"必要且适合共享"的记忆条目(已过密钥清洗)。
- 原始对话语料**不在这里**,它永远留在产生它的那台机器上。

想跨机器共享:把本目录放进任意同步盘,或改用 `sink: github`。
"""


class LocalSink(Sink):
    name = 'local'

    def dir(self):
        d = config.expand(self.conf.get('dir') or os.path.join(config.HOME, 'share'))
        os.makedirs(d, exist_ok=True)
        return d

    def publish_memories(self, rows):
        out = []
        for m in store.shared(rows):
            r = {k: m.get(k) for k in ('id', 'date', 'nature', 'kind', 'horizon', 'content',
                                       'scope', 'expires', 'quote', 'status', 'source',
                                       'source_sid', 'host', 'revises', 'batch')}
            r['content'] = store.scrub(r.get('content'))
            r['quote'] = store.scrub(r.get('quote'))
            r['scope'] = store.scrub(r.get('scope'))
            out.append(r)
            remote_set(m, self.name, m['id'], m.get('status'))
        d = self.dir()
        llm.atomic_write(os.path.join(d, 'memories.jsonl'),
                         ''.join(json.dumps(r, ensure_ascii=False) + '\n' for r in out))
        llm.write_if_changed(os.path.join(d, 'README.md'), README)
        return len(out)

    def publish_snapshot(self, text):
        d = self.dir()
        os.makedirs(os.path.join(d, 'snapshots'), exist_ok=True)
        llm.atomic_write(os.path.join(d, 'snapshots', time.strftime('%Y%m%d-%H%M%S') + '.md'), text)
        p = os.path.join(d, 'snapshot.md')
        llm.atomic_write(p, text)
        return p

    def fetch_snapshot(self):
        p = os.path.join(self.dir(), 'snapshot.md')
        return open(p, encoding='utf-8').read() if os.path.exists(p) else None

    def fetch_memories(self):
        p = os.path.join(self.dir(), 'memories.jsonl')
        if not os.path.exists(p):
            return []
        return [json.loads(l) for l in open(p, encoding='utf-8') if l.strip()]

    def describe(self):
        return f'local:{self.dir()}'
