# ADR-0005 — Standalone domain, not a commercial subdomain

- Status: **Accepted**
- Date: 2026-06-30

## Context

PyBLE needs a web home (project site + the web flasher). The author already owns a commercial company domain and could host PyBLE under it (e.g. `pyble.company.com`) instead of registering a standalone domain.

## Decision

Use a **standalone domain**. `pyble.dev` and `pyble.org` are **registered**; `pyble.dev` is the canonical site, with `pyble.org` redirecting to it. PyBLE is **not** hosted under the commercial company domain.

## Rationale

- **Trust → adoption.** Open-source dev tools with their own domain read as genuine community projects (thonny.org, micropython.org, wokwi.com). A commercial subdomain reads as a marketing funnel and dampens contributor trust.
- **Clean separation.** Keeping PyBLE off the commercial domain reinforces the IP/brand boundary ([ADR-0001](0001-separate-project-not-extend.md)).
- **Cost is negligible** (~$30–45/yr) and not a deciding factor.

## Consequences

- `.dev` (HTTPS-enforced, dev-tool TLD) is the canonical web + flasher host; `.org` redirects.
- Attribution is given as "a SciLabPro open-source project" in the README/About — brand credit without hosting under the commercial domain.
