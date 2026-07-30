# ADR-0022 — Host the canonical static site on a Cloudflare-fronted VPS

- Status: **Accepted**
- Date: 2026-07-29
- Amends: production-hosting aspects of
  [ADR-0020](0020-vinext-sites-deployment-adapter.md)

## Context

[ADR-0019](0019-nextjs-static-public-site.md) selected a portable Next.js
static export, and [ADR-0020](0020-vinext-sites-deployment-adapter.md) added a
vinext package for the first hosted preview. PyBLE now has a dedicated VPS for
its public domains. The canonical site needs a production origin that remains
simple to operate, easy to roll back, and independent of an application
runtime.

The launch routes are build-time documents. They need no Node.js process,
database, account system, remote CMS, or runtime secret. Deploying the vinext
worker envelope to a conventional VPS would add a service process without
adding product capability.

## Decision

Host the canonical `https://pyble.dev` site with this path:

```text
visitor → Cloudflare edge → HTTPS origin → Nginx → tools/web/out/
```

- Cloudflare is the authoritative DNS, public TLS, caching, and security edge.
  Edge-to-origin TLS uses **Full (strict)** mode with a valid origin
  certificate.
- A dedicated Nginx virtual host serves the checked, portable Next.js `out/`
  export. The VPS runs no website Node.js process.
- Each release is stored immutably below
  `/srv/pyble/releases/<timestamp>-<commit>/`. The
  `/srv/pyble/current` symlink selects the active release, so activation and
  rollback are atomic.
- Only an exact committed revision that passes the website release gate may be
  deployed. The release identifier records that Git revision.
- Nginx preserves slashless document URLs, serves the generated 404 document
  with status 404, gives immutable caching only to fingerprinted Next.js
  assets, and sends reviewed security headers.
- `pyble.dev` is the sole content origin. `www.pyble.dev`, `pyble.org`, and
  `www.pyble.org` permanently redirect to the same path and query on
  `https://pyble.dev`. Cloudflare owns the public `.org` redirect; Nginx keeps
  the same redirect as defense in depth once the `.org` DNS and certificate
  are active.
- SSH private keys, TLS private keys, Cloudflare credentials, and host-specific
  secrets never enter the repository.

The vinext `dist/` artifact remains a tested owner-preview and hosting-
compatibility output. It is not the canonical VPS production artifact. This
amends ADR-0020 without changing the authored routes or retiring the existing
preview deployment.

## Rationale

- Static Nginx hosting matches the product's build-time content model and has a
  smaller runtime and patch surface than a Node.js service.
- Cloudflare gives global visitors a nearby cache while allowing the origin to
  remain in one maintainable location.
- Versioned directories and one symlink make a failed content release
  reversible without rebuilding.
- Keeping both portable and preview artifacts preserves host portability.

## Consequences

- Production operations must maintain the VPS operating system, Nginx,
  certificate renewal, firewall, backups, and release history.
- Cloudflare's SSL mode must never be `Flexible`; origin certificate expiry or
  a failed renewal is a production incident.
- A DNS or certificate dependency can delay activation of a newly added
  hostname, especially the `.org` redirect, without blocking the already
  verified canonical `.dev` origin.
- Dynamic accounts, APIs, form handlers, or telemetry still require a separate
  architecture and privacy decision.
