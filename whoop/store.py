"""Encrypted JSON storage.

The repository is public, so tokens and health data are only ever written to
disk AES-256 encrypted (via the openssl CLI). The key comes from the
WHOOP_DATA_KEY environment variable (GitHub secret / Claude environment variable).
"""

import json
import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
# The encrypted files live on the separate `whoop-data` branch, checked out
# into this directory, so hourly syncs don't clutter `main`.
DATA_DIR = Path(os.environ.get("WHOOP_DATA_DIR", ROOT / "state"))
DATA_FILE = DATA_DIR / "whoop.json.enc"
TOKEN_FILE = DATA_DIR / "token.json.enc"

_OPENSSL = ["openssl", "enc", "-aes-256-cbc", "-pbkdf2", "-iter", "200000", "-pass", "env:WHOOP_DATA_KEY"]


def _require_key() -> None:
    if not os.environ.get("WHOOP_DATA_KEY"):
        raise SystemExit("WHOOP_DATA_KEY is not set - cannot read or write encrypted data.")


def load(path: Path, default=None):
    if not path.exists():
        return default
    _require_key()
    out = subprocess.run(_OPENSSL + ["-d", "-in", str(path)], capture_output=True, check=False)
    if out.returncode != 0:
        raise SystemExit(f"Could not decrypt {path.name} - wrong WHOOP_DATA_KEY?")
    return json.loads(out.stdout)


def save(path: Path, obj) -> None:
    _require_key()
    path.parent.mkdir(parents=True, exist_ok=True)
    plain = json.dumps(obj, sort_keys=True, separators=(",", ":")).encode()
    tmp = path.with_suffix(".tmp")
    subprocess.run(_OPENSSL + ["-salt", "-out", str(tmp)], input=plain, check=True)
    tmp.replace(path)
