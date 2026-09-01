<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Website deployment runbook

The canonical site is a static Next.js export served by Nginx on the production
VPS behind Cloudflare. A successful build does not by itself authorize a public
deployment.

## Architecture

```text
visitor → Cloudflare → HTTPS origin → Nginx → /srv/pyble/current
                                                   ↓
                         /srv/pyble/releases/<timestamp>-<commit>

versioned firmware → /srv/pyble/firmware/v<version>/
```

`out/` is the VPS production artifact. `dist/` is the separately tested
Sites/vinext owner-preview artifact; never deploy it to Nginx.
Website releases and the persistent firmware store have separate lifecycles so
a website-only deployment cannot remove or replace an immutable firmware URL.

The VPS needs no Node.js process, application service, database, runtime
environment variable, or repository checkout.

## Release input

From `tools/web/`:

```sh
npm ci
NEXT_TELEMETRY_DISABLED=1 npm run check
```

Review at least:

- home at phone, portrait-tablet, landscape-tablet, and desktop widths;
- home and metadata clearly separate the capability-defined MicroPython + BLE
  platform vision from the targets validated by the current release;
- `/app`, including the current iPad external-beta and Android internal-test
  destinations, scannable local QR images, visible fallback addresses,
  invited-account restriction, and links to firmware and support;
- `/privacy`, including the effective date and public contact address;
- `/support`, including the public contact address;
- `/flash`, confirming the install button is still disabled unless the
  firmware release gate is fully satisfied;
- `/features`, confirming its v0.6.0 snapshot label, semantic feature reference,
  full-size diagram link, and clear boundary back to `/flash`;
- the reviewed functional diagram at
  `/features/pyble-firmware-v0.6.0-functional-block-diagram-473a85d475aa.svg`,
  including selectable text, useful title/description, two-dimensional
  inspection, and no generated board likeness or external image reference;
- `/learn` and all ten ordered tutorials: setup, first program, Files, GitHub
  import, Blocks, examples, hardware safety, configured hardware, Pico 2 W,
  and the Waveshare LCD 1.47B;
- every tutorial's release/compatibility statement, wiring boundary, expected
  result, recovery guidance, previous/next navigation, and immutable source
  link where applicable;
- `out/robots.txt`, `out/sitemap.xml`, and `out/manifest.webmanifest`;
- `out/WEBSITE_THIRD_PARTY_LICENSES.txt`, generated from the exact production
  dependency closure;
- the generated canonical URL on every route;
- the absence of third-party runtime scripts, fonts, analytics, and trackers;
  and
- `dist/` only as the owner-preview compatibility gate described in the
  package README.

The immutable deployment input is the exact committed source revision that
produced the checked `out/` export.

## Stage a firmware release

The normal source build contains no firmware and keeps the installer
unavailable. A website-only production deployment instead authenticates and
carries forward the active qualified selector and immutable release bytes; it
does not silently disable or replace them. Do not put release bytes in
`tools/web/public/`. Generate a v0.6.0 firmware release bundle outside this
package, including `release.json`, `release.schema.json`, the five exact profile
directories, release and recovery documents, and conventional full-coverage
`SHA256SUMS`: `esp32-4mb`, `esp32-s3-n16r8`,
`waveshare-esp32-s3-lcd-147b`, `esp32-c3-4mb`, and `rpi-pico2-w`.

For an all-HIL-passed public bundle:

```sh
staged_root=$(mktemp -d)
export PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR=/absolute/path/to/license-evidence
export PYBLE_FIRMWARE_LICENSE_BUILD_ROOT=/absolute/path/to/release-build-root
export PYBLE_FIRMWARE_SOURCE_ROOT=/absolute/path/to/exact-firmware-source-checkout

PYBLE_FIRMWARE_BUNDLE_DIR=/absolute/path/to/firmware-bundle \
PYBLE_FIRMWARE_OUTPUT_DIR="${staged_root}" \
PYBLE_FLASH_DEPLOYMENT=public \
npm run firmware:stage

PYBLE_FIRMWARE_STAGED_ROOT="${staged_root}" \
deploy/vps/deploy.sh <ssh-user>@<vps-host>
```

Before this command, the exact local tag `firmware-v<version>` must exist as an
annotated tag and peel directly to the full commit recorded by `release.json`
at `provenance.pyble.commit`. The helper binds the tag object and peeled commit
before and after the website build and again before upload.

Public, public-beta, and protected-candidate validation require the explicit
license-evidence, release-build, and exact firmware-source paths shown above.
The source checkout must be the clean source identity recorded by the release,
with its pinned generated build inputs available. The evidence directory must
be the fresh, reviewed output for those exact source and build inputs and must
remain outside both trees. Keep all three variables exported through deployment
because the helper repeats canonical validation for the private trusted staged
snapshot.

