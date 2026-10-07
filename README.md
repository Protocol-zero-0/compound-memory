<div align="center">

# 🧠 compound-memory

**每次开新对话都要重新自我介绍?让 AI 自动记住你。**

一个后台进程,每晚把你和 AI 的对话变成"关于你"的记忆;下一次对话——
换机器、换工具、换模型都一样——开局就带着它,不用你再解释一遍。

[中文](README.md) · [English](README_EN.md) · [原理与设计](docs/design.md) · [检索](docs/recall.md) · [隐私闸](docs/privacy-gate.md)

![python](https://img.shields.io/badge/python-3.9%2B-blue)
![harness](https://img.shields.io/badge/harness-Claude%20Code%20%7C%20Codex%20%7C%20dsh-green)
![deps](https://img.shields.io/badge/依赖-0-lightgrey)
![license](https://img.shields.io/badge/license-MIT-black)

</div>

---

## 长这样(下面是虚构示例,不是真实用户数据)

新会话开局,这段会自动出现在上下文里:

```
<compound-memory-snapshot source="shared">
# Alex · 当前快照
生成:2026-09-20 04:30 · 有效共享记忆 86 条

## A 长时效
### 他明确提出的要求
- 代码审查只看正确性和可简化的地方,不主动扩大范围(09-02)
- 周报用大白话,不用咨询黑话(08-14)

## B 短时效
### 未收口线头
- 等供应商确认交付日期后再定发布时间(09-18)
</compound-memory-snapshot>
```

工作中随时按话题翻细节,带出处:

```bash
$ cm recall "供应商"
【记忆检索】
- [线头·承诺, 09-18] 等供应商确认交付日期后再定发布时间
    出处:claude:3267ab25 · 发布节奏讨论
```

## 为什么好用

- **不用你做任何事。** 每晚自动读会话、提炼、写快照,你只管正常用 AI。
- **跨工具、跨机器。** Claude Code、Codex、DeepSeek Harness 共用同一份记忆,三边都自动注入。
- **会更新,不会越堆越乱。** 改主意了,旧记忆自动失效;不是无限累积的日志。
- **原文永远留在本机。** 只有逐条判定"必要且适合共享"的记忆会出机,出机前清洗密钥。
- **额度有纪律。** 精简调用、每晚上限,撞到额度就停,不会偷偷烧钱。

设计取舍(为什么按 session 不按天、为什么不用文件 mtime、修订语义怎么定、完整架构图)
→ [docs/design.md](docs/design.md)

---

## 🚩 装之前看一眼

- **它会读你全部的会话记录。** 这是它唯一的信息来源。不能接受就别装。
- **它会按配置的模型花钱/花额度。** 默认每晚最多 20 个 session,一个 session 一次调用。
  先用 `cm distill --dry` 看一眼要处理多少个。
- **开局注入会改几个文件**(`~/.claude/settings.json`、`~/.codex/AGENTS.md` 等),
  都先备份、带标记,`cm uninstall` 原样摘掉。
- **默认模型是 Claude Opus。** 对比实验里 Sonnet 会漏掉约四分之一的条目。省钱可以换,
  但知道你在换什么。
- **推断不是规则。** 只有你明确说过的话才带"要求"标记,模型不会替你立规矩。

---

## 一键安装

```bash
git clone https://github.com/<你的账号>/compound-memory.git ~/compound-memory
cd ~/compound-memory && bash install.sh
```

装完会当场跑一次提炼并把快照打出来——不用等到第二天才知道通没通。

```bash
bash install.sh --name 张三 --yes          # 不交互
bash install.sh --no-cron --no-inject      # 只铺文件,自己决定怎么接
cm uninstall                               # 原样摘掉;加 --purge 连记忆一起删
```

前置条件只有一个:**一个能调的模型**。默认用本机已经登录的 `claude` 命令(零额外配置);
没有就把 `config.yaml` 里 `llm.backend` 改成 `openai`,填 `base_url` 和 `api_key_env`,
任何 OpenAI 兼容接口都行。

---

## 支持矩阵

| harness | 读原文 | 开局注入 | 状态 |
|---|---|---|---|
| **Claude Code** | `~/.claude/projects/**/*.jsonl` | `settings.json` 的 `SessionStart` hook | ✅ 已验证 |
| **Codex CLI** | `~/.codex/sessions/**/rollout-*.jsonl` | `~/.codex/AGENTS.md` 追加一段 | ✅ 已验证 |
| **DeepSeek Harness (dsh)** | `~/.dsh/sessions/**/*.jsonl.zstd` | `~/.dsh/AGENTS.md` 追加一段 **+** hook 插件 | ✅ 读原文已验证 · ⚠️ 插件桥见 [docs/dsh.md](docs/dsh.md) |

再加一个 harness = 写一个 `cm/sources/<名字>.py`,提供 `available / scan / load_turns` 三个函数。

---

## 配置说明

配置在 `~/.compound-memory/config.yaml`(装的时候从 `config.example.yaml` 复制过去)。

| 键 | 默认 | 说明 |
|---|---|---|
| `user_name` | 安装时问你 | 记忆是关于谁的 |
| `language` | `zh` | `zh` / `en` |
| `model` / `effort` | `opus` / `high` | 后台提炼用的模型(写别名,自动跟最新版) |
| `llm.backend` | `claude-cli` | 或 `openai`(任何兼容接口) |
| `sink` | `local` | 共享层:`local` / `github` / `feishu` |
| `nightly_limit` | `20` | 每次运行最多处理几个 session |
| `window_days` | `7` | 只看最近多少天有新对话的 session |
| `snapshot_max_chars` | `3200` | 快照正文硬上限,超了自动压缩 |
| `cron` | `30 4 * * *` | 每晚跑的时间 |
| `hosts.<名字>.enabled/inject` | `auto` / `true` | 这个 harness 要不要装开局注入 |

提示词在 `prompts/` 下,纯文本——**这是最该你自己调的东西**。想改又想保留原版,
复制到 `~/.compound-memory/prompts/`,那边优先。改之前先 `cm eval --n 24` 存一套题,
改完用同一套题复跑再比较,见 [docs/recall.md](docs/recall.md)。

---

## 常见问题

**装完什么都没有?**
`cm doctor` 看一眼。最常见的是最近 7 天没有够长的对话,试 `cm distill --days 60 --limit 5`。

**怎么补历史?**
`cm distill --days 365 --limit 0`。按 `nightly_limit` 分几晚跑完也行,水位线记得住。

**已经有一堆记忆了,能搬过来吗?**
能。`python3 tools/import-legacy-jsonl.py <旧文件.jsonl>`,一行一条的旧格式都吃得下,
重复跑安全。

**一晚上要花多少?**
一个 session 一次调用,加一次快照生成。`~/.compound-memory/usage.log` 一行一次,可以自己核。

**会不会把我说的话当成规则执行?**
不会。只有你明确提出的才标"要求";模型的推断在快照里单独一节、逐条标明。

**能多台机器共用吗?**
能。`sink: github` 指一个**私有**仓库,每台机器 clone;或 `sink: feishu` 让人也能随手翻,
`cm sink-init` 一条命令建表。

**卸载会留下什么?**
`cm uninstall` 摘掉注入和 cron;记忆默认留着,要删加 `--purge`。

---

## 隐私

- **原文不出机。** 会话文件只在本机读,不上传。
- **出机的东西逐条判定。** 每条记忆都要回答"别的机器需不需要它"和"含不含密钥/隐私信息";
  拿不准就留本地,密钥清洗做在导出那一步。
- **随时可撤回。** 共享层是文件(或一张表),删掉就没了;本地记忆重跑原文可以重建。
- **推代码之前过闸。** 写文档举例子最容易顺手把真实内容带进仓库。`tools/global-gate/` 给
  本机所有仓库装一道推送闸,拿敏感词表和会话原文指纹扫新内容,命中就推不出去。
  细节见 [docs/privacy-gate.md](docs/privacy-gate.md)。

---

## 许可

MIT。
