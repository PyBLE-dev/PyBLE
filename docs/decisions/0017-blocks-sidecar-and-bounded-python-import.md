# ADR 0017 — Blocks uses a verified sidecar for exact reopen and an all-or-nothing bounded Python importer

**Status:** Accepted (2026-07-28). Extends
[ADR-0013](0013-clean-room-blockly-one-way-file-backed.md) (the acknowledged
Blocks snapshot and file-backed action boundary),
[ADR-0015](0015-generic-micropython-gpio-blocks.md) (generic digital GPIO), and
[ADR-0016](0016-offline-beginner-blockly-examples.md) (atomic candidate
preview/copy/replace). It supersedes only ADR-0013's blanket statement that
PyBLE never reconstructs Blocks from Python and its corresponding rejected
alternative. Arbitrary or live bidirectional Python ↔ Blocks synchronization
remains rejected. This decision changes no PBLE/1, firmware, BLE, or
generic-board contract.

## Context

Generated Python is intentionally inspectable and editable. A Python file alone,
however, cannot preserve visual information such as block IDs and coordinates,
comments, collapsed/disabled state, mutation data, variable/procedure identity,
or the particular block graph chosen for an equivalent expression. Re-parsing
that file therefore cannot provide an exact Blocks round trip.

There are two different user needs:

1. A program that originated in Blocks should reopen as the **same visual
   workspace**. This needs the original Blockly serialization, bound to the
   exact generated Python that the user sees and uploads.
2. A beginner with a small handwritten MicroPython program should be able to
   make a **new editable Blocks workspace** when every construct is inside an
   explicitly published subset. This conversion may normalize formatting and
   layout, but it must never omit an unsupported statement, hide it in a raw-code
   escape block, or imply that arbitrary Python is convertible.

Both flows operate on untrusted user files. They must be offline, bounded,
diagnostic, non-executing, and atomic with respect to the active workspace. A
damaged or stale companion file must never replace a valid Python document or a
live Blocks workspace.

## Decision

**A Blocks-origin program is an integrity-checked Python/sidecar pair. A
Python-origin conversion is a separate, strict, all-or-nothing import that
creates an ordinary workspace only after preview and explicit confirmation.**

### 1. Representation authority is explicit

- During normal visual editing, the active Blockly workspace remains
  authoritative and publishes ADR-0013's immutable
  `{source, workspaceJson, revision}` snapshots.
- A valid sidecar is an exact **reopen record**, not a second editable source.
  It is trusted only while it proves that its workspace and embedded generated
  source still describe the adjacent Python file exactly.
- During Python import, the captured immutable editor document is authoritative
  input. Its content is converted and `boardPathForDocument(capturedDocument)`
  becomes the candidate Blocks source target. The candidate workspace is a new
  copy. After an acknowledged Create/Replace, that workspace and target become
  authoritative for subsequent Blocks edits and generation; later Python edits
  do not live-sync back into it.
- PyBLE never attempts merge, live two-way synchronization, or source-to-source
  patching between a Python buffer and a Blocks workspace.

### 2. Sidecar path and version-1 envelope

For the active normalized absolute user-workspace Python target `P` ending in
`.py`, its companion path is exactly:

```text
S = P + ".pyble-blocks.json"
```

The default target for a hand-built or example-created Blocks workspace remains
`/blocks.py`, so its pair is:

```text
/blocks.py
/blocks.py.pyble-blocks.json
```

Both paths remain inside the board's advertised user `fs_root`, and each full
UTF-8 path is at most PBLE/1's 128-byte path ceiling. The app derives and
preflights **both** paths before any `putFile`; if appending the suffix makes `S`
too long, neither file is written. Traversal, control-plane paths, non-`.py`
source paths, and a sidecar opened without its adjacent source are rejected. A
future project-backed implementation mirrors the same POSIX project paths in
`project_files`; it does not invent a different local naming rule.

The UTF-8 sidecar is at most 1 MiB and has this version-1 shape:

```json
{
  "format": "pyble-blocks",
  "version": 1,
  "source": {
    "path": "/blocks.py",
    "encoding": "utf-8",
    "byteLength": 0,
    "crc32": "00000000",
    "text": ""
  },
  "generator": {
    "id": "pyble-blockly-python",
    "version": 1,
    "blockly": "13.1.0"
  },
  "workspace": {
    "blocks": {
      "languageVersion": 0,
      "blocks": []
    }
  }
}
```