The deploy helper canonically validates the caller staging, requires an
all-HIL-passed public descriptor, and copies exactly that tree into a mode-0700
private snapshot. It revalidates the snapshot and uses it for the production
build, never the mutable caller directory.

Immediately before upload, the helper reruns canonical public validation and
file-for-file parity against the final `out/firmware` tree. It then copies all
of final `out/` to a separate mode-0700, read-only upload snapshot, revalidates
firmware there, and generates a whole-site SHA-256 inventory. Only that
snapshot is passed to `rsync`. The inventory's digest travels separately; the
VPS authenticates it, rejects non-regular nodes, compares the exact remote file
set, and verifies every listed hash before publishing firmware or changing any
website symlink. Firmware and upload evidence remain available through this
remote verification. A caller-supplied evidence or inventory directory is
never trusted. The helper retrieves every published byte afterward.

For the exact digest-bound v0.4.2 hardware-tested beta, use the same retained
license inputs and annotated `firmware-v0.4.2` tag, but select the explicit
public-beta mode:

```sh
staged_root=$(mktemp -d)
export PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR=/absolute/path/to/license-evidence
export PYBLE_FIRMWARE_LICENSE_BUILD_ROOT=/absolute/path/to/release-build-root
export PYBLE_FIRMWARE_SOURCE_ROOT=/absolute/path/to/exact-firmware-source-checkout

PYBLE_FIRMWARE_BUNDLE_DIR=/absolute/path/to/firmware-v0.4.2-bundle \
PYBLE_FIRMWARE_OUTPUT_DIR="${staged_root}" \
PYBLE_FLASH_DEPLOYMENT=public-beta \
npm run firmware:stage

PYBLE_FIRMWARE_STAGED_ROOT="${staged_root}" \
deploy/vps/deploy.sh <ssh-user>@<vps-host>
```

The staging and deployment helpers run the canonical `--audited-candidate`
license gate, require both profile HIL states to remain pending, bind the exact
reviewed `release.json` SHA-256, and keep ESP32-C3 absent. The public site must
identify these bytes as a hardware-tested beta, name the completed production
Chrome installation and interrupted-flash recovery scope, and distinguish it
from complete release qualification.

For a pending release candidate, stage with both explicit controls:

```sh
PYBLE_FIRMWARE_BUNDLE_DIR=/absolute/path/to/firmware-bundle \
PYBLE_FIRMWARE_OUTPUT_DIR="${staged_root}" \
PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR=/absolute/path/to/license-evidence \
PYBLE_FIRMWARE_LICENSE_BUILD_ROOT=/absolute/path/to/release-build-root \
PYBLE_FIRMWARE_SOURCE_ROOT=/absolute/path/to/exact-firmware-source-checkout \
PYBLE_FLASH_DEPLOYMENT=candidate \
PYBLE_FLASH_ACCESS_CONTROLLED=1 \
npm run firmware:stage
```

Build the protected Sites artifact from the external tree without copying
firmware into the source `public/` directory:

```sh
PYBLE_FIRMWARE_STAGED_ROOT="${staged_root}" \
PYBLE_FLASH_SELECTION_FILE="${staged_root}/.pyble-firmware-release-selection.json" \
PYBLE_FIRMWARE_LICENSE_EVIDENCE_DIR=/absolute/path/to/license-evidence \
PYBLE_FIRMWARE_LICENSE_BUILD_ROOT=/absolute/path/to/release-build-root \
PYBLE_FIRMWARE_SOURCE_ROOT=/absolute/path/to/exact-firmware-source-checkout \
NEXT_TELEMETRY_DISABLED=1 \
npm run check
```

The Sites adapter revalidates the staged descriptor, checksums, manifests, and
bytes immediately before it copies the immutable tree into `dist/client/`.
The staged root and `PYBLE_FLASH_SELECTION_FILE` are an inseparable pair: the
selector must be the exact descriptor inside that root, and supplying either
one without the other is rejected.
Deploy that artifact only behind enforced authentication. The boolean is an
attestation to the fail-closed build policy, not access control itself. Never
send a protected candidate through the public VPS helper; it accepts only
qualified public releases whose final-byte HIL statuses are `passed` for every
exact profile, or the exact audited and digest-bound v0.4.2 public-beta legacy
exception. The current public selector is the qualified five-profile v0.6.0
release.

## First-time VPS bootstrap

Use Ubuntu 24.04 LTS or an equivalent release with systemd 254 or newer. Install
the distribution's Nginx, Certbot, and rsync packages. Create:

```text
/srv/pyble/releases/
/srv/pyble/firmware/
/var/lib/letsencrypt/.well-known/acme-challenge/
```

