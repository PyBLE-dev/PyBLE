<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# Cycle 1 — Sprint plan and capacity forecast

| Field | Value |
|---|---|
| Status | C1-S1 remains partial; bounded S2 recovery and app-only qualification pass 31 October engineering review. S2 follow-up and M-05 delivery remain unfinished; original dates/hours remain baseline forecasts |
| Cycle | `C1`, 28 September–20 December 2026, Asia/Bangkok |
| Basis | [Strategy revision 1.8, §8](../../planning/PyBLE_Implementation_Plan_and_Strategy_v1.0.md#8-twelve-week-implementation-schedule) |
| Product Goal and quality rules | [Working agreement](01_Overview_and_Scrum_Framework.md) |
| Acceptance criteria | [Product backlog and stories](05_Product_Backlog_and_Stories.md) |
| Task-level proposal | [Sprint backlogs](06_Sprint_Backlogs.md) |

**31 October acceptance update:** scoped current-text recovery (PYB-006.2 / M-02) and the app-only M-04 candidate pass engineering review at `bef67bd`: 984 ordinary tests, 36 frozen-runtime CI checks, both-platform recovery/keyboard evidence and all ten declared app/profile rows. The [C1-S2 record](c1-s2/00_Execution_Record.md) preserves exact artifacts, firmware baselines, earlier-row impact assessments and the temporary Android qualifier battery-policy condition. Signed packages and the release packet are prepared; original device policy and normal board advertising are restored, and owned fixtures are cleaned. Final branch integration and actual M-05 store delivery remain separate. S1 remains six Done / two Prepared / four Awaiting evidence; S2 has ten engineering tasks Done and participant follow-up unfinished. Original dates/hours remain the baseline; the [continuation plan](04_Sprint_Plan.md#31-october-continuation-order-and-reforecast) records the next work and unresolved human capacity.

## Forecast and commitment boundary

| Planning element | Treatment |
|---|---|
| `C1-S1` | Six tasks Done, including existing channel installations; two Prepared awaiting pilot setup and four Awaiting evidence. Actual staffing and the original formal timebox still require confirmation |
| `C1-S2` … `C1-S6` | Forecasts revised using preceding results, capacity and learning |
| Sprint Goal | One coherent outcome confirmed by the Scrum Team at Planning |
| Scope and task details | Developers select feasible items and adapt their plan with the Product Owner as learning changes scope |
| Milestones | Inspectable evidence/decision points; not mandatory release ceremonies or waterfall phases |
| Estimates | Task hours are initial capacity allowances, not measured velocity, story points, or promises |
| Missing people/devices/access | Explicit blockers; do not invent availability or lower the Definition of Done |

## C1-S1 findings and required reforecast

[Execution evidence](c1-s1/00_Execution_Record.md) records six Done tasks after verifying existing Play and TestFlight installations. T04/T05 are Prepared awaiting pilot setup; T06–T08 await participants and T09 awaits observation records. These more specific states preserve their acceptance criteria. The original calendar is retained; no completed Sprint or SG0 approval is claimed.

| New sizing input | Planning consequence |
|---|---|
| Recovery engineering 38–63h; recipe, representative physical work and one follow-up allowance bring the original two-week scope to 45–72h | Original S2 allowance is insufficient; contract and all required failure/session protections remain intact |
| [Working allocation option](c1-s1/03_Recovery_Design_and_Sizing.md): S2 26h, S3 22h, S4 12h, totaling 60h | Fits within the three 26h ceilings only by replacing original selections; includes 50h engineering, 2h recipe, 5h physical and 3h rolling follow-up |
| [App matrix](c1-s1/04_Validation_Inventory_and_Operator_Recipe.md): 13.5–26 operator h; fresh firmware qualification 30–59h excluding builds/access/repair | Select the applicable scope; do not treat app-only work as a new firmware release or count representative recovery runs twice |
| Connected tablets now verified; human capacity, pilot owner and exact-board setup still unconfirmed | Bind future recovery runs to their actual candidate and board, and confirm owners before selecting revised scope; maintain rolling follow-up only for actual consenting activations |

The remaining 18h under S2–S4's combined 78h ceiling cannot silently absorb all displaced matrix, activation and repair tasks. Reorder those tasks, review the November recruitment window, and reforecast S5/S6 if required. The tables below preserve the original allowance/calendar for comparison; they are **not** an adopted revised forecast. A tested foundation is not the completed recovery user story. All selected increments still need their applicable Definition of Done.

## C1-S2 implementation execution — 31 October

The next-release instruction selects PYB-006.2 engineering and its required
verification, supporting PYB-009.1 recipe work and applicable PYB-008.1 evidence.
The [execution record](c1-s2/00_Execution_Record.md) owns actual results. Source
storage/coordinator/UI/guard work is merged and automated checks pass; the usable story remains in
progress until all applicable acceptance passes. The original 12–25 October S2
window is historical; calendar position does not mark S2 or S3 complete.

The 45–72-hour estimate and 60-hour S2–S4 allocation option remain estimates.
They are not confirmed staffing, measured effort or an adopted replacement for
the tables below. Reorder displaced matrix/activation work with actual capacity;
keep pilot evidence and the M-01/SG0 gap visible while known engineering work
continues. No automatic completion of S1, SG0, broader A-24 or PyBLE Ready follows.

## 31 October continuation order and reforecast

The user requested completion of the remaining work after reviewing the stage
assessment. The selected engineering order is below. This records actual work
selection; it does not invent a completed Sprint Planning event, human staffing,
measured velocity or a new delivery deadline. The original C1-S3 window is
26 October–8 November; unfinished S2 acceptance carries into that window.

| Order / stream | Current work and completion evidence | Forecast treatment |
|---|---|---|
| 1 — M-02 recovery acceptance | Accepted: DR-T01–14 reviewed against automated and exact platform evidence, including generated text and current-target consent | Completed outcome on 31 October; no measured human effort inferred from agent execution |
| 2 — M-04 release qualification | Engineering pass: frozen `bef67bd` artifacts, ten declared app/profile rows, packaging and scoped review; device closeout complete; branch integration tracked separately | This outcome covers the same later forecast batches; do not repeat them without a changed artifact or invalidated evidence |
| 3 — M-05 distribution | Prepared handoffs; verify account/build-number state, submit the admitted artifact after final integration, then record processing/availability and installed-channel evidence | Next release stage; owner access and external review duration remain unresolved |
| Parallel — M-01 pilot baseline | Confirm pilot owner, primary cohort, exact reference setup and actual weekly capacity; collect real consented baseline sessions using the prepared kit | Awaiting human inputs; engineering observations are not participant starts |
| Later — M-03/M-06 learning | Collect useful-task and prospective day-7–14 follow-up observations from actual consenting activations | Preserve original recruitment targets; reforecast dates after real recruitment and capacity are known |
| Conditional — Ready rehearsal | Use an assigned second operator for one exact profile only after capacity is selected | Remains optional; it is not a prerequisite for unrelated maintenance delivery |

Required planning inputs are the named pilot/recruitment owner, selected cohort
and reference setup, actual engineering/pilot hours per week, and any existing
consented session records. Until supplied, the 20h/week assumption, 45–72h
recovery estimate and 60h allocation option remain historical planning inputs.
Do not subtract agent wall-clock time from human capacity or relabel elapsed
calendar time as measured engineering effort. Maintain the original 22 November
activation target alongside any later approved forecast; missed windows remain
missing or late evidence.

## Capacity model

The source assumes one primary maintainer at 20 hours/week. Confirm real availability and any contributor capacity at Planning; extra roles do not create extra hours.

| Sprint | Gross assumed hours | Base planned allowance | Unallocated planned headroom | Reserve | Planned ceiling |
|---|---:|---:|---:|---:|---:|
| C1-S1 | 40 | 22 | 4 | 14 | 26 |
| C1-S2 | 40 | 24 | 2 | 14 | 26 |
| C1-S3 | 40 | 24 | 2 | 14 | 26 |
| C1-S4 | 40 | 22 | 4 | 14 | 26 |
| C1-S5 | 40 | 24 | 2 | 14 | 26 |
| C1-S6 | 40 | 20 | 6 | 14 | 26 |
| **Total** | **240** | **136** | **20** | **84** | **156** |

The reserve covers events/refinement, support, additional qualification and uncertainty. Known tests/reviews belong in each selected item's estimate. Rehearsal or optional work may consume explicitly assigned headroom; do not count it twice. The 26-hour ceiling is a local planning assumption, not a Scrum rule. If required work does not fit, reduce scope or revise the forecast, preserving quality and the fixed Sprint timebox.

## Sprint Goals, usable results, and evidence

| Sprint / dates | Proposed Sprint Goal | Candidate parents / child items | Intended usable result | Review evidence and milestone link |
|---|---|---|---|---|
| **C1-S1** — 28 Sep–11 Oct | Make the current installation and primary-cohort task reproducible, and determine a feasible draft-recovery scope | PYB-001.1/.2, 003.1, 004.1/.2, 006.1, 009.1; 011.2 when follow-up is due; residual 002 only if found | Reviewed installation/evidence record and reusable current-workflow task/operator guidance; accepted recovery design if review completes | [M-01](03_Milestones.md): installed-state evidence/unknowns, named cohort, five baseline starts or explicit recruitment blocker, sized persistence and applicable matrix |
| **C1-S2** — 12–25 Oct | Enable recovery of the smallest accepted current-text draft scope while preserving safe board/session behavior | PYB-006.2; continue 009.1 and start 008.1; rolling 011.2; PYB-005.1 only for a real observed blocker | Usable bounded recovery increment when all selected acceptance and DoD checks pass | [M-02](03_Milestones.md): persisted boundary, relaunch, interrupted/corrupt storage and stale-completion evidence; visible carried A-24/Blocks scope |
| **C1-S3** — 26 Oct–8 Nov | Make the recovery increment reproducibly testable on selected devices and observe useful second tasks | PYB-008.1/.2, 011.1/.2; 006.2 only if replanned unfinished; optional 009.2 | Candidate-specific operator evidence and task findings; qualified maintenance changes may release now | [M-02/M-04](03_Milestones.md): completed versus pending matrix rows, Task C outcomes, optional existing-profile rehearsal with assistance/gaps |
| **C1-S4** — 9–22 Nov | Improve the highest-impact observed task obstacle and establish interpretable activation/follow-up cohorts | PYB-011.1/.2; 012.1 or 005.1 only if evidence selects it; affected 008 reruns | An observed improvement if a defect is selected; otherwise usable findings and existing-workflow guidance | [M-03](03_Milestones.md): at least 12 primary-cohort starts including failures; reasons to choose PyBLE; aim for 20 activated consenting participants by 22 Nov |
| **C1-S5** — 23 Nov–6 Dec | Reach a justified release decision for the candidate and account for mature follow-up windows | PYB-008.2, 013.1, 014.1 when admitted, 011.2 | Release-ready candidate if every applicable gate passes; otherwise explicit blocker and recovery plan | [M-04](03_Milestones.md): immutable artifacts and required gates; follow-up accounting by 6 Dec; submission recorded separately from approval |
| **C1-S6** — 7–20 Dec | Verify actual distribution and choose one next investment from useful-repeat and support evidence | PYB-014.1/.2 as needed, 011.2; cycle decision; optional 015.1 | Verified delivery record or documented external blocker, usable support guidance, evidence-based next backlog order | [M-05/M-06](03_Milestones.md): installed identity, complete denominator and missing-data report, support effort, one next-stage decision |

These are whole-product goals, not separate analysis, coding, testing and release departments. Every delivered increment includes its applicable design, implementation, verification and documentation. S3/S5 qualification work does not postpone tests needed to make earlier increments Done.

The inspected safe recovery slice exceeds the original S2 allowance. PYB-006.1 now supplies the contract and estimate for replanning before selection. Replan a smaller independently safe increment or later delivery; never label happy-path-only persistence Done or count the whole A-24 umbrella as complete.

## Calendar

The diagram shows forecast timeboxes, not guaranteed feature delivery. Reviews and Retrospectives are proposed for the last working Friday; Sprints end on Sunday so the next timebox begins immediately on Monday.

```mermaid
gantt
    title Proposed Cycle 1 Sprint timeboxes
    dateFormat YYYY-MM-DD
    axisFormat %d %b
    section Cycle 1 forecasts
    C1-S1 Reproducible baseline :s1, 2026-09-28, 14d
    C1-S2 Bounded draft recovery :s2, 2026-10-12, 14d
    C1-S3 Reproducible evidence and useful tasks :s3, 2026-10-26, 14d
    C1-S4 Observed task improvement :s4, 2026-11-09, 14d
    C1-S5 Candidate release decision :s5, 2026-11-23, 14d
    C1-S6 Verify delivery and choose next work :s6, 2026-12-07, 14d
```

| Sprint | Planning | Review and Retrospective | Important observation window |
|---|---|---|---|
| C1-S1 | Mon 28 Sep | Fri 9 Oct | First comparable baseline observations |
| C1-S2 | Mon 12 Oct | Fri 23 Oct | Continue recruitment alongside known persistence work |
| C1-S3 | Mon 26 Oct | Fri 6 Nov | Task C attempts and recorded-build cohorts |
| C1-S4 | Mon 9 Nov | Fri 20 Nov | Aim for 20 activated follow-up-consenting participants by Sun 22 Nov |
| C1-S5 | Mon 23 Nov | Fri 4 Dec | Latest target cohort's day-14 window closes Sun 6 Dec; include final late-weekend accounting in S6 if needed |
| C1-S6 | Mon 7 Dec | Fri 18 Dec | Cycle closes Sun 20 Dec; late observations remain clearly dated |

## Replanning and release rules

| Trigger | Action |
|---|---|
| Store/device access is unavailable | Mark the installation task Blocked and assign an owner; continue independent contract/tool work |
| Recruitment is insufficient | Record the gap; preserve the denominator and report outcomes inconclusive where required; continue qualified maintenance work |
| A severe observed defect appears | Order the smallest safe fix against the Sprint Goal; renegotiate selected scope rather than silently adding hours |
| A candidate or relevant input changes | Identify affected evidence and rerun/revalidate applicable checks; do not reuse old hashes as current results |
| All release gates pass before S5 | Release through the authorized normal process; retain dated records and revise later forecasts |
| Release gates do not pass by S5/S6 | Hold the release claim and show the blocker; the calendar does not waive a gate |
| No second operator is available | Keep PYB-009.2 pending; no independent-reproduction claim or Ready award; unrelated delivery continues |
| Cohort has no new task during days 7–14 | Keep it in the full eligible denominator; report opportunity separately and use only prospectively agreed additional windows |
| A future forecast item remains too large or vague | Return to refinement, split by usable outcome and size with Developers; do not fill a Sprint with an unresolved epic |

## Review record template

| Field | Record at each Review/Retrospective |
|---|---|
| Sprint Goal | Achieved, partially achieved or not achieved, with evidence |
| Increment | Demonstrable changes meeting DoD; unfinished items listed separately |
| Quality/release | Applicable test/physical results, exact artifacts, limitations, release state |
| Useful work | Tasks attempted/completed, assistance, opportunity, prompting and missing responses |
| Capacity | Actual delivery/support/event effort compared with allowances; no invented velocity |
| Adaptation | Updated ordered backlog, next proposed Goal, one process improvement |
