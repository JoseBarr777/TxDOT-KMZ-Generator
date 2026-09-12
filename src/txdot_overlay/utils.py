"""Small shared helpers with no natural home in a single module."""
from __future__ import annotations

import re


def slugify(text: str) -> str:
    """Turn a district/county name into a filesystem- and URL-safe slug."""
    slug = text.strip().lower()
    slug = re.sub(r"[^a-z0-9]+", "_", slug)
    return slug.strip("_")
