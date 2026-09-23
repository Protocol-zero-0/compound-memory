#!/usr/bin/env python3
"""记忆的枚举值:内部一律存英文常量,进提示词/给人看时按 language 翻译。

这样两件事都成立:中文用户看到的是中文,JSONL 里的字段对任何语言的用户都可读;
换语言不会把历史记忆变成一堆看不懂的字符串。
"""

NATURE = ['request', 'idea', 'inference', 'fact']
KIND = ['event', 'about_user', 'thread', 'pattern', 'correction']
HORIZON = ['long', 'short']
STATUS = ['active', 'revised', 'overturned', 'closed', 'uncertain']

WORDS = {
    'zh': {
        'request': '要求', 'idea': '想法', 'inference': '推断', 'fact': '事实',
        'event': '事件·决定', 'about_user': '关于本人', 'thread': '线头·承诺',
        'pattern': '模式·矛盾', 'correction': '纠正·重复解释',
        'long': '长期', 'short': '短期',
        'active': '有效', 'revised': '已修正', 'overturned': '已推翻',
        'closed': '已收口', 'uncertain': '不确定',
    },
    'en': {
        'request': 'request', 'idea': 'idea', 'inference': 'inference', 'fact': 'fact',
        'event': 'event/decision', 'about_user': 'about-you', 'thread': 'open-thread',
        'pattern': 'pattern/contradiction', 'correction': 'correction/repeat',
        'long': 'long-term', 'short': 'short-term',
        'active': 'active', 'revised': 'revised', 'overturned': 'overturned',
        'closed': 'closed', 'uncertain': 'uncertain',
    },
}


def _overrides():
    """config.yaml 里的 labels:把某个值改叫别的名字(比如接进一张已有的表,那张表里叫「关于某某」)。"""
    try:
        from . import config
        return config.load().get('labels') or {}
    except Exception:
        return {}


def word(key, lang='zh'):
    ov = _overrides()
    if key in ov:
        return ov[key]
    return WORDS.get(lang, WORDS['zh']).get(key, key)


def options(group, lang='zh'):
    return '|'.join(word(k, lang) for k in group)


_REVERSE = None


def canon(value, group, default):
    """把模型写回来的(任何语言的)值还原成内部常量;认不出就用默认值。"""
    global _REVERSE
    if _REVERSE is None:
        _REVERSE = {}
        for lang, table in WORDS.items():
            for k, v in table.items():
                _REVERSE[v.lower()] = k
                _REVERSE[k.lower()] = k
        for k, v in _overrides().items():
            _REVERSE[str(v).lower()] = k
    if value is None:
        return default
    v = str(value).strip().lower()
    got = _REVERSE.get(v)
    if got in group:
        return got
    for k in group:                       # 容忍"长期(偏好)"这类带尾巴的写法
        for lang in WORDS:
            if v.startswith(WORDS[lang][k].lower()):
                return k
    return default
