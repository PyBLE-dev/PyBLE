<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# PyBLE: Implementation Plan and Development Strategy

> **North Star:** Make a tablet a first-class development tool for nearby MicroPython hardware through a reliable, open, BLE-first workflow.
>
> **Execution principle:** Prove successful use before expanding features; prove repeatable compatibility before expanding the ecosystem.

## Document control

| Field | Value |
|---|---|
| Document version | 1.8 — accepted bounded recovery and app-only qualification; channel/pilot continuation; original filename retained |
| Prepared | 25 September 2026 |
| Last reviewed | 31 October 2026; bounded M-02 and app-only M-04 engineering acceptance recorded with exact candidate, firmware and OEM test conditions; device closeout complete; [PR #41](https://github.com/PyBLE-dev/PyBLE/pull/41) merged after all 36 checks on its final head passed; channel delivery pending |
| Status | C1-S1 has six tasks Done, two Prepared awaiting pilot setup and four Awaiting evidence; Sprint and SG0 remain unfinished. Bounded recovery and app-only qualification pass scoped engineering review; device closeout is complete. [PR #41](https://github.com/PyBLE-dev/PyBLE/pull/41) merged after all 36 checks on its final head passed. Actual channel delivery remains pending. Human capacity and recruitment dates need replanning; no new protocol behavior approved |
| Product | PyBLE — Python over Bluetooth Low Energy |
| Organization | SciLabPro |
| Planning horizon | Immediate 12-week delivery cycle, followed by conditional expansion through September 2028 |
| Proposed first cycle | 28 September–20 December 2026; all dates use Asia/Bangkok |
| Accountable role | Project owner / lead maintainer; role assignment does not imply availability has been committed |
| Repository baseline inspected | `PyBLE-dev/PyBLE`, `main` at `23ed764b0ef88dce9720c66fbd1c0655268860cf` |
| Repository location | `docs/planning/PyBLE_Implementation_Plan_and_Strategy_v1.0.md` |
| Review cadence | Sprint review every two weeks; strategic review after each stage gate |

**Scope of this document.** This plan converts the preceding PyBLE strategy discussion into executable workstreams, priorities, acceptance criteria, and decision gates. Existing repository specifications and contributor rules remain authoritative. Proposed features, names, metrics, staffing, and dates below are planning choices—not claims that those features exist or that resources and approvals are secured.

**Evidence boundary.** The baseline review inspected repository source, specifications, test entry points, publication records, and the GitHub state of PR #33 and issue #24 on 25 September. Revision 1.2 incorporates the subsequent strategy and PyBLE Ready feedback. The dated Android publication review establishes listing status only. Revision 1.3 records direct live-channel/website checks and the original unavailable/locked device attempts. Revision 1.4 adds the connected-device retry in the [C1-S1 ledger](../developments/2026-q4-reliable-workflow/c1-s1/01_Channel_and_Artifact_Ledger.md): existing Play `0.2.0 (8)` and TestFlight `0.2.0 (6)` installations and launches verified. Fresh enrollment/reinstallation was not performed. Android's code/asset comparison supports historical source mapping; iPad source mapping remains unknown. No participant outcome was measured in that baseline review. The subsequent [C1-S2 record](../developments/2026-q4-reliable-workflow/c1-s2/00_Execution_Record.md) adds candidate-specific native storage/restart and board-workflow observations, PR #40 merge evidence and successful integrated CI. Those engineering observations do not supply participant outcomes. Previously reported publicity and GitHub counts are not proof of product-market fit.[^android-review]

**Continuation decision.** Carry forward the completed Android publication/copy correction. Concentrate weekly execution on three outcomes: verify what users install, preserve their work through interruptions, and observe useful repeat tasks in one primary audience. Reuse existing lifecycle handling, tutorials, conformance fixtures, and release tooling. A bounded PyBLE Ready rehearsal can reuse one existing profile's evidence work; new ports, broad badge promotion, classroom bundles, and new protocol behavior remain conditional.

| Revision | Change |
|---|---|
| 1.0 | Initial strategy and proposed 12-week program |
| 1.1 | Updated baseline after PR #33; separated publication from installed-build evidence; mapped remaining work to current code; bounded the schedule and corrected release/pilot dependencies |
| 1.2 | Focused pilot selection and useful second tasks; contextualized retention; defined one version-bound PyBLE Ready badge, installation labels, maintenance rules, and a staged existing-profile/partner pilot |
| 1.3 | Executed C1-S1 repository deliverables in parallel worktrees; recorded device/pilot blockers, stale TestFlight metadata, a bounded recovery contract and larger engineering/matrix estimates; future allocations require replanning |
| 1.4 | Verified existing Play/TestFlight installations on connected tablets; recorded artifact evidence and remaining provenance/metadata limits; replaced blanket pilot blockers with Prepared/Awaiting evidence states without waiving acceptance criteria |
| 1.5 | Implemented bounded current-text recovery for source candidate 0.3.0+9; added candidate execution/operator records; preserved remaining pilot, platform and release gates |
| 1.6 | Reconciled PR #40 merge, passing integrated CI and both local tablet candidates; selected acceptance → qualification → distribution continuation, with human capacity and participant evidence still explicit |
| 1.7 | Recorded normal-app acceptance progress and exact current firmware inputs for app-only compatibility; tracked prepared signed artifacts and remaining candidate, release and channel evidence without inventing pilot results |
| 1.8 | Accepted bounded recovery and the declared ten-row app-only matrix after actual platform checks and scoped engineering review; moved remaining release work to final integration and M-05, preserving pilot gaps and original forecasts |

## Contents

1. [Strategic decision](#1-strategic-decision)
2. [Starting point and evidence gaps](#2-starting-point-and-evidence-gaps)
3. [Target users and positioning](#3-target-users-and-positioning)
4. [Objectives and measurement](#4-objectives-and-measurement)
5. [Architecture and engineering boundaries](#5-architecture-and-engineering-boundaries)
6. [Release and protocol strategy](#6-release-and-protocol-strategy)
7. [Workstreams and deliverables](#7-workstreams-and-deliverables)
8. [Twelve-week implementation schedule](#8-twelve-week-implementation-schedule)
9. [Prioritized implementation backlog](#9-prioritized-implementation-backlog)
10. [Quality, compatibility, and release gates](#10-quality-compatibility-and-release-gates)
11. [Security and physical safety](#11-security-and-physical-safety)
12. [Pilot and adoption strategy](#12-pilot-and-adoption-strategy)
13. [Documentation and international reach](#13-documentation-and-international-reach)
14. [PyBLE Ready and partner development](#14-pyble-ready-and-partner-development)
15. [PyBLE Classroom](#15-pyble-classroom)
16. [Research and publication program](#16-research-and-publication-program)
17. [Sustainability and commercial validation](#17-sustainability-and-commercial-validation)
18. [Team, capacity, and operating process](#18-team-capacity-and-operating-process)
19. [Risks and strategic decision gates](#19-risks-and-strategic-decision-gates)
20. [Immediate execution checklist and handoff](#20-immediate-execution-checklist-and-handoff)
21. [Source references](#21-source-references)

---

## 1. Strategic decision

### 1.1 The direction

Develop PyBLE as an **open, vendor-neutral mobile development platform for MicroPython over BLE**, while keeping the tablet application the primary product and the main source of user feedback.

The long-term platform consists of three essential layers: the PyBLE app, the PBLE protocol, and the board-side agent. Conformance tooling, example collections, classroom resources, and partner ports support those layers. They do not justify a premature rewrite, repository split, or new collection of standalone products.

The first commercial and educational hypothesis is deliberately narrow:

> After an instructor, vendor, or user provisions a compatible board, a learner or maker can repeatedly edit, transfer, run, and inspect MicroPython code from a tablet without a cable or Wi-Fi setup in the normal development loop.

The initial provisioning and recovery steps remain part of the complete user journey. “Wireless development” must never become a promise of “no computer or cable ever required.”

### 1.2 Priorities in order

1. **Reliable first use:** make the existing installation-to-first-program journey understandable and repeatable.
2. **Trustworthy execution and recovery:** preserve files, drafts, and clear connection/run state when things fail.
3. **Repeat use:** establish whether people return to PyBLE for a second real task.
4. **Reproducible compatibility:** turn existing tests and hardware evidence into a reusable conformance process.
5. **Selective expansion:** add classroom workflows and partner ports only after the core workflow is demonstrated.

### 1.3 What the strategy does not assume

Media coverage is evidence of attention, not necessarily use. Stars and forks indicate repository interest, not successful hardware sessions. An app-store download bucket does not establish the number of independent, active, or retained users. CSDN article volume and aggregate read counters do not establish technical validity, unique readers, or adoption.

Likewise, an open protocol is a potential ecosystem foundation—not automatically a defensible moat or emerging standard. The platform hypothesis becomes credible when another engineer can implement or maintain a compatible component and another user can operate it successfully.

### 1.4 Explicit non-goals for the first cycle

Do not build a desktop IDE replacement, GDB/JTAG/SWD debugger, mandatory cloud account system, cloud project storage, plugin marketplace, or AI-first coding experience. Do not undertake universal BLE firmware flashing, broad board-family expansion, or industrial remote maintenance. Do not introduce paid or closed application features; that would conflict with the current contributor rules.[^agents]

Revisit deferred ideas only with a demonstrated user problem, an owner, a maintenance budget, and an approved design.

### 1.5 Three active outcomes

Use this table for weekly prioritization; the remaining workstreams are reference material and conditional options.

| Active outcome | Evidence of progress | Existing backlog |
|---|---|---|
| Verify what users install | Dated channel/build record and a reproducible installation path; unresolved provenance has an owner | PYB-001 and any residual 002 |
| Preserve users' work | Bounded A-24 draft recovery and applicable interruption/recovery checks on recorded artifacts | PYB-006, supported by 008/009 |
| Demonstrate useful repeat use | One primary cohort completes a meaningful task, attempts another, and explains the benefit or obstacle relative to its previous workflow | PYB-003/004/011/012; 005 if observations justify it |

Required qualification accompanies delivery. PyBLE Ready preparation should reuse PYB-009's operator work and an existing profile. Additional reporting, new infrastructure, translations, research, and partner intake need an explicit capacity allocation; document completeness is not the product outcome.

## 2. Starting point and evidence gaps

### 2.1 Repository-grounded baseline

The inspected repository already contains the following capabilities and development direction.[^readme][^public-roadmap]

| Area | Existing baseline | Consequence for implementation |
|---|---|---|
| Tablet app | Flutter app; historical source baseline `0.2.0+8`; merged candidate `0.3.0+9` | Improve and qualify the existing app rather than create a new client |
| Distribution | Android 0.2.0 published on Google Play for open testing; iPad external TestFlight beta | Verify installed build identity separately; production-track availability is not claimed |
| Normal workflow | BLE discovery, PBLE/1 connection, editor, files, run/stop, soft reboot, console | Measure and repair the complete workflow, not isolated features |
| Mobile state | Session ownership and connection retirement protections already implemented; current-text recovery merged in the `0.3.0+9` source candidate | Qualify bounded recovery on recorded platform candidates; retain full-state obligations |
| Learning | Blockly, tutorials, reviewed screenshots, official examples repository | Improve discoverability and completion; do not duplicate the Learning Center |
| Import | Reviewed, SHA-pinned public GitHub `.py` import | Preserve preview, explicit overwrite approval, and non-execution on import |
| Firmware | Public v0.6.1 recorded as owner-confirmed | Preserve the distinction between publication and complete automated qualification |
| Release profiles | Five exact hardware profiles, including four ESP profiles and Pico 2 W | Treat exact configurations—not chip-family names—as the support unit |
| Architecture | Monorepo with app, firmware, protocol, tests, website, and documentation | Keep changes atomic across components |
| Governance | Specification-first, red/green/refactor, DCO, clean-room and license gates | Integrate the plan with existing contribution rules |
| Next firmware direction | v0.7.0 “Reliable Projects” is proposed, not approved | Select and approve scope before implementing new behavior |

The existing five profiles are `esp32-4mb`, `esp32-s3-n16r8`, `waveshare-esp32-s3-lcd-147b`, `esp32-c3-4mb`, and `rpi-pico2-w`. Preserve their documented flash, PSRAM, revision, and exact-board constraints. Board image identity is not physical-board detection or authorization.[^readme]

### 2.2 Completed work and remaining verification

Use the following dated baseline instead of restarting the publication correction:

| Item | Status as reviewed on 25 September 2026 | Remaining work |
|---|---|---|
| Android listing / installation | Official Play listing identifies 0.2.0 open testing; retry verifies an enrolled Lenovo device's existing `0.2.0 (8)` installation and launch | Record existing-install scope; retain code/asset comparison and its provenance limits; no fresh enrollment/reinstall or universal availability claim |
| Maintained public copy | PR #33 merged at `23ed764`; README, roadmap, website copy/metadata, setup guidance, and distribution contract now agree | Maintain those checks; search-engine recrawl timing remains outside project control |
| iPad channel / installation | Retry verifies the external TestFlight beta's offered/installed `0.2.0 (6)` and launch on iPad | Source mapping remains unresolved; review conflicting minimum-OS metadata. Existing-install verification does not claim a fresh enrollment/reinstall |
| Firmware v0.6.1 | Published on owner confirmation; five exact profiles; original artifact/evidence records preserved | New qualification must cite exact tested bytes; pending automated rows remain pending |
| Issue #24 | Closed on 13 September 2026 as superseded (`NOT_PLANNED`) | Create a focused successor only for selected new work; do not reopen the obsolete release umbrella or mark its checklist complete |
| Product usage | No measured activation or retention baseline in this revision | Collect the bounded, consented evidence defined in §§4 and 12 |

The public listing supports an **availability claim**; a successful installation supports an **installation claim**; source/build mapping supports an **artifact-provenance claim**; physical tests support a **compatibility claim**. Do not substitute one for another. A prepared `0.2.0+8` artifact does not prove that a store currently serves that artifact or includes later lifecycle fixes.[^android-review][^pr33][^publication]

Historical release-roadmap statements about an unpublished v0.6.1 or an open #24 are superseded by the dated publication record, current public roadmap, and issue closure. Preserve historical evidence when adding a supersession note; do not change old outcomes retrospectively.[^public-roadmap][^issue24]

**Output:** extend this baseline into a dated channel/artifact matrix with evidence links, owner, verification date, and separate publication/install/provenance/qualification fields. Mark unresolved fields `unverified`, and physical scenarios `not_run` or `blocked`.

### 2.3 C1-S1 execution evidence — 25 September 2026

The [execution record](../developments/2026-q4-reliable-workflow/c1-s1/00_Execution_Record.md) now records **six Done tasks**, **two Prepared awaiting pilot setup** and **four Awaiting evidence** after the connected-device retry. T02/T03 verify existing channel installations; T04/T05 need the named owner, cohort and tested board setup, T06–T08 need participant sessions, and T09 needs their observation records. Early execution does not retrospectively change the proposed 28 September Sprint start or claim a staffed-team ceremony.

| Workstream | Completed output / evidence | Remaining requirement |
|---|---|---|
| PYB-001 | Reviewed ledger; [Lenovo Play `0.2.0 (8)`](../developments/2026-q4-reliable-workflow/c1-s1/06_Android_Channel_Verification.md) and [iPad TestFlight `0.2.0 (6)`](../developments/2026-q4-reliable-workflow/c1-s1/07_iPad_Channel_Verification.md) existing installations, channel/Open and launch verified | iPad build-to-source mapping remains unknown; Android code/asset correspondence does not establish complete binary equivalence or store-console provenance. Fresh enrollment/reinstallation was not performed |
| Residual PYB-002.1 | Accurate replacement TestFlight app-level description prepared after the public page exposed its older ESP/agent-0.4.0 baseline | Distribution owner must apply it and verify the public result; also reconcile build-6 installed `MinimumOSVersion` 18 with TestFlight notes stating 15 before asserting support. No store mutation performed; Android's earlier correction remains complete |
| PYB-003/004 | Operational pilot protocol, safe Tasks A/B/C, consent/retention rules and empty observation/support templates | Human owner, reachable cohort, tested setup and collection decision unconfirmed; no participants or observed outcomes |
| PYB-006.1 | [Recovery contract](../specifications/App/current-draft-recovery.md), ADR-0048, source/peer review, scenario matrix and estimate | Bounded implementation now tracked in the [C1-S2 record](../developments/2026-q4-reliable-workflow/c1-s2/00_Execution_Record.md); scoped engineering acceptance is recorded; broader A-24/Blocks scope and actual channel delivery remain carried |
| PYB-009.1 | Existing tool/gate inventory, ten platform/profile rows, cost model and initial operator recipe; 110 focused host harness tests pass | S2 now supplies the scoped procedure and actual connected-device observations; scoped candidate acceptance is recorded; optional independent reproduction remains separate |

The recovery estimate is **38–63 engineering hours**, or **45–72 hours** with the original recipe, representative-platform and follow-up allowances. The [design review](../developments/2026-q4-reliable-workflow/c1-s1/03_Recovery_Design_and_Sizing.md) offers a conditional 60-hour S2–S4 allocation, displacing earlier matrix and activation forecasts. The [validation inventory](../developments/2026-q4-reliable-workflow/c1-s1/04_Validation_Inventory_and_Operator_Recipe.md) estimates 13.5–26 operator hours for the app matrix and 30–59 for fresh full firmware qualification, excluding builds, unavailable access and defect repair. These are working estimates, not actual effort or promises. **SG0 remains blocked.**

The Android check used a Lenovo `TB-J616X` on Android 12; all 38 selected code/asset entries matched the retained build-8 AAB, supporting its historical source `768fafe45beee7731d1a38480cc0463a2f5680cd`. This comparison is narrower than complete installed-binary or Play Console provenance. The iPad was `iPad16,10` on iPadOS `26.6.2`; native TestFlight offered build 6 with Open, separate app launches succeeded, and the installed signer identity was `TestFlight Beta Distribution`. The historical build-5 handoff does not map build 6 to source. Neither check executes BLE/board qualification or establishes minimum-OS support.

### 2.4 Baseline metrics to collect

Record current store channels, download buckets where visible, repository engagement, issue authorship, and existing third-party demonstrations. Establish separate counts for maintainers, project-recruited testers, classroom participants, and independently arriving users.

Do not spend the first sprint rebuilding a large analytics dashboard. A small private pilot register plus a public aggregate status report is sufficient.

### 2.5 Implementation map: reuse first, then close the gap

| Area and inspected source | Already present | Remaining work for this plan |
|---|---|---|
| [Connection manager](../../app/lib/pble/connection_manager.dart) | Session ownership, stale acquisition protection, serialized connection retirement | Observe failures and extend targeted regressions; preserve the existing `Connection` seam |
| [Editor document](../../app/lib/editor/editor_document.dart), [ADR-0010](../decisions/0010-working-loop-in-memory-document.md), [recovery storage](../../app/lib/data/drift_draft_repository.dart) | One current-text recovery slot implemented with atomic Drift transactions | Verify candidate durability, failure and platform evidence; full projects/Blocks persistence remains deferred |
| [PBLE connection](../../app/lib/pble/pble_connection.dart) | Transfer fails on link loss; a subsequent PUT can consume a firmware-provided resume offset | Measure user retry/reconnect behavior; do not claim automatic continuation from protocol resumability alone |
| [First-program tutorial](../../tools/web/src/app/learn/first-program/page.tsx) | Console-only `print("Hello from PyBLE!")` task without wiring | Reuse it for baseline observation and improve only demonstrated friction |
| [Device information types](../../app/lib/pble/types.dart) | Negotiated chip, agent version, and capabilities | A support export must distinguish observed data from operator-supplied profile/provenance; current HELLO does not prove an artifact hash |
| [Host conformance fixtures](../../tests/firmware_tests/host/conformance/README.md), [HIL guide](../../tests/firmware_tests/hil/README.md) | Shared vectors, compiled-native/portable tests, physical benches and release evidence tools | Add a coverage map and operator recipe before creating another harness or schema |

**Accepted next-release engineering increment:** PYB-006.2 closes the bounded current-text part of the carried A-24 persistence gap. The [C1-S2 record](../developments/2026-q4-reliable-workflow/c1-s2/00_Execution_Record.md) binds its 31 October engineering acceptance, exact artifacts, physical conditions and carried limits. One acknowledged Drift checkpoint can be restored offline; generated Blocks text is covered only after explicit adoption into Editor. Full projects, Blocks graphs and new protocol operations remain outside this increment. [PR #41](https://github.com/PyBLE-dev/PyBLE/pull/41) merged after all 36 checks on its final head passed. Apple accepted the upload and started processing ([receipt](../developments/2026-q4-reliable-workflow/c1-s2/06_Release_Readiness.md#31-october-app-store-connect-upload-receipt)). Complete M-05 distribution next, while arranging real pilot observations and confirmed human capacity. The original design/sizing estimates remain historical forecasts, not measured effort.[^app-contract]

## 3. Target users and positioning

| Segment | Job to be done | Initial offer | Evidence needed before expansion |
|---|---|---|---|
| Tablet-owning makers | Program a nearby compatible board without recurring cable setup | Reliable app, recovery guide, small verified example set | Successful first session and repeat use |
| Educators | Run a supervised physical-computing activity with less repeated setup work | Pre-provisioned boards and one bounded lesson | Completion rate, support burden, and correct board selection |
| Hardware vendors | Make a specific board usable from tablets | Porting guide and repeatable compatibility evidence | Partner can run the process without bespoke maintainer intervention |
| Researchers | Reproduce and evaluate a mobile-to-hardware workflow | Versioned software, protocols, test artifacts, citation metadata | Reproducible experiments and a defensible research question |
| Field technicians | Maintain equipment without a laptop | Deferred discovery interviews only | Authenticated ownership, safe recovery, and operational support requirements |

**Positioning:** “An open, offline-first MicroPython development workflow for tablets and nearby compatible boards.”

“Offline-first” applies to core editing, BLE, files, and execution. App installation, initial firmware acquisition, optional GitHub import, and online documentation can require network access. Avoid confusing that boundary in marketing.

**Provisional first-cycle audience:** tablet-owning makers with a specific nearby-board task. This is a planning default, not a claim that participants have been recruited. In S1, name the reachable cohort, recruitment owner, reference hardware, and task. If an instructor-led group is the accessible cohort instead, record that choice before observations and use instructor-provisioned boards. Choose one primary audience for the cycle; keep other participants' results separately exploratory rather than pooling different setup responsibilities and task schedules.

The first job to test is whether a participant can modify, run, and revisit a small useful program on a nearby board from a tablet. Record the participant's previous workflow and reason to choose PyBLE. Chemistry may provide a later teaching context, but the core remains discipline-neutral. Use low-risk temperature or light measurements with reviewed hardware, not unattended pumps, heaters, or safety-critical experiments.

## 4. Objectives and measurement

### 4.1 North-Star outcome

**Non-maintainer users who complete a real board session and return for another task.**

An activated participant must install a recorded app build, select the correct provisioned board, establish PBLE/1 communication, transfer or open the intended example, and obtain its expected result. An installation, star, connection alone, or maintainer-generated test is not activation.

A repeat user completes another useful session on a different day. Here, independent means outside the implementation/release team, not necessarily unrecruited. Report recruited participants, classroom participants, and independently arriving users separately; never combine them into a claim of organic adoption. First-program completion is onboarding evidence. Product-value evidence also needs a meaningful second task, the participant's reason for choosing PyBLE, and the obstacles or alternatives encountered. Separate participant-initiated use from prompted demonstrations and instructor-assigned work.

### 4.2 Proposed 12-week targets

These are planning targets, not forecasts or statistical claims. Recalibrate after the first observed sessions.

| Objective | Proposed target | Measurement and qualification |
|---|---|---|
| Accurate public status | All maintained entry points agree on verified distribution and support status | Dated channel/build matrix; automated copy/link checks where practical |
| First-use success | At least 80% unassisted completion among at least 12 eligible primary-cohort participants who start the task | At 12 starts, at least 10 must succeed unassisted; failed and abandoned starts remain in the denominator |
| Time to first successful run | Observed p90 at or below 10 minutes for successful, unassisted Task A runs | Starts at first app launch; report alongside all-start completion, failures/timeouts, and raw small-sample distribution; never present successful-only p90 as all-user experience |
| Early repeat use | Provisional indicator: at least 40% complete another useful session in days 7–14, once at least 20 participants are eligible for follow-up | Show all mature eligible participants, confirmed useful returns, respondents, missing follow-up, and prompting/assignment separately; interpret against opportunity to use |
| Useful second task | Record attempts and outcomes beyond the introductory demonstration | Task C in §12: previous workflow, meaningful adaptation or own task, reason to choose PyBLE, assistance, and reason for return/non-return; a repeated print demo alone is insufficient |
| Compatibility evidence | Target a candidate-bound core workflow matrix for five profiles × iPadOS/Android | Ten minimum combinations; stage execution by risk and capacity; incomplete rows cannot support new qualification claims |
| Data safety | Zero unexplained file/draft loss or silent corruption in the defined release suite | A gate for that suite, not a universal reliability guarantee |
| Actual adoption | Aim for 30 non-maintainer activations by cycle end | Report recruitment source; optional consent-based evidence; discovery target, not a release blocker |
| Independent feedback | At least five substantive reports, demonstrations, or walkthroughs | Count positive and negative feedback; no requirement to publish identity or praise |

Before the first observation, fix the task version, eligibility, equipment, permitted written guidance, assistance rule, and maximum session duration. Proposed Task A timeout is 30 minutes, subject to the pilot lead's review before collection. Live hints or intervention count as assistance; a safety intervention always takes priority. Keep failures, abandonment, and timeouts in the completion denominator; document pre-task exclusions. For successful unassisted runs, compute the empirical p90 by the nearest-rank method and report its sample size. If no runs qualify, report it as unavailable.

The 12-person first-use cohort is not enough to assess the 20-person retention indicator. Aim to activate at least 20 primary-cohort follow-up-consenting participants by **22 November**, allowing day-14 windows to close by **6 December**. Report the day-7–14 return fraction among all mature, consented follow-up participants in that cohort, with respondents and missing responses separately. Missing follow-up is not a confirmed non-return. If the denominator is below 20, classify the retention target as **inconclusive**, retain the descriptive results, and defer the broad expansion decision; do not block an otherwise qualified maintenance fix or a bounded existing-profile rehearsal.

At follow-up, record whether a relevant task arose, whether the board/tablet was available, what was attempted, and the reason for returning or choosing another workflow. Retain participants without a new task in the primary denominator; an opportunity-to-use subgroup is supplementary and must disclose its denominator and missing answers. Keep the 7–14-day window for comparability. If the selected audience has a different task cadence, define an additional observation window before follow-up begins and report it separately. A numeric threshold alone does not establish product value, and an infrequent task schedule alone does not establish rejection of PyBLE.

### 4.3 Privacy-preserving evidence

Keep no-telemetry-by-default. Do not introduce background identifiers or silent transmission to satisfy a KPI.

Use explicit pilot observation, optional follow-up, store-console aggregates available to the owner, and a user-initiated diagnostic export if PYB-007 is delivered. Until then, use a reviewed manual support template with the same exclusions. A local measurement record can include a random pilot-session ID, app build, firmware artifact, profile, task outcome, elapsed time, assistance count, broad failure category, task opportunity, and prompting/assignment status. Summarize task purpose, prior workflow, and reasons for return/non-return without recording private project details. Do not include MAC addresses, source code, console contents, student identifiers, or account details by default.

Retention measurement needs a consented way to link two observations. An anonymous single-session report cannot establish retention. Keep contact/consent records separate from technical observations and adopt an explicit retention/deletion policy before collection.

## 5. Architecture and engineering boundaries

### 5.1 Preserve the current component separation

The intended dependency chain remains: **PyBLE app → PBLE contract → agent implementation → MicroPython and board resources**. The application should consume negotiated capabilities rather than route behavior through a hard-coded chip-family allowlist.[^readme]

| Component | Existing location | Planned change |
|---|---|---|
| Tablet application | `app/` | A-24 durable drafts, measured onboarding/retry fixes, optional diagnostics; keep UI behind `Connection` and `FakeConnection` tests |
| Agent and board ports | `firmware/` | Approved reliability work and exact-profile qualification |
| Wire contract | `docs/specifications/protocol.md`, existing `protocol/` assets | Compatibility rules, vectors, approved additive capabilities |
| Validation | `tests/` | Package existing coverage into reproducible operator-facing runs |
| Website and Learning Center | `tools/web/` | Maintain corrected release state and static Next.js export; reuse existing tutorials and add reviewed localization only when resourced |
| Public examples | Separate `PyBLE-dev/examples` repository | Small reviewed tasks with board/wiring/provenance metadata |
| Decisions and planning | `docs/decisions/`, `docs/planning/` | ADRs, this plan, stage decisions, and scope changes |

New filenames and formats proposed in this plan are not existing interfaces. Preserve the root layout mandated by `AGENTS.md`.[^agents]

### 5.2 Non-negotiable technical boundaries

- BLE remains the normal interactive transport; USB/BOOTSEL remain explicit provisioning and recovery paths.
- No automatic execution on import, no implicit overwrite, and no silent formatting of nonblank storage.
- File integrity, session ownership, and bounded memory take precedence over transfer speed.
- Existing upstream dependency boundaries, licensing, and clean-room rules remain intact.
- App version, firmware version, protocol compatibility, and store build identity remain separate.
- A valid hash proves integrity relative to a manifest, not that a publisher or nearby device is trustworthy.
- Device labels and advertised identifiers help selection but do not authenticate ownership.

## 6. Release and protocol strategy

### 6.1 Separate three decisions

**Maintenance release:** fixes existing behavior and improves onboarding without requiring new wire operations.

**Firmware feature release:** implements approved, capability-gated additions with exact cross-version semantics.

**Distribution release:** publishes a particular app artifact to a particular store/testing channel. A merge or version bump does not establish availability.

Do not require the complete v0.7.0 feature program before stabilizing the existing app. Conversely, do not call an incomplete implementation “v0.7.0” merely to meet the calendar.

**Maintenance lane:** release a bounded fix whenever its applicable specification, regression, physical, provenance, and distribution gates pass. Recruitment, retention, translated pages, and the full strategic program are not prerequisites. Record which requirements apply to an app-only, firmware, website, or documentation change; do not waive a normative requirement simply because the change is small.

**Cycle candidate lane:** aggregate the selected changes, qualification evidence, and user observations for the twelve-week review. Pilot findings determine wider acquisition and next investment. They can inform a maintenance release without making every release depend on a completed cohort. Website/docs corrections can ship through their own checks and deployment process without waiting for a store submission.

### 6.2 PBLE/1 policy

Preserve established operation numbers and payload encodings. “Stable PBLE/1” means compatibility stability, not a prohibition on all additive improvements. New operations require specification approval, explicit capability advertisement, fallback behavior, and conformance vectors before implementation. A genuinely incompatible change requires a separate version decision; PBLE/2 is not a scheduled deliverable.[^firmware-roadmap]

### 6.3 Integrate Reliable Projects rather than invent a parallel roadmap

The existing v0.7.0 proposal already identifies the next reliability foundations.[^firmware-roadmap]

| Proposed capability | User outcome | Sequencing decision |
|---|---|---|
| Queryable run/session state | Reconnect without guessing whether code is still running | Early candidate if pilot failures show state ambiguity |
| Transfer status and explicit abort | Understand or cancel a transfer without damaging the prior destination | Prioritize when transfer recovery is a measured blocker |
| Complete directory enumeration | Never mistake a truncated list for a complete workspace | Prioritize before large example collections |
| Project-aware file execution | Portable `__file__`, working directory, sibling imports, and module cleanup | Build on v0.6.1 fresh globals/stdin isolation; do not count that implemented hardening as a new v0.7.0 feature |
| Loss-aware console/input | Distinguish missing output from program behavior | Add only with bounded queues and cross-port parity |
| Diagnostics and recovery ladder | Recover with explicit, explainable steps | Validate current mechanisms before proposing additional reset behavior |

**First-cycle rule:** review and size one proposed capability only if the core backlog leaves capacity. Protocol implementation is not in the base 12-week commitment. An explicit scope decision can substitute one coherent slice for other work after the contract is approved. The complete feature set remains conditional work for a later cycle, not a promised 3–6-month delivery.

**Dependencies:** atomic multi-file deployment follows transfer status/abort and project semantics; classroom bundle import must not imply atomic project publication before that foundation exists. Sensor plotting follows reliable execution and an explicit data-format design. Authenticated ownership has its own threat-model and compatibility gate.

## 7. Workstreams and deliverables

Map these ownership areas to the three active outcomes in §1.5. W1–W3 contain the core delivery work; W4 supports observations with a manual template unless export implementation fits. W5 localization needs reviewer capacity. W6 permits an early existing-profile rehearsal within PYB-009, while badge launch and partner intake remain conditional. W7 contributes pilot preparation only if the selected audience needs it. These are not seven simultaneous implementation commitments.

### W1 — Distribution and release truth

**Owner:** release maintainer, supported by documentation owner.

Extend the existing publication review into one reviewed channel/artifact record. Distinguish prepared, submitted, processing, testing, production, paused, and unavailable states. Record the source of each state and its last verification date. Document country, account, and device restrictions when known; do not imply universal availability from a single successful store-page fetch. Keep existing website copy/link checks; introduce a generated shared data source only if repeated drift warrants that extra machinery.

Deliverables: channel/build matrix, verified installation instructions, maintained README/store/site consistency, store-artifact provenance, and an update/rollback procedure. Accept the listing-status row from dated first-party publication evidence. Accept an installation row from an actual channel installation on an eligible physical device, either performed during the check or verified as an existing installation through channel provenance, observed version/build and successful launch. State which path was exercised; do not erase user data merely to repeat installation or infer fresh enrollment from an existing account. Record uploaded AAB/IPA identity separately from store-delivered/re-signed or split binaries; equal version names or unequal upload/install hashes alone do not resolve provenance.

### W2 — First use and mobile resilience

**Owner:** app maintainer.

Observe users before redesigning screens. Concentrate on permissions, unsupported firmware, ambiguous board names, read-only paths, disconnected sessions, background/resume behavior, keyboard interaction, and error messages. Retain existing readiness and session handling. Specify the persisted draft, write boundary, recovery choice, failure handling, and board association before closing A-24's process-restart gap. Recovering local text must never silently overwrite or run code on a newly selected board.

Deliverables: an observed path through the existing console-only first-program tutorial, improved where evidence warrants; one useful task adapted by participants; a bounded durable-draft increment; and recovery guidance reachable at the relevant failure. Evaluate text-document and Blocks workspace recovery separately. Do not claim a full persistent project system, automatic reconnect, or an unavailable firmware capability from these narrower changes.

### W3 — Reliability and reusable conformance

**Owner:** protocol/firmware maintainer with QA reviewer.

Inventory existing tests before adding a second framework. Start with `tests/firmware_tests/run_tests.sh`, the Python host/conformance suites, Flutter tests, the HIL operator guide, and `firmware/qualification/`. Document prerequisites, exact commands, expected evidence, and safe hardware selection. Publish the operator recipe before or alongside the first matrix run; a fully completed matrix is not a prerequisite for writing that recipe. Distinguish protocol conformance from app usability and physical qualification.

Deliverables: capability/test coverage map, reference failure cases, bounded fault-injection scenarios, profile matrix, and an operator guide that a second engineer can execute. A failing or absent row blocks the corresponding compatibility claim.

### W4 — Feedback without surveillance

**Owner:** QA/pilot coordinator.

Begin with a manual support template. If capacity permits, implement a user-initiated, previewable export of observed app/agent versions, bounded error codes, and optional diagnostic summaries. Label exact profile/build information as operator-supplied or unknown when the current contract cannot report it. Do not infer an exact profile, firmware hash, or source commit from `chip` and agent SemVer. Remove secrets, source, file contents, and persistent device identifiers by default. Console text is excluded unless the user explicitly reviews and includes it.

Deliverables: pilot protocol for one primary cohort, reviewed support template, private participant register, and public aggregate findings on activation, meaningful second tasks, opportunity to use, and support burden; previewable export is optional PYB-007. Do not add automatic upload or background analytics.

### W5 — Authoritative documentation and discoverability

**Owner:** documentation/community lead; native-language review required for localized safety guidance.

Maintain the corrected English identity and existing Learning Center. If a reviewer is assigned, begin with a small Simplified Chinese entry point covering setup, compatibility, and recovery; expand into separate pages after observing demand. Prepare reviewed Thai lesson support where a local pilot needs it. Existing app locale strings are not evidence that website translations or classroom materials are complete. Translations must follow the verified release state rather than introduce additional capability claims.

Deliverables: reviewed localized core pages, a corrections/FAQ page, an evidence-based media kit, and a deduplicated coverage register. Article count and recommendation-panel read counters remain awareness metrics only.

### W6 — Selective ecosystem enablement

**Owner:** lead maintainer, later shared with an external profile maintainer.

Use one existing exact profile to rehearse the published operator procedure with a second engineer. Reuse the five-profile tooling and evidence formats; record assistance and gaps. Prepare a compact PyBLE Ready evidence page and the installation-status distinction in §14. Pilot one external maintainer only after the record and support responsibilities are usable; the pilot can maintain an existing profile.

Early deliverable: one reproducible existing-profile procedure and draft compatibility record, if funded within PYB-009's estimate. Later deliverables: reviewed badge/revalidation rules, the first complete public record, and one external maintenance pilot. New ports require demonstrated demand and capacity. Track setup failures and support effort; keep broad program promotion outside the first-cycle commitment.

### W7 — Classroom and research validation

**Owner:** instructor/research lead with an independent evaluator where feasible.

Start with one low-risk lesson, pre-provisioned exact-profile boards, and a backup workflow. Evaluate both teaching utility and setup/support costs. Run research preparation in parallel, but do not make a manuscript or student project a prerequisite for the initial product release.

Deliverables: lesson pack, teacher runbook, pilot report, reproducible technical benchmark, and a publication decision based on measured contributions.

## 8. Twelve-week implementation schedule

### 8.1 Capacity assumptions

The schedule assumes one primary maintainer can allocate approximately **20 hours per week**, with limited help for physical testing, participant coordination, and translation. This is an explicit planning assumption, not a known commitment.

This gives **240 total hours**, provisionally split into **156 planned hours** and **84 hours reserved** for support, additional qualification, release work, and uncertainty: at most 26 planned hours per two-week sprint. Estimates must include each selected change's known specification, implementation, review, and test effort. The reserve is not a substitute for budgeting mandatory tests. If availability is lower or required physical work exceeds the estimate, reduce optional scope or extend the schedule; do not remove evidence gates.

The draft allocation below uses 136 planned hours and leaves 20 planned hours unassigned. It is a capacity limit to refine in S1, not a claim that A-24 or the full hardware matrix fits a predetermined estimate. Size the persistence design and required matrix first. If either exceeds one sprint, split it into independently reviewable increments and replan before implementation.

The cycle intentionally excludes a complete new protocol version, full classroom product, security implementation, and multiple new ports.

### 8.2 Sprint plan

**31 October continuation:** bounded recovery M-02 and app-only M-04 pass
engineering review at frozen `bef67bd`, with required automated/platform
evidence, exact firmware inputs and the documented Lenovo qualifier condition.
Device closeout is complete. [PR #41](https://github.com/PyBLE-dev/PyBLE/pull/41) merged after all 36 checks on its final head passed. M-05 account, submission and installed-channel
verification remain the next release stage. Do not schedule the same accepted
matrix again without changed scope or invalidated evidence.
The [dated continuation order](../developments/2026-q4-reliable-workflow/04_Sprint_Plan.md#31-october-continuation-order-and-reforecast)
records this selection and the human capacity/pilot inputs still needed. Source
progress does not reconstruct the original Sprint schedule or participant
sessions. The original forecasts remain below for comparison.

**Reforecast required after C1-S1:** the hour rows below retain the original 136-hour base allocation, not an accepted revised selection. Recovery's 45–72 hour estimate exceeds S2's allowance. A conditional S2/S3/S4 allocation of 26/22/12 hours preserves each 26-hour ceiling but leaves only 18 hours for displaced work across those three Sprints. Reorder matrix, activation and conditional fixes with actual owners/access; reassess S5/S6 and the 22 November recruitment target. Do not borrow the event reserve silently, drop failure cases, or count one physical run twice. The [Sprint plan](../developments/2026-q4-reliable-workflow/04_Sprint_Plan.md#c1-s1-findings-and-required-reforecast) owns the detailed comparison.


| Sprint | Proposed dates / planned-hour cap | Selected work | Review evidence / exit condition |
|---|---|---|---|
| S1 | 28 Sep–11 Oct 2026 / 22 h | PYB-001/003/004; residual PYB-002; size PYB-006 and inventory PYB-009 | One primary cohort/task selected; channel unknowns assigned; five baseline observations or recruitment blocker; persistence scope and costed matrix; name a second operator if available |
| S2 | 12–25 Oct 2026 / 24 h | First bounded PYB-006 increment; PYB-005 fix if warranted by observations; operator recipe PYB-009 | Durable-draft contract and regression evidence for delivered scope; existing lifecycle behavior preserved; first representative iPad/Android runs |
| S3 | 26 Oct–8 Nov 2026 / 24 h | Complete selected core increment; staged PYB-008; continue PYB-011 | Exact-artifact results; owners/dates for remaining rows; Task C attempts on a recorded build; optional existing-profile reproduction within 009's budget |
| S4 | 9–22 Nov 2026 / 22 h | PYB-011 and PYB-012 improvement if warranted by observations | At least 12 primary-cohort started-task outcomes, including failures; reasons to choose PyBLE and second-task outcomes; aim for 20 activated follow-up participants by 22 November |
| S5 | 23 Nov–6 Dec 2026 / 24 h | PYB-013/014; finish applicable matrix and mature follow-ups | Frozen candidate, applicable compatibility gates, provenance and recovery evidence; day-14 follow-up accounting; release or documented blocker |
| S6 | 7–20 Dec 2026 / 20 h | Verify PYB-014; cycle review; optional PYB-015 | Actual channel/install state; useful repeat tasks, opportunity-to-use and support findings; any Ready rehearsal results; one explicit next-stage decision |

PYB-007 export, PYB-010 localization, PYB-015 outreach, PYB-016 research preparation, and PYB-017 protocol design use only explicitly allocated spare or independent contributor capacity. They do not displace data safety, required compatibility, or observed onboarding fixes. Qualified maintenance releases can ship in any sprint under §6.1. External store review and recruitment may extend the calendar. Submission is not approval, and approval is not proof of successful activation.

A second-operator rehearsal and draft Ready criteria must fit the existing PYB-009 estimate or use an explicitly assigned part of the 20 unallocated planned hours. Do not add an uncosted program beside the 136-hour allocation. If no second operator is available, retain the procedure and pending result without claiming independent reproduction or blocking unrelated maintenance delivery.

### 8.3 Critical path

**Delivery path:** installed-build/provenance check and scope selection → contract/regression → bounded fix → applicable candidate-bound qualification → release decision → verified distribution.

**Learning path, running alongside delivery:** select one audience/job → baseline observation → useful second task on a recorded build → follow-up with opportunity-to-use context → expansion decision. Significant pilot failures feed back into delivery priority. Recruitment delays are not a dependency for correcting known defects.

Localization and research preparation can run beside this path when independent help exists. New firmware features must not become accidental dependencies for releasing a reliable existing workflow.

### 8.4 Twelve-to-twenty-four-month horizons

| Horizon from start | Direction | Admission condition | Bounded outcome |
|---|---|---|---|
| Months 0–3 | Reliable mobile product | Selected scope and capacity assigned | Qualified maintenance candidate and useful-task evidence; optional existing-profile Ready rehearsal within assigned capacity |
| Months 3–6 | Reliable Projects | Pilot shows a relevant problem; v0.7.0 scope approved | Selected additive capabilities with full compatibility evidence |
| Months 3–9 | PyBLE Ready and partner pilot | Existing-profile procedure reproduced; first complete record and maintenance rules reviewed | One external maintainer/profile pilot; an existing profile is valid; add a new profile only with demonstrated demand |
| Months 6–12 | Classroom workflow | Core app reliable; security review accepts supervised deployment | One reusable lesson workflow and at least two measured pilot sessions |
| Months 6–12 | Research outputs | Reproducible results and a defensible contribution | Technical/software manuscript; education study only with suitable evidence |
| Months 12–24 | Ecosystem and secure deployment | Sustained demand, external ownership, and support capacity | Reviewed compatibility program; authenticated mode or richer data workflow only if justified |

These horizons overlap where staffing permits. They are not simultaneous commitments for a solo maintainer.

## 9. Prioritized implementation backlog

**Planning IDs below are not GitHub issue numbers or approval to implement.** The 25 September review found no open GitHub issues; recheck before creating/linking an accepted work item. Preserve existing story/ADR identities such as A-24 and ADR-0010. P0 means required for the selected stage, P1 means valuable but negotiable, and P2 means discovery or optional expansion. A future-stage P0 is not permission to interrupt the current cycle. Owners below are unassigned roles until a named person accepts them.

### 9.1 First-cycle backlog

Current execution states and the newly identified residual `PYB-002.1` are maintained in the [derived Product Backlog](../developments/2026-q4-reliable-workflow/05_Product_Backlog_and_Stories.md). Parent acceptance below remains binding; prepared procedures do not complete their physical or human-dependent obligations.

| ID | Priority / owner | Deliverable and acceptance criterion | Dependency |
|---|---|---|---|
| PYB-001 | P0 / Release | Extend §2.2 into channel/install/provenance/qualification records; capture actual installed version/build and source mapping, or an explicit unknown with owner | Existing publication review |
| PYB-002 | P0 for accuracy / Docs | Android README/site/metadata correction **complete in PR #33**; retain checks and resolve only newly identified discrepancies or historical supersession notices | 001 for new discrepancies; completed copy is not a blocker |
| PYB-003 | P0 / Lead + QA | Threat model, pilot boundaries, safe hardware scope, consent/data-handling procedure, and signed-off pilot decision | 001 |
| PYB-004 | P0 / QA | One primary cohort/job; repeatable activation task and useful Task C; previous workflow, baseline timing, assistance, failure categories and prospective follow-up rules | 001, 003 |
| PYB-005 | P0 if observed blocker / App | Improve the existing tutorial/readiness flow at the measured failure; novice distinguishes provisioning, permissions, discovery, and ready state | 004 |
| PYB-006 | P0 / App | A-24/ADR-0010 durable current-document recovery: accepted persistence boundary, relaunch recovery, interrupted-write/corrupt-state behavior, no implicit board overwrite/run; explicit Blocks scope; preserve session/lifecycle regression coverage | Bounded 006.2 accepted 31 October; broader A-24 remains carried. App specification/TDD and ADR govern any next slice; 004 informs priority |
| PYB-007 | P1 / App + QA | Optional user-initiated diagnostic export with preview/redaction and observed/supplied/unknown identity fields; manual template is the first-cycle fallback | 003; export contract approved; no dependency on completing 006 |
| PYB-008 | P0 for selected release claims / QA + Firmware | Staged exact-artifact five-profile × two-platform workflow matrix; pass/fail/not-run/blocked per row; map applicable normative gates before running | 001, initial 009 recipe, recorded candidate artifacts; rerun affected rows after relevant changes |
| PYB-009 | P0 / Protocol + QA | Inventory existing suites; add operator recipe and coverage map; within assigned capacity, a second operator rehearses one existing exact profile and supplies a draft Ready record with assistance/gaps | 001 and source inventory; starts before 008; reproduction stays pending without an operator; no new port or badge award required |
| PYB-010 | P1 / Docs | Reviewed Simplified Chinese identity, setup, compatibility, and recovery guidance; code tokens remain unchanged | Verified current guidance and language reviewer; incorporate 005 if selected |
| PYB-011 | P0 for usability decision / Pilot lead | At least 12 primary-cohort started-task outcomes plus useful second-task attempts/reasons; target 20 activated participants for mature follow-up; distinguish prompting, task opportunity, and missing responses | 003, 004, recorded tested pilot setup; start on the current release without waiting for every 008 row or 005 |
| PYB-012 | P0 when a severe failure is observed / Maintainer | Fix the highest-impact observed failure; use regression evidence and comparable task cohorts; no invented issue if observation finds no blocker | Sufficient evidence from 004 or 011; no dependency on completing the cohort |
| PYB-013 | P0 for release / Release + QA | Immutable candidate evidence and sign-off; applicable matrix passes; no unresolved release-blocking data loss, unintended/cross-session writes, or critical workflow regression under the accepted threat model | Applicable 008/009 evidence and included fixes; full 011/012 cohorts are not release prerequisites |
| PYB-014 | P0 when a release is ready / Release | Submit the qualified next app build to the selected existing channel; record submission, availability, installed identity, and installation outcome separately | 013; distribution-owner access; production promotion requires a separate decision |
| PYB-015 | P1 / Community | Accurate release kit and coverage register; pitch only verified capabilities and availability | 002, 013; verified channel before availability claims |
| PYB-016 | P1 / Research lead | Benchmark protocol, pilot analysis plan, and ethics-review decision before research data collection | 003, 004 |

### 9.2 Conditional expansion backlog

| ID | Stage / owner | Deliverable and acceptance criterion | Dependency |
|---|---|---|---|
| PYB-017 | P0 / Protocol | Approved v0.7.0 scope, ADRs, capability registry, and cross-version test plan before implementation | Default after first-cycle review; earlier design only by explicit capacity/scope decision |
| PYB-018 | P0 / Firmware + App | Queryable run/session state; reconnect and autorun tests show no stale-state assumption | 017 |
| PYB-019 | P0 / Firmware + App | Transfer inspection/abort; old destination survives failure, abort is idempotent, ordinary disconnect still permits defined resume | 017 |
| PYB-020 | P0 / Firmware + App | Complete directory enumeration with documented mutation behavior; every entry returned once for an unchanged test directory | 017 |
| PYB-021 | P0 / Firmware | Project-aware execution; sibling imports, path restoration, module cleanup, and fresh runs agree across agents | 017 |
| PYB-022 | P1 / Firmware + App | Bounded loss reporting and explicit recovery UX; console floods cannot silently redefine STOP semantics | 018, 017 |
| PYB-023 | P0 before untrusted deployment / Security lead | Ownership/authentication RFC, independent review, downgrade/reset/recovery tests; implement only after versioning decision | 003; approved security scope |
| PYB-024 | P0 before badge award / Protocol + QA | Reviewed Ready criteria/use/revalidation/withdrawal rules and first complete public exact-profile record; visible installation status; reuse evidence formats; award only when every declared criterion passes | 009 reproduction, applicable qualification evidence, named owner/reviewer; not an app-release dependency |
| PYB-025 | P1 / Partner owner | One external maintainer sustains an existing or justified new exact profile; independent results, agreed support/retest responsibilities, and setup/maintenance effort recorded | 024, demonstrated user need, named owner/capacity; new port optional and subject to normal gates |
| PYB-026 | P1 / Education lead | Offline lesson pack with reviewed wiring, expected outcome, recovery path, and accessibility review | Core workflow gate |
| PYB-027 | P1 / App + Education | Safe lesson import/QR flow; bounded parsing, preview, explicit overwrite consent and separate Run action; no implicit atomic-deployment claim | 026; approved bundle specification |
| PYB-028 | P1 / Education + QA | Two supervised classroom sessions with measured setup, completion, wrong-board events, and support burden | 026; 003 refreshed for classroom use |
| PYB-029 | P2 / Research + App | Sensor-data/plotting experiment with bounded rate, units, timestamps, loss reporting, and explicit export | Stable execution/console; demonstrated demand |
| PYB-030 | P1 / Research lead | Reproducible technical benchmark and submission-ready research package if results justify it | 016, qualified artifacts |
| PYB-031 | P2 / Project owner | One scoped paid-support or vendor-integration pilot with recorded delivery/support effort and no closed app features | Demonstrated demand and support capacity |
| PYB-032 | P2 / Protocol | Atomic project-deployment RFC and interruption model, not an implementation promise | 019, 021; measured multi-file deployment need |

Split any issue that combines several independently releasable behaviors or cannot fit into one sprint. Do not assign opcode numbers, capabilities, schemas, or release numbers in issue text without linking their approved specification.

Before scheduling each selected item, add its named owner/reviewer, estimate including validation, normative references, evidence location, release lane, and current state (`completed`, `ready`, `in_progress`, `blocked`, or `proposed`). Prepared and Awaiting evidence may explain unfinished task states more precisely; neither means Done or waives acceptance criteria. Status belongs to a specific deliverable: PR #33 completion does not complete installed-build verification, and an approved design does not complete its implementation.

## 10. Quality, compatibility, and release gates

### 10.1 Definition of Ready

An implementation issue requires an owner, user problem, affected contract, explicit in/out scope, dependencies, acceptance scenarios, test approach, and rollback/recovery considerations. Protocol changes require an approved specification and compatibility decision. Hardware claims require named physical devices and an evidence plan.

### 10.2 Definition of Done

A behavioral change is done when its relevant specification is updated; the required failing test and minimal passing implementation are recorded; applicable regression, dependency, license, DCO, and clean-room gates pass; documentation matches behavior; and required hardware evidence is attached. Documentation-only planning revisions need source/link/consistency review and applicable repository gates, not artificial behavioral tests. A merged change may be complete as source work while remaining unqualified for release. Preserve that distinction.[^agents]

No screenshot, AI-generated report, mock test, or maintainer assertion substitutes for a physical measurement that a release gate explicitly requires. Record `not_run`, `blocked`, or a reviewed exception instead of manufacturing a pass.

### 10.3 Minimum regression coverage

| Test area | Required scenarios |
|---|---|
| First use | Permissions denied/retried, incompatible firmware, no board, multiple similarly named boards, writable-path guidance |
| Connection lifecycle | Disconnect during transfer/run, background/resume, explicit retry/reconnect, stale acquisition/completion, invalid or missing capability |
| Local recovery | Process termination/relaunch distinguished from in-process suspension; accepted write boundary; interrupted/corrupt local state; text versus Blocks scope; restore never writes/runs on a board implicitly |
| Files | Empty and boundary-size files, Unicode names, full storage, failed overwrite, conflicting mutation, interrupted transfer |
| Execution | Sequential isolated runs, errors, tight loops, console flood, STOP, documented escalation and recovery |
| Compatibility | Name exact released-app/firmware baselines; run released app against changed firmware and candidate app against declared supported firmware; do not treat mutable branch names as artifact identity |
| Import | Immutable source preview, explicit destination/overwrite review, no automatic execution, network failure and rate limit |
| Privacy | No unexpected background requests; exports omit sensitive content by default; offline core workflow still works |
| Provisioning | Correct exact profile, wrong-profile refusal where detectable, erase warning, ESP recovery, Pico BOOTSEL recovery |

Use the current normative latency, resource, and payload limits. Where limits are absent, measure a baseline, propose a bound, and approve it before using it as a gate. Do not invent a faster number and silently weaken an existing guarantee.

### 10.4 Hardware evidence design

For each of the ten minimum app-platform/profile combinations, record app delivery channel/version/build and available artifact provenance, exact firmware bytes, physical board revision and memory, operating system/device, test-suite revision, negotiated BLE conditions, operator, and time. Where installed-byte identity cannot be extracted, record the evidence limitation and whether the applicable gate accepts that provenance; never invent a matching hash. Run controlled and representative interference scenarios separately.

Inventory the existing normative counts, reset/transfer limits, release schemas, and profile-specific gates before estimating the matrix. Start with representative iPad and Android rows to expose harness/setup failures, then execute every row required for the selected claim. A representative subset is an engineering checkpoint, not a substitute for five-profile qualification. Missing hardware or operator capacity becomes a dated blocker; reduce optional work, extend the schedule, or explicitly review the release scope without weakening normative gates.

Additional endurance counts are optional experiments to size after that inventory; this plan adds no arbitrary 100-operation/30-recovery floor on top of existing suites. Include the required interruption/fault cases, not only successful repetition. Zero observed corruption in a finite suite is not proof that corruption can never occur.

Reuse the existing manifests and `firmware/qualification/` reports for release admission. The following is an **illustrative supplemental observation record**, not a new authoritative release schema, completed test, or replacement for required HIL receipts. Map its fields to existing evidence before introducing a maintained format.

```yaml
record_kind: "proposed-pilot-observation"
record_id: "replace-with-unique-test-record-id"
profile: "esp32-4mb"
app:
  platform: "android"
  delivery_channel: null
  version: null
  build_number: null
  source_commit: null
  uploaded_artifact_sha256: null
  installed_artifact_evidence: null
firmware:
  version: null
  source_commit: null
  artifact_sha256: null
hardware:
  profile_evidence: null  # provisioning/operator evidence, not inferred from chip
  board_revision: null
  flash_mib: null
  psram_mib: null
suite_commit: null
os_version: null
started_at: null
scenario: "interrupted-upload-preserves-existing-file"
result: "not_run"
evidence_paths: []
reviewer: null
```

Raw logs belong in appropriate artifact storage, not automatically in Git. Publish redacted manifests and hashes; retain the supporting raw records under the agreed access/retention policy.

### 10.5 Release admission

A new qualification claim requires candidate-bound passing evidence for that claim, an approved support matrix, known limitations, reproducible build/provenance records, recovery instructions, and the applicable installation checks. Publication wording uses the separate evidence levels in §2.2; an official listing can establish open-testing availability without proving installed build identity. Regenerate or explicitly revalidate evidence when relevant code, dependencies, build inputs, or hardware change.

Existing v0.6.1 publication history remains recorded as owner-confirmed with incomplete automated evidence. This plan neither retracts that history nor relabels it fully automated-qualified. New evidence-backed badges and releases must satisfy their declared criteria.[^readme]

**Release-blocking write failures** mean unintended writes, wrong-session completion, jail bypass, or behavior outside the approved contract and accepted deployment threat model. PBLE/1 currently trusts the connected client. This plan does not silently add authenticated ownership as a prerequisite for every maintenance release; untrusted deployment remains a separate security gate. Known exceptions/deviations must be linked and visible, not converted into passing test results.

### 10.6 Verification entry points

Use [.github/workflows/ci.yml](../../.github/workflows/ci.yml) for the current pinned environments and mandatory PR checks. The table identifies existing tools, not a claim that they were rerun for this plan or that every command is needed for every edit.

| Change / evidence | Existing starting point | Limit |
|---|---|---|
| Documentation | `python3 tools/ci/docs_links.py`; publication tests under `tests/publication/` | Normal link discovery uses tracked Markdown; explicitly include a new untracked plan when reviewing it |
| Contributor/source gates | `tools/ci/no_leak.sh`, `tools/ci/spdx_lint.sh`, DCO and affected import/locale gates | Checks do not establish physical behavior |
| App | Locked dependency resolution, analyze/unit/widget/golden/WebView jobs in CI | FakeConnection and emulator results do not replace iPad/Android BLE evidence |
| Firmware/protocol host | `tests/firmware_tests/run_tests.sh`; `python3 -m unittest discover -s tests/firmware_tests/host -p 'test_*.py'` | Host/conformance success is not hardware qualification |
| Physical/release | [HIL operator guide](../../tests/firmware_tests/hil/README.md), `firmware/qualification/`, exact-profile specs | Select actual devices and immutable candidates; report unrun or unavailable rows |
| Website | `npm run check` in `tools/web/` with the pinned Node version; deployment smoke/rollback procedure | Build success does not prove public deployment or search-index refresh |

## 11. Security and physical safety

Security work starts in the first sprint, not when industrial customers arrive. The existing planning documents state that PBLE/1 trusts a connected client and place authenticated ownership behind a separate design milestone.[^firmware-roadmap]

### 11.1 Immediate boundaries

Operate early pilots only in a supervised environment with trusted participants, non-sensitive scripts, and harmless loads. Explicitly explain that nearby device names, pairing UI, and a connected session do not by themselves establish authorized ownership under the current contract.

Measure wrong-board selection and interference in a multi-board setting. If cross-user control cannot be acceptably contained, reduce the pilot to isolated stations or postpone it. Never describe untrusted-network, public-lab, or unattended industrial use as secure without the relevant authentication design and tests.

STOP is software program control, **not an emergency-stop mechanism**. Independent hardware protections and physical disconnects are required wherever actuation creates hazards. The first classroom pilot should avoid motors, pumps, heaters, and mains-powered loads.

### 11.2 Authenticated-owner design gate

Before implementation, define physical-presence bootstrap, identity/key storage, replay and downgrade protection, expiry, revocation, lost-tablet recovery, credential reset, rate limiting, and legacy fallback. Determine which operations may remain public and how a device refuses privileged operations before authentication.

Use established cryptographic constructions and obtain independent review; do not invent a custom cryptographic protocol. Decide explicitly whether the design can be optional and backward-compatible or needs PBLE/2. No security-sensitive fallback may silently turn a failed authenticated connection into an unrestricted one.

### 11.3 Diagnostic and import boundaries

User code is executable content even when supplied as an educational example. Preview source and destination; require a separate Run action. A signature or official-source label does not remove that requirement. Local lesson archives need limits on size, decompression, paths, filenames, and content types before extraction or transfer.

## 12. Pilot and adoption strategy

### 12.1 Separate onboarding from useful work

**Task A — provisioned-board activation.** Provide an installed app or record app installation separately; start the timed task at first app launch with a powered, correctly provisioned board. The participant handles permissions, selection, connection, example transfer, and execution. Do not hide failed attempts or assistance.

**Task B — complete self-service setup.** Start with the actual store invitation/listing and an unprovisioned supported board. Include finding the correct firmware, obtaining a compatible host/browser and cable, backup/erase decisions, flashing or BOOTSEL copying, and the first successful mobile program. Report this duration separately from Task A.

These tasks answer different questions. A fast classroom experience with pre-provisioned hardware does not prove that a new maker can complete self-service setup.

**Task C — meaningful adaptation and return.** After first use, ask the participant to identify a small result they want: for example, adapt a reviewed light/temperature script to change a threshold or sampling interval and inspect the output. Use existing features and a safe exact-board setup. Record the goal, previous workflow, reason to choose PyBLE, attempted change, outcome, assistance, and any alternative chosen. An unchanged rerun of the introductory print example is not sufficient evidence of useful adaptation.

A Task C attempt in the first session measures ability to do useful work; repeat use requires a later-day session. Invite an optional follow-up when a relevant task arises, and label whether it was participant-initiated, researcher-prompted, or instructor-assigned. Assigned work can demonstrate usability and teaching utility without being counted as spontaneous demand. Capture failures and abandoned attempts as well as successful returns.

### 12.2 Recruitment and rollout

Begin with five observed baseline participants in the selected primary audience; extend to at least 12 eligible started tasks for the first usability gate. Include both Android and iPad users and different experience levels where recruitment permits; state any platform/sample limitation. The initial five may count toward the twelve only when task, eligibility, build, and observation rules are comparable; report changed-build/task cohorts and other audiences separately. Aim for 20 activated, consenting participants by 22 November for the retention indicator, or report it inconclusive. A small usability sample is not a population-level efficacy study.

Use the existing console-only first program, then a useful Task C appropriate to the exact board and participant's goal. Record assistance, failures, and abandonment before asking for feedback. Invite—not require—follow-up use during days 7–14, with the task-opportunity and prompting distinctions in §4.

Do not ask students to post positive reviews or use grades to secure participation. Do not reward stars, ratings, or favorable testimonials. Any compensation should be independent of outcome, disclosed, and compatible with the relevant platform rules at the time.

### 12.3 Interpret the outcome

Use observed outcomes to choose the next investment:

| Observation | Next decision |
|---|---|
| Provisioned-board users succeed but self-service users cannot start | Improve board/firmware selection, provisioning and distribution; test whether a Ready record reduces the observed confusion |
| Users return for useful work but repeatedly struggle with several files | Review the relevant Reliable Projects slice and cross-version contract |
| Users complete onboarding but choose another workflow for subsequent tasks | Investigate task fit, project continuity, interaction and examples before adding capabilities |
| No relevant task arose, equipment was unavailable, or follow-up is missing | Record the reason/unknown; continue the prospective observation plan without treating absence as proven rejection |
| Wrong-board control occurs in group use | Contain the pilot and address selection/ownership boundaries before classroom expansion |
| An outside maintainer reproduces a profile, reaches users and accepts maintenance | Consider the bounded PyBLE Ready partner pilot; review support effort before another profile |

If users return but create no public content, private successful use still counts. If public engagement rises without successful sessions, investigate discoverability and technical misinformation. A successful tutorial alone does not establish that the tablet workflow is preferred for real work.

A support issue can be a positive usage signal; a quiet issue tracker can mean either reliability or non-use. Interpret it alongside observed sessions and follow-up, not in isolation.

## 13. Documentation and international reach

### 13.1 Establish one accurate technical identity

Publish a concise fact sheet describing the Flutter tablet client, PBLE/1, compatible agent, current exact profiles, normal offline workflow, and provisioning/recovery boundaries. Explicitly distinguish PyBLE from GDB, JTAG/SWD tunneling, a desktop `bleak` client, Web Bluetooth IDEs, and universal BLE firmware OTA.

Only correct claims that have been directly checked against the specification. Do not amplify inaccurate articles by reproducing their detailed invented interfaces.

### 13.2 Simplified Chinese entry point

Propose a reviewed `/zh-cn/` entry point with four essentials: what PyBLE is, setup and distribution, exact compatibility, and troubleshooting/recovery. Link back to the authoritative versioned English specification. Preserve protocol names, code, UUIDs, and identifiers verbatim.

Treat Simplified Chinese as a targeted discoverability experiment prompted by the preceding CSDN discussion—not a claim that China is already the largest active user market. Measure consented activation/support outcomes where possible. If a reviewer is unavailable, publish a short reviewed page rather than extensive unreviewed safety instructions.

A verified project-controlled CSDN presence may republish this reference with attribution. Do not assume an account already exists or create/post through it without separate authorization.

### 13.3 Coverage register and outreach

Maintain one record per canonical article with URL, outlet, language, first publication date, first discovery date, upstream source, technical accuracy notes, and evidence of hands-on use. Mark syndication and translations as such. Deduplicate recommendation links and mobile/desktop variants.

This avoids repeatedly calling older FabScene or Open Source For You coverage “new,” and prevents publication-date and discovery-date confusion.

Prepare a release kit containing a short real-device demonstration, reviewed screenshots, exact support table, setup guide, known limitations, and verified installation links. Pitch a follow-up to relevant existing outlets only when there is a real new result—such as a verified distribution milestone, independently reproduced port, or measured classroom pilot.

Do not infer a paid campaign from a “Sponsored” page label, campaign termination from a few missing page renders, or article readership from an undocumented trending algorithm. Record observed placement only.

## 14. PyBLE Ready and partner development

### 14.1 Purpose and proposed promise

PyBLE Ready should help users choose the correct board and firmware, complete setup, and find continuing support. It is a proposed compatibility program; this plan does not award a badge or establish an existing certification.

The proposed public promise is:

> This exact board configuration, running the listed firmware, passed PyBLE's published workflow checks with the listed app/platform versions and has a named maintenance owner.

The claim belongs to an exact configuration and tested software matrix. It does not extend automatically to a chip family, another board revision, every peripheral, or later app/firmware releases. A compatibility label is not a security certification. Badge eligibility and use rules must be published and reviewed before the first award.

### 14.2 One badge with visible installation status

Use one public **PyBLE Ready** badge for a maintained, hardware-validated profile. Keep the intermediate evidence states in technical reports:

| Evidence state | Meaning | Public Ready badge |
|---|---|---|
| Experimental | Source/build work with explicit limitations | No |
| Conformance-tested | Named implementation passes a versioned protocol suite | No; host results alone do not establish physical workflow |
| Hardware-validated | Exact board/software matrix passes the applicable physical checks | Not until maintenance, reproduction, and public-record requirements are met |
| Maintained and reviewed | Required checks and second-operator reproduction recorded; named owner and complete public record | Eligible after review against the published program rules |

“Ready” can imply a board arrives already provisioned. Display one of these installation statements prominently beside the listing or badge:

- **Firmware installation required:** the compatible board must first receive the listed firmware; link the exact installation and recovery instructions.
- **Firmware preinstalled:** the particular supplied board or kit includes the identified firmware; state the delivered version/artifact and first-use checks. Do not infer this from the model's compatibility record.

Unknown installation status must be resolved before using the badge on a board/kit offer. A project profile page can state that it makes no claim about a seller's shipped firmware. Preinstalled status never removes the need for recovery instructions.

### 14.3 Public evidence record and review

Every badge must link to a stable public record. A packaging or product-page link must identify the exact configuration and claimed software version, and expose current support status.

| Record field | Required content |
|---|---|
| Hardware | Model, revision, flash/PSRAM and other relevant configuration constraints; no inference from chip identity alone |
| Software | Firmware artifact hash/source and protocol/capabilities; tested app builds, devices, and OS versions with provenance limitations explicit |
| Workflow | Applicable provisioning, connection, file integrity, run/stop, interruption, and recovery results; links to versioned reports and existing release evidence |
| Reproduction | Test date, operator, second operator's reproduction result, suite revision, reviewer, and declared scope |
| Installation and limitations | Installation status as defined above; setup/recovery guide; known limitations and untested combinations |
| Maintenance | Named owner, support route, agreed response/retest responsibilities, review date, and current badge status |

Publish redacted evidence and hashes using the existing release formats; do not expose device identifiers or participant records. Reuse qualification reports rather than create a parallel source of truth. A second operator should reproduce the published provisioning and core/recovery procedure, logging any maintainer assistance. Undocumented instructions or maintainer interventions are procedure gaps: update the recipe and have the second operator rerun the affected steps without bespoke help before the reproduction criterion passes. Assisted rehearsals remain useful pending evidence. Every mandatory release/program gate still needs its own required evidence.

Owner-confirmed v0.6.1 publication **does not automatically confer PyBLE Ready status**. Each profile must meet the badge's declared evidence rules. An existing profile may be used for rehearsal while gaps remain explicitly pending. Reviewing one profile for a bounded compatibility claim does not waive an atomic five-profile release gate or qualify a new firmware release.

### 14.4 Maintenance, corrections, and open access

Assign the program reviewer and maintenance owner before an award. The public rules must define badge use, correction requests, a review interval, and suspension/withdrawal decisions. Use active, under-review (badge claim suspended), and withdrawn states with dated reasons; keep historical records accessible.

Relevant firmware, app, dependency, board-revision, or provisioning changes trigger a documented impact review and the required retesting before extending the claim. New versions are untested until assessed; older passing results remain historical evidence. Missing an agreed review deadline, losing the maintenance owner, or discovering a material compatibility defect triggers review and suspension of the active badge claim as appropriate. Correct or withdraw unsupported claims and update the public record; do not silently rewrite previous results.

Keep conformance tools and criteria openly available. Compatible PBLE agents must remain usable without a badge, program registration, payment, or an app-side board allowlist. The app continues to negotiate capabilities. Paid porting, testing assistance, or support cannot purchase a badge or bypass its evidence requirements.

### 14.5 Phased introduction and outcome measures

| Phase | Bounded work | Evidence needed to advance |
|---|---|---|
| Existing-profile rehearsal | Select one of the five existing exact profiles; reuse PYB-009's operator recipe; have a second operator reproduce it | Recorded results and assistance, reproducible setup/recovery, and explicit remaining gaps; no new port required |
| First public record | Complete the evidence and maintenance record and review the badge rules | All applicable criteria pass; users can distinguish compatibility from installation status; only then award the first badge |
| External maintenance pilot | Work with one outside maintainer on an existing or demand-backed new profile | Agreed ownership, independently reproduced results, and observed setup/support effort |
| Selective expansion | Add one justified profile at a time | User demand, sustainable maintenance, and the normal specification, qualification, and release gates |

A short criteria draft and existing-profile rehearsal may start in the first cycle if included in PYB-009's estimate and a second operator is available. They do not create a new mandatory certification project or displace durable drafts and user observations. Broad promotion and external intake follow the first usable record and demonstrated support capacity. The initial partner pilot has one maintainer/profile; consider a second new profile only after reviewing that pilot.

Measure correct board/firmware selection, provisioning success, setup duration, assistance count/support time, and maintainer effort per update. Compare like tasks, equipment, and starting installation states; report small samples and failures. Partner and badge counts alone do not demonstrate value.

Choose a partner by access to exact hardware, willingness to publish evidence and maintain the profile, and access to users with a relevant task. Maintaining an existing profile is a valid first contribution. No partnership is claimed before agreement, and new chip-family coverage is not a prerequisite for testing the program.

## 15. PyBLE Classroom

### 15.1 Stage A: lesson packs before new application features

Start with a versioned repository release containing readable `.py` examples, a teacher guide, wiring diagram, bill of materials, exact board profile, tested app/firmware versions, expected results, and recovery instructions. A ZIP may distribute teacher materials, but current app import does not imply ZIP ingestion. Reuse the existing reviewed, SHA-pinned import of a bounded public GitHub folder; keep files and categories within its current limits. Offline local lesson-archive import is future work, not a prerequisite for the first lesson.

Pre-provision boards, label stations physically, verify safe selection, and retain a wired recovery station. Prepare a fallback lesson when radio conditions or device eligibility prevent participation.

### 15.2 Stage B: optional structured bundle

Design a `.pyble` lesson bundle only after repeated pilots identify a problem that ordinary lesson packs cannot solve. The extension and schema are proposals until approved. A minimal manifest should identify lesson/version, supported capabilities, tested hardware, source-file hashes, entry-point choices, safety notes, and minimum compatible app behavior.

A QR code should identify a reviewed lesson or link, not silently execute code. Remote retrieval must be explicit; provide an offline file-sharing alternative. Do not add student accounts, mandatory cloud storage, arbitrary package installation, or a new learning-management system.

Bundle validation must reject path traversal, symlinks, unsupported file types, excessive size/decompression, and conflicting destinations. Preview exact files and destinations before transfer; confirm overwrites separately. Until atomic project deployment exists, clearly report partial transfers and never imply that a multi-file project committed atomically. Do not automatically run a partially transferred lesson.

### 15.3 Classroom admission gate

Complete a multi-board interference/selection exercise and a security review before a class pilot. Begin with small groups; larger class sizes are a separate capacity and radio-validation task. Record instructor setup time, intervention count, completion, accessibility issues, wrong-board events, and lesson outcomes. Expand only if support effort is sustainable.

## 16. Research and publication program

### 16.1 Investigator-led technical study

Frame the initial contribution around reliable, recoverable mobile interaction with constrained MicroPython devices—not simply “an IDE exists.” Use released, traceable artifacts and publish the experimental protocol, scripts, configurations, negative results, and analysis.

Compare appropriate USB serial, Wi-Fi, or simple BLE workflows only where they can perform a comparable task on compatible hardware. Document differences in firmware, host, security model, file-integrity behavior, and initial setup. Do not declare victory by comparing unmatched workloads or excluding provisioning from only one condition.

Measure task completion, latency distributions, throughput by payload size, reconnect/recovery time, data integrity under interruption, memory/resource bounds, and control behavior during console load. Energy measurements are optional and require calibrated equipment and a defined measurement boundary.

### 16.2 Education study

Separate exploratory usability work from claims of improved learning. Before collecting research data, determine institutional review and consent requirements. Use equivalent tasks, a counterbalanced or otherwise justified design, prespecified outcomes, and an independent evaluator where feasible. Report prior experience, device access, assistance, attrition, and missing follow-up.

A chemistry-focused lesson could examine temperature acquisition or calibration on safe hardware. A later student project may build on the stable platform, but the first product cycle and technical manuscript should not depend on a future student cohort.

### 16.3 Publication decision

Select a venue after identifying the actual contribution: research software, embedded systems, computing education, or chemistry education. Re-check current submission and software-review requirements before submission. A DOI, license, media story, or extensive test suite helps reproducibility but does not guarantee publishable novelty or acceptance.

Advance a manuscript when the contribution and evidence are sufficient. Otherwise publish an honest technical report and use the findings to improve the product.

## 17. Sustainability and commercial validation

Maintain the free, open core and existing prohibition on paid/closed PyBLE features.[^agents] Test revenue around work and support, not restrictions on basic use.

Candidate offers are vendor porting, validation assistance, instructor training, classroom deployment support, openly maintained lesson development, and hardware kits with documented support. Propose partner-funded improvements that can be maintained upstream. Do not create a proprietary protocol extension or closed reference client to capture revenue.

Before productizing an offer, conduct approximately five discovery conversations and one tightly scoped service pilot. Record engineering hours, recurring maintenance, hardware/logistics cost, support load, and whether someone will pay for the defined outcome. These are experiments, not revenue forecasts.

Keep PyBLE Ready separate from payment for services. Porting, testing assistance, training, and ongoing support may be paid work, but payment cannot buy the badge, change a result, or unlock compatible app use. Keep self-run conformance tools and criteria openly available; define any future administrative funding model through a separate governance decision that preserves these boundaries. Funding through grants, sponsorship, donations, or services should not alter test outcomes or editorial honesty.

## 18. Team, capacity, and operating process

### 18.1 Role allocation

| Role | Responsibility | Minimum practical arrangement |
|---|---|---|
| Project owner / product lead | Scope, prioritization, resources, stage decisions | Lead maintainer; fixed weekly decision slot |
| App maintainer | Flutter workflow, accessibility, lifecycle, diagnostics | Initially may be the lead maintainer |
| Firmware/protocol maintainer | Contracts, agent parity, compatibility | Initially may be the same person; limits parallel work |
| QA/release reviewer | Evidence, physical matrix, recovery, artifact identity | Separate reviewer for high-risk changes wherever feasible |
| Pilot/instructor lead | Recruitment, consent, safe lesson delivery, observation | Named helper or deliberately reduced cohort |
| Documentation/localization reviewer | Release accuracy and language review | Bounded review contribution, not assumed full-time staff |
| Partner port owner | Port maintenance and retesting | Required before accepting a new supported profile |

Multiple roles can belong to one person, but this does not multiply capacity. Record missing independent review; do not disguise self-review as independent validation.

### 18.2 Capacity and budget discipline

Use existing boards/devices first and buy hardware only to close an identified matrix gap. Budget separately for physical test fixtures, spare boards/cables, app distribution, participant logistics, translation, and independent security review. Obtain actual costs before committing a funded milestone; this plan does not assume an approved budget.

Limit work in progress to one substantial implementation change plus one documentation/release task. Hold weekly triage, a two-week evidence review, and a monthly decision review. Track time spent supporting each profile before accepting another.

### 18.3 Issue-to-release workflow

1. Select an issue and verify that it is not already implemented or tracked.
2. Approve scope and update the normative specification/ADR where required.
3. For behavior, add the repository-required failing test and implement the smallest passing change; use applicable document checks for documentation-only work.
4. Run relevant cross-component and clean-room/license gates; sign off commits.
5. Review behavior, evidence, privacy, compatibility, and recovery.
6. Merge only through the repository's actual rules and required checks.
7. Qualify the exact release artifact and update user-facing documentation.
8. Publish or submit, then verify the claimed installation path and record the result.

Do not assume that a plan author, coding assistant, or passing simulator can approve hardware support, submit stores, or authorize a new protocol contract.

## 19. Risks and strategic decision gates

### 19.1 Risk register

| Risk | Early warning | Mitigation / stop condition |
|---|---|---|
| Publicity without use | Articles rise but first-use/return metrics do not | Fix activation or reconsider the job to be done; stop feature expansion |
| Technical assurance without useful work | Reports grow while participants only repeat demonstrations | Keep the three active outcomes visible; observe Task C and reasons to choose PyBLE before expanding scope |
| Inaccurate third-party claims | Users expect GDB, desktop clients, or OTA | Maintain canonical fact sheet and targeted corrections |
| Release-state confusion | README, store, and app build disagree | Separate verified publication, installation, provenance, and qualification fields; date each source |
| Evidence debt | Owner confirmation or old tests reused as fresh qualification | Preserve history; require exact-artifact records for new claims |
| Nearby unauthorized control | Wrong-board access or untrusted-client writes | Restrict environment; stop unsafe pilots; advance ownership-security design |
| File or draft loss | Recorded volatile drafts remain unresolved; overwrite, stale state, or silent corruption appears | Prioritize A-24; reproduce release-blocking regressions; never claim durable recovery before its evidence passes |
| Solo-maintainer overload | Support consumes reserved capacity; fixes accumulate | Reduce new scope and parallel work; review support changes explicitly; recruit ownership before expansion |
| Board fragmentation | Every release requires bespoke fixes | Exact profiles, explicit capability tests, bounded partner intake |
| Misleading or stale Ready badge | Claim spreads to another revision/version, implies preinstalled firmware, or loses its owner | Link exact evidence and installation status; review, suspend or withdraw unsupported claims |
| Store/distribution delay | Rejections, inaccessible beta, regional/device mismatch | Preserve truthful beta path; revise calendar, not evidence |
| Misleading research | Novelty claims depend on unmatched comparisons | Prespecify tasks, report limitations, separate usability from efficacy |
| Premature monetization | Support commitments exceed demand/capacity | One bounded service experiment before productizing |

### 19.2 Stage gates

`SG` identifies strategic gates in this document. These do not rename or replace repository CI G0/G1 or firmware C3-G0…C3-G6 gates. Record each strategic decision as `pass`, `iterate`, `blocked`, or a documented limited-scope decision. Explaining a missed target is useful evidence, not an automatic pass.

| Gate | Decision | Required evidence |
|---|---|---|
| SG0 — Baseline accepted | Commit the selected cycle scope | One primary audience/job and recruitment owner; dated status/unknowns, pilot boundaries, named capacity, sized work, and prioritized failures |
| SG1 — Core release ready | Submit/publish the candidate | Applicable normative matrix, no unresolved release-blocking safety/data-loss defect, recovery, provenance, accurate instructions |
| SG2 — Activation demonstrated | Invest in wider acquisition | At least 12 eligible primary-cohort starts; ≥80% unassisted completion and reported timing target met; no unresolved severe failure; otherwise iterate or explicitly limit scope |
| SG3 — Repeat value demonstrated | Consider broader product investment | At least 20 activated, consented primary-cohort participants whose day-14 windows have closed; ≥40% confirmed useful day-7–14 returns among that full denominator as a provisional indicator; Task C outcomes/reasons, opportunity, prompting and missing data reported; otherwise inconclusive/iterate or a dated limited-scope decision |
| SG4 — Maintained compatibility demonstrated | Expand partner-profile support | Existing-profile procedure independently reproduced; first public record meets Ready criteria; one external maintainer's responsibilities and setup/support effort demonstrated; additional demand and capacity identified |
| SG5 — Classroom ready | Expand supervised teaching | Safe multi-board selection, sustainable support, consent/review, measured pilot outcomes |
| SG6 — Secure deployment ready | Consider untrusted/field use | Approved ownership design, independent review, recovery and downgrade evidence |

SG1 and SG2 can be assessed in the same review, but technical correctness does not substitute for usability. SG2 and SG3 do not gate a qualified maintenance release. The retention percentage alone cannot pass SG3 without meaningful-task evidence, and inadequate opportunity to use calls for interpretation rather than an automatic rejection of the product. Recalibrate proposed thresholds/windows only in a dated prospective decision that preserves the original target and observed results. SG4 governs expansion after a bounded pilot; it does not block the existing-profile rehearsal or criteria draft in §14.

### 19.3 Continue, narrow, or pause

**Continue** when activation and repeat tasks improve and support remains manageable. **Narrow** when one device/profile/use case succeeds and broader claims create failures. **Pause expansion** when users cannot complete the core workflow, evidence remains incomplete, safety is unresolved, or maintenance exceeds capacity.

At cycle end, choose one principal next investment: Reliable Projects, partner portability, or classroom usability. Keep the other tracks at discovery level until staffing permits. Avoid starting all three because the platform vision sounds attractive.

## 20. Immediate execution checklist and handoff

### 20.1 First working week

- [x] Inspect current `main` at `23ed764`, the current public roadmap, implementation seams, and existing validation tools.
- [x] Carry forward PR #33's completed Android open-testing correction and #24's closed/superseded state; preserve pending evidence.
- [x] Identify A-24/ADR-0010 durable drafts as a concrete remaining engineering gap.
- [ ] Confirm one reachable primary audience, recruitment owner, previous workflow and meaningful Task C; keep other audiences exploratory.
- [ ] Assign actual capacity and accept a bounded first sprint; size persistence and mandatory physical work before promising the full cycle.
- [x] Verify existing Play/TestFlight installations and launches on the connected tablets; record actual builds, provenance limits and responsible owner follow-up. Fresh enrollment/reinstallation was not exercised.
- [x] Link PYB-001/003/004/006/009 execution tasks and evidence in the local Scrum package; record the real residual TestFlight discrepancy as PYB-002.1. Preserve A-24/ADR identities; no GitHub issues were fabricated or created.
- [ ] Assign one owner and one review path for each initial issue.
- [ ] Inventory exact test boards, tablets, cables, and available recovery equipment.
- [ ] Freeze Task A/B/C definitions, assistance/timeout rules, prospective follow-up windows and task-opportunity questions, consent procedure, and manual support template; observe initial eligible participants.
- [x] Specify and peer-review the bounded current-text contract and its acceptance scenarios; size the safe increment. Runtime implementation and bounded engineering acceptance are recorded in C1-S2. The dated continuation order preserves original forecasts; source integration and the Apple upload are recorded, while channel delivery remains pending.
- [ ] If operator/capacity is available, include one existing-profile Ready rehearsal and draft record in PYB-009; show installation status and pending evidence explicitly.

### 20.2 Issue template

```markdown
## User problem and evidence
Describe the observed failure or validated need. Link its evidence.

## Scope
In scope:
Out of scope:

## Contract and dependencies
Affected specification / ADR:
Existing story / issue (for example A-24):
App / firmware / protocol compatibility:
Required prior issues:
Estimate including validation / sprint allocation:

## Acceptance criteria
- [ ] Observable user outcome is demonstrated.
- [ ] Failure, interruption, and recovery cases are tested.
- [ ] Existing compatible clients/firmware behave as specified.
- [ ] Privacy and hardware-safety boundaries are preserved.
- [ ] Required exact-artifact hardware evidence is attached or explicitly pending.

Source-complete and release-qualified status must be recorded separately;
pending required evidence does not pass the release gate.

## Verification
Automated tests:
Physical devices / profiles:
Release artifacts and hashes:
Delivery channel / installed-build provenance:
Limitations / not-run cases:

## Ownership and release
Implementation owner:
Reviewer:
Release lane / current work state:
Rollback / recovery:
Documentation and distribution changes:
```

### 20.3 Coding-agent handoff

Use the following task framing for each accepted issue. Work within the maintainer's existing task authorization and repository rules; this plan alone does not approve proposed wire contracts, new hardware claims, or store publication.

```text
Work on one accepted PyBLE issue only.

1. Read AGENTS.md, CONTRIBUTING.md, the affected specification, existing
   tests, and relevant release/architecture decisions.
2. Check for an existing implementation and linked issues before adding code.
3. Identify any contract change. Do not invent opcodes, capabilities,
   firmware support, or release status. Obtain the required approval first.
4. Follow specification-first and red/green/refactor for behavior changes;
   validate documentation-only changes with the relevant document gates.
5. Preserve BLE-first, offline-core, open-source, and no-telemetry boundaries.
6. Run the relevant tests and repository gates. State what was not run.
7. Never fabricate hardware evidence, user adoption, store approval, or a
   successful install. Keep pending hardware/release work explicit.
8. Summarize changed files, observed behavior, compatibility, evidence,
   remaining risks, and the next review decision.
```

### 20.4 Decision record for every sprint

[C1-S1 execution and decision record](../developments/2026-q4-reliable-workflow/c1-s1/00_Execution_Record.md) is the first dated instance. Device installation checks are complete; pilot setup, participant evidence and capacity decisions remain pending. It is not a completed Sprint Review.

Record shipped versus proposed work; exact tested artifacts; pass/fail/not-run results; the selected audience and useful-task outcomes; reasons to choose PyBLE; opportunity-to-use and prompting context; maintenance/support burden; and one explicit next-sprint priority. Include Ready rehearsal/record status only when that work is selected. Store identities and participant data separately from public aggregate reports.

**Next action:** confirm one primary audience, pilot owner, tested board setup and useful task; pursue recorded provenance/metadata follow-up; and replan/select implementation against the specified bounded A-24 recovery contract and its estimate. Observe useful work and follow-up alongside delivery of the smallest qualified maintenance change. Reuse operator work for a bounded existing-profile Ready rehearsal if capacity is assigned. Let task failures, repeat value, and support effort determine subsequent protocol, partner, or classroom investment.

## 21. Source references

The strategy supplies the proposed direction. The sources below ground the existing implementation, governance, and firmware-roadmap constraints. They were inspected on 25 September 2026 at `main` commit `23ed764b0ef88dce9720c66fbd1c0655268860cf`. Footnote source links are pinned to that revision; convenient relative links in the implementation map follow the working tree. GitHub issue/PR links are dated workflow evidence, not immutable test receipts. Current normative specifications and accepted ADRs govern implementation; this planning document cannot override them.

[^readme]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/README.md>
    PyBLE README, sections on application behavior, app source version, firmware v0.6.1 publication, five exact profiles, provisioning, and imports.

[^agents]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/AGENTS.md>
    PyBLE contributor guidelines, including specification-first and test-first development, hardware evidence, DCO sign-off, clean-room/license boundaries, repository layout, and prohibition on paid or closed features.

[^public-roadmap]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/ROADMAP.md>
    PyBLE public roadmap, including current capabilities, owner-confirmed v0.6.1 status, reusable conformance-kit direction, and future-port requirements.

[^firmware-roadmap]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/planning/firmware-v0.6.1-v0.7.0-roadmap.md>
    Firmware v0.6.1/v0.7.0 roadmap, including proposed Reliable Projects capabilities, cross-version constraints, HIL acceptance criteria, separate security design, and deferred atomic project deployment. Some release-state text is historical and requires reconciliation with newer publication records; this plan does not treat it as current distribution truth.

[^android-review]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/testing/website/android-open-testing-2026-09-25.md>
    Dated Android open-testing publication review, including the official Google Play listing observation, package/version, account/device limitations, and absence of signed-in installation or exact installed-build evidence. The [website specification](https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/specifications/website.md) defines the maintained distribution wording.

[^pr33]: <https://github.com/PyBLE-dev/PyBLE/pull/33>
    PR #33, merged on 25 September 2026 at `23ed764b0ef88dce9720c66fbd1c0655268860cf`; source/specification/tests for coordinated Android open-testing copy. Its merge is source-delivery evidence, not proof of a store-installed app or search-engine recrawl.

[^publication]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/testing/firmware-v0.6.1-publication-2026-09-11.md>
    Firmware v0.6.1 publication record: owner-confirmed release, firmware source `c8f549eeabe6d2b8c2766eab022517944bb09c8c`, artifact checks, and preservation of incomplete automated HIL evidence.

[^issue24]: <https://github.com/PyBLE-dev/PyBLE/issues/24>
    Issue #24, inspected closed with reason `NOT_PLANNED` and closure date 13 September 2026; [closure explanation](https://github.com/PyBLE-dev/PyBLE/issues/24#issuecomment-5652537345). Supersession does not complete its historical checklist.

[^app-contract]: <https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/specifications/App/specs.md>
    Current App specification, [App TDD](https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/specifications/App/TDD.md), and [ADR-0010](https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/decisions/0010-working-loop-in-memory-document.md). FR-EDIT-7, FR-PROJ-2/6, and NFR-REL-3 remain carried persistence requirements; A-24 re-freezes the deferred implementation. Protocol behavior remains governed by [PBLE/1](https://github.com/PyBLE-dev/PyBLE/blob/23ed764b0ef88dce9720c66fbd1c0655268860cf/docs/specifications/protocol.md).

---

**End of document — PyBLE Implementation Plan and Development Strategy, revision 1.4**
