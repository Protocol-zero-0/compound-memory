#!/usr/bin/env python3
"""推送前的隐私闸:仓库(当前文件 + 全部历史 + 提交说明)里有没有你的个人信息。

两道检查:
  1. 词表:你自己维护的一份敏感词(真名、公司、客户、机器名、表 ID…),
     放在仓库**外面**(默认 ~/.compound-memory/privacy-terms.txt)—— 词表本身就是隐私。
  2. 原文比对:拿你记忆库里的中文原句切成 10 字片段,看仓库里有没有逐字出现。
     专抓"举个例子"时顺手从真实记忆里抄进文档的那种泄露。

任何一项命中就以非零退出。装成 git pre-push hook 之后,不过闸就推不出去:

    python3 tools/privacy-check.py --install-hook

词表格式:一行一个正则,# 开头是注释。默认区分大小写(`ID` 不该匹配 valid);
要不区分就在行首写 (?i)。
"""
import argparse, json, os, re, subprocess, sys

HOME = os.path.expanduser(os.environ.get('CM_HOME') or '~/.compound-memory')
CJK = re.compile(r'[一-鿿]+')
N = 10


def git(*a):
    return subprocess.run(['git', *a], capture_output=True, text=True).stdout


def corpus():
    """(来源, 行) —— 当前文件、历史里每一行增删、每条提交说明。"""
    for f in git('ls-files').split():
        try:
            for i, line in enumerate(open(f, encoding='utf-8', errors='ignore'), 1):
                yield f'{f}:{i}', line
        except OSError:
            pass
    for line in git('log', '-p', '--all', '--format=%x00%h').splitlines():
        if line.startswith(('+', '-')) and not line.startswith(('+++', '---')):
            yield 'history', line
    for block in git('log', '--all', '--format=%h%x01%B%x00').split('\x00'):
        if '\x01' in block:
            h, msg = block.split('\x01', 1)
            for line in msg.splitlines():
                yield f'commit {h.strip()}', line


def load_terms(path):
    if not os.path.exists(path):
        return []
    out = []
    for raw in open(path, encoding='utf-8'):
        s = raw.strip()
        if s and not s.startswith('#'):
            out.append((s, re.compile(s)))
    return out


def load_shingles(paths):
    sh = {}
    for p in paths:
        if not os.path.exists(p):
            continue
        for line in open(p, encoding='utf-8'):
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            for k in ('content', 'quote', '内容', '引用'):
                for seg in CJK.findall(o.get(k) or ''):
                    for i in range(len(seg) - N + 1):
                        sh.setdefault(seg[i:i + N], (o.get(k) or '')[:50])
    return sh


def install_hook(terms, memories):
    root = git('rev-parse', '--show-toplevel').strip()
    hook = os.path.join(root, '.git', 'hooks', 'pre-push')
    me = os.path.abspath(__file__)
    mem = ' '.join(f'"{m}"' for m in memories)
    with open(hook, 'w') as f:
        f.write(f'#!/bin/sh\n# 隐私闸:不过就不让推。临时绕过:git push --no-verify(别这么干)\n'
                f'cd "$(git rev-parse --show-toplevel)" && '
                f'exec python3 "{me}" --terms "{terms}" --memories {mem}\n')
    os.chmod(hook, 0o755)
    print(f'已装:{hook}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--terms', default=os.path.join(HOME, 'privacy-terms.txt'))
    ap.add_argument('--memories', nargs='*', default=[os.path.join(HOME, 'memory', 'observations.jsonl')],
                    help='拿来做原文比对的记忆库(可多个)')
    ap.add_argument('--install-hook', action='store_true')
    a = ap.parse_args()
    if a.install_hook:
        return install_hook(a.terms, a.memories) or 0
    terms = load_terms(a.terms)
    sh = load_shingles(a.memories)
    if not terms:
        print(f'!! 没有词表 {a.terms} —— 只做原文比对。强烈建议建一份。')
    hits = []
    for where, line in corpus():
        for raw, rx in terms:
            if rx.search(line):
                hits.append((where, f'词表「{raw}」', line.strip()[:100]))
        for seg in CJK.findall(line):
            for i in range(len(seg) - N + 1):
                if seg[i:i + N] in sh:
                    hits.append((where, '与记忆原文逐字重合', f'{line.strip()[:70]}  ←  {sh[seg[i:i+N]]}'))
                    break
    seen = set()
    for h in hits:
        if h not in seen:
            seen.add(h)
            print(f'  ✗ {h[0]}  [{h[1]}]  {h[2]}')
    print(f'隐私闸:词表 {len(terms)} 条 · 记忆片段 {len(sh)} 个 · 命中 {len(seen)} 处')
    return 1 if seen else 0


if __name__ == '__main__':
    sys.exit(main())
