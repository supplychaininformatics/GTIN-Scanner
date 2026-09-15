# ASVS Compliance Mapping — GTIN Barcode Scanner

Phase 3 deliverable. Maps every Phase 2 remediation commit to the specific
ASVS control it satisfies, notes what's only partially closed, and lists
what needs infra-level action rather than a code change. Companion to
[ASVS-AUDIT.md](ASVS-AUDIT.md) (Phase 1 findings) — read that first for the
full context behind each item below.

All commits referenced are on `main`, range `d04fc01..HEAD`. This doc was
updated a second time (commits `7989a5f`..`HEAD`, plus the lockfile) after
the user asked to close out everything left "not addressed" or "partially
fixed" from the first pass — those items are now folded into the tables
below rather than kept as a separate follow-up list.

## Summary: findings → status

| # | Finding | Status |
|---|---|---|
| 1 | Monitor board had no access control | **Fixed** — typed-email gate, shared with admin |
| 2 | Admin auth is typed-email, not verified identity | **Unchanged, by design** — needs an IT-provisioned identity provider; see "Needs infra action" |
| 3 | GTIN never validated before use | **Fixed** |
| 4 | Excel export vulnerable to formula injection | **Fixed** |
| 5 | No offline queue for scan writes | **Fixed, within the confirmed scope** — server↔Neon hop, including the resume-before-sync gap; handheld WiFi dead zones remain a separate, larger problem (see below) |
| 6 | Streamlit's default error page can leak stack traces | **Fixed** (`7989a5f`) |
| 7 | GUDID URL built by raw string interpolation | **Fixed** |
| 8 | Local Parquet cache unencrypted, no hard expiry | **Fixed** (and threat model corrected — see ASVS-AUDIT.md) |
| 9 | Neon connection string plaintext on disk | **Mitigated** — keychain preferred; live credential migrated off `.streamlit/secrets.toml` on this machine; Streamlit-secrets fallback remains for deploy targets that need it |
| 10 | No egress allowlist | **Fixed at the application level** — network-level enforcement is infra's job |
| 11 | Dependency vulnerabilities | **Fixed** — 0 known vulns as of this commit |
| 12 | No timeout/retry/circuit breaker on Fabric | **Fixed** |
| 13 | Admin/audit-log files unencrypted on disk | **Fixed** (`781d04f`) |
| 14 | No dependency lockfile | **Fixed** (`requirements.lock.txt`) |

Only finding #2 remains genuinely open, and it needs an action outside this
repo (see "Needs infra action"). Everything else fixable in code is fixed.

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
  transient outage. This is scoped narrower than the original brief's
  "offline queuing" ask — see the dedicated section below for why (an
  architecture constraint, not a shortcut).
- **Offline-resume gap closed, and an unguarded crash fixed** (commit
  `a18c720`) — a session started while Neon was unreachable existed only in
  the write queue until it synced; a refresh before then made
  `store.get_session()` return `None` and look exactly like an unknown/
  purged session, dropping the picker back to the start gate even though
  nothing was actually lost. `core.session.resume_pending_session` now
  reconstructs it from the queue. Writing this surfaced a second, more
  serious bug in the same area: `app.py`'s force-end liveness check calls
  `store.get_session()` on *every rerun* once a session is active (i.e.
  every scan) and was completely unguarded — during a real Neon outage this
  would have crashed the page on the very first scan, before the write ever
  reached the offline-queue fallback the previous commit built. Now fails
  open (an unreachable Neon reads as "still active," never as a force-end).

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
- **Stack-trace leakage to the UI fixed** (`.streamlit/config.toml`, commit
  `7989a5f`) — `client.showErrorDetails` set to `"none"`, so an uncaught
  non-connectivity exception (a real bug, a Fabric/ODBC failure outside the
  retry path) shows a generic message in the browser instead of the full
  exception type/message/traceback. Full details still print to the server
  console. Overridable per local dev session via
  `STREAMLIT_CLIENT_SHOWERRORDETAILS=full` rather than editing the file, so
  the safe default always ships.

### V8 — Data Protection

- **Secrets prefer the OS keychain** (`core/secrets.py`, commit `3efc374`)
  — the Neon connection string and Fabric service-principal secret now try
  the OS keychain (via `keyring`) before falling back to
  `.streamlit/secrets.toml`. The live Neon credential on this machine has
  since been migrated: `scripts/store_secret.py` (run via a small one-off
  script that read the value straight out of the TOML file, so it never
  passed through a shell command) moved it into the keychain, the
  round-trip was verified, and the plaintext `url` line in
  `.streamlit/secrets.toml` was then stripped and replaced with a commented-
  out restore path. That file stays git-ignored throughout, so none of this
  touched version control.
- **Contract-data cache encrypted at rest, with a hard expiry ceiling**
  (`data/loader.py`, commit `1e4b9ae`) — Fernet-encrypted (same
  keychain-backed key pattern), and refuses to serve anything older than 7
  days even as a stale fallback, rather than accumulating indefinitely.
