你在为 {user_name} 维护一份"关于他本人"的长期记忆。读者是将来任何机器上服务 {user_name} 的 AI:开局读这份记忆就该懂他,不必他再解释。所以你写的是**带日期、带出处的观察**,不是规则。

# 这是一场会议的转写(多人发言,一行一句「说话人: 内容」)
会议:{title} · 时间:{t0} → {t1} · 发言 {turns} 句
{user_name} 在转写里可能用别的名字出现:{aliases}。先判断哪位说话人是他;判断不了就只记会议事实,不要把别人的话安到他头上。
- {text}

# 已有的相关记忆(可能需要被这场会议修正、推翻、收口)
{related}

# 任务
先用一句话概括这场会议(topic 8–16 字,summary ≤45 字:谈了什么、谈到什么程度)。
再写会议纪要 log,四项各 1–4 条短句、没有就留空:points 讨论要点 / next 后续动作(谁、做什么)/ decisions 共识、决定、分歧 / reflections 值得记住的判断或教训。

然后提炼最多 {maxn} 条**对将来服务他有用**的记忆。会议里什么值得记由你判断:可能是他的要求和决定,也可能是双方的共识、分歧、承诺、对某人某事的共同判断、对方的关键信息。没有就输出空列表。每条:
- nature 性质:「{w_request}」只用于他本人明确提出的要求;别人提的要求写成「{w_fact}」。「{w_idea}」「{w_inference}」「{w_fact}」同一般规则,推断要写明"推断自…"。
- kind 类型:{w_event} / {w_about} / {w_thread}(双方谁许了什么、悬着什么)/ {w_pattern} / {w_correction}
- horizon 时效:{w_long} / {w_short}
- content 内容:描述性,写清是谁说的、在什么情境下;不要翻译成指令。
- revises / old_status:只在**取代**已有记忆时填(「{w_revised}」「{w_overturned}」「{w_closed}」);补充、延伸、印证都不算。
- share 共享:会议里有别人。涉及对方的私人信息(身份细节、联系方式、财务、健康、私下评价)一律 false;只有别的机器上的 AI 服务他确实需要、且不涉及对方隐私的才 true。拿不准 false。

只输出 JSON,不要解释、不要代码围栏:
{"topic":"…","summary":"…","log":{"points":["…"],"next":["…"],"decisions":["…"],"reflections":["…"]},"candidates":[{"nature":"{nature_opts}","kind":"{kind_opts}","horizon":"{horizon_opts}","content":"…","scope":"适用范围,或空","expires":"有效期,或空","quote":"原话片段,≤60字","revises":"记忆ID或null","old_status":"{old_status_opts}或null","share":false,"share_reason":"…"}]}
