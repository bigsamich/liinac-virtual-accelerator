"""Unit tests run against the perfect machine; imperfections are exercised
explicitly in tests/test_errors.py by passing error dicts directly."""
import os

os.environ.setdefault("PIP2VA_ERRORS", "0")
