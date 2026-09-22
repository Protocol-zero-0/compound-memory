#!/usr/bin/env python3
"""装机:认出本机装了哪些 harness,把"开局注入"接上去,装每晚的 cron。

原则:**能撤销**。每一处改动都先备份到 ~/.compound-memory/backups/,都带标记,
`cm uninstall` 能原样摘掉。一个记忆系统如果卸不干净,没人敢装。
"""
import json, os, re, shutil, subprocess, time

from . import config, llm
from . import sources

CM_HOME = config.HOME
REPO = config.REPO
BACKUP = os.path.join(CM_HOME, 'backups')
INSTALLED = os.path.join(CM_HOME, 'installed.json')
MARK = 'compound-memory'
CRON_TAG = '# compound-memory'


def cm_bin():
    return os.path.join(REPO, 'bin', 'cm')


def backup(path):
    if not os.path.exists(path):
        return None
    d = os.path.join(BACKUP, time.strftime('%Y%m%d-%H%M%S'))
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, os.path.basename(path))
    shutil.copy2(path, dst)
    return dst


def _record(key, value):
    data = {}
    if os.path.exists(INSTALLED):
        try:
            data = json.load(open(INSTALLED, encoding='utf-8'))
        except json.JSONDecodeError:
            data = {}
    data[key] = value
    llm.atomic_write(INSTALLED, json.dumps(data, ensure_ascii=False, indent=1))


# ---------- 可执行文件 ----------
def link_bin():
    """把 cm 放进 PATH。~/.local/bin 是最不惊扰系统的位置。"""
    d = os.path.expanduser('~/.local/bin')
    os.makedirs(d, exist_ok=True)
    dst = os.path.join(d, 'cm')
    if os.path.islink(dst) or os.path.exists(dst):
        if os.path.realpath(dst) == os.path.realpath(cm_bin()):
            return dst, 'already'
        if not os.path.islink(dst):
            return dst, 'occupied'        # 别覆盖别人的 cm
        os.remove(dst)
    os.symlink(cm_bin(), dst)
    _record('bin', dst)
    return dst, 'linked'


# ---------- Claude Code ----------
def claude_settings():
    return os.path.expanduser('~/.claude/settings.json')


def _is_ours(cmd):
    cmd = cmd or ''
    return MARK in cmd or cmd.rstrip().endswith('cm snapshot')


