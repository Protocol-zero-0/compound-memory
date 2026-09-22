#!/usr/bin/env python3
"""推送前的隐私闸。只依赖 Python 标准库,可以单独拷走当全局 git 钩子用。

两道检查:
  1. 词表:你自己维护的敏感词(真名、公司、客户、机器名、表 ID…),一行一个正则。
     放在仓库**外面**(默认 ~/.compound-memory/privacy-terms.txt)—— 词表本身就是隐私。
  2. 原文指纹:把你**所有会话原文**(用户发言、会话标题)和记忆库里的中文,
     去掉标点后切成 8 字片段、取 winnowing 指纹,存成一份只有哈希的索引(`cm privacy-index` 每晚重建)。
     推送时拿新增内容去比:只要有一段 ≥11 个汉字跟你说过的话逐字相同,就拦。
     索引里只有哈希,不含原文,丢了也还原不出你说过什么。

用法:
  privacy-check.py --range 'A..B'    只查这个范围里**新增**的行和提交说明(pre-push 用;整体加引号)
  privacy-check.py --all             查当前文件 + 全部历史 + 全部提交说明
  privacy-check.py --install-hook    给当前仓库装 pre-push(全局装法见 docs/privacy-gate.md)

退出码:0 = 干净;1 = 有命中;2 = 检查本身没跑成(当作不通过)。
"""
import argparse, array, bisect, hashlib, json, os, re, shlex, subprocess, sys

HOME = os.path.expanduser(os.environ.get('CM_HOME') or '~/.compound-memory')
TERMS = os.path.join(HOME, 'privacy-terms.txt')
INDEX = os.path.join(HOME, 'cache', 'privacy-index.bin')              # 会话原文(严格档才查)
PRIVATE_INDEX = os.path.join(HOME, 'cache', 'privacy-index-private.bin')  # 记忆/会议/内部笔记(两档都查)
META = INDEX + '.json'

CJK = re.compile(r'[一-鿿]+')
K, W = 8, 4             # 片段 8 字,窗口 4:任何 ≥ K+W-1 = 11 个汉字的逐字重合一定能抓到
PARAMS = f'cjk-join-k{K}-w{W}-blake2b8-v2'


# ---------- 指纹(建索引和查询共用同一份实现) ----------
def _h(s):
    return int.from_bytes(hashlib.blake2b(s.encode('utf-8'), digest_size=8).digest(), 'big')


def fingerprints(text):
    """winnowing:每个长度 W 的窗口里取最小哈希,并且保证 ≥ K+W-1 字的公共子串
    一定共享至少一个指纹。

    先把一行里的汉字**拼成一串**(丢掉标点、空格、英文)再切:中文一句话常被逗号切成
    七八个字的短句,按"连续汉字"切的话短句全被跳过 —— 上一版就是这么漏掉整句原话的。
    建索引和查询用同一个函数,两边的归一化自然一致。"""
    out = set()
    joined = ''.join(CJK.findall(text or ''))
    for run in ([joined] if joined else []):
        if len(run) < K:
            continue
        hs = [_h(run[i:i + K]) for i in range(len(run) - K + 1)]
        if len(hs) <= W:
            out.add(min(hs))
            continue
        for i in range(len(hs) - W + 1):
            out.add(min(hs[i:i + W]))
    return out


def _read(path):
    a = array.array('Q')
    if os.path.exists(path):
        with open(path, 'rb') as f:
            a.frombytes(f.read())
    return a


def load_index(mode='strict'):
    """返回 (排好序的 array('Q'), 元信息) 或 (None, 原因)。
    严格档 = 会话原文 + 私密来源;发布档 = 只有私密来源(记忆、会议、内部笔记)。"""
    try:
        meta = json.load(open(META, encoding='utf-8'))
    except (OSError, json.JSONDecodeError):
        return None, f'没有原文指纹索引({META}),先跑 `cm privacy-index`'
    if meta.get('params') != PARAMS:
        return None, f'索引参数 {meta.get("params")} 与本脚本 {PARAMS} 不一致,重建一下'
    if mode == 'publish':
        # 发布档不做原文比对:你自己的站点本来就会用上会话里写的业务文案,记忆库也记着同样的交付,
        # 逐字比对在这里分不清"给客户看的"和"不该外传的",实测会误拦大半推送。只靠 [private] 词表。
        return None, '发布档不做原文比对'
    priv = _read(PRIVATE_INDEX)
    both = sorted(set(_read(INDEX)) | set(priv))
    return array.array('Q', both), meta


def contains(a, x):
    i = bisect.bisect_left(a, x)
    return i < len(a) and a[i] == x


# ---------- 要查的内容 ----------
def git(*args):
    r = subprocess.run(['git', *args], capture_output=True, text=True, errors='replace')
    if r.returncode != 0:
        raise RuntimeError(f"git {' '.join(args)} 失败:{r.stderr.strip()[:200]}")
    return r.stdout


def lines_in_range(rev_args):
    """新增的行(+ 开头)和提交说明。删掉的行不查:它们本来就已经在对方那边了。"""
    for line in git('log', '-p', '--no-color', '--format=%x00%h %s', *rev_args).splitlines():
        if line.startswith('\x00'):
            yield f'提交 {line[1:9]}', line[1:]
        elif line.startswith('+') and not line.startswith('+++'):
            yield 'diff', line[1:]
    for block in git('log', '--format=%h%x01%B%x00', *rev_args).split('\x00'):
        if '\x01' in block:
            h, msg = block.split('\x01', 1)
            for m in msg.splitlines():
                yield f'提交说明 {h.strip()}', m


