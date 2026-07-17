# Dr. Alex — Claude-mobile degradation kit

This folder is a **recreation kit**, not code. It lets you stand up a lightweight
"Dr. Alex" **Project inside the native Claude mobile app** so there's a warm, safe voice to
reach when the Mac (the real Dr. Alex — `alexd` + the book RAG + the memory store) is
**asleep, off, or off-network**.

## What this is — and what it deliberately is NOT

This is a **graceful fallback tier**, the last rung of the ladder:

1. The Mac is awake → the full app (TUI or The Room over Tailscale): grounded, cited,
   remembers, mirrors to your record.
2. The Mac is asleep → this Claude-mobile Project: warm, safe, boundaried — but **degraded on
   purpose**.

It is **NOT a competing front door.** It must never feel like the "real" Dr. Alex, because it
can't be:

- **NO memory writes.** Nothing said here is saved to your canonical record, the memory store,
  Notion, or the state DB. It is a stateless conversation.
- **NO live citations.** It has no access to the book corpus, so it must **never fabricate a
  `[B#]` citation or a page number.** It speaks from general principles only and says so.
- **NO telemetry, no mood DB, no homework store, no Shreya packet.** None of that exists here.
- **Statically pinned crisis card.** The India crisis resources are pasted in as fixed text
  (`crisis-card.md`) so they work even with zero tools. The mobile Alex must read them out
  verbatim and never improvise a number.

## Reconcile on next sync

Anything important from a mobile conversation is **ephemeral until you bring it back**. When
the Mac is next awake, jot the gist into a normal session (or straight into the Active File)
so it lands in the real record. The persona is told to remind you of this gently at the end of
a heavy mobile conversation.

## How to set it up (one time, ~2 minutes)

1. In the Claude mobile app, create a new **Project** named `Dr. Alex`.
2. Paste the entire contents of [`persona/dr-alex.md`](persona/dr-alex.md) into the Project's
   **custom instructions**.
3. Paste [`crisis-card.md`](crisis-card.md) into the Project knowledge (or append it to the
   custom instructions) so the crisis resources are always in context.
4. That's it. Open the Project and talk. It's the same voice, holding the same boundaries —
   just without the memory, the books, or the record.

## Safety is unchanged

The one thing that does **not** degrade is safety. The persona keeps the same rule the Mac
enforces in code: if there's any sign of crisis, it stops coaching, shows the **pinned crisis
card verbatim**, and points you to Shreya and the 24×7 lines — it never tries to be the crisis
service itself.
