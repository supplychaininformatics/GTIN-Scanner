"""Register, list, and revoke handheld API devices (see sync_api/auth.py).

    python -m scripts.manage_devices add "Dock 3 handheld"
    python -m scripts.manage_devices list
    python -m scripts.manage_devices revoke <device_id>

`add` prints the bearer token exactly once. Only its SHA-256 is stored, so a
lost token cannot be recovered — revoke the device and add a new one.
"""

from __future__ import annotations

import argparse
import sys
import uuid

from core import store
from sync_api.auth import hash_token, new_token


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="command", required=True)
    add = sub.add_parser("add", help="register a device and print its token")
    add.add_argument("label", help="human-readable name, e.g. 'Dock 3 handheld'")
    sub.add_parser("list", help="show registered devices")
    revoke = sub.add_parser("revoke", help="cut a device off")
    revoke.add_argument("device_id")
    args = parser.parse_args(argv)

    if args.command == "add":
        device_id = uuid.uuid4().hex[:12]
        token = new_token()
        store.create_device(device_id, args.label.strip(), hash_token(token))
        print(f"device_id: {device_id}")
        print(f"token:     {token}")
        print("Store the token on the device now; it cannot be shown again.")
    elif args.command == "list":
        for d in store.list_devices():
            state = f"REVOKED {d['revoked_at']}" if d["revoked_at"] else "active"
            print(f"{d['device_id']}  {d['label']!r}  {state}  last_seen={d['last_seen_at']}")
    else:
        if store.revoke_device(args.device_id):
            print("Revoked. The API stops honouring the token within about a minute.")
        else:
            print("No active device with that id.", file=sys.stderr)
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
