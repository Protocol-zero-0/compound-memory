#!/usr/bin/env python3
"""github:共享层放在一个 git 仓库里,每晚提交并推送。

适合多台自己的机器共享一份记忆。**请用私有仓库** —— 记忆是关于你本人的。
前置条件:repo_dir 已经 clone 好、能免密 push(SSH key 或 credential helper)。
"""
import os, subprocess, time

from .. import config
from .local import LocalSink


class GithubSink(LocalSink):
    name = 'github'

    def dir(self):
        d = config.expand(self.conf.get('repo_dir') or os.path.join(config.HOME, 'share-git'))
        os.makedirs(d, exist_ok=True)
        return d

    def _git(self, *args, timeout=120):
        return subprocess.run(['git', '-C', self.dir(), *args], capture_output=True,
                              text=True, timeout=timeout)

    def _commit_push(self, message):
        if not os.path.isdir(os.path.join(self.dir(), '.git')):
            self._git('init', '-q')
        self._git('add', '-A')
        r = self._git('commit', '-m', message)
        if r.returncode != 0 and 'nothing to commit' not in (r.stdout + r.stderr):
            raise RuntimeError(f'git commit 失败: {(r.stderr or r.stdout)[:200]}')
        if self.conf.get('push', True):
            br = self.conf.get('branch') or 'main'
            r = self._git('push', 'origin', f'HEAD:{br}', timeout=180)
            if r.returncode != 0:
                raise RuntimeError(f'git push 失败: {(r.stderr or r.stdout)[:200]}')

    def publish_memories(self, rows):
        n = super().publish_memories(rows)
        self._commit_push(f"memories {time.strftime('%Y-%m-%d %H:%M')} ({n})")
        return n

    def publish_snapshot(self, text):
        p = super().publish_snapshot(text)
        self._commit_push(f"snapshot {time.strftime('%Y-%m-%d %H:%M')}")
        return p

    def fetch_snapshot(self):
        self._git('pull', '--ff-only', timeout=120)
        return super().fetch_snapshot()

    def describe(self):
        return f'github:{self.dir()}'
