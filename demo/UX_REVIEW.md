# Live demo — UX teardown (two passes)

**Reality check on the persona.** The reference prompt is a conversion-obsessed founder chasing
10k signups. This demo will be opened by **5–10 technical people** — recruiters and engineers
sizing up a portfolio. There is no trial, no paywall, nothing to "convert" to. So the ruthlessness
is redirected at the only conversions that exist here: **(1) understand what this is in 5 seconds,
(2) believe it's real, (3) click through to the code.** Growth-hacking tactics (urgency, upsell,
signup walls) would be nagware for this audience and are explicitly out.

Findings are the current demo (`demo/index.html`) before this pass, sorted by impact.

---

## Pass 1 — the ruthless designer

**CRITICAL**

- **The whole thing is a dead-end without knowing the data.** The input says "type your own
  question about the taxi data." *What* taxi data? A stranger has no idea what tables, columns, or
  values exist, so they can't write a single question. The product's core action is unusable on
  arrival.
- **The best moment is buried.** The killer proof — ask "Who is the highest-earning driver?" and
  watch the naive agent invent a driver while the careful one refuses — is hidden as dropdown
  option #5. That contrast *is* the demo; it should hit you immediately, not after you go digging.

**HIGH**

- **Empty columns on landing = zero value until you work for it.** Three grey cards saying "Press
  Run." A portfolio viewer skims; if the first paint is empty, half of them leave before clicking.
- **"Replay" as the default reads as "fake."** A skeptic lands, sees the default mode is *Replay*,
  and concludes the whole thing is canned. There's no immediate signal that it genuinely runs a
  model.
- **Columns fire all at once.** The tagline promises "watch it get smarter, one chapter at a time,"
  then `Promise.all` pops all three simultaneously. The progression — the actual story — is lost.
- **Insider jargon as column labels.** "think → act → observe, no guardrails" and "finds the right
  table out of 253" mean something to the author and nothing to a visitor. They can't tell what
  they're comparing or why one answer is better.

**NICE-TO-HAVE**

- Four controls (mode pills, dropdown, text box, button) crowd the top before any value is shown.
- The receipts (`grounded ✓`, tokens, cost) are a genuine trust signal but sit unexplained.

## Pass 2 — first-time user, clicking through

- *Lands.* "Data Agent — watch it get smarter." Okay… smarter at what? I see three empty boxes and
  a question dropdown. **I don't know what this database has, so I don't know what I'm allowed to
  ask.** (→ Critical #1.) I'd probably leave here.
- *Opens the dropdown.* Some questions about tips and zones. I pick one, hit Run. Three answers
  appear at once. They look similar. **I can't tell why there are three or which one is "right."**
  (→ jargon, simultaneous reveal.)
- *Sees `grounded ✓` and `1,829▸106 tok`.* No idea what these mean. I assume they're for someone
  smarter than me and ignore them. (→ no legend.)
- *Wants to see the trick.* I never find it — the driver question is just another dropdown line, so
  I never experience the one thing that would make me trust the "careful" version.
- *Wants the code.* The footer has a GitHub link, but no column tells me *which chapter* built it,
  so I can't jump from "this behavior" to "the code that does it." (→ no per-chapter link.)

---

## Fix list (what this pass implements)

**Critical**
1. **A compact "the data" strip** — the 3 tables, their key columns, and how they join — always
   visible, so anyone knows what they can ask. *(Pass1-C1, Pass2)*
2. **Clickable example questions**, including the driver-trap flagged as a trick, so the best
   contrast is one click (and the visitor never faces a blank prompt). *(Pass1-C2, Pass2)*
3. **Auto-run the trap on load (in free replay)** so the payoff — one agent invents a driver, the
   other refuses — is on screen in under a second, no click, no cost, no cold-start wait.

**High**
4. **Plain-language column headers** ("Just writes SQL — can be confidently wrong" / "Checks its own
   work, refuses the impossible" / "Finds the right tables when the schema is huge"), each linking
   to its chapter's code. *(jargon + no-code-link)*
5. **Sequential reveal** — columns answer left-to-right so you literally watch it improve. *(Pass1)*
6. **A one-line receipts legend** so `grounded`/tokens/cost read as rigor, not noise. *(Pass1/2)*
7. **A visible, honest "▶ Run it live (Cloud)"** path so replay never reads as the whole story.

**Nice-to-have (kept light)**
8. Controls tightened: examples carry most of the load, so the dropdown is gone and the text box +
   mode pills stay secondary.
9. Every column links to its chapter README on GitHub.

**Deliberately not done** (would overload 10 testers): more than 3 chapters, live mermaid rendering
in-page, any signup/upsell/urgency.