`source.text` is the exact generated text whose UTF-8 bytes are uploaded.
`byteLength` is the exact byte count. `crc32` is eight lowercase hexadecimal
digits containing IEEE/zlib CRC-32 over those bytes (reflected polynomial
`0xEDB88320`, initial/final XOR `0xFFFFFFFF`). It is a deterministic
accidental-corruption and torn-pair fingerprint, **not** authentication,
authorization, or a cryptographic security claim. Exact byte/text comparison,
not CRC alone, is required.

`workspace` is the ordinary Blockly JSON object from the same acknowledged
snapshot. The envelope contains no timestamp, board/chip identity, connection
data, selected-device pin profile, PBLE/1 value, or executable callback.
`generator.version` advances whenever PyBLE changes a mapping in a way that can
change generated source or import semantics. `blockly` records the pinned
upstream serialization/generator compatibility point. An unknown
format/envelope/generator/Blockly version is a localized incompatibility
diagnostic; v1 never guesses or silently migrates it. The adjacent `.py` remains
openable as ordinary text.

### 3. Sidecar-last is the pair commit record

Blocks Save and Run each request and freeze one fresh active-host snapshot under
ADR-0013's existing action lock. The native layer builds both files from that
one snapshot and its active target `P`, preflights both full UTF-8 paths against
the 128-byte PBLE/1 ceiling, and captures the connection facade's current local
session stamp before that preflight and the first upload. It then performs:

```text
putFile(P, exact source bytes)          # CRC-verified by the existing transfer
putFile(S, matching sidecar bytes)      # written last: commits the pair
[Run only] runFile(P)
```

The sidecar is never written before the Python upload succeeds. Save reports
success only after both verified uploads. Run never calls `runFile(P)` unless
both uploads succeed. Immediately before the sidecar upload and again before
Run, the coordinator requires the captured session stamp to remain current.
Every facade attach or detach advances that opaque stamp, including a rapid
disconnect/reconnect to the same board. A change produces a typed refusal and
the next write or Run is never dispatched through the facade, preventing one
bundle action from crossing boards. This is only an in-memory action-consistency
stamp: it is not a board identifier, PBLE/1 field, pairing/authentication token,
or value persisted in the sidecar.

If the source succeeds but the sidecar fails, the action reports an
incomplete-pair error that honestly says the Python may have changed; an older
sidecar is now stale and will fail the exact checks below. PBLE/1 has no
multi-file atomic rename, so the sidecar-last record plus exact validation is
the defined recovery mechanism rather than a false atomicity claim.

The text editor does not silently rewrite or delete a Blocks sidecar when the
user edits/saves Python. Such an edit simply invalidates the pair by exact source
mismatch. A later explicit Blocks Save may publish a new valid pair. The sidecar
is plain data, is never passed to `runFile`, and does not create another run
path.

A workspace created from **Convert Python to Blocks** adopts
`boardPathForDocument(capturedDocument)` as `P`; it does not unexpectedly fall
back to `/blocks.py`. A workspace opened from a valid sidecar adopts the
sidecar-bound source path. The default `/blocks.py` applies only when no
explicit Python origin has supplied a target. Target adoption is part of the
same candidate commit/rollback and is shown in Preview.

### 4. Exact reopen validation is fail-closed

An explicit **Open as Blocks** operation for `P` may read `P` and `S` through the
existing file-open path. Before offering a restorable candidate, it must:

1. validate UTF-8, total size, required fields/types, exact format/version,
   canonical source/sidecar paths, both 128-byte path bounds, encoding,
   byte-length bounds, lowercase CRC shape, and supported generator/Blockly
   versions;
2. require the adjacent Python bytes to equal `source.text` encoded as UTF-8,
   with the recorded length and CRC-32 all matching;
3. load `workspace` into a disposable scratch Blockly workspace, serialize it
   again, and require deep JSON equality with the stored object (object key order
   and insignificant JSON whitespace are not workspace state); and
4. run the pinned production generator in that scratch workspace and require
   its complete generated source to equal `source.text` byte-for-byte.

Only all four checks establish an exact candidate. This preserves block IDs,
top-level order, coordinates, fields, comments, `extraState`/mutation data,
variables/procedures, disabled/collapsed state, and every other field retained
by the supported Blockly serializer. A missing, malformed, oversized,
unknown-version, path-mismatched, source-mismatched, lossy-reserialization, or
generation-mismatched sidecar produces localized diagnostics and does not
mutate the editor or active workspace. The safe choices remain **Open Python**
and, when applicable, the bounded **Convert Python to Blocks** flow below.

