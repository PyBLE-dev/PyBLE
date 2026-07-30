// SPDX-License-Identifier: MIT
// Part of PyBLE (https://pyble.dev) — see /LICENSE.

/// The observable link/run state a widget can bind to through [Connection].
///
/// Frozen four-value enum (docs/specifications/app.md §3, TDD §5.2). Neutral by
/// design: no transport detail leaks (D2) — `scanning` is a `lib/connect`
/// scan-facade concern and is deliberately NOT a member here.
///
///   * [disconnected] — no active link to a board.
///   * [connecting]   — link + PBLE/1 session being established.
///   * [ready]        — connected and idle; ready to run.
///   * [running]      — user code is executing on the board.
enum ConnState { disconnected, connecting, ready, running }
