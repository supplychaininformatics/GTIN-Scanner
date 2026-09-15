# ASVS Compliance Mapping — GTIN Barcode Scanner

Phase 3 deliverable. Maps every Phase 2 remediation commit to the specific
ASVS control it satisfies, notes what's only partially closed, and lists
what needs infra-level action rather than a code change. Companion to
[ASVS-AUDIT.md](ASVS-AUDIT.md) (Phase 1 findings) — read that first for the
full context behind each item below.

All commits referenced are on `main`, range `d04fc01..HEAD`.

## Summary: findings → status

| # | Finding | Status |
|---|---|---|
| 1 | Monitor board had no access control | **Fixed** — typed-email gate, shared with admin |
| 2 | Admin auth is typed-email, not verified identity | **Unchanged, by design** — see "Needs infra action" |
| 3 | GTIN never validated before use | **Fixed** |
| 4 | Excel export vulnerable to formula injection | **Fixed** |
| 5 | No offline queue for scan writes | **Partially fixed** — server↔Neon hop only; handheld WiFi dead zones remain out of scope (see below) |
| 6 | Streamlit's default error page can leak stack traces | **Not fixed in this pass** — see "Not addressed" |
| 7 | GUDID URL built by raw string interpolation | **Fixed** |
| 8 | Local Parquet cache unencrypted, no hard expiry | **Fixed** (and threat model corrected — see ASVS-AUDIT.md) |
| 9 | Neon connection string plaintext on disk | **Mitigated** — keychain preferred; Streamlit-secrets fallback remains |
| 10 | No egress allowlist | **Fixed at the application level** — network-level enforcement is infra's job |
| 11 | Dependency vulnerabilities | **Fixed** — 0 known vulns as of this commit |
| 12 | No timeout/retry/circuit breaker on Fabric | **Fixed** |
| 13 | Admin/audit-log files unencrypted on disk | **Not addressed** — see "Not addressed" |
| 14 | No dependency lockfile | **Not addressed** — see "Not addressed" |

---

## Fixed / mitigated, by ASVS chapter

### V1 — Architecture, Design and Threat Modeling

- **Egress allowlist** (`core/egress.py`, commit `fc5e25a`) — a single
  source of truth for the three hosts this app should ever contact (GUDID
  hardcoded, Fabric/Neon from config), enforced at every outbound call site
  before the request is made. Satisfies the *application-level* half of
  V1's secure-architecture expectation. **Does not** satisfy a true network
  segmentation control — see "Needs infra action" below.
- **Circuit breakers + bounded retry** on GUDID and Fabric
  (`core/circuit_breaker.py`, commit `fd5b835`) — poor warehouse-to-cloud
  connectivity degrades to a fast, predictable failure after 3 (GUDID) or 2
  (Fabric) consecutive connectivity failures, instead of every scan
  separately paying a full timeout. Addresses the "retry storm" and
  "hanging the app" requirements directly.
- **Offline write buffering** (`core/offline_queue.py`, commit `3c14562`) —
  hardens the Streamlit server's own connection to Neon against a
  transient outage. **This is a partial fix relative to your original
  brief** — see the dedicated section below.

### V4 — Access Control

- **Monitor board sign-in** (commit `3085c22`) — the board (all pickers'
  Sanford IDs + scan history, plus the Force End action) now requires the
  same typed-email allowlist check the admin page already used, sharing one
  session-state key so signing in once covers both pages.
- **Admin auth remains a typed-email allowlist**, not verified identity.
  This was already true before this audit and is explicitly documented as
  a known, accepted tradeoff in the existing code (`core/admin.py`'s module
  docstring) — every access attempt is audit-logged as the compensating
  control. Closing this fully needs a verified-identity provider (Microsoft
  Entra / `st.login`), which requires an app registration IT provisions —
  see "Needs infra action."

### V5 — Validation, Sanitization and Encoding

- **GTIN validation before use** (`core/lookup.py`, commit `dae723b`) — a
  scan that fails `normalize()`/check-digit validation now resolves locally
  as an invalid-barcode miss instead of being sent, unvalidated, to the
  GUDID API. The validation primitives (`engine/gtin.py`) already existed;
  they just weren't being consulted before the raw string left the process.
- **GUDID query encoding** (`api/goodid_client.py`, commit `fc5e25a`) —
  switched from raw f-string URL interpolation to `httpx`'s `params=`,
  which properly percent-encodes the scanned value.
