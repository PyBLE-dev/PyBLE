<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Cycle 1 — delivery guide and Scrum working agreement

## Document control

| Field | Value |
|---|---|
| Package | PyBLE 2026 Q4 reliable workflow, Cycle 1 (`C1`) |
| Prepared | 25 September 2026; Asia/Bangkok |
| Strategy | [Implementation Plan, revision 1.2](../../planning/PyBLE_Implementation_Plan_and_Strategy_v1.0.md) |
| Repository baseline | `23ed764b0ef88dce9720c66fbd1c0655268860cf` |
| Proposed cycle | 28 September–20 December 2026; six two-week Sprints |
| Status | Proposed delivery package; no Sprint Planning, estimates, named assignments, implementation approval, or new physical results are implied |
| Primary audience | Tablet-owning makers, provisionally; confirm one reachable cohort before observation |
| Authoritative contracts | [Contributor rules](../../../AGENTS.md), [App specification](../../specifications/App/specs.md), [App TDD](../../specifications/App/TDD.md), [PBLE/1](../../specifications/protocol.md), and applicable firmware/release specifications |

This package derives execution views from the strategy. It does not replace normative specifications, expand hardware claims, create GitHub issues, or authorize store/website publication. The strategy file is currently a local document; include it with this package when proposing the documentation for version control.

## Navigation and ownership of information

| File | Canonical responsibility in this package | Update trigger |
|---|---|---|
| [01 — Overview and Scrum framework](01_Overview_and_Scrum_Framework.md) | Product Goal, working agreement, quality and evidence rules | Agreement or governing contract changes |
| [02 — Product roadmap](02_Product_Roadmap.md) | Outcomes, horizons, and conditional investments | Product Goal or strategic priority changes |
| [03 — Milestones](03_Milestones.md) | Evidence-based decisions and admission criteria | New evidence or a milestone decision |
| [04 — Sprint plan](04_Sprint_Plan.md) | Sprint Goal forecasts, calendar, and capacity | Sprint Planning or Sprint Review |
| [05 — Product backlog and stories](05_Product_Backlog_and_Stories.md) | Ordered work, parent/child identities, acceptance criteria, and source traceability | Refinement or changed user evidence |
| [06 — Sprint backlogs](06_Sprint_Backlogs.md) | Candidate tasks, local effort allowances, dependencies, and execution status | Developers select/adapt work during a Sprint |

```mermaid
flowchart LR
    Strategy["Strategy revision 1.2"] --> Goal["One Product Goal"]
    Goal --> Roadmap["Outcome roadmap and milestones"]
    Roadmap --> Product["Ordered Product Backlog"]
    Product --> Planning["Sprint Planning"]
    Planning --> Sprint["Sprint Goal and Sprint Backlog"]
    Sprint --> Increment["Increment meeting Definition of Done"]
    Increment --> Review["Sprint Review: inspect evidence"]
    Review --> Product
    Review --> Roadmap
    Sprint --> Retro["Retrospective: improve how we work"]
    Retro --> Planning
```

## Product Goal and current baseline

**Proposed Product Goal:** tablet-owning makers can complete useful BLE board work, recover their local work after interruption, and choose PyBLE again for a relevant task using accurately identified app and firmware builds.

| Active outcome | Main planning parents | Evidence of value |
|---|---|---|
| Know what users install | PYB-001; residual PYB-002 only | Reproducible installation guidance and dated channel/build evidence |
| Preserve users' work | PYB-006, supported by PYB-008/009 | Accepted draft survives the specified restart/failure cases without implicit board writes |
| Complete useful repeat tasks | PYB-003/004/011/012; PYB-005 if observed | Task C attempts, later-day useful work, reasons to choose PyBLE, and support effort |

