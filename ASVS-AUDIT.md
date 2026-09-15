# ASVS Security Audit — GTIN Barcode Scanner

Phase 1 findings doc. No code was changed to produce this — read-only review
of the codebase as of commit `d04fc01` (branch `main`, 2026-09-14).

Scope note on architecture: this app has two network-facing surfaces that
matter for this review — the internal Microsoft Fabric Lakehouse (ODBC/Azure AD,
[data/loader.py](data/loader.py)) and Neon Postgres (session/scan persistence,
[core/store.py](core/store.py)) are both **outbound to services outside the
warehouse's local network**, not just GUDID. IT flagged GUDID as "the one
internet-facing path," but Fabric and Neon are also internet-routed (Fabric
over the public Azure endpoint, Neon over its public Postgres endpoint) — they
just carry credentials/AAD auth where GUDID doesn't. Worth clarifying with IT
whether their threat model already accounts for this, since the egress
allowlist in Phase 2 needs to cover all three, not just GUDID.

## Severity key
**Critical** — exploitable without auth, or defeats a core security control.
**High** — exploitable by an insider/local attacker, or a real data-exposure path.
**Medium** — real gap but needs a specific precondition or has partial mitigation.
**Low** — hardening/defense-in-depth, not independently exploitable.
**Info** — note for the compliance record, no action strictly required.

## Summary table

| # | Finding | ASVS | Severity |
|---|---|---|---|
| 1 | Monitor board has no access control — anyone with the URL views all pickers' scan history and Sanford IDs, and can force-end any active session | V4 | **Critical** |
| 2 | Admin page auth is a typed, unverified email against an allowlist — not real authentication | V2, V4 | High |
| 3 | GTIN never validated (format/length/check-digit) before use — flows unsanitized into GUDID URL and Excel export | V5 | High |
| 4 | Excel export is vulnerable to CSV/formula injection (untrusted scan/Sanford ID/location text lands in cells unescaped) | V5 | High |
| 5 | No offline queue for scan writes — Postgres write is synchronous and unbuffered; a scan is lost, not queued, on connectivity loss | V1 | High |
| 6 | Streamlit's default error page can leak full stack traces to the handheld UI on any uncaught exception | V7 | Medium |
| 7 | GUDID URL built by raw string interpolation, not a proper query encoder | V5, V9 | Medium |
| 8 | Local Parquet contract-data cache is unencrypted at rest and never hard-expires | V8 | Medium |
| 9 | Neon Postgres connection string (with embedded password) stored in plaintext in `.streamlit/secrets.toml` | V8 | Medium |
| 10 | No egress allowlist / network policy — app can reach any host, not just Fabric/Neon/GUDID | V1 | Medium |
| 11 | Dependency vulnerabilities: `pillow`, `cryptography`, `gitpython`, `starlette`, `pip` | V10 | Medium |
| 12 | No timeout/retry/circuit-breaker on Fabric SQL query execution | V1 | Low |
| 13 | Admin/audit-log files stored unencrypted, world-readable-by-process on local disk | V8 | Low |
| 14 | No dependency lockfile — version ranges only, so what actually ships isn't pinned or reproducible | V10 | Low |

---

## 1. Network calls — TLS, timeouts, retries