Install the repository-owned Nginx files:

| Repository file                            | Server path                                                        |
| ------------------------------------------ | ------------------------------------------------------------------ |
| `deploy/nginx/pyble-security-headers.conf` | `/etc/nginx/snippets/pyble-security-headers.conf`                  |
| `deploy/nginx/00-pyble-http.conf`          | `/etc/nginx/sites-available/00-pyble-http.conf`                    |
| `deploy/nginx/05-default-deny.conf`        | `/etc/nginx/sites-available/05-default-deny.conf`                  |
| `deploy/nginx/10-pyble-dev-https.conf`     | `/etc/nginx/sites-available/10-pyble-dev-https.conf`               |
| `deploy/nginx/20-pyble-org-https.conf`     | `/etc/nginx/sites-available/20-pyble-org-https.conf`               |
| `deploy/vps/reload-nginx-after-renewal.sh` | `/etc/letsencrypt/renewal-hooks/deploy/reload-nginx-after-renewal` |

Enable only `00-pyble-http.conf` and `05-default-deny.conf` before certificate
issuance. Remove the distribution's default site, run `nginx -t`, and reload
Nginx.

Issue the canonical certificate through the persistent webroot:

```sh
certbot certonly \
  --webroot \
  --webroot-path /var/lib/letsencrypt \
  --domain pyble.dev \
  --domain www.pyble.dev
```

Then enable `10-pyble-dev-https.conf`, run `nginx -t`, reload Nginx, and verify
that `certbot renew --dry-run --run-deploy-hooks` succeeds. The Certbot timer
owns renewal, and the deploy hook validates and reloads Nginx after Certbot
installs a renewed certificate.

At Cloudflare:

- proxy the website records;
- use SSL/TLS mode **Full (strict)**, never Flexible;
- preserve the origin's `Cache-Control: no-transform` directive so launch-route
  HTML remains byte-identical to the checked export and Cloudflare does not
  rewrite contact addresses or inject an email-decoder script;
- keep `pyble.dev` as the canonical content host; and
- configure the `.org` redirect at the edge after `.org` DNS is active.

The `.dev` registry is HTTPS-enforced. Do not announce the site until a fresh
browser can load it without a certificate warning.

## Deploy a release

The deploy helper proves that the active `pyble.dev` HTTPS configuration and
security-header snippet are byte-identical to the repository before it builds
or uploads a release. When either repository file changes, first copy it to a
root-owned temporary path on the VPS, retain a dated backup of the installed
file, install it atomically at the path in the bootstrap table, run `nginx -t`,
reload Nginx, and verify the affected policy endpoints. Only then run the
website deployment. A configuration mismatch fails before activation.

The deploy helper refuses every `tools/web/.env*` filesystem node before it
chooses a deployment mode, so Next cannot inject an inherited selector or
other unreviewed build input. It also refuses a dirty source tree, freezes the
full 40-character HEAD before the build, and proves the same clean HEAD again
after building and immediately before upload. It records that identity in
`out/.pyble-source-commit`, which the VPS validates before activation. The
helper runs the complete release gate, uploads only the private trusted
snapshot into a new immutable website release directory, validates the
whole-site inventory, required files, optional firmware checksums, and Nginx
configuration,
publishes a new firmware version atomically under `/srv/pyble/firmware/`,
atomically switches `/srv/pyble/current`, reloads Nginx, and performs public
smoke tests. Existing firmware versions are retained; exact reuse is a no-op,
and a byte difference under an existing version is release-blocking. Before
the symlink switch, it starts a systemd rollback watchdog independent of the
SSH session. The watchdog restores the preceding website release unless the
complete public smoke suite succeeds. Confirmation itself runs as a detached,
waited systemd transaction, stops the watchdog, and proves both transient units
inactive before activation is reported successful. Both transient jobs disable
systemd's command-argument environment expansion so their embedded shell
programs arrive byte-for-byte and expand variables only inside Bash.
The helper rejects a caller-supplied `PYBLE_FLASH_SELECTION_FILE`; it derives
that path only from a freshly verified staged root. A website-only run clears
and then proves the absence of `out/firmware` before packaging.

From the repository root:

```sh
tools/web/deploy/vps/deploy.sh <ssh-user>@<vps-host>
```

The current qualified v0.6.0 selector is carried forward without restaging:
the helper retrieves the active selector and complete immutable release,
validates their authenticated digests and qualified-public contract, and
repackages those exact bytes. If the current installer is instead the legacy
v0.4.2 public beta, a website-only deployment must also export the same retained
license-evidence, release-build, and exact firmware-source paths and retain the
annotated `firmware-v0.4.2` tag. That legacy carry-forward repeats the canonical
audited-candidate and tag checks; neither path relies on the presence of
firmware bytes alone.

