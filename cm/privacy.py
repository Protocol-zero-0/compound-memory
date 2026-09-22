#!/usr/bin/env python3
"""`cm privacy-index`:给推送前的隐私闸建"原文指纹"索引。

读的是**所有**会话(不只是提炼窗口里的):三个 harness 的用户发言、会话标题,
再加上记忆库和配置里 `privacy.extra_sources` 列出的文件。只存 winnowing 哈希,不存原文。

为什么要读原文而不只是记忆库:上一版闸门只跟记忆库比对,结果 dsh 一个会话的原话和标题
被原样写进了文档,两道检查都没抓到 —— 记忆库里根本没有那句话。泄露的来源是原文,
比对的对象就得是原文。
"""
import array, glob, importlib.util, json, os, time

from . import config, sources, store

_spec = importlib.util.spec_from_file_location(
    'privacy_check', os.path.join(config.REPO, 'tools', 'privacy-check.py'))
pc = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(pc)


def _strings(o):
    """JSON 里所有字符串值,递归取出来。"""
    if isinstance(o, str):
        yield o
    elif isinstance(o, dict):
        for v in o.values():
            yield from _strings(v)
    elif isinstance(o, list):
        for v in o:
            yield from _strings(v)


def _file_texts(path):
    if path.endswith('.jsonl'):
        for line in open(path, encoding='utf-8', errors='ignore'):
            try:
                yield from _strings(json.loads(line))
            except json.JSONDecodeError:
                yield line
    elif path.endswith('.json'):
        try:
            yield from _strings(json.load(open(path, encoding='utf-8', errors='ignore')))
        except json.JSONDecodeError:
            pass
    else:
        yield open(path, encoding='utf-8', errors='ignore').read()


def _write(path, fps):
    arr = array.array('Q', sorted(fps))
    os.makedirs(os.path.dirname(path), exist_ok=True)
    tmp = path + '.tmp'
    with open(tmp, 'wb') as f:
        arr.tofile(f)
    os.replace(tmp, path)
    return len(arr)


def build(cfg, verbose=True):
    """两份索引:会话原文(只有严格档查)和私密来源(记忆库、快照、会议、内部笔记 —— 两档都查)。
    分开是因为你的发布站本来就会用上你在会话里写的业务文案,但绝不该出现记忆和会议原文。"""
    t0 = time.time()
    fps, priv, counts = set(), set(), {}
    recs = sources.scan_all(cfg, None)
    for i, r in enumerate(recs):
        try:
            texts = sources.load_turns(r) + [r.get('title') or '']
        except Exception:
            continue
        for t in texts:
            fps |= pc.fingerprints(t)
        counts[r['source']] = counts.get(r['source'], 0) + 1
        if verbose and (i + 1) % 500 == 0:
            print(f'  …{i + 1}/{len(recs)} 个会话,指纹 {len(fps)}', flush=True)
    extra = [store.STORE, os.path.join(config.HOME, 'memory', 'snapshot.md')]
    extra += [config.expand(p) for p in ((cfg.get('privacy') or {}).get('extra_sources') or [])]
    n_files = 0
    for pat in extra:
        for p in glob.glob(pat, recursive=True):
            if os.path.isfile(p):
                for t in _file_texts(p):
                    priv |= pc.fingerprints(t)
                n_files += 1
    n_sess = _write(pc.INDEX, fps)
    n_priv = _write(pc.PRIVATE_INDEX, priv)
    meta = {'params': pc.PARAMS, 'built_at': time.strftime('%Y-%m-%dT%H:%M:%S'),
            'fingerprints': n_sess, 'private_fingerprints': n_priv, 'sessions': counts,
            'extra_files': n_files, 'seconds': round(time.time() - t0, 1)}
    tmp = pc.META + '.tmp'
    with open(tmp, 'w', encoding='utf-8') as f:
        json.dump(meta, f, ensure_ascii=False, indent=1)
    os.replace(tmp, pc.META)
    if verbose:
        print(f"原文指纹索引:会话原文 {n_sess} 个 · 私密来源 {n_priv} 个 · 会话 {counts} · "
              f"私密文件 {n_files} 个 · {meta['seconds']} 秒")
    return meta
