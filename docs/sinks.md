# 共享层(sink)

共享层是"记忆离开本机之后放哪"。**原文永远不进共享层** —— 只有逐条判定过
"必要且适合共享"、并过了密钥模式清洗的记忆条目才会出机。

三种实现,配置里一行 `sink:` 切换。

---

## local(默认,零账号)

```yaml
sink: local
sinks:
  local:
    dir: ''          # 留空 = ~/.compound-memory/share
```

共享层就是本机一个目录:

```
share/
  snapshot.md          当前快照(开局注入读的就是它)
  memories.jsonl       share=true 的记忆条目
  snapshots/           历次快照,留档
  README.md
```

单机用户就用这个,什么都不用配。想跨机器:把这个目录放进任何同步盘
(iCloud / Dropbox / syncthing / NFS)即可。

---

## github(多台自己的机器)

```yaml
sink: github
sinks:
  github:
    repo_dir: ~/memory-share   # 已经 clone 好、能免密 push
    branch: main
    push: true
```

写的文件和 local 一样,写完 `git add -A && git commit && git push`。

**请用私有仓库。** 里面的内容是关于你本人的偏好、决定和未了事项。

典型用法:一台机器跑提炼(`cron` 开着),其余机器只读 —— 把它们的
`hosts.*.inject` 留着、`cron` 关掉,开局时 `cm snapshot` 会先 `git pull` 再读。

> 单写者是有意的设计:只有提炼进程写共享层,别的机器只读。多写者要合并、要解冲突,
> 在还只有你一个人用的时候是纯负担。

---

## feishu(飞书多维表格,人也要翻的时候)

```yaml
sink: feishu
sinks:
  feishu:
    cli: lark-cli
    base_token: 'xxxxxxxxxxxxxxxxxxxxxxxx'
    table_id: 'tblxxxxxxxxxxxx'
    snapshot_doc: ''      # 留空,第一次运行自动建一篇,然后把 token 填回这里
```

前置:装好 [lark-cli](https://github.com/larksuite) 并 `lark-cli auth login`。

好处是记忆一条一行,可以在手机上翻、可以手工改状态、可以按"性质/时效"筛选。
代价是多一个账号依赖。

### 建表

`cm sink-init` 会把字段定义打印出来。手工建也行,字段必须叫这些名字:

| 字段 | 类型 | 选项 |
|---|---|---|
| 内容 | 文本 | |
| 日期 | 日期 | |
| 性质 | 单选 | 要求 / 想法 / 推断 / 事实 |
| 类型 | 单选 | 事件·决定 / 关于本人 / 线头·承诺 / 模式·矛盾 / 纠正·重复解释 |
| 时效 | 单选 | 长期 / 短期 |
| 适用范围 | 文本 | |
| 有效期 | 文本 | |
| 出处 | 文本 | |
| 状态 | 单选 | 有效 / 已修正 / 已推翻 / 已收口 / 不确定 |
| 记忆ID | 文本 | |
| 修订自 | 文本 | |
| 批次 | 文本 | |

字段定义的机器可读版在 `cm/sinks/feishu_fields.json`。

---

## 自己写一个

继承 `cm.sinks.Sink`,实现四个方法:

```python
class MySink(Sink):
    name = 'mine'
    def publish_memories(self, rows):   # rows = 本地全量;自己挑 share=True 的发
        ...
    def publish_snapshot(self, text):   # 返回一个能给人看的位置
        ...
    def fetch_snapshot(self):           # 别的机器开局读它
        ...
    def fetch_memories(self):           # 别的机器 recall 读它
        ...
```

然后在 `cm/sinks/__init__.py` 的 `get()` 里加一个分支。
