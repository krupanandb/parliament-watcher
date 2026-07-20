# Parliament Watch card generator prompt

Copy everything below the line into a Claude chat, attach (or paste)
`template.html` from this folder, then paste the Telegram alert(s) you
received. Claude returns the filled card HTML — save it as an .html file,
open it in a browser, and screenshot the card for Instagram/WhatsApp.

---

You are filling my "Parliament Watch" Instagram card template (1080x1350).
I will give you: (1) the HTML template, and (2) one or more Telegram alerts
from my parliament watcher, plus optionally extra facts I dictate.

Produce ONE completed card per update I choose, following these rules exactly:

1. **Never change** the footer block (`<!-- FOOTER - do not edit -->`), fonts,
   colors, or layout CSS. Only fill content slots.
2. **Top bar**: set `#session` (e.g. "Monsoon Session 2026") and `#dayno`
   ("DAY N" — my alerts state the session day number; if absent, ask me).
3. **Alert strip**: `#house` = LOK SABHA / RAJYA SABHA / BOTH HOUSES.
   `#status` — keep text and class in sync:
   `status-passed` → PASSED, `status-debated` → DEBATED,
   `status-introduced` → INTRODUCED. For non-bill events use the closest
   fit (e.g. adjournment → DEBATED with text "ADJOURNED"; keep the class).
4. **Headline `#headline`**: max ~9 words, one key phrase wrapped in `<em>`.
5. **Hero visual**: `#heronum` = the single biggest number in the story
   (votes, sections, crores, days). `#herolabel` = one line explaining it.
   Swap the SVG for a fitting icon (gavel/building/document/rupee).
   If the story truly has no headline number, delete the whole
   `.hero-visual` block.
6. **Stepper**: for bills, toggle `done` / `current` on the four steps
   (Introduced → Debated → Passed → Assent) to match the bill's real stage.
   For non-bill stories, replace the stepper with a second row of fact cards.
7. **Comparison bars**: only if the story has a real before/after; set the
   inline widths to the true ratio. Otherwise delete the `.compare` block.
8. **Fact cards** `#fact1..3`: one line each — What Changed / Who It Affects /
   What To Do. No paragraphs. For my CA audience, lean toward tax,
   compliance, and business impact.
9. **Source row**: `#src` = source (e.g. "Sansad / Lok Sabha"),
   `#srcdate` = "DD Mon YYYY | <Session name>".
10. **Also output**, after the HTML, the two captions from the template's
    comment block, filled in: the Instagram caption (hook, body with source
    and date, closing lines, max 5 hashtags) and the WhatsApp plain-text
    message. No em/en dashes in the WhatsApp text.
11. **Accuracy over drama**: use only facts from my alerts or what I supply;
    if a needed fact (vote count, section numbers, effective date) is not
    given, ask me instead of inventing it. Dates in "DD Mon YYYY".

If I paste several alerts, first list them as a numbered menu with a
one-line suggested angle each, and ask which one(s) to turn into cards.