- **Excel/CSV formula-injection neutralization** (`core/export.py`, commit
  `dae723b`) — every text cell in the exported workbook (scan payload,
  description, free-text Sanford ID/location) is checked for a leading
  `=`/`+`/`-`/`@`/tab/CR and prefixed with `'` if found. Verified against
  the raw XLSX XML, not just the higher-level pandas/openpyxl API — a
  string starting with `=` is written by openpyxl as an actual `<f>`
  formula element, confirmed empirically, not merely a CSV-reimport
  heuristic.

### V7 — Error Handling and Logging

- **Log sanitization** (`core/logsafe.py`, commit `51cd4fc`) — every log
  line that interpolates a scanned GTIN (validated or not) now strips
  control characters and caps length first, closing the log-injection path
  a crafted barcode could otherwise use.
- **Egress-point logging** (commit `51cd4fc`) — `core/store.py` now logs
  the Neon host (never the connection string/password) on pool open and on
  failure, matching what `api/goodid_client.py` and `data/loader.py`
  already logged for GUDID/Fabric. All three egress points now log
  endpoint + outcome + timestamp (via the shared log formatter), which is
  what your brief asked for IT's monitoring needs.
- **Stack-trace leakage to the UI (finding #6) is NOT fixed** — see "Not
  addressed" below. This is the one item from the original audit that
  didn't get a Phase 2 commit; flagging it explicitly rather than letting
  it look closed by omission.

### V8 — Data Protection

- **Secrets prefer the OS keychain** (`core/secrets.py`, commit `3efc374`)
  — the Neon connection string and Fabric service-principal secret now try
  the OS keychain (via `keyring`) before falling back to
  `.streamlit/secrets.toml`. `scripts/store_secret.py` is the one-time
  operator action to actually move a secret there; **this migration has
  not been run** — the real secret is still sitting in
  `.streamlit/secrets.toml` on this machine as of this commit. That's a
  five-minute manual step for whoever owns that credential, not something
  this pass did automatically (it touches a live credential store and
  seemed better left to an explicit choice).
- **Contract-data cache encrypted at rest, with a hard expiry ceiling**
  (`data/loader.py`, commit `1e4b9ae`) — Fernet-encrypted (same
  keychain-backed key pattern), and refuses to serve anything older than 7
  days even as a stale fallback, rather than accumulating indefinitely.
- **Offline write queue encrypted at rest, with integrity checks and
  auto-expiry** (`core/offline_queue.py`, commit `3c14562`) — SHA-256
  checksum per entry verified before replay; entries older than 24h are
  dropped.
- **Audit log / admin refresh-meta files remain plaintext on disk** —
  see "Not addressed."

### V9 — Communications

- **TLS enforcement confirmed and regression-tested** (commit `14e3efa`) —
  no `verify=False`/`CERT_NONE`/disabled-verification pattern exists in any
  of the three network-call modules, backed by a source-scanning test that
  fails the build if one is ever introduced. Fabric's
  `Encrypt=Yes;TrustServerCertificate=No` and Neon's `sslmode=require`
  enforcement (added in the egress-allowlist commit, `fc5e25a`) are both
  covered by dedicated tests.
- Fixed a **real circular-import bug** discovered while writing that test
  suite (also commit `14e3efa`) — unrelated to TLS itself, but would have
  broken `import api` in any context that touches it before `core` finishes
  loading.

### V10 — Malicious Code / Dependencies

- **All known-vulnerable dependencies updated** (commit `798eaf8`) —
  Pillow, cryptography, gitpython, starlette, pip. Re-ran `pip-audit`
  against the actual installed environment: 0 known vulnerabilities, down
  from 5 flagged packages / 69 advisories at the start of this audit.
- **No dependency lockfile** — see "Not addressed."

---

## Offline queue: what this actually covers (read before relying on it)

Your original brief treated "offline queuing/caching" as a core
requirement because the app is used in poor-signal parts of the warehouse.
Partway through remediation, tracing the actual architecture surfaced that
**this app is a Streamlit web app** — the handheld is a browser with a live
connection to a remote Streamlit server (deployed on Streamlit Cloud). A
WiFi dead zone breaks that connection entirely; no code running on the
server can buffer around a browser that can't reach it, because Streamlit
requires a live round trip for every single interaction. `PLAN.md` already
documented this as an accepted v1 limitation before this audit ("scanning
is online-only... No offline queue").

This was reviewed with you mid-remediation, and the agreed scope was:
**harden the Streamlit server's own connection to Neon**, which can blip
independently of the handheld's WiFi (cold start, a transient network
issue, a brief maintenance window). That's what `core/offline_queue.py`
does — it does not, and cannot, fix a handheld that can't reach the server
at all.

**Known residual gap even within that narrower scope**: `start_session()`
generates the session id locally and queues the `create_session` write if
Neon is unreachable at that moment. If the browser refreshes or the tab is
lost before that queued write actually lands, the resume-by-URL flow
(`app.py`'s `?sid=` gate) won't find a row to resume from — there's no
server-side record yet. This is a narrow window (only between session
start and the first successful sync) but it exists, and is called out in
`core/session.start_session`'s docstring.

**If you want the actual client-side WiFi dead-zone problem solved**, that
needs a different kind of client: a service worker, local storage, and
background sync — effectively a PWA rewrite of the handheld page. That's a
separate, much larger project, not a security-remediation commit — happy to
scope it separately if it's worth doing.

---

## Not addressed in this pass

These were in the Phase 1 audit but didn't get a Phase 2 commit. Not
forgotten — deliberately left for you to prioritize, since none of them
were on your original 8-item list and each has a real design decision
behind it:

1. **Streamlit's default error page can leak stack traces (finding #6,
   V7.4).** Fix is small — `.streamlit/config.toml`'s `[client]
   showErrorDetails` set to `"none"` or `"type"` — but changes what
   developers/admins see when something breaks in production too, which
   felt like a call you should make rather than one to make silently.
2. **Admin audit log and refresh-metadata files are plaintext on local
   disk** (`data/cache/admin_audit.log`, `refresh_meta.json`). Lower
   severity than the credential/cache findings — this is an audit trail,
   not a secret — but the same encryption pattern used for the write queue
   and contract cache could be extended here if you want it.
3. **No dependency lockfile** (finding #14). `requirements.txt`/
   `pyproject.toml` now have accurate version floors, but nothing pins
   exact versions for reproducibility. Adding `pip-compile` (pip-tools) or
   migrating to `uv` would close this and make future SCA runs auditable
   from the manifest alone rather than needing shell access to the running
   environment (as this audit did).
4. **`start_session`'s narrow resume-before-sync gap** described above.

---

## Needs infra-level action (can't be fixed from inside this repo)

1. **Network-level egress restriction.** `core/egress.py` is the
   application-side control; actually preventing this app's host/container
   from reaching anything besides GUDID, the Fabric endpoint, and Neon
   needs a firewall/NSG/proxy rule at the hosting layer (Streamlit Cloud's
   network config, or wherever this is actually deployed). Confirm with
   whoever manages that hosting whether an egress allowlist is even
   configurable there — Streamlit Community Cloud may not expose this.
2. **Verified identity for the admin/board pages** (finding #2, still
   open). Needs an OIDC app registration (Microsoft Entra is the natural
   choice given the `.org` email domains already in the allowlist) that
   only IT can provision, then a small code change to wire up `st.login`.
3. **Secrets vault decision.** This pass added OS-keychain support as a
   better-than-plaintext option for local/interactive use. If the
   organization has a real secrets manager (Azure Key Vault, etc.) that
   Streamlit Cloud's deployment can reach, that would be the appropriate
   final home for the Neon connection string and Fabric service-principal
   secret in production — the keychain path is aimed at whoever runs this
   locally, not the deployed instance.
4. **MDM / device policy for handhelds.** The original audit's "lost/
   stolen handheld" framing turned out to apply to less than initially
   thought (contract data and the write queue both live server-side, not
   on the device — see ASVS-AUDIT.md's correction). What *does* still live
   on the device is whatever the browser itself caches (page state, and
   the session's `?sid=` URL in browser history) — a lock-screen /
   auto-lock policy on the handhelds themselves is the relevant control
   here, and that's an MDM/device-policy decision, not a code fix.
5. **A true client-side offline mode**, if the handheld WiFi dead-zone
   problem is worth solving beyond what this pass covered — see the
   dedicated section above. This is a product/architecture decision
   (PWA rewrite) requiring its own scoping, not an infra ticket, but it's
   listed here because it's the one item that's neither "fixed in code"
   nor "a small infra config change."

---

## Verifying this yourself

- `pytest tests/` — 83 tests, all passing as of `798eaf8`, covering every
  security-relevant change in this document (egress allowlist, TLS
  enforcement, GTIN validation, export injection, offline queue encryption/
  integrity/expiry, contract-cache encryption/expiry, circuit breakers,
  log sanitization).
- `pipx run pip-audit` against `.venv` (or wherever this is deployed) — 0
  known vulnerabilities as of this commit; re-run periodically, since this
  is a point-in-time result, not a standing guarantee.
- The app was smoke-tested (`streamlit run app.py`, mock data source) after
  every commit in this series and confirmed to still start and serve scans
  correctly.
