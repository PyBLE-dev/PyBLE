<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Reviewed website dependency license texts

These third-party license texts retain their own licenses. They are stored
locally because the exact published dependency or adapter bundle omits them;
website generation reads these files without fetching remote text.

| Dependency                                                        | Reviewed source                                                                                                                                                                 | Exact bytes | SHA-256                                                            |
| ----------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ----------- | ------------------------------------------------------------------ |
| `@resvg/resvg-wasm@2.4.1`                                         | [Upstream v2.4.1 LICENSE at commit `2347b417e1955a6954223f1c17b815e177a01765`](https://raw.githubusercontent.com/thx/resvg-js/2347b417e1955a6954223f1c17b815e177a01765/LICENSE) | 16,724      | `4b89d4518bd135ab4ee154a7bce722246b57a98c3d7efc1a09409898160c2bd1` |
| `image-size@2.0.4`, bundled by Vinext 1.4.0                       | `package/LICENSE` in the [official npm tarball](https://registry.npmjs.org/image-size/-/image-size-2.0.4.tgz)                                                                   | 1,112       | `3109783dad7527b490aabc49c3cb148573c19b41b843e70cf9388a93f3d7fccd` |
| `fflate@0.7.3`, inflate-only subset bundled by `@vercel/og` 1.0.3 | `package/LICENSE` in the [official npm tarball](https://registry.npmjs.org/fflate/-/fflate-0.7.3.tgz)                                                                           | 1,069       | `62249119bb7df6e54300f37a37145c26a6d4420410aac8881a119c5b427cf751` |

The resvg source is the full Mozilla Public License 2.0 from the immutable
commit behind [the v2.4.1 tag](https://github.com/thx/resvg-js/blob/v2.4.1/LICENSE).
Its missing package license must not be substituted with another dependency's
MIT text. The generator checks its exact package version and source digest;
the build regression checks the complete package-specific published notice.

The image-size text is the full MIT license and copyright notice extracted
from the exact published package. Its reviewed bundle path is tied to both the
parser version and the owning Vinext version. Dependency upgrades require
renewed source, digest, and notice review.
