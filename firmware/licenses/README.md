# Firmware license catalog provenance

This directory retains the exact license and notice bytes reviewed for the
pinned PyBLE firmware inputs. The release policy binds each shipped input to
these committed files by repository-relative path and SHA-256 digest.

The BSD-1-Clause, BSD-2-Clause, BSD-2-Clause-Views, BSD-3-Clause, CC0-1.0,
GPL-2.0-or-later, ISC, LLVM-exception, MIT, and Unlicense standard texts in
`texts/` were copied verbatim from `spdx/license-list-data` commit
`c4a7237ec8f4654e867546f9f409749300f1bf4c` (license-list version 3.28.0).
`GPL-3.0-or-later.txt`, `GCC-exception-3.1.txt`, and the three distinct newlib
compilations preserve the exact bytes distributed by the pinned ESP-IDF, ESP
GNU, and Arm GNU toolchains. The Arm GNU 14.2.Rel1 newlib compilation is kept
separately because its bytes differ from both ESP toolchain copies.

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

## RP2 policy and source provenance

`rp2-license-policy.json` is the canonical schema-1 policy for the retained
Raspberry Pi Pico 2 W build. It maps exact linked, frozen, and compiler-runtime
inputs to the most-specific reviewed source owner. In particular, it does not
assign one broad license to heterogeneous `lib/libm`, pico-sdk, or Arm GNU
runtime inputs. A `review-required` disposition is deliberately release
blocking; it records complete evidence without claiming that a legal decision
has been made.

The retained MicroPython checkout is commit
`e0e9fbb17ed6fd06bb76e266ae554784c9c80804`. Its selected nested checkouts are:

- lwIP `77dcd25a72509eb83f72b033d219b1d40cd8eb95`;
- Mbed TLS `107ea89daaefb9867ea9121002fbbdf926780e98`;
- pico-sdk `a1438dff1d38bd9c65dbd693f0e5db4b9ae91779`;
- BTstack `77e752abd6a0992334047a48038a5a3960e5c6bc`;
- CYW43 driver `055d64274b014dd7b1c2fc94d26e8a18face7124`;
- TinyUSB `aa0fc2e08f1c2dd6f026a431e8989357fbb4c5bf`.

The RP2 evidence copies of the lwIP license, BTstack stock license and
Raspberry Pi grant, and CYW43 stock license are byte-identical to those pinned
trees. The CYW43 Raspberry Pi grant and the pico-sdk top-level license are
bound directly to their exact checked-in upstream bytes because those files
do not end in a newline.

The adapted MicroPython libm closure preserves musl provenance separately
from its retained-source identity. `evidence/rp2/musl/v0.9.15/COPYRIGHT` is
the verbatim file from official musl tag `v0.9.15` (commit
`b589fb4e2999026494fa4bced90aeca9e613f754`, SHA-256
`3d6f953fd6af9b22396aaad9629e01fc67f8bfc0a9abd509d25cd38e32e7f003`).
The `v1.1.16` copy is from commit
`8fe1f2d79b275b7f7fb0d41c99e379357df63cd9` (SHA-256
`70ca142d257e2690a1f8eda8a296e64a6d1b16d8aee6784f8ddcf67f3163635d`).
The exact Sun/fdlibm grant and selected-source attribution are retained in
`texts/LicenseRef-PyBLE-Fdlibm-Sun.txt` and
`notices/rp2/libm-fdlibm.txt`. The exact Sun and MIT terms and MicroPython
adaptation attribution have been reviewed for the selected libm owners.

The Arm GNU evidence is from Arm's official 14.2.Rel1 source release at
`https://developer.arm.com/-/media/Files/downloads/gnu/14.2.rel1/srcrel/`.
The 311,500,280-byte source snapshot has SHA-256
`e6405f20f8a817a50d92dbf7974d0ee77708dfdf9e79900a59c5d343b464ef9c`.
The retained official manifest (SHA-256
`470cdb8bae9f5fed96c17b10834bbd22820e933cfad99914c3f37997cae36745`)
pins GCC commit `a05ea1e5ee0867191bb432a84c055be99dbdbc16` and newlib-cygwin
commit `7923059bff6c120c6fb74b63c7553ea345c0a8f3`. The GPLv3 and GCC
Runtime Library Exception files are byte-identical to those source-snapshot
files. `texts/COPYING.NEWLIB.arm-gnu-14.2.rel1.txt` is the snapshot's verbatim
`newlib-cygwin/COPYING.NEWLIB` (SHA-256
`fcfb5ec69b6ab52676dcc4dab7cf4338c8000ef97812dadd35b8592a640a8419`).
The locked Darwin Arm64 binary distribution remains independently pinned in
`firmware/versions.lock` by SHA-256
`c7c78ffab9bebfce91d99d3c24da6bf4b81c01e16cf551eb2ff9f25b9e0a3818`.

The current fail-closed review queue is: the CYW43 Raspberry Pi grant as
applied to the selected embedded firmware arrays, the complete pico-sdk CMSIS
source/header closure, and the exact GCC/newlib runtime closure. Their
evidence is retained, but none is represented as an approved release
conclusion. The target-scoped BTstack grant and the exact fdlibm/adapted-musl
classes are approved only for the hash-bound owner records above.
