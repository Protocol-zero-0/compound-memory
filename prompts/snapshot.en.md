You are maintaining a long-term memory *about {user_name}* — for whatever AI serves {user_name} next, on any machine.

Below are all the live shared memories (with nature/kind/horizon/date). Turn them into a "current snapshot" for an AI to read at the start of a session. Rules:
- At most {soft_limit} characters ({hard_limit} is the hard cap; over it, a machine compresses it). What doesn't fit is found by search — do not cram. One sentence each, no examples.
- Four fixed sections, as H2 headings:
  ## A Long-horizon  (subsections: Identity & background / Long-term goals and current main line / What he has explicitly asked for (one per line, with date and scope; only nature=«{w_request}») / Key people / Inferred tendencies (separate list, each marked «{w_inference}»))
  ## B Short-horizon  (subsections: Recent decisions and events / Open threads (list every live «{w_thread}» — they never expire by time) / Questions he is still wrestling with)
  ## C Patterns & contradictions  (include «{w_uncertain}» items, stated as uncertain)
  ## D Metric  (one line only: «{w_correction}» memories in this batch = {n_corr})
- Keep the date on every line. Never write an inference as a fact, or an idea as a request, or invent anything not in the memories.
- Previous snapshot (for wording stability only — it is not evidence; where memories contradict it, the memories win):
{prev}

# Memories
{mems}

Output the Markdown body only, starting at "## A Long-horizon".
