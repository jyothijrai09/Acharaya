"""
Authentication and approval.

Sign-in is Google, via Supabase Auth. The browser completes the OAuth flow and
sends the resulting access token on every API call; this module turns that
token into an application user, and decides whether that user may proceed.

    signed out   -> no token, nothing but /api/config is reachable
    pending      -> row exists, an admin has not approved it yet
    approved     -> full use of their own charts
    admin        -> the above, plus every chart and the approval queue
    rejected     -> treated as pending-forever; no access

Why the token is verified against Supabase rather than decoded locally:
verifying the signature ourselves would mean holding the project's JWT secret
and tracking Supabase's key rotation. Asking Supabase who the token belongs to
costs one HTTPS round trip and cannot drift out of date. Results are cached
briefly so a burst of calls from one page load does not repeat it.

The admin list is an environment variable, not a database flag, so the first
admin exists before any row does — otherwise nobody could approve the first
user, including themselves.
"""

import json
import os
import time
import urllib.error
import urllib.request

SUPABASE_URL = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
SUPABASE_ANON_KEY = (os.environ.get("SUPABASE_ANON_KEY")
                     or os.environ.get("SUPABASE_PUBLISHABLE_KEY") or "")

# Comma-separated. Matching addresses are provisioned as admin on first
# sign-in and never need approving.
ADMIN_EMAILS = {
    e.strip().lower()
    for e in (os.environ.get("ADMIN_EMAILS") or "").split(",")
    if e.strip()
}

# Seconds to trust a verified token without asking Supabase again. Short
# enough that a revoked session stops working promptly, long enough that one
# page load does not make several identical round trips.
_CACHE_TTL = 60
_token_cache = {}


class AuthError(RuntimeError):
    """Raised with a message safe to show the person signing in."""

    def __init__(self, message, status=401):
        super().__init__(message)
        self.status = status


def is_configured():
    """Whether sign-in can work at all. False leaves the app open, which is
    the correct behaviour for a local single-user run with no Supabase."""
    return bool(SUPABASE_URL and SUPABASE_ANON_KEY)


def verify_token(token):
    """Return {'id', 'email'} for a Supabase access token, or raise AuthError."""
    if not token:
        raise AuthError("Not signed in.")
    if not is_configured():
        raise AuthError(
            "Sign-in is not configured on the server: SUPABASE_URL and "
            "SUPABASE_ANON_KEY are unset.", status=500)

    hit = _token_cache.get(token)
    if hit and hit[0] > time.time():
        return hit[1]

    request = urllib.request.Request(
        SUPABASE_URL + "/auth/v1/user",
        headers={"Authorization": "Bearer " + token,
                 "apikey": SUPABASE_ANON_KEY},
    )
    try:
        with urllib.request.urlopen(request, timeout=8) as response:
            data = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        if e.code in (401, 403):
            raise AuthError("Your session has expired. Sign in again.") from e
        raise AuthError("Could not verify your sign-in.", status=502) from e
    except Exception as e:
        raise AuthError("Could not reach the sign-in service.", status=502) from e

    uid, email = data.get("id"), (data.get("email") or "").lower()
    if not uid or not email:
        raise AuthError("That sign-in did not return an account.")

    user = {"id": uid, "email": email}
    _token_cache[token] = (time.time() + _CACHE_TTL, user)
    # The cache is unbounded otherwise, and one process can see many tokens.
    if len(_token_cache) > 512:
        now = time.time()
        for k, (expiry, _) in list(_token_cache.items()):
            if expiry <= now:
                _token_cache.pop(k, None)
    return user


def bearer_token(headers):
    """Pull the token out of an Authorization header, or None."""
    raw = headers.get("Authorization") or ""
    if raw.lower().startswith("bearer "):
        return raw[7:].strip()
    return None


def intended_status(email):
    """The status a newly seen account should be created with."""
    return "admin" if email.lower() in ADMIN_EMAILS else "pending"


def may_use_app(record):
    """Approved and admin accounts may use the app; nothing else may."""
    return bool(record) and record.get("status") in ("approved", "admin")


def is_admin(record):
    return bool(record) and record.get("status") == "admin"
