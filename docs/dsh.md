# DeepSeek Harness(dsh)的会话格式

公开文档没写会话落在哪、长什么样。下面是在装好的 dsh 上实测出来的结果,
`cm/sources/dsh.py` 就是按这份写的。格式将来要是变了,用第 5 节的方法自己复查。

## 1. 会话文件在哪

```
~/.dsh/sessions/<工作区槽>/session-<uuid>/session.jsonl.zstd       # 旧版(version: 0)
~/.dsh/sessions/<工作区槽>/session-<uuid>/session.v3.jsonl.zstd    # 新版(version: 3)
~/.dsh/sessions/<工作区槽>/session-<uuid>/session.lock
```

- `<工作区槽>` 是工作区路径压平后的名字,例如 `--home-you-work-myproject-WorkSpace--`。
- **同一个目录里可能同时存在两代文件**。一个 session 只认版本最高的那份,否则会重复计数。
- 文件是 **zstd 压缩的 JSONL**。解压优先级:Python 3.14 的 `compression.zstd` →
  `zstandard` 模块 → 系统 `zstd -dc` 命令。
- 旁边还有 `~/.dsh/storages/session_projcache/sessions/<session-id>.json`,存着标题、
  turn 数、token 用量等投影缓存。它是缓存不是事实来源,本项目不读它。

## 2. 事件长什么样

第一行是会话头:

```json
{"type":"session","version":3,"id":"session-<uuid>","createdAt":1700000000000,
 "cwd":"/home/you/project","agentPreset":"standard"}
```

之后每行一个事件,常见类型:`permission/preset`、`sandbox/mode`、`turn/start`、
`step/start`、`system/message`、`assistant/message`、`tool/call`、`tool/result`、
`user/message`、`agent/inbox/spliced`、`session/title`。

时间戳是 **epoch 毫秒**,在事件的 `time` 字段上(不是 ISO 字符串)。

## 3. 三个会数错的坑

**坑一:`agent/inbox/spliced` 里也有用户消息。**
它是收件箱的搬运记录:同一条消息先被 `inserted` 进去、再被 `removedCount` 拿走,
一条消息会出现两次。**只认 `type == "user/message"`。**

**坑二:`user/message` 不都是人说的。** 实测 `data.source.kind` 有四种取值:

| source.kind | 是什么 |
|---|---|
| `user` | 人真正敲进去的 |
| `plugin` | 插件注入的上下文 —— **包括本项目自己注入的快照** |
| `agent-instructions` | AGENTS.md / CLAUDE.md 被读进去的内容 |
| `skill-catalog` | skill 目录 |

只取 `kind == "user"`。这一条不是洁癖:漏掉它,我们注入的快照会被当成"他说过的话"
再提炼一遍,记忆就开始自我循环。

**坑三:标题有两条。** `type == "session/title"` 会出现两次,
`data.source.kind == "fallback"` 那条是把首句硬截断(形如"帮我把这个函数改成异步的,顺"),
`kind == "provider"` 那条才是模型起的标题(形如"函数改异步")。取 provider 的。

## 4. 开局注入:AGENTS.md 已验证,插件桥没观察到触发

### 走得通的那条:`~/.dsh/AGENTS.md`

dsh 每个 session 都会把 `~/.dsh/AGENTS.md` 作为 `agent-instructions` 注入进去 ——
这一点在会话日志里看得到:

```json
{"type":"user/message","data":{"source":{"kind":"agent-instructions"},
 "content":[{"type":"text","text":"<system-reminder>\nThe following workspace instructions...
 Instructions from: ~/.dsh/AGENTS.md ..."}]}}
```

所以 `cm install` 会往那里写一段带标记的说明,告诉模型开局先跑 `cm snapshot`。
实测有效:装完之后问一句"你收到的指令里出现过 compound-memory 吗",回答 YES。

代价是它靠模型自觉去跑命令,不如把快照正文直接塞进上下文可靠。

### 更好但目前没通的那条:`dsh-hooks-claude-code` 插件

dsh 有一个 `@deepseek-ai/dsh-hooks-claude-code` 插件,能直接跑 Claude Code 格式的
hooks 配置,`SessionStart` 对应它的 `agent/session-start` 扩展点,钩子 stdout 会被
`agent.inject()` 喂进这个 session。理论上这是最干净的路,不用模型自己动手。

`cm install` 会把它挂进**每个** profile 的 `cordis.patch.yml`:

```yaml
- insert:
    - id: compound-memory
      name: '@deepseek-ai/dsh-hooks-claude-code'
      config:
        configPath: /home/you/.compound-memory/dsh-hooks.json
```

`dsh-hooks.json` 是一份 Claude Code 形状的配置:

```json
{"hooks":{"SessionStart":[{"hooks":[{"type":"command","command":"/path/to/cm snapshot","timeout":60}]}]}}
```

**但在撰写时的版本上实测没有触发。** 做过的排查:

| 查了什么 | 结果 |
|---|---|
| patch 有没有被合成进 profile 树 | ✅ `dsh --profile web --dump-config` 里能看到这一行 |
| 插件模块能不能解析到 | ✅ `require.resolve('@deepseek-ai/dsh-hooks-claude-code')` 通 |
| profile 里有没有插件声明的依赖服务(`shell` / `sessionProjections`) | ✅ 两个都在 |
| 挂上之后 dsh 能不能正常启动 | ✅ web 与 headless 都正常 |
| 钩子进程到底跑没跑 | ❌ 把 command 换成 `touch <文件>`,跑完文件不存在 |
| 会话日志里有没有 `hook/invoked` / `hook/result` | ❌ 一条都没有 |
| 把 `configPath` 指到不存在的文件(该 warn) | 没有任何输出 —— 启动期的 logger 没接控制台,看不出是"没 apply"还是"warn 被吞了" |

两个已知的可疑点,留给后续:

- 插件源码里自己写着 `// TODO(session-start-gating): add a startup gate before promising
  first-turn delivery.` —— SessionStart 是 detached 执行的,**一次性任务可能在钩子返回前就发完了第一个请求**。
  但这解释不了"钩子进程根本没跑"。
- Cordis 的激活是服务可用性驱动的,插件声明了 `inject = ['shell', 'sessionProjections']`;
  服务看着都在,但激活顺序没验证过。

结论:**插件那条路留着不删**(它不会造成任何损害,dsh 哪天通了就自动生效),
同时一定要有 AGENTS.md 那条兜底。不想要插件那部分:`hosts.dsh.plugin_hook: false`。

还有两条要知道的限制(来自插件自己的文档):

- 配置**只在进程启动时读一次**,改完要重启 dsh。
- payload 里的 `transcript_path` 恒为空字符串 —— 会话日志是 zstd 压缩的,官方明确不打算
  给钩子脚本读。所以"读原文"只能自己解压,不能靠钩子拿路径。
- profile 的 `cordis.yml` 是生成物,**不要改它**;用户层改动一律写 `cordis.patch.yml`。

## 5. 怎么自己验证

```bash
# 看一个 session 的原始事件
zstd -dc ~/.dsh/sessions/*/session-*/session.v3.jsonl.zstd | head -5

# 数一数各种 source.kind
zstd -dc ~/.dsh/sessions/*/session-*/session*.jsonl.zstd | python3 -c "
import sys,json,collections
c=collections.Counter()
for l in sys.stdin:
    try: o=json.loads(l)
    except: continue
    if o.get('type')=='user/message':
        c[((o.get('data') or {}).get('source') or {}).get('kind')]+=1
print(c)"

# 本项目认出来的结果
cm sessions | grep dsh
```
