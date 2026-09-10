# PyBLE Google Play Data safety working assessment

Prepared 2026-09-10 for the Android open-testing candidate. This is a source
audit and a proposed declaration worksheet, not a submitted or certified Play
Console form. Reconcile it with the exact signed bundle, all active versions
covered by the package-level form, endpoint behavior and the final Console
questions before submission.

## Why the internal-testing answer needs review

The move to open testing requires a Data safety form. Google defines
collection by off-device transmission, including direct third-party requests.
A user-initiated-transfer exception to **sharing** does not itself exempt
**collection**. Local-only processing is different from transmission to a
nearby board. [Google Data safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en).

PyBLE's lack of accounts, telemetry and a developer backend is verified by the
reviewed app source; those facts alone cannot justify checking "no data
collected." Optional GitHub HTTP traffic and intentional BLE transfers need
their own assessment.

## Observed app data flows

| Flow | App source behavior | Destination and retention boundary |
| --- | --- | --- |
| Python editing | In-memory document state, selection and editor settings; syntax highlighting is local | App memory; no implemented durable local project database. |
| BLE discovery | Scan filtered to PyBLE service; display board name, radio signal and connection identity | Nearby board-to-app communication; app does not send scan results to an internet endpoint. |
| Files and Run | Source text, board paths, filenames and control commands go to the chosen board after user action | Connected board; saved files persist there until removed, changed or erased. |
| Blocks | Bundled Blockly assets run locally; generated Python and companion JSON are saved to the board explicitly | Local WebView and selected board; no remote Blockly script or analytics endpoint. |
| Console input | User-entered stdin is sent to the board | Board/user program; user code can retain input. |
| Existing board labels | Displayed from nearby board advertisements; no implemented app rename/set-label flow | Local discovery UI; the board may advertise a label configured outside this app. |
| Console output and board information | Board output and facts displayed in the app | Board to app; no authored automatic crash/diagnostic upload. |
| Public GitHub import | HTTPS GET to exact `api.github.com`, only after opening importer; public repository/ref/tree/blob selectors and app-version User-Agent | GitHub handles network/request metadata independently; no credentials, cookies, board facts or private project source are sent. |
| About/privacy/licenses | Bundled/offline content and policy URL | No new HTTP client required for reading the in-app policy. |
| Support email/public issues | User chooses to contact the maintainer outside the app | Contact provider/project support process, distinct from an automatic in-app upload. |

