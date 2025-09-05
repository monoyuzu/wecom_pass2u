# pass2u_api.py
from pathlib import Path
from dotenv import load_dotenv
import os, requests
from urllib.parse import quote

BASE_DIR = Path(__file__).resolve().parent
load_dotenv(dotenv_path=BASE_DIR/".env")

class Pass2UError(Exception): ...

def _auth_headers():
    api_key = os.getenv("PASS2U_API_KEY", "")
    if not api_key:
        raise Pass2UError("PASS2U_API_KEY not set")
    hdr = os.getenv("PASS2U_AUTH_HEADER", "Authorization")
    scheme = os.getenv("PASS2U_AUTH_SCHEME", "Bearer")
    return {hdr: f"{scheme} {api_key}", "Content-Type": "application/json", "Accept": "application/json"}

def create_pass2u_link(external_userid: str, extras: dict | None = None) -> str:
    base = os.getenv("PASS2U_BASE", "https://api.pass2u.net").rstrip("/")
    model_id = os.getenv("PASS2U_MODEL_ID")
    if not model_id:
        raise Pass2UError("PASS2U_MODEL_ID not set")
    utm = quote(os.getenv("PASS2U_UTM_SOURCE", "wecom"))
    url = f"{base}/v2/models/{model_id}/passes?utm_source={utm}"

    payload = {
        "fields": [
            {"key": "externalId", "value": external_userid}
        ],
        "barcode": {"message": external_userid, "altText": external_userid},
        "metadata": extras or {}
    }

    r = requests.post(url, json=payload, headers=_auth_headers(), timeout=15)
    if r.status_code >= 400:
        raise Pass2UError(f"pass2u create failed {r.status_code}: {r.text}")
    data = r.json()
    for k in ("link", "url", "downloadUrl", "passUrl"):
        if isinstance(data, dict) and data.get(k):
            return data[k]
    pid = data.get("passId") if isinstance(data, dict) else None
    return f"{base}/v2/passes/{pid}/download" if pid else None