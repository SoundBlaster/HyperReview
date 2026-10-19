"""Versioned, packaged review guidance shared by all model providers."""

from hashlib import sha256
from importlib.resources import files


VERSION = "hyperreview-review-profile.v1"


def content():
    """Load the trusted reviewer profile from this installed package."""
    return files(__package__).joinpath("reviewer_profile.md").read_text(encoding="utf-8")


def identity():
    """Return the version and digest that bind requests and receipts to guidance."""
    return {"version": VERSION, "sha256": sha256(content().encode("utf-8")).hexdigest()}
