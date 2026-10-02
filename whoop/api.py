"""Minimal WHOOP Developer API client (OAuth2 + v2 endpoints), stdlib only."""

import json
import secrets
import time
import urllib.error
import urllib.parse
import urllib.request

BASE = "https://api.prod.whoop.com"
AUTH_URL = f"{BASE}/oauth/oauth2/auth"
TOKEN_URL = f"{BASE}/oauth/oauth2/token"
API = f"{BASE}/developer"

SCOPES = [
    "offline",
    "read:recovery",
    "read:cycles",
    "read:workout",
    "read:sleep",
    "read:profile",
    "read:body_measurement",
]


# WHOOP's edge firewall rejects the default "Python-urllib" user agent with HTTP 403.
USER_AGENT = "whoop-coach/1.0 (+https://github.com/no6hp/WHOOP)"


class WhoopError(RuntimeError):
    pass


def _error_detail(e: urllib.error.HTTPError) -> str:
    """Short, token-free description of an error response."""
    try:
        body = json.loads(e.read())
        parts = [str(body.get(k)) for k in ("error", "error_description") if body.get(k)]
        return f" ({': '.join(parts)})" if parts else ""
    except Exception:
        return ""


def authorization_url(client_id: str, redirect_uri: str) -> str:
    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": " ".join(SCOPES),
        # WHOOP requires a state of at least 8 characters.
        "state": secrets.token_hex(8),
    }
    return f"{AUTH_URL}?{urllib.parse.urlencode(params)}"


def _post_form(url: str, data: dict) -> dict:
    body = urllib.parse.urlencode(data).encode()
    req = urllib.request.Request(
        url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
                 "User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.load(resp)
    except urllib.error.HTTPError as e:
        # Error responses carry no tokens; only the OAuth error fields are shown.
        raise WhoopError(f"Token request failed: HTTP {e.code}{_error_detail(e)}") from None


def _with_expiry(tok: dict, previous: dict | None = None) -> dict:
    out = {
        "access_token": tok["access_token"],
        # WHOOP rotates refresh tokens; fall back to the old one if none is returned.
        "refresh_token": tok.get("refresh_token") or (previous or {}).get("refresh_token"),
        "expires_at": int(time.time()) + int(tok.get("expires_in", 3600)) - 60,
    }
    if not out["refresh_token"]:
        raise WhoopError("No refresh token received - was the 'offline' scope granted?")
    return out


def exchange_code(client_id: str, client_secret: str, redirect_uri: str, code: str) -> dict:
    tok = _post_form(TOKEN_URL, {
        "grant_type": "authorization_code",
        "code": code,
        "client_id": client_id,
        "client_secret": client_secret,
        "redirect_uri": redirect_uri,
    })
    return _with_expiry(tok)


def refresh(client_id: str, client_secret: str, tokens: dict) -> dict:
    tok = _post_form(TOKEN_URL, {
        "grant_type": "refresh_token",
        "refresh_token": tokens["refresh_token"],
        "client_id": client_id,
        "client_secret": client_secret,
        "scope": "offline",
    })
    return _with_expiry(tok, tokens)


class Client:
    def __init__(self, access_token: str):
        self.access_token = access_token

    def get(self, path: str, params: dict | None = None) -> dict:
        url = f"{API}{path}"
        if params:
            url += "?" + urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        req = urllib.request.Request(
            url, headers={"Authorization": f"Bearer {self.access_token}", "Accept": "application/json",
                          "User-Agent": USER_AGENT}
        )
        for attempt in range(5):
            try:
                with urllib.request.urlopen(req, timeout=30) as resp:
                    return json.load(resp)
            except urllib.error.HTTPError as e:
                if e.code == 429 or e.code >= 500:
                    time.sleep(2 ** attempt)
                    continue
                raise WhoopError(f"GET {path} failed: HTTP {e.code}") from None
        raise WhoopError(f"GET {path} failed after retries")

    def collection(self, path: str, start: str | None = None, end: str | None = None) -> list[dict]:
        """Fetch all pages of a paginated collection endpoint."""
        records, next_token = [], None
        while True:
            page = self.get(path, {"limit": 25, "start": start, "end": end, "nextToken": next_token})
            records.extend(page.get("records", []))
            next_token = page.get("next_token")
            if not next_token:
                return records

    def profile(self) -> dict:
        return self.get("/v2/user/profile/basic")

    def body(self) -> dict:
        return self.get("/v2/user/measurement/body")


COLLECTIONS = {
    "cycles": "/v2/cycle",
    "recoveries": "/v2/recovery",
    "sleeps": "/v2/activity/sleep",
    "workouts": "/v2/activity/workout",
}