### 1.1 GUDID (FDA AccessGUDID) — `api/goodid_client.py`
[api/goodid_client.py:51-108](api/goodid_client.py#L51-L108)

- **TLS**: `httpx.Client()` default — certificate validation is on, no
  `verify=False` anywhere in the codebase (confirmed by repo-wide grep). Good.
- **Timeout**: single `10.0s` timeout applied uniformly to connect/read/write/pool
  ([api/goodid_client.py:29](api/goodid_client.py#L29)). Reasonable, but a single
  10s stall is a real UX hit on warehouse Wi-Fi, and there's no distinction
  between "can't even open a TCP connection" (fail fast) and "connection is
  open but slow" (worth waiting longer for).
- **Retries**: none. `httpx.Client` does no retry by default, and none is
  implemented here. One transient blip = one lost lookup, surfaced to the
  picker as "Not Found" (see §3 — this conflates "not on contract" with
  "network hiccup").
- **Circuit breaker**: none. Nothing stops the app from re-attempting GUDID on
  every miss even during a sustained outage — not a DoS risk against a public
  FDA API at this app's scale, but it does mean every miss during an outage
  pays the full 10s timeout, serially, on the handheld's main thread.

### 1.2 Microsoft Fabric Lakehouse — `data/loader.py`
[data/loader.py:159-417](data/loader.py#L159-L417)

- **TLS**: `Encrypt=Yes; TrustServerCertificate=No;` in the ODBC connection
  string ([data/loader.py:174-175](data/loader.py#L174-L175)) — this is the
  correct pairing; `TrustServerCertificate=No` means the driver validates the
  server cert against a trusted CA rather than accepting anything. Good.
- **Timeout**: `Connection Timeout=60;` ([data/loader.py:176](data/loader.py#L176))
  covers connection establishment only. There is no `statement_timeout`/query
  timeout on `cursor.execute()` ([data/loader.py:397](data/loader.py#L397)) — a
  slow or hung query against the SQL analytics endpoint can block the
  handheld's Streamlit script thread indefinitely.
- **Retries**: none on the ODBC connect or the query.
- **Auth-over-network**: the AAD token acquisition itself (`credential.get_token`,
  [data/loader.py:349](data/loader.py#L349)) goes over HTTPS to Microsoft's
  identity endpoints via `azure-identity`, which does its own TLS validation —
  not something this app controls or needs to.

### 1.3 Neon Postgres — `core/store.py`
[core/store.py:132-194](core/store.py#L132-L194)

- **TLS**: the stored connection string enforces it —
  `sslmode=require&channel_binding=require` (seen in
  `.streamlit/secrets.toml`, not committed — see §2). `channel_binding=require`
  is a strong setting (defeats MITM even against a compromised CA), good
  practice already in place. Note this is enforced by the *connection string
  value*, not by code — if the string is ever pasted without those params
  (e.g. from a different Neon connection tab), TLS enforcement silently
  weakens. Nothing in `core/store.py` independently asserts `sslmode=require`.
- **Timeout**: pool acquisition timeout `20s` ([core/store.py:184](core/store.py#L184)),
  `max_idle=300`. No per-statement timeout — same gap as Fabric.
- **Retries**: none beyond the pool's own liveness `check` before handing out a
  connection ([core/store.py:182](core/store.py#L182)), which helps with Neon's
  scale-to-zero cold start but does not retry a failed `INSERT`/`UPDATE`.
- **This is the path most exposed to the "poor warehouse signal" requirement**:
  every `record_scan()`, `create_session()`, `increment_scan()` call
  ([core/store.py:223-401](core/store.py#L223-L401)) is a synchronous network
  round-trip with no local buffering. See finding #5.

---

## 2. Credentials and secrets

| Credential | Storage | Assessment |
|---|---|---|
| Fabric/Azure AD | Interactive/device-code flows persist tokens via `azure-identity`'s `TokenCachePersistenceOptions` — OS keychain-backed — plus an `AuthenticationRecord` pointer file on disk ([data/loader.py:203, 275-326](data/loader.py#L203)) | **Good.** No password/secret is ever stored by this app for the interactive/default modes; the actual token lives in the OS keychain, not app-controlled disk. |
| Fabric service-principal (`FABRIC_CLIENT_SECRET`) | Read from env var only ([data/loader.py:305-318](data/loader.py#L305-L318)), documented in `.env.example` as "never commit" | Only used for non-interactive deploy. Not in OS keychain/secrets manager — plain env var. Acceptable for a container/CI secret injection model, but confirm however it's actually deployed (Streamlit Cloud secrets, CI env, etc.) doesn't land it in a log or process-list-visible arg. |
| Neon Postgres connection string (**contains a live password**) | `.streamlit/secrets.toml` — **git-ignored, confirmed not in version control** — plaintext file on local disk; same value pasted into Streamlit Cloud's secrets UI for deploy | **Finding #9.** Not committed to git (good), but sits in cleartext on whatever machine runs the app locally. Redacted from this report; the file is `.streamlit/secrets.toml`, present locally. |
| Admin allowlist emails | Same `secrets.toml`, `[admin]` table | Not a credential (just gate config), but same plaintext-on-disk profile. |
| GUDID | None — public API, no key | N/A, correctly documented as such. |

No hardcoded credentials found anywhere in source (`git ls-files` confirms
only `secrets.toml.example` — a template with no real values — is tracked).
`.gitignore` correctly excludes `.env` and `.streamlit/secrets.toml`.

## 3. Scanned barcode input — validation and injection surface

This is the most consequential finding set, because the barcode is the one
input in this app that's attacker-reachable without physical access to a
keyboard — anyone who can print a barcode and get it scanned controls this
string end-to-end.

- **`extract_gtin()`** ([core/lookup.py:100-106](core/lookup.py#L100-L106)) tries
  a GS1 AI regex match; **if it doesn't match, it returns the raw scanned
  string completely unchanged** — no length cap enforcement beyond the UI's
  `max_chars=50` ([app.py:244](app.py#L244)), no character-set restriction.
- **`engine/gtin.py` has solid validation primitives** — `normalize()`,
  `check_digit_valid()`, `is_digits()` ([engine/gtin.py:36-81](engine/gtin.py#L36-L81))
  — but **`resolve_scan()` never calls `check_digit_valid()`**. A string that
  fails GTIN validation entirely still flows into:
  1. **`api/goodid_client.py:68`** — `url = f"{_GUDID_LOOKUP_URL}?di={gtin}"`.
     Raw string interpolation, not `urllib.parse.quote()` / `httpx.QueryParams`.
     A scanned payload containing `&`, `#`, or other URL-structural characters
     changes what query parameters actually get sent to the FDA host. This
     isn't classic SSRF (the host is hardcoded, can't be redirected elsewhere)
     but it is unsanitized untrusted input reaching a URL — flagged both as
     V5 (encoding) and V9 (this is the one internet-facing call IT is
     specifically worried about). See finding #7.
  2. **Logging** — `logger.info("Cache MISS for GTIN %s...", gtin)`
     ([core/lookup.py:187-190](core/lookup.py#L187-L190)) and the equivalent in
     `api/goodid_client.py:69,76`. A crafted scan containing newlines could
     forge extra log lines (log injection / CRLF), though Python's default
     logging formatter doesn't execute anything from this — worst case is a
     confusing log, not code execution. Low-severity on its own, noted for
     completeness under V7.
  3. **Postgres INSERT** ([core/store.py:355-386](core/store.py#L355-L386)) —
     **safe**: every value is passed as a psycopg parameter (`%s` placeholders),
     never string-formatted into SQL. No SQL injection path here regardless of
     what the scan contains. Table/column identifiers are separately
     regex-validated ([data/loader.py:57-58](data/loader.py#L57-L58)) and sourced
     from `.env`, not the scan.
  4. **Excel export** — see finding #4 below, the most concrete exploitation
     path for an unvalidated scan string.
  5. **UI rendering (`ui/components.py`)** — checked thoroughly:
     `html.escape()` is applied consistently on every user/scan-derived field
     before HTML interpolation ([ui/components.py:16,110-407](ui/components.py#L16)),
     including the one spot that looked like a gap (`_val()`,
     [ui/components.py:290-292](ui/components.py#L290-L292)). **No XSS path found** —
     this is a genuine strength worth preserving exactly as-is during
     remediation.

**Net assessment**: validation primitives exist and are well-built, they're
just not wired into the one function (`resolve_scan`) that needs to call them
before the raw string leaves the process boundary (URL, export file, log).

## 4. Offline caching / queueing

Two entirely separate caches exist and need to be evaluated separately:

### 4.1 Contract-line reference data — `data/loader.py`
[data/loader.py:866-936](data/loader.py#L866-L936)

- Cached to `data/cache/contract_lines.parquet`, unencrypted, git-ignored.
- **Does not hard-expire.** `load_contract_data()` treats it as "fresh" for
  24h by mtime, but if a refresh fetch then fails (e.g., no connectivity), it
  falls back to serving the stale file **indefinitely**
  ([data/loader.py:902-909](data/loader.py#L902-L909)) — which is exactly the
  behavior the "must survive poor connectivity" requirement wants, but it
  means the file can sit on a lost/stolen handheld with no TTL-driven
  self-destruction. It contains contract line business data (manufacturer,
  item numbers, pricing-adjacent fields) — not patient/PII, but internal
  supply-chain data the org may not want on an unencrypted lost device. `base_cost`
  is deliberately excluded from every source query specifically to keep
  pricing out of this cache ([data/loader.py:122-138](data/loader.py#L122-L138)) —
  good existing discipline to preserve.
- No integrity check on read — a corrupted or tampered Parquet file would
  either fail to parse (safe failure) or silently serve altered data (no
  checksum/signature to catch the latter).

### 4.2 Scan session data — `core/store.py` / `core/session.py`
**There is no offline queue for this data at all.** `core/session.record_scan()`
calls `store.record_scan()` synchronously
([core/session.py:207-215](core/session.py#L207-L215) →
[core/store.py:355-386](core/store.py#L355-L386)), which is a direct network
round-trip to Neon. Same for `start_session`/`create_session`
([core/session.py:149-159](core/session.py#L149-L159)). If the handheld has no
connectivity when a picker scans:
- The call raises (psycopg connection/timeout error).
- Nothing catches it in `app.py`'s scan-handling block
  ([app.py:258-293](app.py#L258-L293)) — it propagates as an unhandled
  exception.
- With Streamlit's default error display (see finding #6), the picker sees a
  raw exception, not a graceful "saved locally, will sync later" message.
- **The scan is lost**, not queued. This directly contradicts the stated
  requirement that offline queuing is "a core requirement, not an edge case."

This is the single largest gap between the app's actual behavior and the
brief you gave me — flagging it prominently for Phase 2 prioritization
(**finding #5**, and probably the most consequential remediation item overall,
even though it's an availability/architecture gap as much as a strict ASVS
control).

## 5. Logging — what's captured, PII/token exposure

- Configured once, app-wide: `logging.basicConfig(level=LOG_LEVEL, ...)` in
  both [app.py:56-59](app.py#L56-L59) and [pages/board.py:31-34](pages/board.py#L31-L34)
  (duplicated setup — harmless since `basicConfig` is a no-op if handlers
  already exist, but worth consolidating).
- **Tokens**: never logged. `_fabric_access_token()` returns packed bytes
  that are only ever passed to `pyodbc.connect(attrs_before=...)`
  ([data/loader.py:328-381](data/loader.py#L328-L381)) — confirmed no log
  statement anywhere touches the token or credential objects. Good.
- **The device-code sign-in prompt is logged at WARNING**
  (`"AZURE AD SIGN-IN REQUIRED: open %s and enter code %s"`,
  [data/loader.py:294-296](data/loader.py#L294-L296)) — this is a short-lived
  device code (expires in minutes), necessary for the headless flow to be
  usable at all, low risk.
- **Raw GTINs are logged** at INFO on every hit/miss
  ([core/lookup.py:135,187](core/lookup.py#L135), [api/goodid_client.py:69,76](api/goodid_client.py#L69)).
  GTIN itself isn't PII, but per finding #3 it's *unvalidated* — so whatever a
  malicious/malformed barcode contains ends up in the log verbatim.
- **Sanford ID / location**: not found in any log statement — only ever
  handled as session state / DB columns / audit records. Good.
- **Admin audit log** ([core/admin.py:91-109](core/admin.py#L91-L109)) — records
  admin email + event + timestamp in a plaintext JSON-Lines file on local
  disk. Not encrypted (finding #13), but is an intentional, appropriately
  scoped audit trail — working as designed.
- **HTTP error bodies**: `api/goodid_client.py:94` logs
  `exc.response.text[:300]` on a GUDID HTTP error — this is the FDA API's own
  response body, not app-internal data, low risk.

## 6. Dependency vulnerabilities (SCA)

Ran `pip-audit` against the actual installed environment
(`.venv`, via `pipx run pip-audit`, OSV/PyPI advisory data as of 2026-09-14):

| Package | Installed | Fixed in | CVEs | Pulled in by | Exposure |
|---|---|---|---|---|---|
| `pillow` | 12.2.0 | 12.3.0 | 13 advisories | **direct dependency** + streamlit | Processes images (assets, any uploaded/rendered image data) — image-parsing libraries are a classic memory-safety attack surface; direct dep so easy to bump. |
| `cryptography` | 49.0.0 | 50.0.0 | CVE-2026-69247 (Bleichenbacher oracle in `pkcs7_decrypt_*`) | transitive via `azure-identity`/`Authlib`/`msal` | This app never calls the affected PKCS7 decrypt functions directly, so exploitability here is low, but it's an easy version bump and removes the question entirely. |
| `gitpython` | 3.1.50 | 3.1.51 | 22 advisories | transitive via `streamlit` (dev/watch tooling) | Not exercised by this app's own code; comes along for the ride with Streamlit. Update via the streamlit bump. |
| `starlette` | 1.2.1 | 1.3.1 | 2 advisories | transitive via `streamlit` | Same — Streamlit's internal web server dependency, not called directly. |
| `pip` | 25.1.1 | 25.3 | 6 advisories | build tooling | Only matters if `pip` itself runs in the deployed image at runtime (it shouldn't); still worth bumping the base image/build stage. |

**No vulnerabilities found** in `psycopg`, `httpx`, `python-dotenv`, `pyarrow`,
`openpyxl`, `pyodbc`, `streamlit` itself, `pandas`, or `azure-identity` at
their currently installed versions.

**Process finding (#14)**: `requirements.txt`/`pyproject.toml` both use `>=`
ranges with no lockfile (`requirements.txt` does cap with `<major`, but
nothing pins exact versions). This means "what's installed" isn't
reproducible or auditable from the manifest alone — the versions above came
from actually inspecting `.venv`, not from reading the manifest. Worth adding
a lockfile (`pip-compile`, `uv.lock`, or equivalent) so a future SCA run (and
IT's own tooling) can audit what's *actually* deployed without needing shell
access to the runtime environment.

## 7. Error handling — information leakage

- **`.streamlit/config.toml` does not set `[client] showErrorDetails`**
  ([.streamlit/config.toml](/.streamlit/config.toml)). Streamlit's default for
  this setting shows the full exception type, message, and stack trace in the
  browser on any uncaught exception. Combined with finding #5 (no offline
  queue → unhandled exception on a failed Neon write) and the Fabric/ODBC
  path having several `raise`/re-raise points that aren't caught above
  `app.py`'s call sites, this is a real path for internal details (file
  paths, table names, driver error text, possibly fragments of the connection
  string) to reach a picker's handheld screen. **Finding #6.**
- Where error handling *does* exist, it's done well:
  - `api/goodid_client.py` — every httpx exception type is caught explicitly
    and turned into a structured `GoodIDResult`, never raises
    ([api/goodid_client.py:71-108](api/goodid_client.py#L71-L108)).
  - `data/loader.py`'s Fabric block gives a specific, actionable error for the
    common "ODBC driver not installed" failure (`IM002`) rather than a raw
    driver exception ([data/loader.py:383-393](data/loader.py#L383-L393)).
  - `load_contract_data()` catches fetch failures broadly and falls back to
    stale cache before giving up ([data/loader.py:892-909](data/loader.py#L892-L909)).
- The gap is specifically the **handheld scan path in `app.py`** and the
  **session-store calls** (`core/store.py`) — neither wraps its Postgres calls,
  so any Neon-side failure (network blip, pool exhaustion, cold-start
  timeout) is an unhandled exception rendered straight to the UI.

---

## Access control (bonus findings, not in the original 7 but directly relevant)

While tracing the scan/session data flow I found two access-control gaps
worth flagging even though they weren't explicitly on your checklist —
they're squarely V4 and change how urgent some of the above is.

- **Finding #1 (Critical)**: `pages/board.py` has **no authentication or
  authorization check at all** — confirmed by grep, no `is_admin`/`st.secrets`/
  auth call anywhere in the file. Anyone who has (or guesses/finds) the
  board URL can view every picker's full scan history, Sanford ID, and
  warehouse location across the full 3-day retention window, and can
  **force-end any active session** ([pages/board.py:138-147](pages/board.py#L138-L147))
  — an unauthenticated state-changing action against another employee's
  in-progress work.
- **Finding #2 (High)**: `pages/admin.py`'s gate (`core/admin.is_admin()`,
  [core/admin.py:75-88](core/admin.py#L75-L88)) is explicitly, and
  self-documented as, **not real authentication** — it's a typed email string
  checked against an allowlist, "the way a sign-in sheet works," with no
  identity verification. The code comments already flag this honestly and
  compensate with an audit trail, which is the right instinct, but it means
  anyone who knows or guesses an allowlisted address gets admin access
  (trigger data refreshes, force-end sessions, view the audit log).

---

## What's already solid (don't regress these in Phase 2)

- GTIN check-digit/normalization math (`engine/gtin.py`) is correct and
  well-tested-looking — just needs to be *called*.
- HTML output encoding in `ui/components.py` is comprehensive and consistent.
- SQL parameterization in `core/store.py` is done correctly everywhere; no
  string-built queries against user data.
- No hardcoded credentials in source; `.gitignore` correctly excludes real
  secrets and the cache directory.
- TLS is enforced (not disabled) on every network call found in the codebase.
- Fabric auth uses OS-keychain-backed token caching via `azure-identity`
  rather than a stored password — genuinely good design.
- `base_cost`/pricing fields are deliberately excluded from every cache layer.

---

## Phase 2 scoping decisions

Reviewed with the user on 2026-09-14:

1. Findings #1 (board access control) and #2 (admin auth) are **folded into
   the Phase 2 priority list**, addressed alongside the original 8 items
   rather than tracked separately.
2. The Phase 2 egress allowlist covers **all three outbound hosts** — GUDID,
   the Fabric SQL analytics endpoint, and Neon Postgres — not just GUDID.
3. The board access-control fix gates **both viewing and Force End** behind
   the same typed-email check the admin page uses (not just Force End) —
   the board no longer works as an unattended shared-screen display.
4. **Architecture correction discovered mid-remediation, changing findings
   #5 and #8's threat model:** this app is a Streamlit web app — the
   handheld is a *browser* with a live connection to a remote Streamlit
   server (deployed on Streamlit Cloud per README/PLAN.md), not a native or
   offline-capable client. Two consequences, confirmed with the user before
   building anything further:
   - **Finding #5 (offline queue)**: `PLAN.md` already documents "scanning
     is online-only for v1... No offline queue" as a deliberate, prior
     product decision — a handheld WiFi dropout breaks the browser↔server
     connection entirely, which no server-side code can buffer around
     (that would need a client-side PWA rewrite: service worker + local
     storage + background sync — a separate, larger project, out of scope
     here). What *is* in scope and was built: hardening the Streamlit
     server's own connection to Neon, which can blip independently of the
     handheld's WiFi. See ASVS-COMPLIANCE.md for the resulting scope split.
   - **Finding #8 (local cache)**: the Parquet contract-data cache lives on
     the Streamlit **server's** disk (e.g. Streamlit Cloud's container),
     not on the physical handheld. The original "lost/stolen handheld"
     framing was wrong — the real exposure is server-side disk/container
     access (a compromised host, an unencrypted backup, another process on
     the same machine), which is what the encryption-at-rest fix now
     actually defends against. Still worth encrypting; just not for the
     reason originally stated.
