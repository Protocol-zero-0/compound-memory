<div align="center">

# 🧠 compound-memory

**你照常工作,AI 自己越用越懂你**

一个后台进程,每晚读你和 AI 的对话原文,提炼成"关于你"的长期记忆;
下一个 session —— 哪怕换了机器、换了工具、换了模型 —— 开局就带着它。

[中文](README.md) · [English](README_EN.md) · [dsh 会话格式](docs/dsh.md) · [共享层](docs/sinks.md)

![python](https://img.shields.io/badge/python-3.9%2B-blue)
![harness](https://img.shields.io/badge/harness-Claude%20Code%20%7C%20Codex%20%7C%20dsh-green)
![deps](https://img.shields.io/badge/依赖-0-lightgrey)
![license](https://img.shields.io/badge/license-MIT-black)

</div>

---

## 它做什么

1. **自动读原文,不用你记录。** 每晚扫一遍本机的会话文件,按 session 增量提炼。你不需要
   写日志、不需要在对话结束时说"记一下" —— 你什么都不用做。
2. **开局自动注入。** 新 session 一开,快照就在上下文里:你的长期偏好、你明确提过的要求、
   最近的决定、还没收口的事。不用再从头解释一遍。
3. **工作中按需检索。** `cm recall "报价"` 翻出相关记忆和出处。快照只是导航,故意很短。
4. **换工具不掉记忆。** Claude Code、Codex、DeepSeek Harness 共用同一份记忆,
   三边都自动注入。
5. **记忆会被修订,不是越堆越多。** 你改了主意,旧条会被标成"已推翻"从快照里消失;
   线头完成了就"已收口"。补充和延伸不会误伤旧记忆(这条很容易做错,见[修订语义](#修订语义))。
6. **原文永远不出机。** 出机的只有逐条判定过"必要且适合共享"的记忆,而且过一遍密钥清洗。
   默认共享层就是本地一个目录,零账号。
7. **额度有纪律。** 后台调用走精简出口(背景开销从 ~4.3 万 token 降到 ~1.1 万),
   显式指定模型,每晚有条数上限,撞到额度上限立刻停且不推进水位线。

> 一句话:**资产是你的原始对话语料,记忆只是可以随时重算的缓存。** 模型变强了,
> 回到原文重提炼一遍就行 —— 而不是被今天这版提炼方式锁死。

---

## 🚩 注意事项

- **它会读你全部的会话记录。** 这是它唯一的信息来源。不能接受就别装。
- **它会按配置的模型花钱/花额度。** 默认每晚最多 20 个 session,一个 session 一次调用。
  先用 `cm distill --dry` 看一眼要处理多少个。
- **共享层请用私有仓库。** `sink: github` 的内容是关于你本人的。
- **开局注入会改这几个文件**:`~/.claude/settings.json`、`~/.codex/AGENTS.md`、
  `~/.dsh/AGENTS.md`、dsh 每个 profile 的 `cordis.patch.yml`。都先备份到
  `~/.compound-memory/backups/`,改动都带标记,`cm uninstall` 原样摘掉。
- **默认模型是 Claude Opus。** 对比实验里 Sonnet 会漏掉约四分之一的条目、还会把好几条
  独立要求揉成一条。省钱可以换,但知道你在换什么。
- **推断不是规则。** 模型写的是带日期的观察;只有你**明确说过**的话才带"要求"标记。
  别指望它替你立规矩。

---

## 一键安装

```bash
git clone https://github.com/<你的账号>/compound-memory.git ~/compound-memory
cd ~/compound-memory && bash install.sh
```

装完会当场跑一次提炼并把快照打出来 —— 不用等到第二天才知道通没通。

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
| **DeepSeek Harness (dsh)** | `~/.dsh/sessions/**/session*.jsonl.zstd`(zstd 压缩) | `~/.dsh/AGENTS.md` 追加一段 **+** 挂 `dsh-hooks-claude-code` 插件 | ✅ 读原文已验证 · ✅ AGENTS.md 注入已验证 · ⚠️ 插件桥在撰写时的版本上没观察到触发,见 [docs/dsh.md](docs/dsh.md) |

dsh 的会话格式公开文档没写,是实测摸出来的(压缩格式、两代文件共存、
`user/message` 里混着插件注入的内容)。细节和自己验证的方法都在 [docs/dsh.md](docs/dsh.md)。

再加一个 harness = 写一个 `cm/sources/<名字>.py`,提供 `available / scan / load_turns` 三个函数。

---

## 工作原理

```
  你照常工作
      │
      ▼
 ┌──────────────────────────────────────────────┐
 │  原始对话语料(session 文件)                  │   ← 资产。永远留在本机。
 │  Claude Code · Codex · dsh                    │
 └──────────────────────────────────────────────┘
      │  每晚一次,按 session 增量
      │  水位线 = 该 session 最后一条消息的时间戳(不是 mtime)
      │  新增不足 max(3 轮, 25%) 就攒着,不值得再调一次模型
      ▼
 ┌──────────────────────────────────────────────┐
 │  提炼:整个 session + 它以前提炼出的记忆       │   一次模型调用
 │  一起重新理解 → 候选记忆                      │
 │  性质 要求/想法/推断/事实 · 类型 · 时效        │
 │  取代旧条时标 已修正/已推翻/已收口             │
 └──────────────────────────────────────────────┘
      │
      ├──────────────▶ 本地全量  observations.jsonl   ← 什么都留着
      │
      │  逐条判定"必要且适合共享" + 密钥模式清洗
      ▼
 ┌──────────────────────────────────────────────┐
 │  共享层   local 目录 / git 私有仓库 / 飞书表   │   ← 只有记忆出机,原文不出
 │  + 当前快照(四节,正文 ≤3200 字)             │
 └──────────────────────────────────────────────┘
      │
      ├── 开局:SessionStart hook 注入快照  ← 任何机器、任何 harness
      └── 工作中:cm recall "话题"           ← 带出处
```

### 为什么是"按 session"而不是"按天"

按天处理会把一个跨夜的 session 劈成两半,迟到的数据补不回来,而且没法续跑。
按 session + 水位线:增量、可续跑、迟到自动补、跑到一半断了下次接着跑。

### 为什么用"最后一条消息的时间戳"而不是文件 mtime

挂着的会话进程会自己写元数据,mtime 天天在动、内容却没变。按 mtime 判"有没有新内容",
结果是每小时重算一批其实没变的会话 —— 这种空转会在你不知情的时候一直烧额度。

### 修订语义

这是最容易做错的一块。**只有"取代"才动旧记忆**:

| 情况 | 旧记忆 |
|---|---|
| 同一件事有了更准确/更新的说法 | 标 `已修正`,从快照里消失 |
| 他明确改了主意、与旧条相反 | 标 `已推翻` |
| 旧条是线头,这次明确完成/取消了 | 标 `已收口` |
| **补充、延伸、相关、再次印证** | **不动,保持有效** |

最后一行是血的教训:早期版本把"补充"也当成取代,一次就误关了一大批还有效的记忆。
提示词里现在把这四种情况逐条写死,并且明说"填了就会从快照消失,所以宁缺毋滥"。

---

## 配置说明

配置在 `~/.compound-memory/config.yaml`(装的时候从 `config.example.yaml` 复制过去)。

| 键 | 默认 | 说明 |
|---|---|---|
| `user_name` | 安装时问你 | 记忆是关于谁的;提示词里的 `{user_name}` |
| `language` | `zh` | `zh` / `en`,决定提炼提示词与快照的语言 |
| `model` | `claude-opus-5` | 后台提炼用的模型 |
| `effort` | `high` | 思考深度(仅 `claude-cli` 后端) |
| `llm.backend` | `claude-cli` | `claude-cli`(用本机已登录的 claude)或 `openai`(任何兼容接口) |
| `llm.claude_flags` | 见示例 | 精简出口的 flag;改坏了背景开销会翻几倍 |
| `sink` | `local` | 共享层:`local` / `github` / `feishu`(后两种配好后跑一次 `cm sink-init`) |
| `nightly_limit` | `20` | 每次运行最多处理几个 session |
| `window_days` | `7` | 只看最近多少天有新对话的 session |
| `max_candidates` | `8` | 每个 session 最多提炼几条 |
| `text_budget` | `14000` | 每个 session 喂给模型的字数上限(头 40% + 尾 60%) |
| `snapshot_max_chars` | `3200` | 快照正文硬上限,超了自动压缩 |
| `cron` | `30 4 * * *` | 每晚跑的时间 |
| `baseline_file` | 空 | 指一个本机规则文件,原样抄进快照最后一节,不经模型改写 |
| `hosts.<名字>.enabled` | `auto` | `auto` = 装了就用 |
| `hosts.<名字>.inject` | `true` | 要不要给这个 harness 装开局注入 |

提示词在 `prompts/` 下,是纯文本文件 —— **这是最该你自己调的东西**。
想改又想保留原版,把文件复制到 `~/.compound-memory/prompts/`,那边优先。

---

## 常见问题

**装完什么都没有?**
`cm doctor` 看一眼。最常见的是最近 7 天没有够长的对话(少于 2 轮的 session 直接跳过),
试 `cm distill --days 60 --limit 5`。

**怎么补历史?**
`cm distill --days 365 --limit 0`。按 `nightly_limit` 分几晚跑完也行,水位线记得住。

**一晚上要花多少?**
一个 session 一次调用,加一次快照生成。默认上限 20 个 session = 21 次调用。
`~/.compound-memory/usage.log` 一行一次,可以自己核。

**它会不会把我说过的话当成规则去执行?**
不会。记忆分四种性质,只有你**明确提出**的才标"要求"并带适用范围;模型的推断在快照里
单独一节、逐条标"推断"。硬底线不走模型 —— 用 `baseline_file` 指一个本机文件,原文照抄。

**注入的快照会不会又被当成我说的话,提炼回去?**
不会。注入的内容带 `compound-memory-snapshot` 标记,三个适配器都会滤掉;
dsh 那边还多一层(它自己标了 `source.kind: plugin`)。

**能多台机器共用吗?**
能。`sink: github` 指向一个**私有**仓库,每台机器都 clone 它;
提炼可以只在一台机器上跑,其余机器只读。原文不跨机搬运。
想让人也能随手翻(手机上看、手工改状态)就用 `sink: feishu`,
`cm sink-init` 一条命令把表建好并写回配置。

**能不用 Claude 吗?**
能。`llm.backend: openai` + `base_url` + `api_key_env`,任何 OpenAI 兼容接口。
只是默认值(Opus / high)是在对比实验里选出来的,换模型请自己验一遍覆盖率。

**卸载会留下什么?**
`cm uninstall` 摘掉三处注入和 cron,改动前的备份在 `~/.compound-memory/backups/`。
记忆默认留着;要一起删加 `--purge`。

---

## 隐私

- **原文不出机。** 会话文件只在本机读,不上传、不备份到共享层。
- **出机的东西逐条判定。** 每条记忆在生成时就要回答"别的机器上的 AI 需不需要它"
  和"含不含密钥 / 第三方私密细节 / 财务法律健康信息";拿不准就留本地。
- **密钥清洗做在导出那一步。** 不是事后拿检查表去抹 —— 事后抹是打地鼠。
- **本地全量、出去脱敏。** 本机 `observations.jsonl` 留全部,共享层只有 `share: true` 的。
- **随时可撤回。** 共享层是文件(或一张表),删掉就没了;本地记忆重跑原文可以重建。

---

## 许可

MIT。
