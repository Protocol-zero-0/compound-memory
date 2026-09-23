#!/usr/bin/env python3
"""feishu:共享层放飞书(Lark)多维表格 +一个文档。

适合"人也要翻、还想在手机上看"的场景:记忆一条一行,可以筛选、可以手工标状态。
前置条件:装好 lark-cli 并登录,自己先建一张表(字段见 docs/sinks.md,
`cm sink-init` 会把字段定义打印出来),把 base_token / table_id 填进 config.yaml。
"""
import json, os, re, subprocess

from .. import config, llm, store, lexicon as L
from . import Sink, remote_of, remote_set, needs_push

def _created_ids(res):
    """批量建记录返回的 record_id,按请求顺序。不同版本的壳字段不一样,都兜一下。"""
    d = res.get('data') or {}
    recs = d.get('records') or (d.get('record') or {}).get('record_id_list') or d.get('record_id_list') or []
    out = []
    for r in recs:
        out.append(r.get('record_id') if isinstance(r, dict) else r)
    return out


def _one(v):
    """多维表格里单选/多选字段回来的是列表,文本是字符串 —— 统一成一个标量。"""
    if isinstance(v, list):
        return v[0] if v else ''
    return v


class FeishuSink(Sink):
    name = 'feishu'

    def __init__(self, cfg):
        super().__init__(cfg)
        self.lang = cfg.get('language') or 'zh'
        self.cli = self.conf.get('cli') or 'lark-cli'
        self.base = self.conf.get('base_token') or ''
        self.table = self.conf.get('table_id') or ''

    def _require(self):
        """晚一点才报错:没配好也要能跑 `cm doctor` / `cm sink-init`。"""
        if not (self.base and self.table):
            raise RuntimeError('feishu sink 还没建表,先跑一次 `cm sink-init`(或手工填 '
                               'sinks.feishu.base_token / table_id,字段见 docs/sinks.md)')

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
            '性质': [L.word(m.get('nature'), self.lang)],
            '类型': [L.word(m.get('kind'), self.lang)],
            '时效': [L.word(m.get('horizon'), self.lang)],
            '适用范围': store.scrub(m.get('scope') or ''),
            '有效期': m.get('expires') or '',
            '出处': self._origin(m),
            '状态': [L.word(m.get('status'), self.lang)],
            '记忆ID': m.get('id'),
            '修订自': m.get('revises') or '',
            '批次': m.get('batch') or '',
        }

    def init(self):
        """一条命令建好 Base + 「记忆」表,并把 token 写回 config.yaml。

        这是"拉下来 1-2 步就能用"落在飞书上的样子 —— 不让用户对着字段表手工建表。
        """
        if self.base and self.table:
            return f'已经配好了:base={self.base} table={self.table}(想重建就先把配置里这两项清空)'
        fields = json.load(open(os.path.join(config.REPO, 'cm', 'sinks', 'feishu_fields.json'),
                                encoding='utf-8'))
        name = f"{self.cfg.get('user_name')} · compound-memory"
        res = self._lark(['base', '+base-create', '--name', name,
                          '--table-name', 'Memories' if self.lang == 'en' else '记忆',
                          '--fields', json.dumps(fields, ensure_ascii=False), '--json'], timeout=120)
        if not res.get('ok'):
            raise RuntimeError(f"建 Base 失败:{(res.get('error') or {}).get('message')}")
        d = res.get('data') or {}
        app = d.get('base') or d.get('app') or d
        self.base = app.get('base_token') or app.get('app_token') or d.get('app_token')
        url = app.get('url') or d.get('url')
        if not self.base:
            raise RuntimeError(f'建 Base 成功但没拿到 token,返回:{json.dumps(d, ensure_ascii=False)[:300]}')
        res = self._lark(['base', '+table-list', '--base-token', self.base, '--json'], timeout=60)
        tables = ((res.get('data') or {}).get('tables')
                  or (res.get('data') or {}).get('items') or [])
        self.table = (tables[0].get('table_id') or tables[0].get('id')) if tables else ''
        if not self.table:
            raise RuntimeError(f'Base 建好了但读不到表 id,返回:{json.dumps(res, ensure_ascii=False)[:300]}')
        config.update_file({'sinks.feishu.base_token': self.base,
                            'sinks.feishu.table_id': self.table,
                            'sinks.feishu.base_url': url or ''})
        return f'已建好并写回配置:{url or self.base}(table {self.table})'

    def _id_map(self):
        """表里已有的 记忆ID → record_id。

        为什么要有它:本地的"已同步回执"要是丢了(换机器、重装、手工删了 observations.jsonl),
        再发一次就会把整张表复制一遍。发之前先跟表对一次账,既补回执又防重复,只花一两次请求。
        """
        out, offset = {}, 0
        while True:
            args = ['base', '+record-list', '--base-token', self.base, '--table-id', self.table,
                    '--field-id', '记忆ID', '--field-id', '状态', '--limit', '200', '--json']
            if offset:
                args += ['--offset', str(offset)]
            res = self._lark(args, timeout=90)
            d = res.get('data') or {}
            fields, data = d.get('fields') or [], d.get('data') or []
            rids = d.get('record_id_list') or []
            if not data:
                break
            for vals, rid in zip(data, rids):
                row = {k: _one(v) for k, v in zip(fields, vals)}
                if row.get('记忆ID'):
                    out[row['记忆ID']] = (rid, L.canon(row.get('状态'), L.STATUS, None))
            if not d.get('has_more'):
                break
            offset += len(data)
        return out

    def _chunks(self, seq, n=200, max_bytes=60000):
        """每批最多 200 条(接口上限),而且整批 JSON 不超过 60KB —— 批量内容走命令行参数,
        记忆正文一长,整批塞一个参数会撞操作系统的参数长度上限(实跑遇到过)。"""
        cur, size = [], 0
        for m in seq:
            b = len(json.dumps(self._labels(m), ensure_ascii=False).encode())
            if cur and (len(cur) >= n or size + b > max_bytes):
                yield cur
                cur, size = [], 0
            cur.append(m); size += b
        if cur:
            yield cur

    def _origin(self, m):
        base = m.get('source_label') or f"{m.get('host')} · {m.get('source')}:{m.get('source_sid')}"
        q = store.scrub(m.get('quote') or '')
        return base + (f" · 「{q}」" if q and q not in base else '')   # 从旧系统搬来的出处里已经带着原话

    def publish_memories(self, rows):
        self._require()
        todo = [m for m in rows if m.get('share') and needs_push(m, self.name)]
        if not todo:
            return 0
        if any(not remote_of(m, self.name).get('id') for m in todo):
            try:
                known = self._id_map()
            except Exception as ex:
                print(f'  ! 读飞书已有记录失败,跳过对账({type(ex).__name__})', flush=True)
                known = {}
            for m in todo:
                if not remote_of(m, self.name).get('id') and m['id'] in known:
                    rid, st = known[m['id']]
                    remote_set(m, self.name, rid, st)   # 补回执,连表里当前的状态一起记下:一样就不重写
        todo = [m for m in todo if needs_push(m, self.name)]   # 对完账还一致的就不用再写(实跑漏过这一步,重写了一整表)
        creates = [m for m in todo if not remote_of(m, self.name).get('id')]
        updates = [m for m in todo if remote_of(m, self.name).get('id')]
        n = 0
        for chunk in self._chunks(creates):
            body = {'create_records': [self._labels(m) for m in chunk]}
            res = self._lark(['base', '+record-batch-create', '--base-token', self.base,
                              '--table-id', self.table, '--json',
                              json.dumps(body, ensure_ascii=False)], timeout=180)
            if not res.get('ok'):
                print(f"  ! 批量写飞书失败({len(chunk)} 条): "
                      f"{(res.get('error') or {}).get('message')}", flush=True)
                continue
            ids = _created_ids(res)
            for i, m in enumerate(chunk):
                remote_set(m, self.name, ids[i] if i < len(ids) else None, m.get('status'))
            n += len(chunk)
        for chunk in self._chunks(updates):
            body = {'update_records': {remote_of(m, self.name)['id']: self._labels(m) for m in chunk}}
            res = self._lark(['base', '+record-batch-update', '--base-token', self.base,
                              '--table-id', self.table, '--json',
                              json.dumps(body, ensure_ascii=False)], timeout=180)
            if not res.get('ok'):
                print(f"  ! 批量更新飞书失败({len(chunk)} 条): "
                      f"{(res.get('error') or {}).get('message')}", flush=True)
                continue
            for m in chunk:
                remote_set(m, self.name, remote_of(m, self.name)['id'], m.get('status'))
            n += len(chunk)
        return n

    def publish_snapshot(self, text):
        self._require()
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
        if not config.update_file({'sinks.feishu.snapshot_doc': doc or '',
                                   'sinks.feishu.snapshot_url': url or ''}):
            print(f'  · 飞书快照文档已建好,请把 snapshot_doc: {doc} 填进 {config.CONFIG_PATH}', flush=True)

    def fetch_snapshot(self):
        doc = self.conf.get('snapshot_doc')
        if not doc:
            return None
        res = self._lark(['docs', '+fetch', '--doc', doc, '--doc-format', 'markdown'], timeout=60)
        d = res.get('data') or {}
        text = d.get('content') or d.get('markdown') or (d.get('document') or {}).get('content')
        # 飞书取回的 markdown 头上带一行 <title>…</title>,注入给模型前去掉,别当成正文
        return re.sub(r'^\s*<title>.*?</title>\s*', '', text or '', flags=re.S) or None

    def fetch_memories(self):
        """别的机器上 `cm recall` 读的就是这里。翻页 + 把多选字段的列表值拆出来。"""
        self._require()
        out, offset = [], 0
        while True:
            args = ['base', '+record-list', '--base-token', self.base, '--table-id', self.table,
                    '--limit', '200', '--json']          # limit 上限就是 200,写大了整个请求会被判非法
            if offset:
                args += ['--offset', str(offset)]
            res = self._lark(args, timeout=90)
            d = res.get('data') or {}
            fields, data = d.get('fields') or [], d.get('data') or []
            if not data:
                break
            for vals in data:
                row = {k: _one(v) for k, v in zip(fields, vals)}
                out.append({
                    'id': row.get('记忆ID'), 'date': str(row.get('日期') or '')[:10],
                    'nature': L.canon(row.get('性质'), L.NATURE, 'fact'),
                    'kind': L.canon(row.get('类型'), L.KIND, 'event'),
                    'horizon': L.canon(row.get('时效'), L.HORIZON, 'short'),
                    'status': L.canon(row.get('状态'), L.STATUS, 'active'),
                    'content': row.get('内容'), 'scope': row.get('适用范围'),
                    'expires': row.get('有效期'), 'revises': row.get('修订自'),
                    'source_label': row.get('出处')})
            if not d.get('has_more'):
                break
            offset += len(data)
        return out

    def describe(self):
        if not (self.base and self.table):
            return 'feishu(还没建表,跑一次 `cm sink-init`)'
        return f'feishu:{self.base}/{self.table}'
