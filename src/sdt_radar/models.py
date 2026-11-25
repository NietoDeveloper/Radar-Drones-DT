"""Domain and wire models.

Wire/API models are pydantic (strict validation at the edge). Hot-path structures used by the tracker
are plain dataclasses holding numpy arrays.
"""

from __future__ import annotations

    tentative = "tentative"
    confirmed = "confirmed"
    coasting = "coasting"
    lost = "lost"