An exact candidate uses the same structural-empty **Create workspace** versus
confirmed non-empty **Replace workspace** decision and rollback/active-host
acknowledgement boundary as ADR-0016. A restore/generation/host failure restores
the prior JSON/program/revision/source target and never announces success first.
Only the acknowledged commit adopts `P` as the active Blocks target.

### 5. Python subset version 1

The importer accepts UTF-8 Python text only, fully offline. Input is bounded to
256 KiB, 4,096 physical lines, 20,000 syntax nodes, and 32 indentation levels.
Indentation is spaces-only; semicolon-separated statements are not admitted.
Identifiers are ASCII Python identifiers, may not be keywords or generator
reserved names, and integers used as Blockly numeric literals must be within
JavaScript's exact safe-integer range `[-9007199254740991, 9007199254740991]`.
Decimal float syntax whose finite value is integral (for example `1.0` or
`1e3`) is rejected because Blockly's ordinary number field would regenerate it
as integer syntax and change observable Python type/printing. Raw U+0000 is not
admitted in a string because the pinned generator cannot emit it as valid
Python source.

Leading imports, when required by a used construct, are accepted only in these
exact unaliased forms and at most once:

```python
from machine import Pin
from time import sleep_ms
```

An unused, missing, duplicate, aliased, reordered-among-executable-code, or
different import is an error because the produced workspace could not preserve
it exactly.

The admitted statement grammar is:

- assignment `name = expression`;
- numeric change `name += expression`;
- `print(expression)` with exactly one positional argument;
- `sleep_ms(N)` where `N` is a non-negative decimal integer literal;
- `pin.value(0)` / `pin.value(1)` where `pin` is a simple identifier bound to a
  supported `Pin` constructor;
- `if` with zero or more `elif` branches and an optional `else`;
- `while condition`;
- `for name in range(...)` under the literal bounds below;
- a call to a supported user function as a statement;
- top-level `def name(parameters): ...` under the function bounds below; and
- `pass` only as the sole statement of a suite that Blockly can represent as an
  empty statement input.

Expressions are bounded to:

- finite decimal integer literals and finite non-integral decimal float
  literals, ordinary single- or double-quoted strings without raw U+0000 and
  with supported escapes, `True`, `False`, `None`, and simple names;
- parentheses; unary `not`, unary `+`, and unary `-`;
- arithmetic `+`, `-`, `*`, `/`, `%`, and `**`;
- Boolean `and` / `or`;
- one comparison `==`, `!=`, `<`, `<=`, `>`, or `>=` (chained comparisons are
  not admitted);
- a supported user-function call with positional arguments only;
- `Pin(GPIO, Pin.IN|Pin.OUT[, None|Pin.PULL_UP|Pin.PULL_DOWN])`, where `GPIO` is
  an explicit non-negative decimal integer literal and no board/chip default or
  validity lookup is performed; and
- `pin.value()` as a value expression.

`range` accepts one, two, or three decimal integer literals. Its step is
non-zero; the range must be non-empty; a positive step requires `start < stop`
and a negative step requires `start > stop`; all values and the adjusted
inclusive Blockly endpoint remain in the exact safe-integer range. This permits
an exact standard `controls_for` mapping (`stop - 1` for a positive step,
`stop + 1` for a negative step) without changing Python's exclusive-stop
semantics. Dynamic, empty, or direction-inconsistent ranges are diagnosed
rather than approximated.

At most 16 top-level functions with at most eight unique positional parameters
each are admitted. Definitions precede executable module statements. There are
no decorators, annotations, defaults, keyword/variadic parameters, nested
functions, closures, global/nonlocal access, or recursive call cycles. A
function body may use its parameters and literals, but may not assign/read
free or local variables; this avoids Blockly procedure generation introducing
different `global` semantics. A function has either no return or exactly one
final `return expression`; calls to returning functions are used as expressions
and calls to non-returning functions as statements, with exact arity.

Everything not listed is unsupported, including comments/docstrings, multiline
or prefixed strings, collection literals, subscripts/slices, comprehensions,
attribute access other than the admitted `Pin` constants/`.value`, multiple
assignment, `del`, `break`, `continue`, `for` over collections, `match`, classes,
lambda, `yield`, `async`/`await`, exceptions, context managers, dynamic imports,
I/O other than the admitted `print`, metaprogramming, and arbitrary calls.

### 6. Conversion is all-or-nothing and self-checking

