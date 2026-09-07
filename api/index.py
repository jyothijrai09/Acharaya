"""
Vercel serverless entry point.

Vercel's Python runtime looks for a WSGI callable named `app` in this module.
The real application lives in app.py at the repository root, so this file only
puts the root on the import path and re-exports it — keeping `python app.py`
working unchanged for local development.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402,F401  (re-exported for Vercel)
