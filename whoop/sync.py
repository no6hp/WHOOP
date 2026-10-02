"""Pull new WHOOP data and merge it into the encrypted local store."""

import os
import time
from datetime import datetime, timedelta, timezone

from . import api, store

BACKFILL_DAYS = 120   # first sync
OVERLAP_DAYS = 4      # re-fetch window so late scores (PENDING -> SCORED) get updated
KEEP_DAYS = 400


def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.000Z")


def _key(kind: str, rec: dict) -> str:
    # Recoveries have no id of their own; they belong to exactly one cycle.
    return str(rec["cycle_id"] if kind == "recoveries" else rec["id"])


def _start_of(kind: str, rec: dict) -> str:
    return rec.get("start") or rec.get("created_at") or ""


def _clean(value: str) -> str:
    # Pasted secrets often carry stray whitespace, line breaks or quotes.
    return value.strip().strip("\"'").strip()


def credentials() -> tuple[str, str]:
    try:
        return _clean(os.environ["WHOOP_CLIENT_ID"]), _clean(os.environ["WHOOP_CLIENT_SECRET"])
    except KeyError as e:
        raise SystemExit(f"Missing environment variable {e}") from None


def access_token() -> str:
    tokens = store.load(store.TOKEN_FILE)
    if not tokens:
        raise SystemExit("No WHOOP login stored yet - run the setup workflow first.")
    if tokens["expires_at"] <= time.time():
        tokens = api.refresh(*credentials(), tokens)
        # Persist immediately: the old refresh token is now invalid.
        store.save(store.TOKEN_FILE, tokens)
    return tokens["access_token"]


def sync(now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    db = store.load(store.DATA_FILE, default={}) or {}
    last = db.get("synced_at")
    since = (datetime.fromisoformat(last) - timedelta(days=OVERLAP_DAYS)) if last else now - timedelta(days=BACKFILL_DAYS)

    client = api.Client(access_token())
    changed = False
    counts = {}
    for kind, path in api.COLLECTIONS.items():
        bucket = db.setdefault(kind, {})
        records = client.collection(path, start=_iso(since), end=_iso(now))
        for rec in records:
            k = _key(kind, rec)
            if bucket.get(k) != rec:
                bucket[k] = rec
                changed = True
        counts[kind] = len(records)

    for name, fetch in (("profile", client.profile), ("body", client.body)):
        val = fetch()
        if db.get(name) != val:
            db[name] = val
            changed = True

    # Prune old history.
    cutoff = _iso(now - timedelta(days=KEEP_DAYS))
    for kind in api.COLLECTIONS:
        bucket = db.get(kind, {})
        for k in [k for k, r in bucket.items() if _start_of(kind, r) and _start_of(kind, r) < cutoff]:
            del bucket[k]
            changed = True

    if changed or not last:
        db["synced_at"] = now.isoformat()
        store.save(store.DATA_FILE, db)
    return {"changed": changed, "fetched": counts}
