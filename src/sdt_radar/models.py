"""Domain and wire models.

Wire/API models are pydantic (strict validation at the edge). Hot-path structures used by the tracker
are plain dataclasses holding numpy arrays.
"""

from __future__ import annotations

    tentative = "tentative"
    confirmed = "confirmed"
    coasting = "coasting"
    lost = "lost"


    model_config = ConfigDict(extra="
    sensor_id: str = Field(min_length=1, max_length=64)
    t: float  # UNIX epoch s