You are maintaining a long-term memory *about {user_name}* — for whatever AI serves {user_name} next, on any machine. Reading it at the start of a session should be enough to understand him without him explaining again. The better the model, the better it should be able to re-read the raw transcripts. So what you write are **dated, sourced observations** — not rules.

# Raw transcript of this session ({user_name}'s own turns, in order; the AI's replies are not shown)
source: {src} · title: {title} · time: {t0} → {t1} · user turns: {turns}
- {text}

# Existing related memories (this session may correct, overturn or close them)
{related}

# Task
First summarize the session in one line (topic: a short title; summary: ≤30 words on what was done and how far it got — the subject may drift mid-session, so cover the whole thing, not just the opening).

Also write a plain session log, 1–4 short lines each, empty if none: points (what was discussed) / next (follow-ups: who does what) / decisions (what was decided or concluded) / reflections (lessons). Only what actually happened in this session.

Then extract at most {maxn} memories **worth keeping long-term and useful for serving him later**. If there are none, return an empty list — never pad.

- nature: «{w_request}» = something he explicitly asked of the AI or of how work is done (state the scope; state an expiry if he gave one). A thought, a musing, a question, a one-off decision is NOT a request — that is «{w_idea}». «{w_inference}» = a preference or tendency you infer from his behavior; say "inferred from …" inside the content. «{w_fact}» = something that happened, was decided, or resulted.
- kind: {w_event} / {w_about} / {w_thread} (a promise he made, a promise made to him, an open question) / {w_pattern} (contradicts an existing memory, or keeps recurring) / {w_correction} (he corrected the AI, or re-explained something he had already explained — record these faithfully, they are the evidence of whether this system is getting better)
- horizon: {w_long} (preferences, goals, relationships, principles) / {w_short} (recent events, things in flight)
- content: descriptive; keep his own words and the situation. Do not translate it into "from now on you should…".
- revises: fill in an existing memory ID **only when this one replaces it**, and give old_status — «{w_revised}» = a more accurate/newer statement of the same thing; «{w_overturned}» = he changed his mind, this contradicts it; «{w_closed}» = the old one was an open thread and it is now finished or cancelled. **Adding to, extending, relating to, or re-confirming does NOT count as replacing** — in that case revises=null and the old memory stays live. Setting old_status makes the old memory disappear from the snapshot, so when in doubt, don't.
- share: should this leave this machine, into the cross-machine shared layer? Only true when it is both necessary (an AI on another machine needs it to serve him) and appropriate (no secrets, no private details about third parties, no financial/legal/health information he clearly would not want out). When unsure, false. Give a one-line share_reason.

Output JSON only — no explanation, no code fences:
{"topic":"…","summary":"…","log":{"points":["…"],"next":["…"],"decisions":["…"],"reflections":["…"]},"candidates":[{"nature":"{nature_opts}","kind":"{kind_opts}","horizon":"{horizon_opts}","content":"…","scope":"where it applies, or empty","expires":"expiry, or empty","quote":"his own words, ≤25 words","revises":"memory id or null","old_status":"{old_status_opts} or null","share":true,"share_reason":"…"}]}
