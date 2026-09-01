from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping


PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRETS_DIR = PROJECT_ROOT / "config" / "secrets"
STATE_DIR = PROJECT_ROOT / "config" / "state"


def _plain(value: Any) -> Any:
    if hasattr(value, "to_dict"):
        return {key: _plain(item) for key, item in value.to_dict().items()}
    if isinstance(value, Mapping):
        return {key: _plain(item) for key, item in value.items()}
    if isinstance(value, list):
        return [_plain(item) for item in value]
    return value


def _write_text(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(str(value).strip() + "\n", encoding="utf-8")


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_plain(value), indent=2), encoding="utf-8")


def materialize_streamlit_secrets(secrets: Mapping[str, Any]) -> list[str]:
    """Create the ignored credential files expected by the existing sources."""
    written: list[str] = []
    json_files = {
        "google_service_account": SECRETS_DIR / "google_service_account.json",
        "google_oauth_client_secret": SECRETS_DIR / "google_oauth_client_secret.json",
        "youtube_oauth_token": STATE_DIR / "youtube_oauth_token.json",
        "libsyn_credentials": SECRETS_DIR / "libsyn_credentials.json",
    }
    text_files = {
        "hubspot_private_app_token": SECRETS_DIR / "hubspot_private_app_token.txt",
        "x_bearer_token": SECRETS_DIR / "x_bearer_token.txt",
        "app_store_private_key": SECRETS_DIR / "AuthKey_WVG978J68Z.p8",
    }
    for key, path in json_files.items():
        if key in secrets:
            _write_json(path, secrets[key])
            written.append(key)
    for key, path in text_files.items():
        if key in secrets:
            _write_text(path, secrets[key])
            written.append(key)

    if "meta" in secrets or "instagram" in secrets:
        lines: list[str] = []
        for section in ("meta", "instagram"):
            if section not in secrets:
                continue
            lines.append(f"[{section}]")
            for key, value in _plain(secrets[section]).items():
                escaped = str(value).replace('"', '\\"')
                lines.append(f'{key} = "{escaped}"')
            lines.append("")
        _write_text(SECRETS_DIR / "meta.toml", "\n".join(lines))
        written.append("meta / instagram")
    return written
