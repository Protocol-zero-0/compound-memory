#!/usr/bin/env python3
"""所有模型调用的唯一出口(改一处全生效),外加几个文件工具。

为什么要有这个文件:后台例程裸调 `claude -p` 会白带整套环境(工具 / skill / 插件 / MCP 清单 +
全局规则),实测单次背景开销 ~4.3 万 token,还会吃掉默认模型。统一成一个出口后:
  1. 关工具、关 skill、关 MCP、只读本目录设置源 → 背景开销降到 ~1.1 万 token(同模型同提示词实测)
  2. 显式指定模型与思考深度,不吃全局默认
  3. 不落会话文件(否则调用记录会堆成上万个会话)
  4. 提示词走 stdin,避开 argv 长度上限
  5. 每次真调了模型就记一行 usage.log,方便日后核对"是不是在偷偷烧"
"""
import fcntl, json, os, subprocess, time, urllib.request, urllib.error
from . import config

cfg = config.load()
HOME = config.HOME
USAGE_LOG = os.path.join(HOME, 'usage.log')

MODEL = os.environ.get('CM_MODEL') or cfg.get('model')
EFFORT = os.environ.get('CM_EFFORT') or cfg.get('effort')

# 重提炼门槛:真实用户轮数比上次提炼时至少多 max(3, 25%),才值得再调一次模型
RESUM_MIN_NEW = 3
RESUM_RATIO = 0.25


class UsageLimit(Exception):
    """订阅额度 / 限流。遇到它要立刻停,并且不推进水位线。"""


LIMIT_MARKERS = ('usage limit', 'session limit', 'rate limit', 'rate_limit',
                 'quota', 'insufficient_quota', 'too many requests', '429')


def needs_resummary(base_turns, now_turns):
    return now_turns - base_turns >= max(RESUM_MIN_NEW, RESUM_RATIO * base_turns)


def _looks_like_limit(text):
    t = (text or '').lower()
    return any(m in t for m in LIMIT_MARKERS)


def _ask_claude_cli(prompt, timeout):
    lc = cfg.get('llm') or {}
    cmd = [lc.get('command') or 'claude', '-p', '--model', MODEL, '--effort', EFFORT,
           *(lc.get('claude_flags') or [])]
    r = subprocess.run(cmd, input=prompt, capture_output=True, text=True,
                       timeout=timeout, cwd=HOME)
    out = (r.stdout or '').strip()
    if r.returncode != 0 or not out:
        err = ((r.stderr or '') + out)[:400]
        if _looks_like_limit(err):
            raise UsageLimit(err)
        raise RuntimeError(f'claude -p 失败 rc={r.returncode}: {err}')
    if _looks_like_limit(out) and len(out) < 300:
        raise UsageLimit(out)
    return out


def _ask_openai(prompt, timeout):
    lc = cfg.get('llm') or {}
    key = os.environ.get(lc.get('api_key_env') or 'OPENAI_API_KEY', '')
    if not key:
        raise RuntimeError(f"环境变量 {lc.get('api_key_env')} 没设置,openai 后端用不了")
    body = json.dumps({
        'model': MODEL,
        'messages': [{'role': 'user', 'content': prompt}],
        'temperature': lc.get('temperature', 0.2),
        'max_tokens': lc.get('max_tokens', 8000),
    }).encode()
    url = (lc.get('base_url') or '').rstrip('/') + '/chat/completions'
    req = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json', 'Authorization': f'Bearer {key}'})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode())
    except urllib.error.HTTPError as e:
        detail = e.read().decode(errors='replace')[:400]
        if e.code == 429 or _looks_like_limit(detail):
            raise UsageLimit(f'{e.code} {detail}')
        raise RuntimeError(f'接口报错 {e.code}: {detail}')
    return (data['choices'][0]['message']['content'] or '').strip()


def ask(prompt, timeout=420):
    """把 prompt 交给模型,返回文本。额度类失败抛 UsageLimit,其余抛 RuntimeError。"""
    backend = ((cfg.get('llm') or {}).get('backend') or 'claude-cli').lower()
    if backend in ('claude-cli', 'claude'):
        return _ask_claude_cli(prompt, timeout)
    if backend in ('openai', 'openai-compatible', 'api'):
        return _ask_openai(prompt, timeout)
    raise RuntimeError(f'不认识的 llm.backend: {backend}')


def ask_json(prompt, timeout=420):
    """要求模型只输出 JSON;容忍代码围栏和前后废话。"""
    out = ask(prompt, timeout)
    s, e = out.find('{'), out.rfind('}')
    if s < 0 or e <= s:
        raise ValueError('模型输出里没有 JSON:' + out[:200])
    return json.loads(out[s:e + 1])


# ---------- 文件工具 ----------
def atomic_write(path, text):
    os.makedirs(os.path.dirname(path) or '.', exist_ok=True)
    tmp = f'{path}.tmp{os.getpid()}'
    with open(tmp, 'w', encoding='utf-8') as f:
        f.write(text)
    os.replace(tmp, path)


def write_if_changed(path, text):
    try:
        if open(path, encoding='utf-8').read() == text:
            return False
    except FileNotFoundError:
        pass
    atomic_write(path, text)
    return True


_locks = []


def try_lock(name):
    """非阻塞文件锁,防两次提炼同时写。拿不到返回 None;拿到就持有到进程结束。"""
    os.makedirs(HOME, exist_ok=True)
    f = open(os.path.join(HOME, f'.{name}.lock'), 'w')
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        f.close()
        return None
    _locks.append(f)
    return f


def log_usage(kind, n):
    os.makedirs(HOME, exist_ok=True)
    with open(USAGE_LOG, 'a', encoding='utf-8') as f:
        f.write(f"{time.strftime('%Y-%m-%dT%H:%M:%S')} {kind} model={MODEL} effort={EFFORT} n={n}\n")
