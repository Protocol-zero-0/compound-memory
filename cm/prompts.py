#!/usr/bin/env python3
"""提示词加载与渲染。

提示词单独放在 prompts/ 下,方便直接改 —— 它是这个系统里最该由你自己调的东西。
渲染用的是"只替换已知的 {占位符}",不是 str.format:提示词里有 JSON 样例,
用 format 会被一堆大括号绊住。
"""
import os

from . import config, lexicon as L

DIRS = [os.path.join(config.HOME, 'prompts'), os.path.join(config.REPO, 'prompts')]


def load(name, lang='zh'):
    """先找 ~/.compound-memory/prompts/(用户改过的),再找仓库自带的;英文版找不到就退回默认。"""
    cands = []
    if lang and lang != 'zh':
        cands.append(f'{name}.{lang}.md')
    cands.append(f'{name}.md')
    for d in DIRS:
        for c in cands:
            p = os.path.join(d, c)
            if os.path.exists(p):
                return open(p, encoding='utf-8').read()
    raise FileNotFoundError(f'找不到提示词 {name}(找过:{DIRS})')


def words(lang='zh'):
    w = {f'w_{k}': L.word(k, lang) for k in
         ('request', 'idea', 'inference', 'fact', 'event', 'thread', 'pattern',
          'correction', 'long', 'short', 'revised', 'overturned', 'closed', 'uncertain')}
    w['w_about'] = L.word('about_user', lang)
    w['nature_opts'] = L.options(L.NATURE, lang)
    w['kind_opts'] = L.options(L.KIND, lang)
    w['horizon_opts'] = L.options(L.HORIZON, lang)
    w['old_status_opts'] = '|'.join(L.word(k, lang) for k in ('revised', 'overturned', 'closed'))
    return w


def render(template, **vars):
    out = template
    for k, v in vars.items():
        out = out.replace('{' + k + '}', '' if v is None else str(v))
    return out


def build(name, lang='zh', **vars):
    v = words(lang)
    v.update(vars)
    return render(load(name, lang), **v)
