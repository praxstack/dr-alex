# 04: Remove request flags as high-sensitivity authority

**What to build:** Keep compatibility request fields syntactically accepted where needed, but make them incapable of granting high-sensitivity recall or full-body access. Authorize before retrieval and before reading body bytes.

**Blocked by:** None (can start immediately in a separate agent-memory worktree).

**Status:** ready-for-agent

- [ ] `M1-A01` through `M1-A11` pass.
- [ ] General launches cannot use `include_sensitive`, requested client names, roots, tags, filters, or ceilings to gain high access.
- [ ] Existing approved Dr. Alex launch behavior and low/medium access remain unchanged.
- [ ] Metadata is parsed through the same no-follow descriptor before any body byte is read.
- [ ] Refusal logs contain no query, snippet, body, or private marker.
