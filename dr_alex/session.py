"""Per-session state — currently the crisis-questioning discipline flags (G1).

A ``SessionState`` lives for the length of one conversation (one TUI run, or one
threaded one-shot sequence). It carries the single fact the safety-questioning
discipline needs to be *structural* rather than a prompt-hope: whether the one-time
safety check-in has already been offered, and whether Prax has declined it. The engine
reads this to inject the "already asked — do not re-ask" directive and to run the
deterministic re-ask backstop.
"""

from __future__ import annotations

from dataclasses import dataclass

from safety.triage import Tier


@dataclass
class SessionState:
    #: Has our reply already asked the direct safety question this session?
    safety_probe_asked: bool = False
    #: Has Prax already answered "no"/"stop" to it?
    safety_probe_declined: bool = False
    #: Last turn's tier, for recent-risk escalation (optional, mirrors the TUI).
    recent_risk: Tier | None = None

    @property
    def suppress_safety_probe(self) -> bool:
        """Once asked (or declined), the probe is capped for the rest of the session."""
        return self.safety_probe_asked or self.safety_probe_declined