The importer is a fresh MIT tokenizer/parser and typed subset model; it does not
execute Python, use `eval`, start a Python interpreter, fetch a parser or grammar
from the network, or introduce a raw-Python Blockly escape block. Its pipeline
is:

```text
captured editor document content
  → bounded tokenize/parse + name/import/control-flow validation
  → complete typed subset tree or diagnostics (never a partial tree)
  → ordinary Blockly JSON with fresh IDs and deterministic top-level layout
  → disposable scratch-workspace restore
  → pinned production Python generation
  → reparse generated Python to the same normalized subset model
  → semantic-model equality
  → immutable {input fingerprint, workspaceJson, generatedSource, warnings}
```

Any syntax, unsupported construct, semantic, resource-limit, scratch restore,
generator, or semantic-model comparison error yields **no candidate**.
Recognized statements are never kept while unrecognized statements are dropped,
commented out, converted to disabled blocks, or hidden in opaque metadata.
Formatting, quotes, redundant parentheses, blank lines, and deterministic block
layout may normalize; those non-semantic changes are disclosed and the complete
generated Python is selectable in Preview before commit.
The normalized model treats numeric `name += value` as
`name = name + value` and an omitted third `Pin` argument as explicit `None`,
because those are the ordinary workspace forms emitted by the production
generator. Floor division is not in v1 because the current toolbox has no block
that reproduces it without an opaque helper.

The captured input is bound by the complete immutable editor document, including
name/content/`boardPath`, its resolved target path, exact text, UTF-8 byte
length, and CRC-32. Before commit the controller compares the current editor
document exactly. If its content, identity, name, or bound path changed while
Preview was open, the candidate is stale and Create/Replace stays disabled until
the user explicitly refreshes conversion.

### 7. Diagnostics and explicit UI

Every diagnostic has stable, unlocalized technical data:

```text
{code, severity, startLine, startColumn, endLine, endColumn, messageKey, args}
```

Positions are one-based Unicode-scalar columns with an end-exclusive range.
`code` and source excerpts remain technical text; the visible message is
ARB-sourced from `messageKey` and typed arguments. Errors block a candidate.
Warnings may describe formatting/layout normalization but never conceal lost
behavior. Raw parser exceptions, JavaScript stacks, and English-only fallback
messages are not shown to users.

The editor exposes an explicit **Convert Python to Blocks** action. A valid
paired file also exposes **Open as Blocks**. Both open one shared adaptive
preview surface showing the captured source identity, a navigable diagnostic
list with line/column context, the exact source/companion target paths, and—only
for a valid candidate—the complete selectable generated Python. At widths below
600 dp it is a scroll-controlled
modal bottom sheet; at 600 dp and wider it is a dialog. It scrolls under large
text and keyboard insets.

If the active workspace is structurally empty, the valid candidate offers
**Create workspace**. Otherwise it offers **Replace workspace**, with the same
localized confirmation, exact rollback, and active-host acknowledgement used by
example replacement. Cancel and every failure are non-mutating. Successful
commit may navigate to Blocks and announces completion once, only after the
active host accepts the candidate snapshot.

Rows, source, diagnostics, and actions are keyboard/switch accessible, expose
name/role/enabled/error state, meet the 48 dp target rule, preserve focus, and
move focus to the first error on a failed conversion. Screen readers receive
the error count and one completion announcement, not repeated announcements
while diagnostics rebuild.

### 8. No implicit file, board, or execution action

Parsing, sidecar validation after bytes are supplied, Preview, Create, Replace,
and cancellation call no `Connection`, `ProgramActions`, Save, Run,
`runFile`, editor replacement, console, or network API. An explicit File
Explorer open may perform only the existing reads of the selected `.py` and its
adjacent sidecar; it authorizes no write. Only the pre-existing explicit Blocks
Save/Run actions write the pair, and only explicit Run executes `P`.

No conversion chooses a GPIO, reads `DeviceInfo`, validates a physical pin
against a board profile, or performs hidden board probing. Standard
MicroPython remains the runtime authority for actual GPIO support.

### 9. Clean-room and licensing boundary

The envelope, parser, subset model, mappings, UI, diagnostics, and tests are
fresh MIT PyBLE work. They may use public Python/MicroPython language behavior
and the pristine pinned Apache-2.0 Blockly API, but copy no source, parser,
identifiers, block catalog, curriculum, conversion rules, UI implementation, or
pedagogy from a closed or unknown-license product. Any future third-party parser
requires a separate dependency/license review and pin before adoption. The
no-leak, SPDX, dependency, offline-asset, and locale-parity gates cover the new
shipping source and assets.

