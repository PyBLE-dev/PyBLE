# ADR 0012 — Adopt `flutter_code_editor` behind an `EditorSurface` interface (closes App OI-1; bounds R1 instead of clearing it)

**Status:** Accepted (2026-07-25). **Closes App [OI-1](../specifications/App/specs.md) — the Flutter Python-editor widget choice.** Does **not** clear [R1](../specifications/App/TDD.md#17-risks--open-questions): R1 is re-scoped from "maturity unproven" to a **measured, bounded residual risk** with explicit fallback triggers. Re-freezes the rich-editor half of FR-EDIT-1/2/3/4 that [ADR-0010](0010-working-loop-in-memory-document.md) deferred. Honors [ADR-0003](0003-license-mit.md) (MIT), [ADR-0007](0007-riverpod-state-management.md) (Riverpod) and [ADR-0008](0008-signal-design-system.md) (Signal tokens). Preserves, without weakening, the hardware-verified typographic-substitution guarantee shipped in `lib/editor/smart_punctuation.dart`. [ADR-0040](0040-sha-pinned-connected-github-import.md) narrowly supersedes this decision's original app-wide `package:http` prohibition only for the bounded public-GitHub adapter under `lib/github_import/`; the editor sandbox and every prohibition on sending editor/user source remain unchanged.

## Context

[ADR-0010](0010-working-loop-in-memory-document.md) shipped a deliberately plain editor: a `SignalCodeColors`-styled `TextField` over `editorDocumentProvider` (`app/lib/editor/editor_view.dart`), with syntax highlighting, multi-file tabs, find/replace and external-keyboard shortcuts **deferred to OI-1** ([specs.md §4.6](../specifications/App/specs.md), [TDD.md §11.1](../specifications/App/TDD.md#111-editor)).

OI-1 has been open since the App TDD was authored. The spec already **names** `flutter_code_editor` as the intended widget behind an `EditorSurface` interface, with a WebView-hosted Monaco/CodeMirror editor as the documented fallback ([TDD.md §4.3](../specifications/App/TDD.md), [PRD §16.1](../specifications/prd.md)). What was open was never the *shape* of the answer — it was the **evaluation**, and specifically **R1**: *"`flutter_code_editor` tablet/external-keyboard maturity is unproven."*

Two things changed since ADR-0010, and both bear on the choice.

**1. The editor acquired a correctness invariant it did not have before.** iPadOS Smart Punctuation was rewriting `"` into `“ ”` as the user typed, and the board answered `SyntaxError: invalid syntax` against a line that looked correct on screen. This was **verified on real hardware**: `/test.py` was read back off the bench board over BLE as

```
b'print(\xe2\x80\x9cHello world!!\xe2\x80\x9d)\n'
```

The guarantee now has three layers: a `SmartPunctuationFormatter` on the editor field, a Python-aware scanner that corrects only *code position* and preserves string/comment *data* (`lib/editor/smart_punctuation.dart`), and unconditional normalization in `SaveController.save()` and `RunController.run()` so the board can never receive bytes it cannot tokenize. This is a user-facing, hardware-proven invariant. **No editor migration may weaken it**, and that constraint drove much of what follows.

**2. OI-1 was evaluated rather than assumed.** `flutter_code_editor` 0.3.5 was read at source level, its dependency closure resolved against the pinned toolchain, and its licence chain traced. The findings are neither a clean win nor a rejection, and they are the substance of this ADR.

**The decisive structural fact — it is a Flutter `TextField`.** `CodeField` builds an ordinary `TextField` (`lib/src/code_field/code_field.dart`). Everything PyBLE depends on therefore keeps working: iPadOS IME and dictation, selection handles and the magnifier, accessibility, `tester.enterText`, the existing widget/golden test ladder — and, critically, the smart-punctuation invariant stays enforceable *inside the Dart text pipeline* rather than behind a platform boundary. No WebView-hosted candidate has this property, and that single fact outweighs most of the costs below.

**What the evaluation found against it** (each verified directly in the installed package):

- **No `inputFormatters`.** `CodeField` does not expose them (zero occurrences in `code_field.dart`), so the A-25 field-level guard cannot be carried across as-is.
- **A Tab-key data-loss defect.** The private `_shortcuts` map binds `LogicalKeySet(LogicalKeyboardKey.tab)` **twice** in one literal — first to `IndentIntent`, later to `TabKeyIntent`. `LogicalKeySet` has value equality, so in a Dart map literal the later entry silently overwrites the earlier: `IndentIntent` is unreachable. `TabKeyIntent` reaches `onTabKeyAction()`, which calls `insertStr(' ' * params.tabSpaces)`, which is `text.replaceRange(selection.start, selection.end, str)`. **Pressing Tab with a multi-line selection replaces that selection with two spaces.** Block-indent — the behaviour a code editor is expected to have, and the one the package intended — cannot be reached. For a tablet-first IDE whose users attach external keyboards, this is a work-destroying defect, not a cosmetic one.
- **A dormant network capability.** `DartPadAnalyzer` POSTs the user's source to `https://stable.api.dartpad.dev/api/dartservices/v2/analyze`. It is an *example* implementation: the default is `DefaultLocalAnalyzer` (purely local), and `DartPadAnalyzer` is referenced nowhere else in the package. So no request is made unless we wire it — but the capability and its `http` dependency ship in the binary, which is exactly the class of thing NFR-OFF and SEC-5 exist to keep out.
- **A 24-package dependency closure**, resolved on the pinned toolchain via `flutter pub add --dry-run`: `autotrie`, `hive`, `http`, `http_parser`, `crypto`, `url_launcher` **plus seven platform packages**, `scrollable_positioned_list`, `linked_scroll_controller`, `tuple`, `equatable`, `charcode`, `typed_data`, `flutter_highlight`, `highlight`, `mocktail`. Notable individually: `url_launcher` is a native plugin on every platform, pulled in only so an error gutter can open links; `hive` is an embedded NoSQL database reached transitively through `autotrie`; and **`mocktail`, a test library, sits in the package's runtime `dependencies:`** — an upstream packaging defect that ships test code into the app.
- **A weak-copyleft dependency.** `flutter_code_editor` itself is Apache-2.0 (with a retained MIT grant covering the original `code_field` code it forked), which is straightforwardly compatible with shipping MIT-licensed software. But **`autotrie` is MPL-2.0** — file-level copyleft — and it is unavoidable: `CodeController` field-initialises an `Autocompleter`, which constructs autotrie tries, which `import 'package:hive/hive.dart'`. It cannot be avoided by turning autocomplete off. MPL-2.0 does not reach PyBLE's own files (it is per-file, and we modify none of it), but it is a real obligation and it sits against CLAUDE.md's blunt statement that every file in this repo is MIT.
- **Superlinear per-keystroke cost, structurally.** The whole buffer is one `TextField` with no viewport virtualization; each edit re-parses the document, splits the text on newlines twice, and the autocompleter **rebuilds its trie from scratch** (`_updateText` clears all entries and re-enters every word in the buffer). Evaluation benchmarking on a debug host put the per-keystroke cost at roughly 10×/20×/50× a plain `TextField` at 200/1000/3000 lines; treat the ratios and the *growth shape* as the finding, not the absolute milliseconds. There is also no soft wrap: the field lives inside an `IntrinsicWidth` in a horizontal scroll view.
- **A dormant upstream.** The last release is 0.3.5 with no newer publish; the tracker carries dozens of open issues including unanswered ones asking whether the project is maintained, and community PRs (IME, gutter alignment, RTL) have sat unmerged. Fixes will not arrive on our schedule.
- **R1's real shape is different from what the TDD assumed.** The tracker contains essentially nothing about iPads, tablets, or external keyboards — not because the package handles them well, but because **it appears to have no tablet-first consumer.** R1 is therefore not "known broken upstream"; it is *unexercised*, and PyBLE would be the one exercising it. The Tab defect above is precisely the kind of bug that survives in an unexercised area, and it survives in the package's own test suite because its Tab tests call `indentSelection()` directly instead of pressing Tab.

The question OI-1 actually poses, then, is not "is this package good?" but **"what does PyBLE own, and what does it rent?"** Renting a hand-written Python highlighter, a folding implementation and a shortcut scaffold is a large saving. Renting the correctness of our editing invariants is not acceptable.

## Decision

**Adopt `flutter_code_editor`, pinned exactly at `0.3.5`, behind an `EditorSurface` interface — with the package's optional surfaces switched off, its Tab binding neutralised at the adapter layer, and the existing plain `TextField` retained as a second live `EditorSurface` implementation.** Concretely:

1. **`EditorSurface` is the seam, and it is the only thing feature code binds to.** `lib/editor` exposes an `EditorSurface` abstraction; `editorDocumentProvider` remains the single source of truth for buffer content (ADR-0010 unchanged). The package is an *implementation detail behind that interface*, never imported by the shell, files, console, or any widget outside `lib/editor`. The TDD §4.3 sketch is corrected in the same `[docs]` commit: a synchronous `set text` is wrong for a controller-backed surface, so the contract is push-in / stream-out.

2. **The smart-punctuation invariant is preserved and re-pinned by test.** Because `CodeField` has no `inputFormatters`, the guard moves to a `CodeController` subclass overriding its `value` setter — the same interception point, one layer lower. The `save()`/`run()` normalizers stay exactly as they are and remain the unconditional guarantee: whatever any widget does, the bytes that reach the board tokenize. A test asserts the invariant **through whichever `EditorSurface` is active**, so it cannot regress silently during or after the swap.

3. **Every optional editor-package surface is off by default.** No `DartPadAnalyzer` (local analyzer only), no error gutter, no package find UI (its strings are unlocalizable English, which would breach FR-I18N), and the `wip/`-quality autocomplete popup is enabled only behind an explicit, tested opt-in. The network boundary forbids `DartPadAnalyzer` throughout `app/lib/` and forbids `package:http` outside the exact `lib/github_import/` production composition/client boundary authorized later by [ADR-0040](0040-sha-pinned-connected-github-import.md). In particular, `lib/editor/`, the editor adapter, analyzers, and every code path that can observe editor/user source remain unable to import or call the HTTP client. The GitHub exception sends no editor/user source and is consumed elsewhere through the neutral `GithubApi` seam, so the dormant editor-package network capability stays dormant by construction rather than intention.

4. **The Tab defect is fixed at the adapter, not worked around in docs.** PyBLE installs its own Tab handling above the package's `Shortcuts` so Tab with a multi-line selection indents and never replaces. This is a `[red]`-first item: the failing test comes before the fix, and it pins the exact reproduction (`a = 1\nb = 2\nc = 3\n`, lines 1–2 selected, Tab).

5. **The plain `TextField` surface is kept, not deleted.** It stays as a working second implementation of `EditorSurface`. This is what makes the documented WebView fallback credible: we retain a shipping-quality escape hatch rather than a paragraph promising one.

6. **R1 stays open with concrete fallback triggers.** We switch implementations if any of these is observed: (a) a correctness or data-loss defect on iPad that cannot be fixed at the adapter layer; (b) unusable typing latency on a realistic beginner file on target hardware; (c) a Flutter SDK bump the dormant upstream does not follow. R1 is re-scoped in the TDD accordingly rather than being declared solved.

7. **The licence and dependency facts are recorded, not glossed.** The MPL-2.0 `autotrie` link, the Apache-2.0 + retained-MIT chain, the 24-package closure, `mocktail`-in-runtime-deps and the `url_launcher`/`hive` transitives all go into the pubspec dependency ledger and a generated `THIRD_PARTY_LICENSES` (BLD-6), with the in-app open-source notices screen surfacing them. The MPL-2.0 carve-out against CLAUDE.md's "every file is MIT" is an **owner ratification**, called out explicitly because it is a policy change, not an implementation detail.

Unchanged: the `Connection` seam (D1), neutral types (D2), `UI → lib/pble → lib/ble` layering, the offline-first mandate, the clean-room rule, and every §1A.3 rejection. Nothing in this ADR is derived from any closed-source sibling product: the package is public, and its evaluation was performed against its own source.

## Alternatives considered

- **Keep the hand-rolled `TextField` and add highlighting/completion ourselves.** Rejected, but it is the closest call. It keeps the dependency set pristine and the invariants fully owned — and it is exactly what we would fall back to. Rejected because a correct Python highlighter, folding, and a completion index are a large, low-novelty build that would consume the budget that should go to the BLE working loop.
- **WebView-hosted Monaco or CodeMirror** (the TDD's documented fallback). Rejected for now on the strength of the structural argument above: moving text editing behind a platform boundary breaks `tester.enterText`, the widget/golden ladder, and — decisively — puts the smart-punctuation invariant on the far side of a bridge, right after we proved on hardware how expensive getting that wrong is. It also needs assets bundled offline and adds a heavyweight platform view. Retained as the escape hatch, now backed by a real second implementation.
- **`re_editor` / `code_text_field` / other pub.dev editors.** Rejected: `code_text_field` is the abandoned ancestor of this package; the alternatives trade one dormant upstream for another without the "it is just a `TextField`" property that makes this choice testable and recoverable.
- **Adopt the package as-is, wiring its autocomplete popup, find UI and error gutter.** Rejected: the find UI ships unlocalizable English (FR-I18N), the popup is `wip/` quality, and the error gutter is what drags in `url_launcher`. Renting the text surface is worthwhile; renting half-finished UI is not.
- **Vendor/fork the package into the repo under MIT.** Rejected: it would make PyBLE the maintainer of a 60-file editor, and the retained-MIT grant covers only part of the tree with no per-file headers to delimit it — relabelling would be a licence overreach.

## Consequences

**Positive**
- Closes OI-1 with evidence rather than assumption, and re-freezes FR-EDIT-1/2/3/4 with a shipping path.
- Syntax highlighting, line numbers, auto-indent and folding arrive without PyBLE writing or maintaining a Python grammar.
- Because the surface is a `TextField`, the entire existing test ladder — widget, golden, and the A-25 invariant tests — keeps applying.
- `EditorSurface` plus a retained plain-field implementation converts the WebView fallback from a documented intention into an executable one.
- Two upstream defects (Tab data loss, dormant network path) are now *known and gated* instead of latent.

**Costs / mitigations**
- **+24 packages**, including a native plugin family and an embedded database we will never use. *Mitigation:* recorded in the ledger; footprint measured before/after and reported, not estimated; optional surfaces off.
- **MPL-2.0 in the closure via `autotrie`, unavoidable.** *Mitigation:* we modify none of it, so no source-disclosure duty attaches to PyBLE's own files; it is disclosed in `THIRD_PARTY_LICENSES` and the notices screen — but it requires the owner ratification named above.
- **Dormant `DartPadAnalyzer` network path.** *Mitigation:* default local analyzer, plus a boundary that forbids `DartPadAnalyzer` everywhere and permits `package:http` only inside ADR-0040's exact bounded `lib/github_import/` production adapter. No editor or analyzer receives that exception.
- **Superlinear typing cost with no soft wrap.** *Mitigation:* fallback trigger (b) makes this a measured, actionable condition on real hardware rather than a vague worry.
- **Dormant upstream.** *Mitigation:* exact version pin, adapter-level fixes, retained second implementation, fallback trigger (c).
- **Golden churn.** The editor surface changes appearance, so the shell goldens must be regenerated deliberately and reviewed as an intended visual change.

**Process**
- Spec-first: this ADR, the OI-1/R1 re-scoping in [specs.md](../specifications/App/specs.md) and [TDD.md](../specifications/App/TDD.md), and the corrected `EditorSurface` contract land together in a `[docs]` commit **before** any `[red]`.
- Test-first: `[red]` tests are authored against the frozen contract — the Tab reproduction, the smart-punctuation invariant through `EditorSurface`, and the CI gate — then `[green]`, then the gates (no-leak, import-boundary, locale parity, iPadOS + Android golden parity).
- Dependency governance (`pubspec.yaml` ledger entry, `THIRD_PARTY_LICENSES`, notices screen) is a build-plane change and lands with the implementation, not before the ADR is accepted.

## Related

- Closes App **OI-1**; re-scopes **R1** ([TDD.md §17](../specifications/App/TDD.md#17-risks--open-questions)).
- Supersedes the rich-editor deferral in [ADR-0010](0010-working-loop-in-memory-document.md); leaves ADR-0010's volatile-document decision and its FR-EDIT-7 deviation untouched.
- Honors [ADR-0003](0003-license-mit.md) (MIT — see the MPL-2.0 carve-out), [ADR-0007](0007-riverpod-state-management.md), [ADR-0008](0008-signal-design-system.md).
- Narrowly superseded for one network boundary by [ADR-0040](0040-sha-pinned-connected-github-import.md); its public GitHub client does not weaken this ADR's editor isolation or source-exfiltration prohibition.
- Preserves the A-25 typographic-substitution guarantee (`app/lib/editor/smart_punctuation.dart`), which was established from a hardware-verified failure and is re-pinned by test as part of this work.