- **Offline write queue encrypted at rest, with integrity checks and
  auto-expiry** (`core/offline_queue.py`, commit `3c14562`) — SHA-256
  checksum per entry verified before replay; entries older than 24h are
  dropped.
- **Admin audit log / refresh metadata encrypted at rest** (`core/admin.py`,
  commit `781d04f`) — same Fernet/keychain pattern, switched from append-only
  JSON Lines to a single encrypted JSON array (capped at 2000 records) since
  whole-file encryption makes "append" a decrypt/re-encrypt operation, which
  is the right tradeoff for a low-volume admin log. This machine's real
  audit history (27 records) was migrated from the old plaintext files into
  the new encrypted ones and verified before the plaintext originals were
  deleted — both files are git-ignored, so nothing here touched version
  control either.

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
- **Dependency lockfile added** (`requirements.lock.txt`) — every package in
  the full dependency closure of `pip install -e ".[fabric,dev]"` pinned to
  an exact version, resolved in a clean venv (not frozen from the long-lived
  dev `.venv`, which had accumulated unrelated packages like `playwright`)
  and re-verified with `pip-audit`: 0 known vulnerabilities. `requirements.
  txt`/`pyproject.toml` stay the source of truth for version ranges; the
  lock file is what makes "what's actually installed" reproducible without
  needing shell access to a running environment, which is what this audit
  needed to do at the start to find the pandas version mismatch noted above.

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

**The resume-before-sync gap this used to have is now closed** (commit
`a18c720`): `start_session()` generates the session id locally and queues
the `create_session` write if Neon is unreachable at that moment; if the
browser refreshes or the tab is lost before that queued write lands, the
resume-by-URL flow now checks the offline queue
(`core.session.resume_pending_session`) and rehydrates from there instead
of finding nothing and looking like the session never existed.

**If you want the actual client-side WiFi dead-zone problem solved**, that
needs a different kind of client: a service worker, local storage, and
background sync — effectively a PWA rewrite of the handheld page. That's a
separate, much larger project, not a security-remediation commit — happy to
scope it separately if it's worth doing.

---

## Not addressed

Nothing fixable from inside this repo remains open. The four items
previously listed here — Streamlit's error-detail leak, the plaintext
admin audit log, the missing dependency lockfile, and `start_session`'s
resume-before-sync gap — are now covered above (`7989a5f`, `781d04f`,
`requirements.lock.txt`, `a18c720`). The only genuinely open item is
finding #2 (admin auth), which needs an IT-provisioned identity provider —
see below.

---

## Needs infra-level action (can't be fixed from inside this repo)

0. **Four GitHub repo-settings toggles**, none of which a PR can carry
   (Settings pages, not files) — added CI/Dependabot/CODEOWNERS/SECURITY.md
   in a PR to cover everything that *can* live in the repo; these four are
   what's left:
   - **Branch protection on `main`** — currently none at all (checked via
     `gh api repos/.../branches/main/protection` → 404 "Branch not
     protected"): no required reviews, no required status checks, nothing
     stopping a direct push or force-push. Once the CI workflow PR merges,
     turn on "Require a pull request before merging" + "Require status
     checks to pass" (select the new `Tests + lint + dependency audit`
     check) + "Require review from Code Owners".
   - **Dependabot alerts** — currently disabled (`vulnerability-alerts`
     endpoint returns 404 "disabled"). This is GitHub's passive "a CVE was
     published against something you use" notification, separate from the
     `dependabot.yml` version-update PRs added in this PR. Settings →
     Security → enable "Dependabot alerts".
   - **Dependabot security updates** — also disabled; auto-PRs a fix when
     an alert fires. Same Settings → Security page as above.
   - **Private vulnerability reporting** — disabled (checked via `gh api
     .../private-vulnerability-reporting` → `{"enabled": false}`).
     SECURITY.md (added in this PR) references this but it needs enabling
     at Settings → Security → Private vulnerability reporting before the
     "Report a vulnerability" button actually appears.
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

- `pytest tests/` — 96 tests, all passing as of `a18c720`, covering every
  security-relevant change in this document (egress allowlist, TLS
  enforcement, GTIN validation, export injection, offline queue encryption/
  integrity/expiry/resume, contract-cache encryption/expiry, admin-log
  encryption, circuit breakers, log sanitization).
- `pipx run pip-audit` — 0 known vulnerabilities as of this commit, checked
  two ways: against the long-lived dev `.venv`, and independently against a
  clean venv built from `requirements.lock.txt` alone (so the lock file
  itself is verified, not just assumed clean because the dev venv was).
  Re-run periodically, since this is a point-in-time result, not a standing
  guarantee.
- The app was smoke-tested (`streamlit run app.py`, mock data source) after
  every commit in this series and confirmed to still start and serve scans
  correctly.