| Baseline fact | Consequence |
|---|---|
| Android open-testing copy correction is complete in PR #33 | Do not replan that correction; identify any new discrepancy separately |
| App source is `0.2.0+8`; Play publicly identifies `0.2.0`; iPad remains external TestFlight beta | Source version does not prove the installed store binary or its source commit |
| Firmware v0.6.1 is published on owner confirmation across five exact profiles | Pending automated results stay pending; no automatic PyBLE Ready badge |
| Issue #24 is closed/superseded | Do not resurrect its old release umbrella as a dependency |
| Editor draft is volatile under [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md) | Close an accepted subset of A-24; do not claim full project persistence or Blocks recovery |
| Lifecycle protections, tutorials, imports, and test tools already exist | Reuse them; refine only observed gaps and the documented persistence gap |

## Applying Scrum to PyBLE

The [2020 Scrum Guide](https://scrumguides.org/scrum-guide.html) is the framework reference. The Product Backlog is ordered by the Product Owner; Developers select and adapt Sprint work. Product Goal, Sprint Goal, and Definition of Done guide the respective artifacts. A Sprint Review inspects progress and informs adaptation; it is not a mandatory release approval meeting. Roadmaps, milestones, user-story notation, and hour allowances below are PyBLE planning practices, not additional Scrum requirements.

| Accountability | Proposed PyBLE arrangement | Assignment state |
|---|---|---|
| Product Owner | One maintainer accountable for the Product Goal, backlog order, and stakeholder tradeoffs | Named person TBD |
| Scrum Master | Facilitates effective Scrum, impediment removal, and sustainable delivery | Named person TBD; any combined responsibility must be explicit |
| Developers | Contributors collectively plan and deliver work, including applicable tests and evidence | Actual availability and skills TBD |
| Stakeholders/contributors | Release owner, board operator, pilot coordinator, instructor, and language reviewer supply expertise/access | These contribution responsibilities do not create extra Scrum accountabilities |

Do not represent a solo-maintainer workflow with missing accountabilities as a fully staffed Scrum Team. Record the practical arrangement and its limits. Role labels in tables are suggestions, not assignments to absent people. A coding agent does not supply independent physical evidence or become the accountable Product Owner.

| Event/practice | Proposed local cadence | Concrete output | Capacity treatment |
|---|---|---|---|
| Sprint Planning | First working day; initially allow 60 minutes | One Sprint Goal, selected items, task plan, named capacity and dependencies | Inside the Sprint's gross hours |
| Daily Scrum | 15 minutes each working day | Developers inspect the Goal and adapt the immediate plan | Inside the Sprint's gross hours |
| Sprint Review | Last working day; initially allow 60 minutes | Inspect usable Increment and evidence with stakeholders; adapt backlog | Inside the Sprint's gross hours |
| Sprint Retrospective | After Review; initially allow 45 minutes | One improvement to apply in the next Sprint | Inside the Sprint's gross hours |
| Refinement | Up to one hour weekly initially, adjusted to need | Split/clarify upcoming items; Developers size their work | Included within available capacity; no separate approval ceremony |

These local durations can change with the team; the Daily Scrum remains 15 minutes. The 14-hour reserve per Sprint includes events, refinement, support, additional qualification, and uncertainty. Do not count those hours again as extra delivery capacity.

## Local readiness and Definition of Done

| Before selection: local readiness aid | Required clarification |
|---|---|
| User outcome or learning question | Named beneficiary, observed problem, bounded in/out scope |
| Governing contract | Specification/ADR and prior approval required for behavior changes; any carried exception visible |
| Acceptance and evidence | Observable scenarios, relevant tests, physical devices when required, evidence location |
| Feasibility | Developers' estimate, actual owner/access, dependencies, safe rollback/recovery |

Readiness is a local refinement aid. It does not replace Sprint Planning or add a formal Scrum commitment. Unknowns can be selected as time-boxed discovery items with their own explicit output.

| Definition of Done: applicable requirement | Evidence required |
|---|---|
| Behavioral scope agrees with the accepted contract | Specification/ADR changed before implementation where required; all selected acceptance scenarios satisfied |
| Behavior is verified | Required `[red]` then `[green]` work, relevant regression checks, and mandatory physical evidence for the selected scope; refactor only while green |
| Repository boundaries hold | DCO-signed commits when committing; no-leak, license, dependency, localization/import, and actual required CI checks as applicable |
| Increment is coherent and usable | Review completed; integration and relevant documentation agree; no unresolved blocking data-loss or unintended-write defect |
| Claims have evidence | Exact artifacts, pass/fail/not-run states, limitations and pending release work recorded truthfully |
| Documentation/discovery scope is complete | Usable reviewed record/guide or agreed findings, source/link checks, and explicit unmet targets; no invented physical results |

This is the proposed package-wide minimum; accepted normative requirements remain binding. Apply it to the selected item rather than treating a source merge as a finished feature. A documentation or discovery item can be Done with a negative finding, while a required physical-installation task cannot be Done if no installation happened. A usable Sprint 1 documentation increment should help an operator or user perform the current workflow; an internal plan alone is not evidence of improved app behavior.

| State distinction | Meaning |
|---|---|
| Source complete | Implementation/review work reached its source milestone; required physical or integration work may still prevent Done |
| Done Increment | Selected acceptance and applicable Definition of Done are met; it can be inspected and used in its declared scope |
| Release admitted | All applicable release-level gates, support matrix, provenance and distribution prerequisites pass |
| Submitted / available / installed | Three different distribution observations, each requiring its own evidence |

Unfinished items return to the Product Backlog for reordering and replanning. Do not count them as Done or convert a blocked result into a pass. A release can happen during any Sprint when its applicable gates pass; recruitment and retention do not block an otherwise qualified maintenance release.

## IDs, evidence, and change control

| Convention | Rule |
|---|---|
| `PYB-001` … `PYB-032` | Existing strategy planning parents; not GitHub issue numbers |
| `PYB-006.1`, `PYB-006.2`, etc. | Derived child items in this package; acceptance is maintained in file 05 |
| `A-24` | Existing broader persistence story; a bounded child does not complete all of it |
| `C1-S1` … `C1-S6` | This cycle's Sprints; distinct from historical App TDD Sprint labels |
| `C1-S1-T01`, etc. | Proposed task rows; not new public contracts |
| `M-01`, etc.; `SG0` … `SG6` | Delivery milestones versus strategy gates; neither replaces CI G0/G1 or C3 firmware gates |
| Item/task status | Proposed → Selected at Planning → In progress → Review → Done; Blocked records a reason/owner; later forecasts remain Proposed |
| Private versus public records | Contact/consent, device identifiers and raw logs remain private/ignored; publish only reviewed aggregate findings and redacted evidence |

When facts or priority change, update the canonical file above and its dependent tables together. Preserve old evidence and dated decisions. New opcode/capability values, hardware support, Ready awards, and publication need their normal specification and authorization paths; none is inferred from this package.

## Source map

| Source | Use and precedence |
|---|---|
| [Strategy revision 1.2](../../planning/PyBLE_Implementation_Plan_and_Strategy_v1.0.md) | Scope, targets, six-Sprint capacity, three outcomes, Ready program and conditional horizons |
| [Public roadmap](../../ROADMAP.md), [README](../../../README.md) | Current capability and distribution baseline |
| [App specification](../../specifications/App/specs.md), [App TDD](../../specifications/App/TDD.md), [ADR-0010](../../decisions/0010-working-loop-in-memory-document.md) | Persistence contract and recorded implementation deviation; consult frozen working-loop scope |
| [Firmware roadmap](../../planning/firmware-v0.6.1-v0.7.0-roadmap.md), [PBLE/1](../../specifications/protocol.md) | v0.7 proposals versus frozen wire behavior; old v0.6.1 publication/#24 wording is historical |
| [Android publication review](../../testing/website/android-open-testing-2026-09-25.md), [v0.6.1 publication record](../../testing/firmware-v0.6.1-publication-2026-09-11.md) | Dated evidence; neither establishes a newly installed binary or missing automated qualification |
| [HIL guide](../../../tests/firmware_tests/hil/README.md), [CI workflow](../../../.github/workflows/ci.yml), [CONTRIBUTING](../../../CONTRIBUTING.md) | Reuse existing tools and gates; actual CI requirements govern merges |
