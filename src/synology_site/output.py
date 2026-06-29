from __future__ import annotations

from rich.console import Console

console = Console()


def ok(message: str) -> None:
    console.print(f"[OK] {message}")


def warn(message: str) -> None:
    console.print(f"[WARN] {message}")


def error(message: str) -> None:
    console.print(f"[ERROR] {message}")


def next_step(message: str) -> None:
    console.print(f"[NEXT] {message}")
