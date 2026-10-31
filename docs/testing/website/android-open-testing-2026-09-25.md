<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Android open-testing publication review — 2026-09-25

## Observed status

The project owner confirms that PyBLE is published on Google Play. Current
first-party README and website copy still described an invited Android
internal test, while the public store listing described open testing.

The official [Google Play listing](https://play.google.com/store/apps/details?id=dev.pyble.pyble)
was retrieved over HTTPS on 2026-09-25 with English/US presentation parameters
(`hl=en&gl=US`). It returned HTTP 200 and identified **SciLabPro**, app version
**0.2.0**, and release notes stating **“Open testing for PyBLE 0.2.0.”** The
package is `dev.pyble.pyble`. This primary-source result supports the
owner-confirmed publication and supersedes the invited internal-testing copy.

The [AppAgg entry](https://appagg.com/android/education/pyble-micropython-ide-44135975.html?hl=en)
also lists version 0.2.0 and the same open-testing release notes, with a
2026-09-16 listing date. It is corroborating third-party indexing, not proof of
the exact rollout date or Play Console configuration.

## Current publication contract

- Describe Android as **PyBLE 0.2.0 published on Google Play for open testing**.
- Keep iPad described as the external TestFlight beta.
- Link directly to the existing official Google Play listing and encode the
  same destination in the neutral `/google-play/pyble-google-play-qr.svg` asset.
- Keep README, home, `/app`, metadata, setup guidance, and current distribution
  documentation consistent. Remove the invitation requirement from current
  Android installation guidance.
- Google Play determines account, country, device, and testing availability.
  Open testing does not establish a production-track release or universal
  availability.

The candidate opt-in endpoint redirected to Google sign-in. No signed-in
enrollment or on-device installation was verified in this review. The public
listing remains the link; no inferred opt-in destination is introduced.

## Source and evidence boundaries

At the original review, the repository's App source version was `0.2.0+8`. The public app version
`0.2.0` does not establish the installed store artifact's version code, source
commit, or inclusion of later connection-lifecycle fixes. The
[build-8 handoff](../google-play/0.2.0-build-8.md) and original submission
materials remain historical preparation records. Firmware versions and
qualification evidence remain independent of the app distribution channel.

This record documents availability and the coordinated content contract. It
does not attest a deployment, signed-in Play Console state, installed app
binary, or hardware-validation result. Search engines control when indexed
snippets refresh after updated pages are published.

## 31 October 2026 public-page recheck

A fresh HTTPS GET of the [official Google Play listing](https://play.google.com/store/apps/details?id=dev.pyble.pyble&hl=en&gl=US)
at 11:46 UTC returned HTTP 200. Its English/US release notes still describe
`0.2.0` open testing, with 16 September 2026 shown as the update date. This
reconfirms the public copy baseline; it does not identify the current delivered
version code, account eligibility or binary. The `0.3.0+9` app candidate remains
under [release preparation](../../developments/2026-q4-reliable-workflow/c1-s2/06_Release_Readiness.md).

Raw response and receipt: ignored
`local/recovery-completion/public-channel-recheck/play.html` and
`play-receipt.json`; response SHA-256
`270403bcba91faa4c8b9c7eb0ce8aa0882a3d3251c23623faf346e8a62d8b659`.
No enrollment, installation or store mutation was performed by this recheck.
