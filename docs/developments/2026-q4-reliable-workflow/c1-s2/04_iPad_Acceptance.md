<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# iPad recovery acceptance continuation

| Field | Record |
|---|---|
| Date | 31 October 2026, Asia/Bangkok |
| Scope | Remaining normal-app recovery and affected workflow observations for PYB-006.2 / PYB-008.1 |
| Current outcome | Candidate installation and launch pass; automated native UI execution awaits the device owner's iPadOS authentication |
| Source | PR #40 merged at `6f5b3ea73a70342331fb49d0685938ce2a4cae11`; subsequent planning changes do not change app runtime bytes |
| Candidate | PyBLE Preview `0.3.0 (9)`, normal `lib/main.dart`, signed profile mode, isolated `dev.pyble.recoveryqualification` identity |
| Physical platform | iPad Air 13-inch (M4), model `iPad16,10`, iPadOS `26.6.2` |
| Operator | Automated engineering run on the maintainer's Mac; no independent human review or participant observation claimed |
| Prior results | [Platform observations](02_Platform_Qualification.md); native storage seed/kill/verify is distinct from normal-app interaction acceptance |

## Candidate and initial state

The signed app archive is retained privately as
`local/recovery-implementation/ipad-preview-0309/PyBLE-Preview-0.3.0-9-profile.app.zip`.
Its SHA-256 is
`c91bc6f7e14f421a528668bd3723e3f965d55f79f11ea90fec707a8fb15a4d1a`.
The copied Dart runtime matches merged source; only the isolated native identity
and display name distinguish the installation. Signature verification,
installation and foreground launch passed. The disconnected scan displayed all
five board labels. Discovery alone does not establish a connection or completed
board workflow.

The existing TestFlight `dev.pyble.pyble` installation remains version
`0.2.0 (6)`. The Preview application support files were copied privately before
continuation. The copied SQLite database passes `integrity_check` and contains
zero draft rows and zero content bytes. No storage reset, user-data deletion or
board write was used to establish that initial state.

## Native UI runner attempt

| Step | Actual observation |
|---|---|
| Build | Native XCTest helper builds successfully against the connected physical-device SDK; it operates the separately installed normal app |
| Runner startup | Signed helper starts on the iPad |
| OS authentication | iPadOS displays **Touch ID for “XCTest” — Enable UI Automation** |
| Result | Runner initialization times out after 60 seconds while enabling automation mode; the test body does not run |
| Classification | Operator-access dependency, not a failed PyBLE recovery assertion |
| Required action | Device owner authenticates the iPadOS prompt; retry the retained test and then execute the remaining workflow steps |

The owner was asked to authenticate on the device. No passcode or biometric
material was requested, captured or substituted. Raw screenshots and the
`.xcresult` remain in ignored `local/recovery-completion/ipad/`; they are not
public documentation assets.

## Acceptance accounting

| Evidence | State after this attempt |
|---|---|
| Installed normal candidate, version and signature | Pass, limited to the local Preview identity |
| Foreground launch and five-board discovery | Pass, disconnected discovery only |
| Native storage process termination/reopening | Prior passing seed/verify evidence retained in the platform report |
| DR-T12 normal Blocks-to-Editor checkpoint/relaunch | Not run in this continuation; native UI access pending |
| DR-T14 normal offline Restore and physical current-board consent | Not run in this continuation; native UI access pending |
| Remaining applicable P01–P15 steps | Execute and record actual outcomes after UI authorization; the prepared test is not execution evidence |
| Five-profile iPad release rows | Pending; no qualification inferred from the five scan results |
| M-02 / release admission | Remain pending until mandatory evidence and review are complete |

The [operator recipe](01_Operator_Recipe.md) and
[normative scenario matrix](../../../specifications/App/current-draft-recovery.md#7-required-evidence-before-acceptance)
remain the acceptance authority. This record does not change their requirements.
