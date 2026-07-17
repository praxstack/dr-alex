"""Dr. Alex Morgan — Phase 1 (warm, safe terminal therapy-support companion).

A Textual TUI over a deterministic safety shell (`safety`) and `claude -p`. Phase 1
keeps everything local and in-memory: no RAG, no memory writes, no Notion. The one
network call is the Claude CLI on Prax's own subscription.
"""

__version__ = "0.1.0"
