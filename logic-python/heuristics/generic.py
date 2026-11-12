"""
GenericHeuristic: the Standard Proactive condition (docs/REVIEW.md D18, D19, D27).

Sends a neutral invitation drawn from the fixed, hand-written Standard pool (services/message_pools.py,
protocol appendix A.5). No language model, no memory, no name: every Standard participant receives
exactly the messages printed in the protocol. Always produces a message.
"""
from __future__ import annotations

from typing import Optional

from heuristics.base_heuristic import BaseHeuristic
from services import message_pools


class GenericHeuristic(BaseHeuristic):

    POOL = "standard"

    _pool_previous: Optional[dict] = None
    _pool_taken: bool = False

    def create_memory(self) -> None:
        """Nothing to do: memory is built by the shared pipeline and Standard does not use it."""

    def get_proactive_message(self) -> Optional[str]:
        self.used_fallback = False   # the pool IS the designed path of this condition
        self.memory_content = ""
        self.message_source = "pool"
        text, self._pool_previous = message_pools.take(self.mongodb_client, self.user_id, self.user, self.POOL)
        self._pool_taken = True
        return text

    def undo_selection(self) -> bool:
        """A failed send must not use up a pool message."""
        if not self._pool_taken:
            return False
        self._pool_taken = False
        return message_pools.restore(self.mongodb_client, self.user_id, self.POOL, self._pool_previous)
