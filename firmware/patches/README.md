# Upstream patches — default ZERO

Part of [PyBLE](https://pyble.dev) · MIT — see [`/LICENSE`](../../LICENSE).

PyBLE is **not** a fork of MicroPython (CON-1/2). The upstream submodule under
[`firmware/upstream/micropython/`](../upstream/) stays **pristine** — never edited
in place. The **default patch count is ZERO** (CON-12, BLD-15).

## When a patch is unavoidable

If (and only if) an upstream defect cannot be worked around in the Layer-2 board
overlay or the Layer-3 agent, an isolated patch may live here:

```
firmware/patches/micropython-<tag>/
  <name>.patch      # the diff, applied at build prep only
  REASON.md         # REQUIRED, non-empty: why the patch exists, upstream ref/issue,
                    # and the condition under which it can be retired
```

- `<tag>` matches the MicroPython `ref` in [`../versions.lock`](../versions.lock)
  (e.g. `micropython-v1.28.0`).
- Every `*.patch` **must** have a non-empty sibling `REASON.md`, or the
  `tools/ci/patches_policy.sh` gate refuses the build.
- Patches apply **only at build prep** (`firmware/scripts/prepare.sh`), never
  committed into the submodule, and are **re-reviewed for retirement at every
  upgrade** (`upgrade_micropython.sh`).

The gate that enforces this: [`tools/ci/patches_policy.sh`](../../tools/ci/patches_policy.sh).