def inject_claude(cfg, remove=False):
    p = claude_settings()
    if not os.path.isdir(os.path.dirname(p)):
        return False, 'Claude Code 没装(没有 ~/.claude)'
    data = {}
    if os.path.exists(p):
        try:
            data = json.load(open(p, encoding='utf-8'))
        except json.JSONDecodeError:
            return False, f'{p} 不是合法 JSON,没敢动;请自己加一个 SessionStart hook'
    hooks = data.setdefault('hooks', {})
    groups = hooks.setdefault('SessionStart', [])
    present = any(_is_ours(h.get('command')) for g in groups for h in (g.get('hooks') or []))
    if remove:
        if not present:
            return True, '没装过,跳过'
        backup(p)
        for g in list(groups):
            g['hooks'] = [h for h in (g.get('hooks') or []) if not _is_ours(h.get('command'))]
            if not g['hooks']:
                groups.remove(g)
        if not groups:
            hooks.pop('SessionStart', None)
        if not hooks:
            data.pop('hooks', None)
        llm.atomic_write(p, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
        return True, '已摘掉 SessionStart hook'
    if present:
        return True, '已经装过(SessionStart hook)'
    backup(p)
    groups.append({'hooks': [{'type': 'command', 'command': f'{cm_bin()} snapshot'}]})
    llm.atomic_write(p, json.dumps(data, ensure_ascii=False, indent=2) + '\n')
    _record('claude', p)
    return True, f'已加 SessionStart hook → {p}'


# ---------- 标记块(Codex / dsh 的 AGENTS.md 走同一套) ----------
def _block(cfg):
    name = cfg.get('user_name')
    if (cfg.get('language') or 'zh') == 'en':
        body = (f'## Read the snapshot first (compound-memory)\n\n'
                f'At the start of every session, run `{cm_bin()} snapshot` to load the long-term '
                f'memory about {name} (preferences, explicit requests, recent decisions, open threads). '
                f'It is orientation only — run `{cm_bin()} recall "<topic>"` when you need the details. '
                f'The transcripts live on the machine that generated them; mark anything you cannot '
                f'verify locally as unverified.\n')
    else:
        body = (f'## 开局先读快照(compound-memory)\n\n'
                f'每个 session 开始时先运行 `{cm_bin()} snapshot`,读关于 {name} 的长期记忆'
                f'(偏好、明确提出的要求、近期要事、未收口线头)。快照只是导航;'
                f'细节用 `{cm_bin()} recall "话题"` 按任务检索。'
                f'原文在产生它的那台机器上,本机不可核查的细节标「未核实」。\n')
    return f'<!-- {MARK}:start -->\n{body}<!-- {MARK}:end -->\n'


def _patch_markdown(path, cfg, remove=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    old = open(path, encoding='utf-8').read() if os.path.exists(path) else ''
    pat = re.compile(re.escape(f'<!-- {MARK}:start -->') + r'.*?' +
                     re.escape(f'<!-- {MARK}:end -->') + r'\n?', re.S)
    if remove:
        if not pat.search(old):
            return True, '没装过,跳过'
        backup(path)
        llm.atomic_write(path, pat.sub('', old).rstrip() + '\n')
        return True, f'已从 {path} 摘掉'
    blk = _block(cfg)
    if pat.search(old):
        if pat.search(old).group(0).strip() == blk.strip():
            return True, f'已经装过({path})'
        backup(path)
        llm.atomic_write(path, pat.sub(blk, old))
        return True, f'已更新 {path}'
    backup(path)
    new = (old.rstrip() + '\n\n' + blk) if old.strip() else blk
    llm.atomic_write(path, new)
    return True, f'已写入 {path}'


def inject_codex(cfg, remove=False):
    d = os.path.expanduser('~/.codex')
    if not os.path.isdir(d):
        return False, 'Codex 没装(没有 ~/.codex)'
    ok, msg = _patch_markdown(os.path.join(d, 'AGENTS.md'), cfg, remove)
    if ok and not remove:
        _record('codex', os.path.join(d, 'AGENTS.md'))
    return ok, msg


# ---------- DeepSeek Harness ----------
def dsh_profiles(cfg):
    """dsh 的注入是**按 profile** 的,一台机器可能有好几个(web / tui / headless…),
    所以全都要装,不能只装第一个。"""
    override = config.expand(config.host_cfg(cfg, 'dsh').get('profile_dir') or '')
    if override:
        return [override] if os.path.isdir(override) else []
    root = os.path.expanduser('~/.dsh/profiles')
    if not os.path.isdir(root):
        return []
    return [os.path.join(root, n) for n in sorted(os.listdir(root))
            if os.path.exists(os.path.join(root, n, 'cordis.patch.yml'))]


def dsh_plugin_available(profile):
    """插件要能从 profile 目录解析到,才值得写进 patch(profile 自己的 node_modules,或上一层的)。"""
    for base in (os.path.join(profile, 'node_modules'),
                 os.path.join(os.path.dirname(profile), 'node_modules')):
        if os.path.isdir(os.path.join(base, '@deepseek-ai', 'dsh-hooks-claude-code')):
            return True
    return False


def dsh_hooks_json():
    """dsh 能直接跑 Claude Code 格式的 hooks,所以复用同一份配置。"""
    p = os.path.join(CM_HOME, 'dsh-hooks.json')
    llm.atomic_write(p, json.dumps(
        {'hooks': {'SessionStart': [{'hooks': [
            {'type': 'command', 'command': f'{cm_bin()} snapshot', 'timeout': 60}]}]}},
        ensure_ascii=False, indent=2) + '\n')
    return p


DSH_PATCH_BLOCK = """
# {mark}:start  —— 开局注入快照(dsh 自带 Claude Code 格式的 hook 桥)
- insert:
    - id: {mark}
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: {cfgpath}
# {mark}:end
"""


def _patch_dsh_profile(profile, remove=False):
    p = os.path.join(profile, 'cordis.patch.yml')
    old = open(p, encoding='utf-8').read() if os.path.exists(p) else '[]\n'
    pat = re.compile(r'\n?# ' + re.escape(MARK) + r':start.*?# ' + re.escape(MARK) + r':end\n?', re.S)
    if remove:
        if not pat.search(old):
            return None
        backup(p)
        new = pat.sub('\n', old)
        if not re.search(r'(?m)^\s*-\s', new):          # 摘光了就还原成空数组,否则不是合法 YAML
            new = new.rstrip() + '\n[]\n'
        llm.atomic_write(p, new)
        return f'摘掉插件 {p}'
    blk = DSH_PATCH_BLOCK.format(mark=MARK, cfgpath=dsh_hooks_json())
    backup(p)
    if pat.search(old):
        llm.atomic_write(p, pat.sub('\n' + blk, old))
    else:
        body = re.sub(r'(?m)^\s*\[\]\s*$\n?', '', old)   # 空数组占位符要去掉
        llm.atomic_write(p, body.rstrip() + '\n' + blk)
    return f'挂插件 {p}'


def inject_dsh(cfg, remove=False):
    """两条路一起走:

    1. `~/.dsh/AGENTS.md` —— **已验证**:dsh 每个 session 都会把它作为
       `agent-instructions` 注入(实测在会话日志里看得到)。
    2. `dsh-hooks-claude-code` 插件 —— 更好的那条路(直接把快照正文喂进去,不用模型自己去跑
       命令),但在撰写时的版本上实测没观察到 SessionStart 真的触发(见 docs/dsh.md)。
       它不会造成任何损害,留着;哪天 dsh 那边通了就自动生效。

    不想要插件那一条:config 里 `hosts.dsh.plugin_hook: false`。
    """
    if not os.path.isdir(os.path.expanduser('~/.dsh')):
        return False, 'dsh 没装(没有 ~/.dsh)'
    msgs = []
    if config.host_cfg(cfg, 'dsh').get('plugin_hook', True) is not False:
        for profile in dsh_profiles(cfg):
            if not dsh_plugin_available(profile) and not remove:
                continue
            try:
                m = _patch_dsh_profile(profile, remove)
            except Exception as ex:
                m = f'!! {os.path.basename(profile)}: {type(ex).__name__}'
            if m:
                msgs.append(m)
    ok, msg = _patch_markdown(os.path.expanduser('~/.dsh/AGENTS.md'), cfg, remove)
    msgs.append(msg)
    if ok and not remove:
        _record('dsh', os.path.expanduser('~/.dsh/AGENTS.md'))
    return ok, ';'.join(msgs)


INJECTORS = {'claude': inject_claude, 'codex': inject_codex, 'dsh': inject_dsh}


# ---------- cron ----------
def _crontab_read():
    r = subprocess.run(['crontab', '-l'], capture_output=True, text=True)
    return r.stdout if r.returncode == 0 else ''


def _crontab_write(text):
    r = subprocess.run(['crontab', '-'], input=text, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError((r.stderr or r.stdout)[:200])


def install_cron(cfg, remove=False):
    if not shutil.which('crontab'):
        return False, '本机没有 crontab,自己挂个定时器调 `cm distill`'
    cur = _crontab_read()
    lines = [l for l in cur.splitlines() if CRON_TAG not in l]
    if remove:
        if len(lines) == len(cur.splitlines()):
            return True, '没装过,跳过'
        _crontab_write('\n'.join(lines).rstrip() + '\n')
        return True, '已摘掉 cron'
    when = cfg.get('cron') or '30 4 * * *'
    log = os.path.join(CM_HOME, 'cron.log')
    # cron 的 cwd 是 $HOME,相对路径会静默错位 —— 所以显式 cd
    line = f'{when} cd {REPO} && {cm_bin()} distill >> {log} 2>&1  {CRON_TAG}'
    _crontab_write('\n'.join(lines + [line]).rstrip() + '\n')
    _record('cron', line)
    return True, f'已装 cron:{when}'


# ---------- 现状 ----------
def detect(cfg):
    out = []
    for name in ('claude', 'codex', 'dsh'):
        mod = sources.REGISTRY[name]
        hc = config.host_cfg(cfg, name)
        avail = mod.available(cfg)
        n = 0
        if avail:
            try:
                n = len(mod.scan(cfg, None))
            except Exception:
                n = -1
        out.append({'name': name, 'available': avail, 'dir': config.expand(hc.get('dir') or ''),
                    'sessions': n, 'inject': bool(hc.get('inject', True)),
                    'injected': is_injected(name, cfg)})
    return out


def is_injected(name, cfg):
    try:
        if name == 'claude':
            p = claude_settings()
            if not os.path.exists(p):
                return False
            data = json.load(open(p, encoding='utf-8'))
            return any(_is_ours(h.get('command'))
                       for g in ((data.get('hooks') or {}).get('SessionStart') or [])
                       for h in (g.get('hooks') or []))
        if name == 'codex':
            p = os.path.expanduser('~/.codex/AGENTS.md')
            return os.path.exists(p) and f'{MARK}:start' in open(p, encoding='utf-8').read()
        if name == 'dsh':
            p = os.path.expanduser('~/.dsh/AGENTS.md')
            if os.path.exists(p) and f'{MARK}:start' in open(p, encoding='utf-8').read():
                return True
            for profile in dsh_profiles(cfg):
                q = os.path.join(profile, 'cordis.patch.yml')
                if os.path.exists(q) and f'{MARK}:start' in open(q, encoding='utf-8').read():
                    return True
            return False
    except Exception:
        return False
    return False


def cron_installed():
    return CRON_TAG in _crontab_read()