def lines_everything():
    for f in git('ls-files').split('\n'):
        if not f:
            continue
        try:
            with open(f, encoding='utf-8', errors='ignore') as fh:
                for i, line in enumerate(fh, 1):
                    yield f'{f}:{i}', line
        except OSError:
            pass
    yield from lines_in_range(['--all'])


# ---------- 检查 ----------
def load_terms(path, mode='strict'):
    """词表分两档,用小节标题切换:

        [private]   别人的名字、联系方式、内部地址、各种 ID —— 任何仓库都不许出现
        [brand]     你自己的品牌、产品、价格、对外名字 —— 只在严格档(开源 / 给别人提 PR)里拦

    没写小节标题的行算 [private]。发布档只用 [private]。"""
    out, tier = [], 'private'
    if not os.path.exists(path):
        return out
    for raw in open(path, encoding='utf-8'):
        s = raw.strip()
        if not s or s.startswith('#'):
            continue
        if s in ('[private]', '[brand]'):
            tier = s[1:-1]
            continue
        if mode == 'publish' and tier != 'private':
            continue
        try:
            out.append((s, re.compile(s)))
        except re.error:
            print(f'  ! 词表里这一行不是合法正则,跳过:{s}', file=sys.stderr)
    return out


def repo_allow():
    """仓库自己的放行名单:git config --add privacy-gate.allow <正则>。
    给"内容本身就是这些"的仓库用(比如人名库),每一条都该是仓库主人亲自决定加的。"""
    r = subprocess.run(['git', 'config', '--get-all', 'privacy-gate.allow'], capture_output=True, text=True)
    out = []
    for s in r.stdout.splitlines():
        try:
            out.append(re.compile(s.strip()))
        except re.error:
            pass
    return out


def scan(lines, terms, index, allow=()):
    hits, seen = [], set()
    for where, line in lines:
        for raw, rx in terms:
            m = rx.search(line)
            if m and not any(a.fullmatch(m.group(0)) for a in allow):
                hits.append((where, f'词表「{raw}」', line.strip()[:110]))
        if index is not None:
            for fp in fingerprints(line):
                if contains(index, fp):
                    hits.append((where, '与你说过的话逐字重合(≥11 个汉字)', line.strip()[:110]))
                    break
    out = []
    for h in hits:
        if h not in seen:
            seen.add(h)
            out.append(h)
    return out


def install_hook():
    root = git('rev-parse', '--show-toplevel').strip()
    hook = os.path.join(root, '.git', 'hooks', 'pre-push')
    me = os.path.abspath(__file__)
    with open(hook, 'w') as f:
        f.write('#!/bin/sh\n# 隐私闸:扫这次要推的新内容,不过就不让推。\n'
                'z=0000000000000000000000000000000000000000\n'
                'while read lref lsha rref rsha; do\n'
                '  [ "$lsha" = "$z" ] && continue\n'
                '  if [ "$rsha" = "$z" ]; then r="$lsha --not --remotes"; else r="$lsha ^$rsha --not --remotes"; fi\n'
                f'  python3 "{me}" --range "$r" || exit 1\n'
                'done\n')
    os.chmod(hook, 0o755)
    print(f'已装:{hook}')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--terms', default=TERMS)
    ap.add_argument('--range', help='git log 能接受的范围参数,整体用引号包起来,如 "A..B" 或 "SHA --not --remotes"')
    ap.add_argument('--all', action='store_true')
    ap.add_argument('--install-hook', action='store_true')
    ap.add_argument('--no-index', action='store_true', help='只用词表(GitHub Action 里用这个)')
    ap.add_argument('--mode', choices=['strict', 'publish'],
                    help='严格档(默认)/ 发布档。不给就读当前仓库的 git config privacy-gate.mode')
    a = ap.parse_args()
    if a.install_hook:
        return install_hook() or 0
    mode = a.mode
    if not mode:
        r = subprocess.run(['git', 'config', '--get', 'privacy-gate.mode'], capture_output=True, text=True)
        mode = r.stdout.strip() if r.stdout.strip() in ('strict', 'publish') else 'strict'
    try:
        terms = load_terms(a.terms, mode)
        index, meta = (None, '已关闭') if a.no_index else load_index(mode)
        if index is None and mode != 'publish':
            print(f'  ! 原文指纹这一道没跑:{meta}', file=sys.stderr)
        if not terms and index is None:
            print('隐私闸:词表和索引都没有,什么都查不了 —— 当作不通过。', file=sys.stderr)
            return 2
        lines = lines_in_range(shlex.split(a.range)) if a.range else lines_everything()
        hits = scan(lines, terms, index, repo_allow())
    except Exception as ex:                          # 检查没跑成 = 不放行
        print(f'隐私闸:检查本身出错了,当作不通过 —— {type(ex).__name__}: {ex}', file=sys.stderr)
        return 2
    for where, why, text in hits:
        print(f'  ✗ {where}  [{why}]  {text}', file=sys.stderr)
    n_idx = f'{len(index)} 个指纹' if index is not None else '未启用'
    print(f'隐私闸({"发布档" if mode == "publish" else "严格档"}):词表 {len(terms)} 条 · 原文索引 {n_idx} · 命中 {len(hits)} 处', file=sys.stderr)
    return 1 if hits else 0


if __name__ == '__main__':
    sys.exit(main())
