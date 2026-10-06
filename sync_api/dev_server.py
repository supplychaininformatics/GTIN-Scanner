"""
DEV ONLY — runs the sync service against mock data and an in-memory store,
with one fixed token, so client work (the Android app) can be developed and
tested without Neon, the lakehouse, or a registered device.

    DATA_SOURCE=mock python -m sync_api.dev_server        # 127.0.0.1:8080
    token: dev-token  (override with DEV_SYNC_TOKEN)

Binds to loopback only, and refuses to start unless DATA_SOURCE=mock so it can
never be pointed at the real lakehouse by accident.
"""

from __future__ import annotations

import os
import sys

import uvicorn

from sync_api.app import create_app
from sync_api.auth import TokenVerifier, hash_token
from sync_api.memory_store import InMemoryStore
from sync_api.reference import ReferenceData


def build_app():
    from data import load_contract_data  # noqa: PLC0415

    token = os.environ.get("DEV_SYNC_TOKEN", "dev-token")
    store = InMemoryStore({hash_token(token): {"device_id": "dev-device", "label": "dev"}})
    return create_app(
        store=store,
        reference=ReferenceData(load_contract_data),
        verifier=TokenVerifier(store.device_for_token_hash),
    )


def main() -> int:
    if os.environ.get("DATA_SOURCE", "mock") != "mock":
        print("dev_server only runs with DATA_SOURCE=mock.", file=sys.stderr)
        return 1
    os.environ["DATA_SOURCE"] = "mock"
    port = int(os.environ.get("DEV_SYNC_PORT", "8080"))
    uvicorn.run(build_app(), host="127.0.0.1", port=port, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
