#!/usr/bin/env python3
"""命令行入口。`cm <子命令>`。"""
import argparse, json, os, shutil, sys

from . import config


def cmd_distill(args):
    from .distill import main as distill_main
    return distill_main(args)


def cmd_snapshot(args):
    from . import recall
    ap = argparse.ArgumentParser(prog='cm snapshot')
    ap.add_argument('--refresh', action='store_true', help='忽略缓存,直接问共享层要')
    a = ap.parse_args(args)
    try:
        return recall.print_snapshot(config.load(), a.refresh)
    except Exception as ex:               # 开局注入绝不能把 harness 搞崩
        print(f'(compound-memory: 快照读取失败 {type(ex).__name__})', file=sys.stderr)
        return 0


def cmd_recall(args):
    from . import recall
    ap = argparse.ArgumentParser(prog='cm recall')
    ap.add_argument('query', nargs='+')
    ap.add_argument('--k', type=int, default=8)
    ap.add_argument('--fast', action='store_true', help='纯本地字面匹配(默认就是)')
    ap.add_argument('--expand', action='store_true', help='先让小模型扩几个说法再搜(默认关,见 docs/recall.md)')
    ap.add_argument('--all', action='store_true', help='连已推翻的记忆一起找')
    a = ap.parse_args(args)
    fast = None if not (a.fast or a.expand) else (not a.expand)
    return recall.print_recall(config.load(), ' '.join(a.query), a.k, fast, a.all)


def cmd_doctor(args):
    from . import bootstrap, store, sinks
    cfg = config.load()
    print(f'配置        {cfg["_path"]}{"" if os.path.exists(cfg["_path"]) else "  (还没有,用的是默认值)"}')
    print(f'数据目录    {config.HOME}')
    print(f'用户        {cfg.get("user_name")}   语言 {cfg.get("language")}')
    print(f'模型        {cfg.get("model")}  effort={cfg.get("effort")}  '
          f'后端={(cfg.get("llm") or {}).get("backend")}')
    try:
        print(f'共享层      {sinks.get(cfg).describe()}')
    except Exception as ex:
        print(f'共享层      !! {ex}')
    rows = store.load()
    live = [m for m in rows if m.get('status') in ('active', 'uncertain')]
    print(f'记忆        本地 {len(rows)} 条,有效 {len(live)} 条,共享 {len(store.shared(rows))} 条')
    print(f'水位线      {len([k for k in store.load_state() if not k.startswith("_")])} 个 session 已处理')
    print()
    print(f'{"harness":8} {"装了":6} {"会话数":>7}  {"开局注入":8} 目录')
    for h in bootstrap.detect(cfg):
        print(f'{h["name"]:8} {"是" if h["available"] else "否":6} {h["sessions"]:>7}  '
              f'{"已接上" if h["injected"] else ("未接" if h["available"] else "-"):8} {h["dir"]}')
    print()
    print(f'cron        {"已装" if bootstrap.cron_installed() else "未装"}  ({cfg.get("cron")})')
    cmbin = shutil.which('cm')
    print(f'cm 在 PATH  {cmbin or "否 —— 把 ~/.local/bin 加进 PATH"}')
    return 0


def cmd_install(args):
    from . import bootstrap
    ap = argparse.ArgumentParser(prog='cm install')
    ap.add_argument('--no-inject', action='store_true')
    ap.add_argument('--no-cron', action='store_true')
    a = ap.parse_args(args)
    cfg = config.load()
    dst, how = bootstrap.link_bin()
    print(f'  cm        {dst}  ({how})')
    if not a.no_inject:
        for h in bootstrap.detect(cfg):
            if not h['available']:
                print(f'  {h["name"]:9} 跳过(没装)')
                continue
            if not h['inject']:
                print(f'  {h["name"]:9} 跳过(配置里 inject: false)')
                continue
            ok, msg = bootstrap.INJECTORS[h['name']](cfg)
            print(f'  {h["name"]:9} {"" if ok else "!! "}{msg}')
    if not a.no_cron:
        ok, msg = bootstrap.install_cron(cfg)
        print(f'  cron      {"" if ok else "!! "}{msg}')
    return 0


