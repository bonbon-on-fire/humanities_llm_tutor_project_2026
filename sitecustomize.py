"""
Project-wide Python startup customizations.

We keep this narrowly-scoped: suppress a known third-party warning that is
noisy under Python 3.14+ and not actionable at runtime for this project.
"""

from __future__ import annotations

import warnings


warnings.filterwarnings(
    "ignore",
    message=r"Core Pydantic V1 functionality isn't compatible with Python 3\.14 or greater\.",
    category=UserWarning,
)

