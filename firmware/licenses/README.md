# Firmware license catalog provenance

This directory retains the exact license and notice bytes reviewed for the
pinned PyBLE firmware inputs. The release policy binds each shipped input to
these committed files by repository-relative path and SHA-256 digest.

The BSD-1-Clause, BSD-2-Clause, BSD-2-Clause-Views, BSD-3-Clause, CC0-1.0,
GPL-2.0-or-later, ISC, LLVM-exception, MIT, and Unlicense standard texts in
`texts/` were copied verbatim from `spdx/license-list-data` commit
`c4a7237ec8f4654e867546f9f409749300f1bf4c` (license-list version 3.28.0).
`GPL-3.0-or-later.txt`, `GCC-exception-3.1.txt`, and the two distinct newlib
compilations preserve the exact bytes distributed by the pinned ESP-IDF and
ESP GNU toolchains.

The Berkeley DB LicenseRef is an exact concatenation of:

- lines 1–33 of `lib/berkeley-db-1.xx/btree/bt_close.c` from MicroPython
  commit `e0e9fbb17ed6fd06bb76e266ae554784c9c80804`
  (whole-file SHA-256
  `ae506f8cc5f0c54f3d8f933553bfa2f0d8da9cd1f7c70521b5077d6c9cf4ce8f`);
- the complete `lib/berkeley-db-1.xx/README.Impt.License.Change` from the same
  commit (SHA-256
  `a1fd7df45e2777279d3037dc04e98ad764de7dabeb5b8f12217acf3123fc520e`).

The files in `evidence/` are verbatim copies from these reviewed sources:

- ESP-IDF commit `fcae32885b0296b32044cb99ecbdc50d98dddb83`;
- MicroPython commit `e0e9fbb17ed6fd06bb76e266ae554784c9c80804`;
- micropython-lib commit `8380c7bb8f9e5e5260e9539156742925e00366b2`;
- LAN867x component version 1.0.3, component hash
  `0ff9dae3affeff53811e7c8283e67c6d36dc0c03e3bc5102c0fba629e08bf6c4`;
- the MicroPython TinyUSB fork commit
  `e4c0ec3caab3d9c25374de7047653b9ced8f14ff`.
