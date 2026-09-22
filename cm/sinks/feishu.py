#!/usr/bin/env python3
"""feishu:共享层放飞书(Lark)多维表格 +一个文档。

适合"人也要翻、还想在手机上看"的场景:记忆一条一行,可以筛选、可以手工标状态。
前置条件:装好 lark-cli 并登录,自己先建一张表(字段见 docs/sinks.md,
`cm sink-init` 会把字段定义打印出来),把 base_token / table_id 填进 config.yaml。
"""
import json, os, subprocess

from .. import config, llm, store, lexicon as L
from . import Sink

FIELD_ORDER = ['content', 'date', 'nature', 'kind', 'horizon', 'scope', 'expires',
               'source', 'status', 'id', 'revises', 'batch']


class FeishuSink(Sink):
    name = 'feishu'

    def __init__(self, cfg):
        super().__init__(cfg)
        self.lang = cfg.get('language') or 'zh'
        self.cli = self.conf.get('cli') or 'lark-cli'
        self.base = self.conf.get('base_token') or ''
        self.table = self.conf.get('table_id') or ''
        if not (self.base and self.table):
            raise RuntimeError('feishu sink 需要 sinks.feishu.base_token 和 table_id;见 docs/sinks.md')

    # ---------- lark-cli ----------
    def _lark(self, args, timeout=90):
        r = subprocess.run([self.cli, *args, '--as', 'user'], capture_output=True,
                           text=True, timeout=timeout, cwd=config.HOME)
        try:
            return json.loads(r.stdout)
        except json.JSONDecodeError:
            return {'ok': False, 'error': {'message': (r.stdout + r.stderr)[:300]}}

    def _labels(self, m):
        """表里给人看的是本地语言,存储里是英文常量。"""
        return {
            '内容': store.scrub(m.get('content')),
            '日期': (m.get('date') or '') + ' 12:00:00',
            '性质': L.word(m.get('nature'), self.lang),
            '类型': L.word(m.get('kind'), self.lang),
            '时效': L.word(m.get('horizon'), self.lang),
            '适用范围': store.scrub(m.get('scope') or ''),
            '有效期': m.get('expires') or '',
            '出处': (m.get('source_label') or f"{m.get('host')} · {m.get('source')}:{m.get('source_sid')}")
                    + (f" · 「{store.scrub(m.get('quote'))}」" if m.get('quote') else ''),
            '状态': L.word(m.get('status'), self.lang),
            '记忆ID': m.get('id'),
            '修订自': m.get('revises') or '',
            '批次': m.get('batch') or '',
        }

    def publish_memories(self, rows):
        n = 0
        for m in rows:
            if not m.get('share'):
                continue
            if m.get('remote_id') and m.get('remote_status') == m.get('status'):
                continue
            args = ['base', '+record-upsert', '--base-token', self.base, '--table-id', self.table,
                    '--json', json.dumps(self._labels(m), ensure_ascii=False)]
            if m.get('remote_id'):
                args += ['--record-id', m['remote_id']]
            res = self._lark(args)
            if not res.get('ok'):
                print(f"  ! 写飞书失败 {m['id']}: {(res.get('error') or {}).get('message')}", flush=True)
                continue
            d = res.get('data') or {}
            ids = (d.get('record') or {}).get('record_id_list') or []
            m['remote_id'] = m.get('remote_id') or (ids[0] if ids else d.get('record_id'))
            m['remote_status'] = m.get('status')
            n += 1
        return n

    def publish_snapshot(self, text):
        tmp_abs = os.path.join(config.HOME, '.snapshot_upload.md')
        llm.atomic_write(tmp_abs, text)
        tmp = '.snapshot_upload.md'          # lark-cli 的 @file 只吃相对 cwd 的路径,_lark 已把 cwd 设成 CM_HOME
        doc = self.conf.get('snapshot_doc') or ''
        if doc:
            res = self._lark(['docs', '+update', '--doc', doc, '--command', 'overwrite',
                              '--doc-format', 'markdown', '--content', f'@{tmp}'], timeout=180)
        else:
            res = self._lark(['docs', '+create', '--title', 'compound-memory · snapshot',
                              '--doc-format', 'markdown', '--content', f'@{tmp}',
                              '--parent-position', 'my_library'], timeout=180)
            if res.get('ok'):
                d = res.get('data') or {}
                doc = (d.get('document_id') or d.get('doc_token') or d.get('token')
                       or (d.get('document') or {}).get('document_id'))
                url = d.get('url') or (d.get('document') or {}).get('url')
                self._remember_doc(doc, url)
        if not res.get('ok'):
            raise RuntimeError(f"快照写飞书失败: {(res.get('error') or {}).get('message')}")
        return self.conf.get('snapshot_url') or doc

    def _remember_doc(self, doc, url):
        """第一次自动建文档后,把 token 记回 config.yaml,下次直接覆盖同一篇。"""
        self.conf['snapshot_doc'], self.conf['snapshot_url'] = doc, url
        p = config.CONFIG_PATH
        try:
            s = open(p, encoding='utf-8').read()
        except FileNotFoundError:
            return
        if "snapshot_doc: ''" in s:
            s = s.replace("snapshot_doc: ''", f"snapshot_doc: '{doc}'")
            if url:
                s = s.replace(f"snapshot_doc: '{doc}'",
                              f"snapshot_doc: '{doc}'\n      snapshot_url: '{url}'")
            llm.atomic_write(p, s)
        else:
            print(f'  · 飞书快照文档已建好,请把 snapshot_doc: {doc} 填进 {p}', flush=True)

    def fetch_snapshot(self):
        doc = self.conf.get('snapshot_doc')
        if not doc:
            return None
        res = self._lark(['docs', '+fetch', '--doc', doc, '--doc-format', 'markdown'], timeout=60)
        d = res.get('data') or {}
        return d.get('content') or d.get('markdown') or (d.get('document') or {}).get('content')

    def fetch_memories(self):
        res = self._lark(['base', '+record-list', '--base-token', self.base,
                          '--table-id', self.table, '--limit', '500', '--json'], timeout=90)
        d = res.get('data') or {}
        fields = d.get('fields') or []
        out = []
        for vals in d.get('data') or []:
            row = dict(zip(fields, vals))
            out.append({'id': row.get('记忆ID'), 'date': str(row.get('日期') or '')[:10],
                        'nature': L.canon(row.get('性质'), L.NATURE, 'fact'),
                        'kind': L.canon(row.get('类型'), L.KIND, 'event'),
                        'horizon': L.canon(row.get('时效'), L.HORIZON, 'short'),
                        'status': L.canon(row.get('状态'), L.STATUS, 'active'),
                        'content': row.get('内容'), 'scope': row.get('适用范围'),
                        'source_label': row.get('出处')})
        return out

    def describe(self):
        return f'feishu:{self.base}/{self.table}'