Sources: [`app/pubspec.yaml`](../../app/pubspec.yaml),
[`AndroidManifest.xml`](../../app/android/app/src/main/AndroidManifest.xml),
[`app/lib/github_import/`](../../app/lib/github_import/),
[`app/lib/blocks/`](../../app/lib/blocks/),
[`app/lib/data/`](../../app/lib/data/),
[`app/lib/pble/`](../../app/lib/pble/),
[PBLE/1 security boundary](../specifications/protocol.md#10-security-note-v1)
and the [public privacy policy](https://pyble.dev/privacy).

The current manifest does not opt out of Android backup defaults. Do not
claim that operating-system backup or device-provider handling is disabled.
The public privacy policy separates platform/store handling from the app.

## Proposed form answers

This is a complete recommended declaration for owner review. The board and
GitHub tables below specify all five proposed data types and their handling.
Where a provider's published policy is broader than its API documentation,
the recommendation identifies the conservative inference explicitly. The
owner must review and attest the final Console form against the artifact.

| Console topic | Proposed answer | Basis or outstanding decision |
| --- | --- | --- |
| Does the app collect or share any required user-data types? | **Yes**, under a conservative interpretation | Source files and related user input leave the Android device for the board; optional GitHub requests also leave it. |
| Account creation | **No account creation** | No PyBLE login, authentication provider, credentials or subscription. |
| All collected data encrypted in transit | **No** | GitHub uses HTTPS, but PBLE/1 does not require paired/encrypted BLE. Do not claim universal encryption. |
| Independent security review | **No** | No qualifying independent security assessment has been established. Project tests are not this badge. |
| Families commitment | **Do not assert pending audience/compliance review** | No review establishes the applicable Families obligations for the selected ages/countries. |
| Account-deletion URL | **Not applicable to account creation** | No accounts exist; do not invent an account-deletion service. |
| Data deletion request mechanism | Proposed **No** for a centralized request mechanism covering the data types declared here | Board-file deletion and local app clearing are user controls; the maintainer cannot delete the user's board contents or GitHub metadata. The public support contact does not establish that capability. |
| Advertising/marketing collection | **No in the audited app source** | No ads, advertising SDK or advertising identifier access. Reassess any independently disclosed endpoint purpose. |

Google's collection, encryption, optionality and deletion questions use
specific definitions. A feature controlled by the user is not automatically
"optional" when its data is required for the app's principal function.
[Google Data safety guidance](https://support.google.com/googleplay/android-developer/answer/10787469?hl=en).

### Board transfer categories

The following mapping is an inference from the app's implemented transfers,
not a ruling from Google about PyBLE:

| Data type | Collected | Shared | Required/optional | Purpose | Ephemeral |
| --- | --- | --- | --- | --- | --- |
| Files and docs | Proposed **Yes** for source files, paths, names and Blocks companion records sent to the board | Proposed **No**, where only the user's explicit transfer to their selected board occurs | Conservatively **Required**: board-file operations are central to this connection-gated IDE | App functionality | **No**; board files persist. |
| Other user-generated content | Proposed **Yes** for console input | Proposed **No**, where the transfer is clearly user-initiated and expected | **Optional** for stdin; user can edit/run programs without supplying console input | App functionality | **No** as a blanket answer; user code may retain it. |

The no-sharing proposal relies on the actual user action and destination being
clear. It must not be generalized to unrelated SDK handling or independent
endpoint processing. Do not label source files "ephemeral" because the app
buffer is in memory when the board deliberately saves them.

### GitHub metadata: complete conservative recommendation

**API-specific facts.** The app makes public repository/ref/tree/blob requests
with an app-version User-Agent. GitHub associates unauthenticated REST calls
with their originating IP and enforces a 60-request hourly limit to protect
service availability and prevent abuse. Request counting spans individual
responses, so this is not solely transient packet routing.
[GitHub REST rate limits](https://docs.github.com/en/rest/using-the-rest-api/rate-limits-for-the-rest-api?apiVersion=2026-03-10).

**Broader published handling.** GitHub's policy covers service use through
IDEs, describes request/IP usage data, IP-based general-location inference,
service improvement and security processing. Its policy does not provide an
endpoint-by-endpoint inventory. The analytics and approximate-location
entries below are conservative inferences from that statement, not evidence
that every unauthenticated PyBLE request is geolocated or used for analytics.
[GitHub privacy statement](https://docs.github.com/en/site-policy/privacy-policies/github-general-privacy-statement).

| Data type | Collected | Shared | Required/optional | Collection and sharing purposes | Ephemeral |
| --- | --- | --- | --- | --- | --- |
| App activity → App interactions | **Yes**: repository/branch/tree/file request activity | **Yes** | **Optional** | App functionality; Analytics; Fraud prevention, security, and compliance | **No** |
| Device or other IDs | **Yes**: originating IP used to associate requests; conservative mapping to this category | **Yes** | **Optional** | App functionality; Analytics; Fraud prevention, security, and compliance | **No** |
| Location → Approximate location | **Yes**, conservatively covering GitHub's published IP-location inference | **Yes** | **Optional** | Analytics; Fraud prevention, security, and compliance | **No** |

For each of these rows, select the listed purposes for both collection and
sharing if Console asks separately. The app-functionality purpose belongs to
fetching public source; PyBLE does not need physical location for that feature.
Security and request association have API-specific support. Analytics and
IP-derived location are deliberately broader provider-policy inferences.
GitHub also documents IP-derived location for trade compliance, although its
examples concern accounts and do not establish anonymous-API implementation.
[GitHub trade controls](https://docs.github.com/en/site-policy/other-site-policies/github-and-trade-controls).

The **Shared: Yes** recommendation avoids asserting that GitHub's independent
metadata handling is covered by the explicit-user-transfer or service-provider
exception. It does not change the separate no-sharing proposal for source
sent only to the user's board. **Optional** reflects that the entire GitHub
workflow can be skipped. **Ephemeral: No** covers the documented request
counter and makes no unsupported real-time-only retention promise for logs
or inferred data. No exact log-retention period is claimed.

Use **App interactions** for these fetch/selection events; do not also select
In-app search history or Web browsing history for the same activity. The
importer is not a general browser or a separate search-history feature. Do not
select User IDs merely because a public repository owner's name appears in a
request: that is a resource selector and need not identify the app user.

This proposal does not select advertising/marketing, personalization, account
management or developer communications for the integration. The reviewed
requests contain no cookies, login credentials or user contact details and
load no marketing pages, ads or personalized recommendations. GitHub's
website-cookie and enterprise-marketing descriptions should not automatically
be assigned to this API flow. That evidence boundary is not a guarantee about
undocumented provider processing.

**Owner attestation:** accept or revise this complete recommendation, record
the rationale, and compare the final form with the public and in-app policy.
Those policies already disclose GitHub request/IP metadata under GitHub's
own policy; verify that the final presentation makes the provider's role
clear alongside the app's lack of a telemetry SDK. If GitHub supplies narrower
authoritative API guidance, update the form and policy together as needed.
A network trace can confirm outbound fields and destinations, but cannot
establish the provider's retention or secondary uses.

Users can delete board files in Files and clear/uninstall local app data.
Requests concerning GitHub-controlled data can be sent to
`privacy@github.com` under GitHub's rights process. The PyBLE maintainer cannot
promise to erase those third-party records. No app account-deletion service
is needed because PyBLE creates no app account.

### Types not observed in the authored app

No implemented app feature requests contacts, calendar, camera, microphone,
photos/videos, SMS/call logs, health data, financial data, race/religion/sexual
orientation, installed-app inventories, an advertising ID or precise device
location. There is no automatic analytics/crash-reporting SDK in the reviewed
dependency set. User-written Python can contain arbitrary text; do not claim
the app analyzes that text to infer these sensitive categories.

This observation is limited to the audited source and dependencies. It does
not cancel the GitHub metadata issue above or replace the merged release
manifest/native SDK inventory review.

## Android permission worksheet

| Declared permission/feature | Scope and truthful explanation |
| --- | --- |
| `BLUETOOTH_SCAN` | Discover compatible nearby PyBLE boards; declares `neverForLocation`. |
| `BLUETOOTH_CONNECT` | Connect and communicate with the board the user selects. |
| `BLUETOOTH`, `BLUETOOTH_ADMIN` | Legacy Bluetooth permission path through Android 11/API 30. |
| `ACCESS_FINE_LOCATION` | Legacy BLE scan requirement through API 30; no app location derivation. |
| `ACCESS_COARSE_LOCATION` | Legacy scan compatibility through API 28. |
| `INTERNET` | User-started public GitHub import using HTTPS; ordinary editing/BLE/Files/Blocks work offline. |
| BLE hardware | Required feature; classic Bluetooth and location hardware are explicitly optional. |

No background location, all-files access, foreground service, VPN,
accessibility service or advertising-ID permission is declared in the audited
main manifest. Review the **merged release manifest** after building because
dependencies can add permissions. Runtime accessibility support through
TalkBack is not an accessibility service.

The candidate's merged manifest also includes
`dev.pyble.pyble.DYNAMIC_RECEIVER_NOT_EXPORTED_PERMISSION`, declared with
`signature` protection and requested by the app for AndroidX receiver
protection. This is an app-defined permission, not another dangerous Android
permission or a grant to access personal data. Record it alongside the seven
Android permissions above in the final artifact inventory.

## Audience dependency

The proposed ages 13–15, 16–17 and 18+ describe the intended open-test audience
only if the owner confirms them. The project personas do not establish ages.
Google notes that teenagers may still be considered children in some locales;
age choices and supported countries must be assessed together.
[Target audience guidance](https://support.google.com/googleplay/android-developer/answer/9867159?hl=en).

The current BLE adapter uses scanning directly, not Android Companion Device
Manager. Google's Families policy includes a Companion Device Manager
condition for Bluetooth requests in apps within Families scope, including
mixed audiences containing children. Adding child-directed audiences therefore
requires a specific implementation and policy review; selecting ages solely
to avoid that review would not resolve it.
[Families policy](https://support.google.com/googleplay/android-developer/answer/9893335?hl=en).

## Retained attestation

Before submitting, record outside Git:

- reviewer/owner name, date, package, final version code and AAB SHA-256;
- inspected merged manifest and dependency/native SDK inventory;
- each final Data safety category, purpose, required/optional and sharing
  choice, including the GitHub endpoint determination;
- policy URLs and in-app policy screenshots for the exact artifact;
- accepted audience/countries and applicable Families determination;
- final Console preview/export, submission status and later review feedback.

Keep screenshots containing private account/Console details in the ignored
publication workspace. Reassess this worksheet whenever a feature, dependency,
endpoint, audience or release artifact changes.
