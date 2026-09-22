#!/usr/bin/env python3
"""配置加载:~/.compound-memory/config.yaml(可用 CM_HOME 换位置)。

没装 PyYAML 也能跑 —— 内置一个只认本项目配置那点语法的迷你解析器(嵌套字典、标量列表、
注释、引号、布尔/整数)。目的是让"拉下来就能用"不依赖任何 pip 安装。
"""
import os, re, sys

HOME = os.path.expanduser(os.environ.get('CM_HOME') or '~/.compound-memory')
REPO = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
CONFIG_PATH = os.path.join(HOME, 'config.yaml')
EXAMPLE_PATH = os.path.join(REPO, 'config.example.yaml')

DEFAULTS = {
    'user_name': 'you', 'language': 'zh', 'model': 'claude-opus-5', 'effort': 'high',
    'llm': {'backend': 'claude-cli', 'command': 'claude', 'claude_flags': [
        '--no-session-persistence', '--disable-slash-commands', '--strict-mcp-config',
        '--setting-sources', 'local', '--tools', ''],
        'base_url': 'https://api.openai.com/v1', 'api_key_env': 'OPENAI_API_KEY',
        'temperature': 0.2, 'max_tokens': 8000},
    'sink': 'local',
    'sinks': {'local': {'dir': ''},
              'github': {'repo_dir': '', 'branch': 'main', 'push': True},
              'feishu': {'cli': 'lark-cli', 'base_token': '', 'table_id': '', 'snapshot_doc': ''}},
    'nightly_limit': 20, 'window_days': 7, 'max_candidates': 8, 'text_budget': 14000,
    'snapshot_max_chars': 3200, 'cron': '30 4 * * *', 'baseline_file': '',
    'snapshot_cache_seconds': 3600,
    'hosts': {'claude': {'enabled': 'auto', 'dir': '~/.claude/projects', 'inject': True},
              'codex': {'enabled': 'auto', 'dir': '~/.codex/sessions', 'inject': True},
              'dsh': {'enabled': 'auto', 'dir': '~/.dsh/sessions', 'inject': True,
                      'plugin_hook': True, 'profile_dir': ''}},
}


# ---------- 迷你 YAML(只覆盖本项目配置用到的语法) ----------
def _scalar(s):
    s = s.strip()
    if not s or s == '~' or s.lower() == 'null':
        return ''
    if len(s) >= 2 and s[0] == s[-1] and s[0] in '"\'':
        return s[1:-1]
    if s.lower() in ('true', 'yes'):
        return True
    if s.lower() in ('false', 'no'):
        return False
    if re.fullmatch(r'-?\d+', s):
        return int(s)
    if re.fullmatch(r'-?\d+\.\d+', s):
        return float(s)
    return s


def _strip_comment(line):
    out, q = [], None
    for ch in line:
        if q:
            out.append(ch)
            if ch == q:
                q = None
        elif ch in '"\'':
            q = ch
            out.append(ch)
        elif ch == '#':
            break
        else:
            out.append(ch)
    return ''.join(out).rstrip()


def mini_yaml(text):
    root, stack = {}, [(-1, {})]
    stack[0] = (-1, root)
    for raw in text.splitlines():
        line = _strip_comment(raw)
        if not line.strip():
            continue
        indent = len(line) - len(line.lstrip(' '))
        body = line.strip()
        while stack and indent <= stack[-1][0]:
            stack.pop()
        parent = stack[-1][1]
        if body.startswith('- '):                      # 标量列表项
            key = stack[-1][2] if len(stack[-1]) > 2 else None
            if isinstance(parent, list):
                parent.append(_scalar(body[2:]))
            continue
        if body == '-':
            continue
        if ':' not in body:
            continue
        k, _, v = body.partition(':')
        k, v = k.strip(), v.strip()
        if v == '':                                     # 可能是嵌套字典,也可能是列表
            node = {}
            parent[k] = node
            stack.append((indent, node, k))
        elif v.startswith('[') and v.endswith(']'):
            inner = v[1:-1].strip()
            parent[k] = [_scalar(x) for x in inner.split(',')] if inner else []
        else:
            parent[k] = _scalar(v)
    return root


def _fix_lists(text, data):
    """迷你解析器第一遍把 `key:` 后跟 `- item` 的当成了空字典,这里按原文把它们改回列表。"""
    lines = [(_strip_comment(l), l) for l in text.splitlines()]
    keys_with_list = set()
    pending = None
    for stripped, _ in lines:
        if not stripped.strip():
            continue
        body = stripped.strip()
        if body.startswith('- ') or body == '-':
            if pending:
                keys_with_list.add(pending)
            continue
        if stripped.endswith(':'):
            pending = body[:-1].strip()
        else:
            pending = None

    def walk(node, text_lines):
        if not isinstance(node, dict):
            return node
        for k in list(node):
            if isinstance(node[k], dict) and not node[k] and k in keys_with_list:
                node[k] = _list_under(text_lines, k)
            else:
                walk(node[k], text_lines)
        return node

    def _list_under(text_lines, key):
        out, grab, base = [], False, None
        for stripped, _ in text_lines:
            if not stripped.strip():
                continue
            ind = len(stripped) - len(stripped.lstrip(' '))
            body = stripped.strip()
            if grab:
                if body.startswith('- ') or body == '-':
                    out.append(_scalar(body[2:] if len(body) > 1 else ''))
                    continue
                if ind <= base:
                    break
                continue
            if body == key + ':':
                grab, base = True, ind
        return out

    return walk(data, lines)


def parse_yaml(text):
    try:
        import yaml                                    # 有 PyYAML 就用它,更稳
        return yaml.safe_load(text) or {}
    except ImportError:
        return _fix_lists(text, mini_yaml(text))


# ---------- 合并与取值 ----------
def deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = deep_merge(out[k], v)
        elif v is not None:
            out[k] = v
    return out


_cache = None


def load(path=None):
    global _cache
    if _cache is not None and path is None:
        return _cache
    p = path or CONFIG_PATH
    user = {}
    if os.path.exists(p):
        user = parse_yaml(open(p, encoding='utf-8').read())
    cfg = deep_merge(DEFAULTS, user)
    cfg['_path'] = p
    cfg['_home'] = HOME
    cfg['_repo'] = REPO
    if path is None:
        _cache = cfg
    return cfg


def expand(p):
    return os.path.expanduser(os.path.expandvars(p or ''))


def data_dir(*parts):
    d = os.path.join(HOME, *parts)
    os.makedirs(os.path.dirname(d) if os.path.splitext(d)[1] else d, exist_ok=True)
    return d


def host_cfg(cfg, name):
    return (cfg.get('hosts') or {}).get(name) or {}


if __name__ == '__main__':
    import json
    print(json.dumps(load(), ensure_ascii=False, indent=1))
