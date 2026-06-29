from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class GeneratedFile:
    path: str
    content: str
    secret: bool = False
