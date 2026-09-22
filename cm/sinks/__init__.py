#!/usr/bin/env python3
"""共享层适配器:记忆离开本机之后放哪。

原文永远不出机,只有被判定为"必要且适合共享"的记忆条目会走到这里,而且出机前过一遍
密钥模式清洗。默认 local —— 纯本地文件、零账号,单机用户什么都不用配。
"""


def remote_of(m, sink_name):
    """这条记忆在某个共享层里的状态。

    按 sink 分开存是必须的:同一份本地记忆可能先后(或同时)发到不同共享层,
    共用一个 remote_id 的话,换 sink 之后老记录会被当成"已经同步过"而整批漏发。
    """
    return (m.get('remote') or {}).get(sink_name) or {}


def remote_set(m, sink_name, rid, status):
    m.setdefault('remote', {})[sink_name] = {'id': rid, 'status': status}


def needs_push(m, sink_name):
    r = remote_of(m, sink_name)
    return not r.get('id') or r.get('status') != m.get('status')


class Sink:
    name = 'base'

    def __init__(self, cfg):
        self.cfg = cfg
        self.conf = (cfg.get('sinks') or {}).get(self.name) or {}

    # 写
    def publish_memories(self, rows):
        """rows = 本地全量记忆。实现方自己挑 share=True 的发出去,并把远端 id 写回 row。
        返回这次实际发出去的条数。"""
        return 0

    def publish_snapshot(self, text):
        """返回一个能给人看的位置(路径或 URL)。"""
        raise NotImplementedError

    # 读(给别的机器用)
    def fetch_snapshot(self):
        return None

    def fetch_memories(self):
        return []

    def init(self):
        """第一次用这个共享层时的准备工作(建表、建目录…)。默认什么都不用做。"""
        return '不用初始化'

    def describe(self):
        return self.name


def get(cfg):
    name = (cfg.get('sink') or 'local').lower()
    if name == 'local':
        from .local import LocalSink
        return LocalSink(cfg)
    if name == 'github':
        from .github import GithubSink
        return GithubSink(cfg)
    if name == 'feishu':
        from .feishu import FeishuSink
        return FeishuSink(cfg)
    raise RuntimeError(f'不认识的 sink: {name}(可选 local / github / feishu)')