The SSH target is an argument so no host address or private-key path is stored
in the repository. Authentication must be non-interactive and key-based.

## `pyble.org` activation

`pyble.org` is not a second content origin. After both `pyble.org` and
`www.pyble.org` have proxied Cloudflare DNS records targeting the production
origin:

```sh
certbot certonly \
  --webroot \
  --webroot-path /var/lib/letsencrypt \
  --domain pyble.org \
  --domain www.pyble.org
```

Enable `20-pyble-org-https.conf`, validate and reload Nginx, then configure the
Cloudflare redirect with these semantics:

```text
https://pyble.org/<path>?<query>
  → 308 https://pyble.dev/<path>?<query>
```

Apply the same rule to `www.pyble.org`. Test `/`, `/privacy`, `/support`, and a
URL containing a query string.

## Security baseline

- Permit only SSH, HTTP, and HTTPS through the host/provider firewalls.
- Keep SSH key authentication working before disabling password authentication.
- Test a second SSH connection before ending the bootstrap session.
- Apply supported operating-system security updates and keep unattended
  security upgrades enabled.
- Keep SSH keys, TLS private keys, Cloudflare credentials, and backups outside
  the repository.
- Do not expose a Node.js port; Nginx is the only website process.

Restricting origin web ports to Cloudflare address ranges or enabling
Authenticated Origin Pulls is a useful later hardening step, but it must include
an explicit recovery path so a Cloudflare configuration error cannot lock out
certificate renewal.

## Post-deploy smoke test

```sh
curl -fsSI https://pyble.dev/
curl -fsSI https://pyble.dev/app
curl -fsSI https://pyble.dev/privacy
curl -fsSI https://pyble.dev/support
curl -fsSI https://pyble.dev/flash
curl -fsSI https://pyble.dev/features
curl -fsSI https://pyble.dev/features/pyble-firmware-v0.6.0-functional-block-diagram-473a85d475aa.svg
for route in learn learn/setup learn/first-program learn/files \
  learn/github-import learn/blocks learn/examples learn/hardware \
  learn/configured-hardware learn/pico-2-w learn/waveshare-lcd-147b; do
  curl -fsSI "https://pyble.dev/${route}"
done
curl -fsSI 'https://pyble.dev/features/?source=redirect-check'
curl -fsSI 'https://pyble.dev/learn/setup/?source=redirect-check'
curl -fsSI 'https://www.pyble.dev/privacy?source=redirect-check'
curl -fsSI 'https://pyble.org/privacy?source=redirect-check'
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://pyble.dev/not-found-smoke)" = 404
test "$(curl -sS -o /dev/null -w '%{http_code}' \
  https://pyble.dev/learn/not-a-tutorial)" = 404
```

Confirm:

- the final URL is canonical and redirects preserve path/query;
- HTML returns `Cache-Control: no-cache, no-transform`, remains byte-identical
  to the checked export through Cloudflare, and revalidates while
  `/_next/static/` assets are immutable;
- `/features` is byte-identical to `out/features.html`; its fingerprinted SVG
  is byte-identical to the reviewed `out/` asset and returns `image/svg+xml`;
- `/features/?source=redirect-check` returns `308` to the slashless canonical
  URL with its query string intact;
- all eleven Learn documents are byte-identical to their nested `out/` files,
  each slash redirect returns `308` with its query intact, and an unknown Learn
  pathname returns the authored `out/404.html` body with status `404`;
- versioned `/firmware/` assets, when present, are immutable and serve JSON and
  binary files with their explicit safe MIME types;
- the helper tests the selected release's deferred C3 manifest as a `404`
  `no-store` path only for the exact legacy `v0.4.2` `public-beta`; qualified
  v0.6.0 instead validates and retrieves every descriptor-declared profile,
  including C3 and Pico 2 W;
- the manifest uses `application/manifest+json`;
- the reviewed security headers are present;
- no third-party runtime request appears; and
- Cloudflare reports the origin connection as Full (strict).

Then inspect the pages in a real browser with JavaScript disabled,
keyboard-only navigation, and reduced motion enabled.

## Rollback

List `/srv/pyble/releases/`, choose the preceding checked release, create a
temporary symlink to that exact directory, and atomically replace
`/srv/pyble/current`. Run `nginx -t` before the switch and reload Nginx after
it.

Never delete the active release. Retain at least one preceding known-good
release until the replacement has passed public validation. Website rollback
does not mutate `/srv/pyble/firmware/`: those version paths remain available
and immutable independently of the selected website release. An interrupted
deployment may leave a transient `pyble-activation-*.timer`; it restores the
preceding release after 15 minutes unless the deploy helper has confirmed the
successful production smoke test and stopped it.
