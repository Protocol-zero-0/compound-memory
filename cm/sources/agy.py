"""Antigravity CLI's JSONL transcript, generated alongside its conversation DB."""
import json
from pathlib import Path
import re

from . import cached_scan, clean, iso, is_noise, since_epoch
from .. import config

NAME = 'agy'
HOOK_GROUP = 'compound-memory-agy'
REQUEST = re.compile(r'\A<USER_REQUEST>\n(.*?)\n</USER_REQUEST>(?:\n<ADDITIONAL_METADATA>(?:\n|$)|\s*\Z)', re.S)


def root(cfg):
    return Path(config.expand(config.host_cfg(cfg, NAME).get('dir')
                              or '~/.gemini/antigravity-cli/brain'))


def hooks_path():
    return Path.home() / '.gemini/config/hooks.json'


def attached():
    try:
        data = json.loads(hooks_path().read_text(encoding='utf-8'))
        group = data.get(HOOK_GROUP, {})
        return bool(group.get('enabled', True) and group.get('SessionStart'))
    except (OSError, ValueError, AttributeError):
        return False


def available(cfg):
    return root(cfg).is_dir()


def _user_turns(path):
    with open(path, encoding='utf-8', errors='replace') as transcript:
        for line in transcript:
            try:
                step = json.loads(line)
            except ValueError:
                continue
            if not isinstance(step, dict):
                continue
            if (step.get('type'), step.get('source')) != ('USER_INPUT', 'USER_EXPLICIT'):
                continue
            body = step.get('content')
            stamp = step.get('created_at')
            if not isinstance(body, str) or not isinstance(stamp, str):
                continue
            # AGY puts generated context after the user's request and can truncate it.
            match = REQUEST.match(body)
            if not match:
                continue
            message = match.group(1).strip()
            if message.startswith('/plan '):
                message = message[len('/plan '):].strip()
            if not (message.startswith('/') or is_noise(message)):
                yield iso(stamp), clean(message)


def _parse(path):
    stamps = [stamp for stamp, _ in _user_turns(path) if stamp]
    if stamps:
        return {'source': NAME, 'sid': Path(path).parents[2].name, 'path': path,
                'cwd': None, 'title': None, 'ts_first': min(stamps),
                'ts_last': max(stamps), 'n_user_turns': len(stamps)}


def scan(cfg, since=None):
    enabled = config.host_cfg(cfg, NAME).get('enabled', 'auto')
    if str(enabled).lower() in ('false', 'no', 'off'):
        return []
    if enabled is not True and not attached():
        return []
    paths = root(cfg).glob('*/.system_generated/logs/transcript.jsonl')
    return cached_scan(NAME, (str(path) for path in paths), _parse, since_epoch(since))


def load_turns(rec):
    return [message for _, message in _user_turns(rec['path'])]
