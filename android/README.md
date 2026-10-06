# GTIN Scanner — Android client

Offline-first handheld client for the Zebra HC50 (Android + DataWedge). It scans
and looks items up with no network, queues everything durably on the device, and
syncs to the Python `sync_api` service when a connection exists. The wire
contract is [../SYNC-API.md](../SYNC-API.md).

## Layout

| Module | What | Builds with |
|---|---|---|
| `core/` | Pure Kotlin/JVM: GS1 extraction, mirror download (paged, resumable, atomic swap), upload queue draining, scan flow. No Android imports. | JDK 17 only |
| `app/` | Android layer: SQLite stores, DataWedge intent receiver, WorkManager sync, plain UI, MDM-managed config. | Android SDK |

`:app` is only included when an Android SDK is configured (`ANDROID_HOME` or
`local.properties`), so `:core` builds and tests on any machine or CI job.

## Build & test

```
cd android
./gradlew :core:test                      # 37 unit tests, no SDK needed
```

End-to-end against the real service (proves client and server agree on the wire format):

```
# terminal 1, from the repo root
DATA_SOURCE=mock python -m sync_api.dev_server        # 127.0.0.1:8080, token "dev-token"
# terminal 2
SYNC_API_URL=http://127.0.0.1:8080 SYNC_API_TOKEN=dev-token ./gradlew :core:test
```

The app: open `android/` in Android Studio (it will set up the SDK), or
`./gradlew :app:assembleDebug` with the SDK installed. Point a debug build at a
dev server from the emulator:

```
adb shell am start -n com.sanford.gtinscanner/.MainActivity \
  --es sync_url http://10.0.2.2:8080 --es sync_token dev-token
```

Release builds take the URL and token from **Managed Configuration** pushed by
the MDM (keys `sync_url`, `sync_token`); HTTPS is mandatory there.

## How it behaves

- **Scan**: DataWedge broadcasts the decoded string → validated → queued to
  SQLite *first* → resolved against the on-device mirror → shown. No network call.
- **Mirror miss** is shown as "not on contract file — will be verified when
  online", never as a final Not Found: the server re-resolves every scan at sync
  time (including the goodID fallback, which can't be mirrored).
- **Sync**: WorkManager runs when the network is up (after each scan, plus every
  15 min). Ops leave the queue only when the server says applied / duplicate /
  rejected; `retry` and any failed request keep them. Re-sends reuse the op id,
  so a lost response never double-counts a scan.
- **Mirror update**: downloaded into a staging table page by page (a dropped
  connection resumes from the last cursor), swapped in atomically only after the
  last page, restarted if the server's data changes mid-download.

## Status — read this

- `core/` is compiled and tested (37 unit tests + a live end-to-end test).
- `app/` has **not been built or run**. Its Kotlin was type-checked against the
  Android 14 framework jar and WorkManager 2.9.1, but the Android Gradle build
  (manifest/resource merge), the SQLite code, the DataWedge profile
  (`DataWedge.configure` follows Zebra's documented SET_CONFIG API but is
  unverified on a device), and WorkManager scheduling have never executed.
  Expect a first-build fix-up pass in Android Studio.
- Not built yet: a proper UI (this one is a functional stub), launch-time
  provisioning error screens, surfacing `rejected` ops to the operator, an
  instrumented test suite, and release signing / MDM distribution.
- Package name `com.sanford.gtinscanner` is a placeholder — change it to the
  organisation's real application id before distributing.
