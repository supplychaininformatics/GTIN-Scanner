# Security Policy

## Reporting a vulnerability

If you find a security issue in this app, report it privately rather than
opening a public GitHub issue — this repo is public, and a public issue
discloses the problem before it's fixed.

Preferred: GitHub's private vulnerability reporting for this repository
(**Security** tab → **Report a vulnerability**), which opens a private
advisory visible only to repo maintainers until it's resolved. **This
needs to be turned on in repo settings first** (Settings → Security →
Private vulnerability reporting) — it is not yet enabled as of this
writing; see ASVS-COMPLIANCE.md's infra-action list.

Until then, or if you don't have GitHub access, contact Supply Chain
Informatics directly through your normal internal channel.

Please include:
- What you found and where (file/endpoint/flow)
- Steps to reproduce, or a proof of concept
- What you think the impact is

## What's in scope

- The application code in this repository (`app.py`, `core/`, `data/`,
  `engine/`, `api/`, `ui/`, `pages/`)
- The GitHub Actions workflows in `.github/workflows/`
- Configuration that ships with the repo (`.streamlit/config.toml`,
  `pyproject.toml`, dependency manifests)

## What's out of scope

- The Streamlit Cloud hosting platform itself, or Neon/Microsoft Fabric's
  own infrastructure — report those to the respective vendor.
- Social engineering, physical access to a handheld device, or anything
  requiring access you shouldn't already have.
- Findings against dependencies that are already tracked — check
  `requirements.lock.txt` and run `pip-audit` first; if it's a known,
  already-flagged CVE with no fix released yet, it's tracked, not new.

## Supported versions

This app doesn't maintain multiple released versions — `main` is what's
deployed, and every fix lands there. There's no backport policy.

## Current known state

[ASVS-AUDIT.md](ASVS-AUDIT.md) and [ASVS-COMPLIANCE.md](ASVS-COMPLIANCE.md)
document a full ASVS-based security review of this app, findings, fixes,
and what's intentionally left open pending infra action (verified identity
for the admin/monitor pages, network-level egress restriction, and a few
others — see ASVS-COMPLIANCE.md's "Needs infra-level action" list). Read
those before reporting something already tracked there.