## Verification contract

Red tests precede implementation and cover at least:

- exact target adoption/path derivation and rejection of traversal,
  control-plane/non-`.py`, or source/companion paths above PBLE/1's 128-byte
  limit before any PUT;
- golden encode/decode of the v1 envelope; UTF-8 byte length and the
  `123456789 → cbf43926` CRC anchor; malformed/oversized input, unknown versions,
  wrong path, stale/torn source, and unsupported generator;
- sidecar-last failure injection: source failure prevents sidecar, sidecar
  failure prevents success/Run and leaves a detectably stale pair, and Run
  occurs only after both verified writes;
- exact reopen of IDs, order, coordinates, comments, `extraState`, variables,
  procedures, and disabled/collapsed state; scratch reserialization or generated
  source mismatch is fail-closed and preserves the active workspace;
- tokenizer/parser/precedence fixtures for every admitted form and a diagnostic
  fixture for every rejected family, including all resource, numeric, range,
  function, import, and GPIO bounds;
- parse → workspace → production generate → reparse normalized-model equality
  for each supported construct and composed beginner programs;
- all-or-nothing behavior: one unsupported statement among supported statements
  yields no workspace/candidate/raw-code placeholder;
- immutable non-mutating Preview, captured document/target display,
  stale-editor identity/content/path invalidation, empty Create,
  confirmed/cancelled/failed Replace rollback of workspace and target, and
  host-acknowledged success;
- zero Connection/Save/Run/editor/console/network calls from validation,
  conversion, Preview, Create, Replace, and cancel;
- localized diagnostic-key coverage and parity; keyboard, focus, semantics,
  one-shot announcements, 48 dp targets, keyboard inset, 1×–3× text, compact
  bottom sheet, wide dialog, and no overflow;
- actual pinned WebView restoration/generation on iPadOS and Android, including
  a valid sidecar reopen and one composed Python-subset import; and
- no-leak, SPDX, import-boundary, dependency/license, local-assets/CSP, analyze,
  unit/widget/golden/integration, and packaged-asset gates.

## Alternatives considered

- **Infer all Blocks from every Python file.** Rejected: Python is more
  expressive than the toolbox, equivalent source has many possible graphs, and
  layout/IDs cannot be recovered.
- **Store only workspace JSON.** Rejected: it would not prove which adjacent
  Python revision the workspace generated.
- **Store only a source fingerprint.** Rejected: CRC is not collision-resistant
  and does not substitute for exact source comparison; the complete committed
  generated source is intentionally present.
- **Treat CRC-32 as a signature.** Rejected: the sidecar is user data, not a
  trust boundary. CRC detects ordinary corruption/torn pairs only.
- **Write the sidecar first.** Rejected: a new commit record could point at an
  old Python file. Sidecar-last makes successful companion upload the commit
  point and every torn ordering detectable.
- **Partially convert supported lines.** Rejected: omission is code loss even
  when accompanied by a toast. Unsupported input yields diagnostics and no
  candidate.
- **Use a raw-Python/custom escape block.** Rejected: it is opaque, bypasses the
  visual-language contract, and turns unsupported code into a false success.
- **Continuously synchronize editor and Blocks.** Rejected: authority,
  conflict, formatting, and semantics become ambiguous. Both hand-offs are
  explicit snapshots.

## Consequences

Blocks-origin work can reopen exactly while its Python/sidecar pair remains
consistent, and ordinary beginner Python can enter Blocks through a small,
testable language rather than a misleading universal converter. Python always
remains readable when companion validation fails, and no conversion can
silently lose executable behavior.

The costs are a visible companion data file, duplicated generated source in that
record, two verified uploads for Blocks Save/Run, strict rejection of many valid
Python programs, and a versioned parser/mapping surface that must grow only
spec-first. Because PBLE/1 provides no multi-file transaction, a failed
sidecar-last upload can leave updated Python beside an old sidecar; exact reopen
detects that state and never restores it as valid.

## Related

- [App specs §4.10](../specifications/App/specs.md)
- [App TDD §4.6, §11.2, and §15](../specifications/App/TDD.md)
- [Public roadmap](../ROADMAP.md)
- [ADR-0013](0013-clean-room-blockly-one-way-file-backed.md)
- [ADR-0015](0015-generic-micropython-gpio-blocks.md)
- [ADR-0016](0016-offline-beginner-blockly-examples.md)
