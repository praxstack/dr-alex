"""Deterministic safety shell for Dr. Alex Morgan.

Nothing in this package calls an LLM. The crisis classifier (`triage`) and the
crisis card (`crisis_card`) are pure Python so they cannot be prompt-injected or
talked out of firing. This is the trust path: it runs *before* any model call.
"""

from safety.triage import Tier, triage
from safety import crisis_card

__all__ = ["Tier", "triage", "crisis_card"]
