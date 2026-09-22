<div align="center">

# 🧠 compound-memory

**You just work. The AI gets better at knowing you.**

A background process that reads your own transcripts every night, distills them into a
long-term memory *about you*, and hands it to your next session — on any machine,
in any harness, with any model.

[中文](README.md) · [English](README_EN.md) · [dsh session format](docs/dsh.md) · [Shared layer](docs/sinks.md)

![python](https://img.shields.io/badge/python-3.9%2B-blue)
![harness](https://img.shields.io/badge/harness-Claude%20Code%20%7C%20Codex%20%7C%20dsh-green)
![deps](https://img.shields.io/badge/dependencies-0-lightgrey)
![license](https://img.shields.io/badge/license-MIT-black)

</div>

---

## What it does

1. **Reads the transcripts. You log nothing.** Every night it scans this machine's session
   files and distills, session by session, incrementally. You never have to say "remember this".
2. **Injects at session start.** A new session opens with the snapshot already in context:
   your standing preferences, what you have explicitly asked for, recent decisions, and
   what is still open. No re-explaining.
3. **Searches on demand.** `cm recall "pricing"` pulls the relevant memories with their
   sources. The snapshot stays short on purpose.
4. **Switching tools doesn't lose memory.** Claude Code, Codex and DeepSeek Harness share
   one memory and all three get the injection.
5. **Memories get revised, not piled up.** Change your mind and the old entry is marked
   *overturned* and drops out of the snapshot; a finished thread is *closed*. Adding to or
   confirming a memory never touches it (easy to get wrong — see [Revision semantics](#revision-semantics)).
6. **Transcripts never leave the machine.** Only entries individually judged both *necessary*
   and *appropriate* to share go out, after a secret-pattern scrub. The default shared layer
   is a local directory — no account needed.
7. **Budget discipline.** Background calls go through one slim entry point (background
   overhead down from ~43k to ~11k tokens per call), the model is named explicitly, each
   run has a session cap, and hitting a usage limit stops the run *without* advancing the
   watermark.

> In one line: **your raw transcripts are the asset; the memory is a cache you can always
> recompute.** When models get better, re-distill from the transcripts — don't get locked
> into today's distillation.

---

## 🚩 Before you install

- **It reads all of your session logs.** That is its only input. If that's not OK, don't install it.
- **It spends model budget.** Up to 20 sessions per night by default, one call each.
  Run `cm distill --dry` first to see how many that is.
- **Use a private repo for the shared layer.** With `sink: github`, the contents are about you.
- **Session-start injection edits a few files**: `~/.claude/settings.json`,
  `~/.codex/AGENTS.md`, `~/.dsh/AGENTS.md`, and each dsh profile's `cordis.patch.yml`.
  Every one is backed up to `~/.compound-memory/backups/` first, every edit is marked,
  and `cm uninstall` removes exactly what it added.
- **The default model is Claude Opus.** In a side-by-side run, Sonnet missed about a quarter
  of the entries and collapsed several distinct requests into one. Downgrade if you want —
  just know what you're trading.
- **An inference is not a rule.** What the model writes are dated observations. Only things
  *you said explicitly* are tagged as requests, with a scope. Don't expect it to legislate for you.

---

## Install

```bash
git clone https://github.com/<you>/compound-memory.git ~/compound-memory
cd ~/compound-memory && bash install.sh
```

It runs one distillation right away and prints the snapshot — you find out whether it
works now, not tomorrow morning.

```bash
bash install.sh --name Alex --yes          # non-interactive
bash install.sh --no-cron --no-inject      # just lay down files
cm uninstall                               # remove cleanly; --purge also deletes memories
```

One prerequisite: **a model you can call.** By default it uses the `claude` CLI you're
already logged into (zero extra setup). Otherwise set `llm.backend: openai` in
`config.yaml` with `base_url` and `api_key_env` — any OpenAI-compatible endpoint works.

---

## Support matrix

| Harness | Reads transcripts from | Session-start injection | Status |
|---|---|---|---|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | `SessionStart` hook in `settings.json` | ✅ verified |
| **Codex CLI** | `~/.codex/sessions/**/rollout-*.jsonl` | appended block in `~/.codex/AGENTS.md` | ✅ verified |
| **DeepSeek Harness (dsh)** | `~/.dsh/sessions/**/session*.jsonl.zstd` (zstd) | a block in `~/.dsh/AGENTS.md` **plus** the `dsh-hooks-claude-code` plugin | ✅ reading verified · ✅ AGENTS.md injection verified · ⚠️ the plugin bridge never fired on the version tested — see [docs/dsh.md](docs/dsh.md) |

dsh's session format is undocumented publicly — it was reverse-engineered on a live install
(compressed, two file generations side by side, `user/message` events that also carry
plugin-injected context). Details and how to verify it yourself: [docs/dsh.md](docs/dsh.md).

Adding a harness = one file, `cm/sources/<name>.py`, exposing `available / scan / load_turns`.

---

## How it works

```
  you, working normally
      │
      ▼
 ┌──────────────────────────────────────────────┐
 │  raw transcripts (session files)             │   ← the asset. never leaves the machine.
 │  Claude Code · Codex · dsh                   │
 └──────────────────────────────────────────────┘
      │  nightly, incremental, per session
      │  watermark = timestamp of the last message in that session (NOT file mtime)
      │  fewer than max(3 turns, 25%) new? let it accumulate — not worth a call
      ▼
 ┌──────────────────────────────────────────────┐
 │  distill: the whole session + the memories    │   one model call
 │  it produced before, understood together      │
 │  nature request/idea/inference/fact · kind ·  │
 │  horizon · revised/overturned/closed          │
 └──────────────────────────────────────────────┘
      │
      ├──────────────▶ local, complete   observations.jsonl
      │
      │  per-entry share judgment + secret-pattern scrub
      ▼
 ┌──────────────────────────────────────────────┐
 │  shared layer:  local dir / private git / Lark│   ← memories leave, transcripts don't
 │  + the snapshot (4 sections, ≤3200 chars)     │
 └──────────────────────────────────────────────┘
      │
      ├── at session start: SessionStart hook injects the snapshot
      └── during work:      cm recall "topic"   (with sources)
```

### Why per session, not per day

A day boundary splits an overnight session in half, can't absorb late data, and can't
resume. Per session with a watermark: incremental, resumable, late data lands automatically,
and an interrupted run picks up where it stopped.

### Why "last message timestamp" and not file mtime

A live session process rewrites its own metadata, so mtime moves while the content doesn't.
Judging "is there anything new" by mtime means re-processing unchanged sessions every hour —
quietly burning budget the whole time.

### Revision semantics

The easiest part to get wrong. **Only a replacement touches the old memory:**

| Situation | Old memory |
|---|---|
| A more accurate or newer statement of the same thing | marked `revised`, drops out of the snapshot |
| He explicitly changed his mind; this contradicts it | marked `overturned` |
| It was an open thread and this finishes or cancels it | marked `closed` |
| **Adding to, extending, relating, re-confirming** | **untouched, stays live** |

That last row was learned the hard way: an early version treated "adds to" as "replaces"
and closed a whole batch of still-valid memories in one run. The prompt now spells out all four cases and
states that setting the flag makes the old entry disappear, so when in doubt, don't.

---

## Configuration

Lives in `~/.compound-memory/config.yaml` (copied from `config.example.yaml` at install).

| Key | Default | Meaning |
|---|---|---|
| `user_name` | asked at install | who the memory is about; the `{user_name}` in the prompts |
| `language` | `zh` | `zh` / `en` — language of the prompts and the snapshot |
| `model` | `claude-opus-5` | model used for distillation |
| `effort` | `high` | reasoning effort (`claude-cli` backend only) |
| `llm.backend` | `claude-cli` | `claude-cli` (the CLI you're logged into) or `openai` |
| `llm.claude_flags` | see example | the slim entry point; break these and overhead multiplies |
| `sink` | `local` | shared layer: `local` / `github` / `feishu` |
| `nightly_limit` | `20` | max sessions processed per run |
| `window_days` | `7` | only sessions with new activity in this window |
| `max_candidates` | `8` | max memories extracted per session |
| `text_budget` | `14000` | characters of a session fed to the model (first 40% + last 60%) |
| `snapshot_max_chars` | `3200` | hard cap on the snapshot body; over it, it is compressed |
| `cron` | `30 4 * * *` | when the nightly run fires |
| `baseline_file` | empty | a local rules file copied verbatim into the snapshot's last section |
| `hosts.<name>.enabled` | `auto` | `auto` = use it if it's installed |
| `hosts.<name>.inject` | `true` | whether to install session-start injection for it |

The prompts are plain files under `prompts/` — **the thing you should most want to tune**.
To edit them while keeping the originals, copy them to `~/.compound-memory/prompts/`,
which takes precedence.

---

## FAQ

**Nothing showed up after installing.**
Run `cm doctor`. Usually there just wasn't a long enough conversation in the last 7 days
(sessions with fewer than 2 user turns are skipped). Try `cm distill --days 60 --limit 5`.

**How do I backfill history?**
`cm distill --days 365 --limit 0`, or a few nights at `nightly_limit` — the watermark remembers.

**What does a night cost?**
One call per session plus one snapshot build. At the default cap that's 21 calls.
`~/.compound-memory/usage.log` has one line per call, so you can check for yourself.

**Will it turn things I said into rules it then follows?**
No. Memories carry a *nature*: only what you stated explicitly is tagged as a request, with
a scope. The model's inferences sit in their own snapshot section, each labelled. Hard limits
don't go through the model at all — point `baseline_file` at a local file and it's copied verbatim.

**Does the injected snapshot get distilled back in as something I said?**
No. The injection carries a `compound-memory-snapshot` marker that all three adapters filter
out; dsh has a second layer (it tags the injection `source.kind: plugin`).

**Can several machines share one memory?**
Yes. Point `sink: github` at a **private** repo and clone it everywhere. Run the distillation
on one machine; the others read only. Transcripts are never moved between machines.

**Can I use it without Claude?**
Yes — `llm.backend: openai` plus `base_url` and `api_key_env`. Just note that the defaults
(Opus / high) were chosen by a side-by-side comparison; if you swap the model, re-check coverage.

**What's left after uninstalling?**
`cm uninstall` removes the three injections and the cron entry; pre-change backups stay in
`~/.compound-memory/backups/`. Memories are kept unless you pass `--purge`.

---

## Privacy

- **Transcripts stay local.** Read in place; never uploaded, never copied to the shared layer.
- **Every shared entry is judged individually** at the moment it's written: does an AI on
  another machine need this, and does it contain secrets / third-party private details /
  financial, legal or health information? When unsure, it stays local.
- **Scrubbing happens at the export step**, not as an after-the-fact checklist — cleaning up
  afterwards is whack-a-mole.
- **Complete locally, redacted on the way out.** `observations.jsonl` keeps everything;
  the shared layer only gets entries marked `share: true`.
- **Always revocable.** The shared layer is files (or one table) — delete it and it's gone;
  local memories can be rebuilt from the transcripts.

---

## License

MIT.
