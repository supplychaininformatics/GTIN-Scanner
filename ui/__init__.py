"""ui package — presentation layer only. No business logic lives here."""

from .theme import PALETTE, STATUS, inject_theme, scanner_runtime

__all__ = ["PALETTE", "STATUS", "inject_theme", "scanner_runtime"]
