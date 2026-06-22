"""No known test secret may appear in any generated Phase 3 output."""

from pathlib import Path

from clearlane.phase3.common import redact
from clearlane.phase3.runner import run_phase3

# Known sample secrets that exist only in the developer's parent-dir Mappls probe
# files. They must NEVER appear in any committed/generated Phase 3 artifact.
KNOWN_SECRETS = [
    "01c4a1c9-24bc-4712-b8a3-62eb874b24ac",
    "96dHZVzsAusnIs3erx_kNfcBVzbFlJbzFwTQAArNjL4ZN2i0vpGczfvIfEvejO9ZRWAZrHJUPwTDxI5fqtL3eWNRZJofo9Db",
]


def test_redact_scrubs_credentials():
    payload = {
        "access_token": "01c4a1c9-24bc-4712-b8a3-62eb874b24ac",
        "client_id": "secretid",
        "url": "https://apis.mappls.com/advancedmaps/v1/REALKEY123/route_adv/driving/1,2;3,4",
        "nested": {"rest_key": "abc", "ok": "value"},
    }
    red = redact(payload)
    text = str(red)
    assert "01c4a1c9-24bc-4712-b8a3-62eb874b24ac" not in text
    assert "secretid" not in text
    assert "REALKEY123" not in text
    assert "abc" not in text
    assert "value" in text  # non-secret preserved


def test_generated_outputs_have_no_secret(root):
    run_phase3("replay", "configs/phase3.yaml", root=root)
    scan_dirs = [
        root / "artifacts" / "phase3",
        root / "data" / "processed",
        root / "data" / "live",
        root / "data" / "interim",
    ]
    offenders = []
    for base in scan_dirs:
        if not base.exists():
            continue
        for p in base.rglob("*"):
            if p.is_file() and p.suffix.lower() in {".json", ".csv", ".geojson", ".txt", ".parquet"}:
                try:
                    data = p.read_bytes()
                except Exception:
                    continue
                for secret in KNOWN_SECRETS:
                    if secret.encode() in data:
                        offenders.append(str(p))
    assert offenders == [], f"secret leaked into: {offenders}"
