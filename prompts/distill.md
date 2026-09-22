你在为 {user_name} 维护一份"关于他本人"的长期记忆。读者是将来任何机器上服务 {user_name} 的 AI:开局读这份记忆就该懂他,不必他再解释;越用越懂;模型升级后能重新理解原文。所以你写的是**带日期、带出处的观察**,不是规则。

# 这个 session 的原文({user_name} 的发言,按时间顺序;AI 的回复没给,你只看得到他说了什么)
来源:{src} · 标题:{title} · 时间:{t0} → {t1} · 用户轮数:{turns}
- {text}

# 已有的相关记忆(可能需要被这个 session 修正、推翻、收口)
{related}

# 任务
先用一句话概括这个 session(topic 8–16 字的标题,summary ≤45 字说清做了什么、到什么程度;注意话题可能中途漂移,要覆盖全程而不只是开头)。

然后从这个 session 提炼最多 {maxn} 条**值得长期保留、对将来服务他有用**的记忆。没有就输出空列表——不要为了凑数写。每条:
- nature 性质:「{w_request}」= 他明确提出的、对 AI 或工作方式的要求(必须写清适用范围;有明确期限就写有效期)。表达过一个想法、设想、疑问、一次性决定 ≠ 要求,那是「{w_idea}」。「{w_inference}」= 你从他言行推断的偏好/倾向,内容里写明"推断自…"。「{w_fact}」= 发生了的事、做出的决定、结果。
- kind 类型:{w_event} / {w_about} / {w_thread}(他许出去的、别人许给他的、悬着的问题)/ {w_pattern}(和已有记忆矛盾、或重复出现)/ {w_correction}(他纠正了 AI,或重复解释了以前说过的事——这类要如实记,它是系统有没有变好的证据)
- horizon 时效:{w_long}(偏好、目标、关系、原则)/ {w_short}(近期事件、进行中的事)
- content 内容:描述性,尽量带他的原话和情境;不要翻译成"以后应该怎样"的指令。
- revises 修订自:只在这条**取代**上面某条已有记忆时填它的记忆 ID,并给 old_status——「{w_revised}」= 同一件事有了更准确/更新的说法;「{w_overturned}」= 他明确改了主意、与旧条相反;「{w_closed}」= 旧条是线头·承诺且这次明确完成/取消了。**补充、延伸、相关、再次印证都不算取代**,那种情况 revises=null,旧记忆保持有效。填了 old_status,旧记忆就会从快照里消失,所以宁缺毋滥。
- share 共享:这条要不要出机、放到跨机器共享层?必要(别的机器上的 AI 服务他需要它)且适合(不含密钥、不含第三方的私密细节、不含他明显不想外流的财务/法律/健康信息)才 true;拿不准 false。给一句 share_reason。

只输出 JSON,不要解释、不要代码围栏:
{"topic":"…","summary":"…","candidates":[{"nature":"{nature_opts}","kind":"{kind_opts}","horizon":"{horizon_opts}","content":"…","scope":"适用范围,或空","expires":"有效期,或空","quote":"原话片段,≤60字","revises":"记忆ID或null","old_status":"{old_status_opts}或null","share":true,"share_reason":"…"}]}