def cmd_uninstall(args):
    from . import bootstrap
    ap = argparse.ArgumentParser(prog='cm uninstall')
    ap.add_argument('--purge', action='store_true', help='连 ~/.compound-memory 里的记忆一起删(不可逆)')
    a = ap.parse_args(args)
    cfg = config.load()
    for name, fn in bootstrap.INJECTORS.items():
        try:
            ok, msg = fn(cfg, remove=True)
        except Exception as ex:
            ok, msg = False, f'{type(ex).__name__}: {ex}'
        print(f'  {name:9} {"" if ok else "!! "}{msg}')
    ok, msg = bootstrap.install_cron(cfg, remove=True)
    print(f'  cron      {"" if ok else "!! "}{msg}')
    link = os.path.expanduser('~/.local/bin/cm')
    if os.path.islink(link) and os.path.realpath(link) == os.path.realpath(bootstrap.cm_bin()):
        os.remove(link)
        print(f'  cm        已删 {link}')
    if a.purge:
        import shutil as sh
        sh.rmtree(config.HOME, ignore_errors=True)
        print(f'  数据      已删 {config.HOME}')
    else:
        print(f'  数据      保留在 {config.HOME}(要删加 --purge)')
    return 0


def cmd_sessions(args):
    from . import store, sources
    cfg = config.load()
    state = store.load_state()
    recs = sources.scan_all(cfg, None)
    recs.sort(key=lambda r: r.get('ts_last') or '')
    for r in recs[-int(args[0]) if args and args[0].isdigit() else -30:]:
        st = state.get(f"{r['source']}:{r['sid']}") or {}
        print(f"{(r.get('ts_last') or '')[:16]}  {r['source']:7} {sources.short(r['sid'])} "
              f"{r.get('n_user_turns',0):>4}轮  {'✓' if st else ' '} "
              f"{st.get('topic') or r.get('title') or ''}")
    return 0


def cmd_eval(args):
    from .evaluate import main as eval_main
    return eval_main(args)


def cmd_sink_init(args):
    from . import sinks
    cfg = config.load()
    try:
        print(f"  {cfg.get('sink')}  {sinks.get(cfg).init()}")
        return 0
    except Exception as ex:
        print(f'  !! {type(ex).__name__}: {ex}')
        if (cfg.get('sink') or '').lower() == 'feishu':
            p = os.path.join(config.REPO, 'cm', 'sinks', 'feishu_fields.json')
            print('\n自己建表的话,字段是这些(也见 docs/sinks.md):\n')
            print(json.dumps(json.load(open(p, encoding='utf-8')), ensure_ascii=False, indent=1))
        return 1


COMMANDS = {
    'distill': cmd_distill, 'snapshot': cmd_snapshot, 'recall': cmd_recall,
    'doctor': cmd_doctor, 'install': cmd_install, 'uninstall': cmd_uninstall,
    'sessions': cmd_sessions, 'sink-init': cmd_sink_init, 'eval': cmd_eval,
}

USAGE = """compound-memory —— 把每天的对话自动沉淀成"关于你"的长期记忆

  cm distill [--days N] [--limit N] [--dry]   提炼(每晚 cron 自动跑,也可手动)
  cm snapshot [--refresh]                     打印当前快照(开局注入用的就是它)
  cm recall "话题" [--k N] [--expand]         按话题检索记忆
  cm doctor                                   看现状:配置、记忆条数、各 harness 接没接上
  cm sessions [N]                             列最近的 session 与处理状态
  cm eval [--n N] [--set 题目文件]            量检索:出题→看标准答案排第几
  cm install / cm uninstall                   接上/摘掉开局注入与 cron
  cm sink-init                                共享层初始化提示

配置:{cfg}
"""


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if not argv or argv[0] in ('-h', '--help', 'help'):
        print(USAGE.format(cfg=config.CONFIG_PATH))
        return 0
    if argv[0] in ('-V', '--version'):
        from . import __version__
        print(__version__)
        return 0
    cmd = COMMANDS.get(argv[0])
    if not cmd:
        print(f'不认识的子命令:{argv[0]}\n')
        print(USAGE.format(cfg=config.CONFIG_PATH))
        return 2
    return cmd(argv[1:])


if __name__ == '__main__':
    raise SystemExit(main())
