# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# pyble_agent — the rpi-pico2-w portable agent wiring + supervisor (plan C11;
# port spec ports/rpi-pico2-w.md P1/P2/P3/P4; the init_agent() twin of the
# native ESP32 agent).
#
# Two altitudes, split for host-testability:
#   * Agent — the host-testable wiring core. The constructor builds the
#     Dispatcher, registers a handler for EVERY protocol.md §4 CMD opcode
#     (IDENTIFY included: its REGISTERED handler answers EUNSUPPORTED while
#     has_identify=0, P1), wires link.on_message -> dispatch ->
#     link.send_message, link.on_disconnect -> in-RAM transfer reset (the
#     jailed <dest>.pbltmp persists — F-10 resume), and publishes the §7 caps
#     via link.set_info_payload. It NEVER calls link.start() and NEVER touches
#     os.dupterm — BLE bring-up and the dupterm tee are main()'s (device-only).
#     poll() is ONE supervisor iteration: run-mailbox pickup (RUN_STATE(running)
#     emit -> exec -> terminal emit), the GET transfer pump, and the deferred
#     SOFT_REBOOT reset after a bounded TX-flush delay (P4).
#   * main() — the device entry frozen into the image (_boot.py calls it):
#     builds the BleLink, pins micropython.kbd_intr(3) (P3), installs the
#     console tee via os.dupterm (guarded so a CPython import never breaks),
#     and defers os.dupterm_notify through micropython.schedule so the pending
#     KeyboardInterrupt is created only after the synchronous BTstack IRQ and
#     its RSP have returned. It starts the link, runs maybe_autorun() LAST, then
#     loops poll() forever.
#     An outer fault restart rebuilds the BleLink and re-advertises (H9): the
#     board never needs BOOTSEL to recover from a supervisor fault.
#
# Execution model (P2): fast opcodes answer inline in BLE scheduled context
# via the Dispatcher; RUN execution and GET streaming are mailboxed to the
# supervisor, which structurally guarantees RSP-before-RUN_STATE and
# RSP-before-DATA ordering. Transfers during an active RUN answer EBUSY
# inline (legal §8; concurrency returns with OI-P5).
#
# Runs on MicroPython v1.28 and imports under CPython 3.9+ (host suite).

import pyble_boot
import pyble_console
import pyble_device_config
import pyble_fs
import pyble_info
import pyble_proto
import pyble_runner

try:
    from time import ticks_ms as _ticks_ms, ticks_diff as _ticks_diff
except ImportError:                            # CPython host suite
    from time import monotonic as _monotonic

    def _ticks_ms():
        return int(_monotonic() * 1000)

    def _ticks_diff(a, b):
        return a - b

_OP = pyble_proto.OPCODES
_ST = pyble_proto.STATUS
OK = _ST["OK"]
EBADREQ = _ST["EBADREQ"]
EBUSY = _ST["EBUSY"]
ERANGE = _ST["ERANGE"]
EUNSUPPORTED = _ST["EUNSUPPORTED"]

# P4: bounded TX-flush delay between the SOFT_REBOOT RSP{OK} handoff and the
# injected machine.reset — long enough for the notify queue to drain, short
# enough that the observable behavior matches the ESP32 port (link drops,
# board returns advertising with a fresh VM).
REBOOT_FLUSH_MS = 250

# §4 SET_IDENTIFY_LED validation bound (P1: payloads are validated per the
# frozen §4 — ERANGE if gpio out of range — but nothing persists while
# has_identify=0). The Pico 2 W's RP2350A exposes user GPIO 0..29.
_IDENTIFY_GPIO_MAX = 29

_RUNNING = pyble_runner.RUNNING


def _noop():
    return None


def _make_scheduled_dupterm_notify(schedule, dupterm_notify):
    """Return the zero-arg console notify seam used on rp2 (P3/P4).

    BTstack delivers GATTS writes from a synchronous scheduler node. Calling
    os.dupterm_notify inline there creates a pending KeyboardInterrupt inside
    the protected BLE IRQ callback: that loses the command RSP and upstream
    disables the IRQ handler. Enqueue the native callable itself so the current
    BTstack node can finish; the pending interrupt is then raised back in the
    supervisor's user-code frame at its next VM back-edge.
    """
    def _notify():
        schedule(dupterm_notify, None)

    return _notify


class Agent:
    """The host-testable agent wiring (interface pinned by
    tests/firmware_tests/host/test_pyble_agent.py):
    Agent(link, fs_root, unique_id=bytes, reset=callable, clock=callable).
    `unique_id` is the machine.unique_id() bytes (device_id derivation, P1);
    `reset` the machine.reset seam (P4); `clock() -> int ms`; `notify` the
    os.dupterm_notify seam handed to the console STOP channel (P3)."""

    def __init__(self, link, fs_root, unique_id=b"\x00\x00", reset=None,
                 clock=None, notify=None):
        self._link = link
        self._root = fs_root or "/"
        self._reset = reset
        self._clock = clock if clock is not None else _ticks_ms
        self._reboot_at = None          # ms deadline for the deferred reset
        self._interrupt_after_rsp = False  # P3/P4: never inject inside handler
        self._device_id = pyble_info.device_id_from_unique_id(unique_id)

        # Persisted config (P5: /pyble_conf.json in the workspace jail).
        self._config = pyble_device_config.DeviceConfig(
            self._root, self._device_id, set_adv_name=link.set_adv_name)

        # Console: the one io.IOBase tee/stdin/STOP object (P8). main() hands
        # it to os.dupterm; the notify seam pokes os.dupterm_notify on device.
        self.console = pyble_console.Console(
            self._console_emit, notify if notify is not None else _noop,
            clock=self._clock)

        # Filesystem bridge (F-08/F-09/F-17): EVT emission via emit().
        self._fs = pyble_fs.FsService(
            self._root, self.emit,
            chunk_size=pyble_info.chunk_size(link.mtu()))

        # Runner (P2/P3): handler reserves inline; service() executes on the
        # supervisor with the console stderr path for tracebacks.
        self._runner = pyble_runner.Runner(
            self._emit_run_state,
            pyble_runner.make_exec_fn(write_stderr=self._stderr))

        # Dispatcher: EVERY §4 CMD opcode gets a registered handler — none may
        # fall through to the EUNSUPPORTED default (that default is only for
        # opcodes outside the frozen §4 set, FR-PROTO-9).
        d = pyble_proto.Dispatcher()
        d.register(_OP["HELLO"], self._h_info)
        d.register(_OP["DEVICE_INFO"], self._h_info)
        d.register(_OP["FILE_LIST"], self._h_list)
        d.register(_OP["FILE_STAT"], self._h_stat)
        d.register(_OP["FILE_GET_BEGIN"], self._h_get_begin)
        d.register(_OP["FILE_PUT_BEGIN"], self._h_put_begin)
        d.register(_OP["FILE_PUT_DATA"], self._h_put_data)
        d.register(_OP["FILE_PUT_END"], self._h_put_end)
        d.register(_OP["FILE_DELETE"], self._h_delete)
        d.register(_OP["MKDIR"], self._h_mkdir)
        d.register(_OP["FILE_RENAME"], self._h_rename)
        d.register(_OP["RUN"], self._h_run)
        d.register(_OP["STOP"], self._h_stop)
        d.register(_OP["SOFT_REBOOT"], self._h_soft_reboot)
        d.register(_OP["SET_AUTORUN"], self._config.handle_set_autorun)
        d.register(_OP["CONSOLE_INPUT"], self._h_console_input)
        d.register(_OP["SET_LABEL"], self._config.handle_set_label)
        d.register(_OP["SET_IDENTIFY_LED"], self._h_set_identify_led)
        d.register(_OP["IDENTIFY"], self._h_identify)
        self._dispatcher = d

        # Link wiring: on_message -> dispatch -> send_message; disconnect
        # resets the in-RAM transfer state (keeps .pbltmp — F-10). on_oversize
        # is a BleLink-only seam (P6) — absent on host fakes, hence guarded.
        link.on_message(self._on_message)
        link.on_disconnect(self._on_disconnect)
        link.on_connect(self._on_connect)
        oversize = getattr(link, "on_oversize", None)
        if oversize is not None:
            oversize(self._on_oversize)

        # §2/§7: an INFO characteristic read serves the caps text verbatim.
        link.set_info_payload(self.info_payload())

    # -- caps / identity -------------------------------------------------------
    def _caps_args(self):
        return (self._link.mtu(), pyble_info.free_mem_now(), self._device_id,
                self._config.label, self._config.auto_run)

    def info_payload(self):
        """The live §7 caps text (INFO characteristic value, no status)."""
        mtu, free_mem, device_id, label, auto_run = self._caps_args()
        return pyble_info.info_char_payload(
            mtu, free_mem, device_id, label, auto_run)

    def adv_name(self):
        """Label-else-`PyBLE-XXXX` (FR-BLE-5/12; XXXX from unique_id, P1)."""
        return pyble_device_config.adv_name(self._device_id, self._config.label)

    def autorun(self):
        """maybe_autorun (called LAST by main(), after the link is up)."""
        return pyble_boot.maybe_autorun(self._config, self._runner, self._root)

    # -- outbound paths --------------------------------------------------------
    def emit(self, opcode, payload):
        """The agent's EVT path: TYPE=EVT, ID=0, valid §3.1 CRC."""
        self._link.send_message(
            pyble_proto.encode(pyble_proto.EVT, opcode, 0, payload))

    def _console_emit(self, stream, data):
        self.emit(_OP["CONSOLE_DATA"], bytes((stream,)) + data)

    def _stderr(self, data):
        self.console.out(pyble_console.STDERR, data)

    def _emit_run_state(self, state):
        # The run-active console gate (P8) tracks the lifecycle exactly:
        # opened at RUN_STATE(running), closed at every terminal state.
        self.console.set_run_active(state == _RUNNING)
        self.emit(_OP["RUN_STATE"], bytes((state,)))

    # -- link callbacks --------------------------------------------------------
    def _on_message(self, msg):
        rsp = self._dispatcher.on_message(msg)
        # STOP/SOFT_REBOOT only arm this one-shot from their active-run handler.
        # Snapshot+clear before TX so a failed/dead link cannot leak the intent
        # into an unrelated later command. The actual dupterm notify is itself
        # scheduler-deferred by main() so its KBI lands outside the BLE IRQ.
        interrupt_after_rsp = self._interrupt_after_rsp
        self._interrupt_after_rsp = False
        if rsp is not None:
            self._link.send_message(rsp)
        if interrupt_after_rsp:
            self.console.inject_stop()

    def _on_connect(self):
        # Refresh the INFO read for the new session (mtu/free_mem/label live).
        self._link.set_info_payload(self.info_payload())

    def _on_disconnect(self):
        # F-10: reset the in-RAM transfer state ONLY — the jailed
        # <dest>.pbltmp stays on flash as the durable resume watermark.
        self._fs.on_disconnect()

    def _on_oversize(self, head):
        # P6: an oversize reassembled message was dropped — answer RSP ERANGE
        # with the best-effort opcode/id echo carried in the §3.1 header bytes.
        opcode = head[2] if len(head) > 2 else 0x00
        id_ = head[3] if len(head) > 3 else 0x00
        self._link.send_message(
            pyble_proto.encode(pyble_proto.RSP, opcode, id_, bytes((ERANGE,))))

    # -- helpers ---------------------------------------------------------------
    def _run_active(self):
        # RUNNING covers reserved-but-not-picked-up AND executing (P2).
        return self._runner.rsm.state == _RUNNING

    # -- §4 handlers (handler(frame) -> RSP payload bytes | None) --------------
    def _h_info(self, frame):
        # HELLO RSP == DEVICE_INFO RSP == [OK] + the single caps source (§7).
        # The request payload is not parsed: the §9 VER gate in dispatch
        # already refused any non-v1 frame (pble_info.c twin). The INFO read
        # and the GET chunk size are refreshed here so both track the
        # negotiated MTU (HELLO is the first post-MTU-exchange request).
        mtu, free_mem, device_id, label, auto_run = self._caps_args()
        self._fs._chunk = pyble_info.chunk_size(mtu)  # own-module seam (P2)
        self._link.set_info_payload(pyble_info.info_char_payload(
            mtu, free_mem, device_id, label, auto_run))
        return pyble_info.hello_rsp_payload(
            mtu, free_mem, device_id, label, auto_run)

    def _h_list(self, frame):
        return self._fs.handle_list(frame.payload)

    def _h_stat(self, frame):
        return self._fs.handle_stat(frame.payload)

    def _h_get_begin(self, frame):
        if self._run_active():
            return bytes((EBUSY,))      # transfers-during-RUN (P2)
        return self._fs.handle_get_begin(frame.payload)

    def _h_put_begin(self, frame):
        if self._run_active():
            return bytes((EBUSY,))      # transfers-during-RUN (P2)
        return self._fs.handle_put_begin(frame.payload)

    def _h_put_data(self, frame):
        return self._fs.handle_put_data(frame.payload)   # ACK-only: None

    def _h_put_end(self, frame):
        return self._fs.handle_put_end(frame.payload)

    def _h_delete(self, frame):
        return self._fs.handle_delete(frame.payload)

    def _h_mkdir(self, frame):
        return self._fs.handle_mkdir(frame.payload)

    def _h_rename(self, frame):
        return self._fs.handle_rename(frame.payload)

    def _h_run(self, frame):
        # Validate -> reserve -> RSP status ONLY (P2). RUN_STATE(running) is
        # supervisor work — RSP-before-RUN_STATE is structural.
        return bytes((self._runner.handle_run(frame.payload),))

    def _h_stop(self, frame):
        # §6/P3: RSP{OK} always (idempotent). Only an ACTIVE run additionally
        # requests the post-RSP console 0x03 path — an idle STOP must neither
        # emit a RUN_STATE nor leave a stale interrupt armed for the next run.
        status = self._runner.handle_stop()
        if self._run_active():
            self._interrupt_after_rsp = True
        return bytes((status,))

    def _h_soft_reboot(self, frame):
        # P4: RSP{OK} first (the dispatcher return sends it), then stop any
        # user code via the 0x03 path, then the injected reset runs from the
        # supervisor once the bounded TX-flush delay has elapsed.
        if self._run_active():
            self._runner.handle_stop()
            self._interrupt_after_rsp = True
        self._reboot_at = self._clock() + REBOOT_FLUSH_MS
        return bytes((OK,))

    def _h_console_input(self, frame):
        return self.console.feed_input(frame.payload)    # fire-and-forget: None

    def _h_set_identify_led(self, frame):
        # P1: validated per frozen §4, persisted NOWHERE while has_identify=0.
        # [] clears (OK); [gpio:u8][active_level:u8]; ERANGE if gpio out of
        # range; EBADREQ if active_level not in {0,1} or the pair is short.
        payload = bytes(frame.payload)
        if len(payload) == 0:
            return bytes((OK,))         # empty payload clears the identify LED
        if len(payload) < 2:
            return bytes((EBADREQ,))
        if payload[0] > _IDENTIFY_GPIO_MAX:
            return bytes((ERANGE,))
        if payload[1] > 1:
            return bytes((EBADREQ,))
        return bytes((OK,))

    def _h_identify(self, frame):
        # P1: has_identify=0 this increment — the REGISTERED handler answers
        # EUNSUPPORTED (spec-legal per §4: no identify LED is configured).
        return bytes((EUNSUPPORTED,))

    # -- supervisor ------------------------------------------------------------
    def poll(self):
        """ONE supervisor iteration (P2): run-mailbox pickup (RUN_STATE
        (running) -> exec -> terminal RUN_STATE), the GET transfer pump, then
        the deferred SOFT_REBOOT reset (P4). Never raises: a 0x03 landing
        outside user code (idle STOP / SOFT_REBOOT stop step) is swallowed."""
        try:
            self._runner.service()
            self._fs.pump()
        except KeyboardInterrupt:
            pass                        # stray interrupt: supervisor survives
        if self._reboot_at is not None:
            if _ticks_diff(self._clock(), self._reboot_at) >= 0:
                self._reboot_at = None  # exactly once (P4)
                if self._reset is not None:
                    self._reset()


# -----------------------------------------------------------------------------
# Device entry (frozen into the image; _boot.py calls main()). DEVICE-ONLY:
# the host suite drives Agent directly and never calls main().
# -----------------------------------------------------------------------------
def _activate_usb(machine_mod):
    """Bring up the builtin USB device from the supervisor (port spec P2).

    rp2's main.c calls mp_usbd_init() only AFTER _boot.py returns — and the
    supervisor never returns — so without this the board runs BLE-only with no
    USB CDC console (hardware-observed 2026-08-11 on the first flashed image).
    Best-effort: a build without machine.USBDevice (or CPython) is a no-op."""
    usb_device = getattr(machine_mod, "USBDevice", None)
    if usb_device is None:
        return
    try:
        dev = usb_device()
        # The singleton starts with builtin_driver = BUILTIN_NONE
        # (machine_usb_device.c:69): activating without selecting the builtin
        # CDC enumerates a device with NO interfaces — hardware-observed as no
        # USB CDC at all. Select the builtin driver BEFORE activating.
        builtin = getattr(usb_device, "BUILTIN_DEFAULT", None)
        if builtin is not None:
            dev.builtin_driver = builtin
        dev.active(True)
    except Exception:
        pass                            # USB is a console convenience, never fatal


def _serve_forever():
    import os
    import time

    import machine

    import pyble_ble

    _activate_usb(machine)
    link = pyble_ble.BleLink()
    dupterm_notify = getattr(os, "dupterm_notify", None)
    try:
        import micropython
    except ImportError:
        micropython = None
    schedule = getattr(micropython, "schedule", None)
    if dupterm_notify is not None and schedule is not None:
        # P3/P4: schedule the NATIVE callable (not a Python wrapper) so it runs
        # only after the current BTstack scheduler node has returned. It then
        # creates the pending KBI that unwinds the supervisor's user-code frame.
        _notify = _make_scheduled_dupterm_notify(schedule, dupterm_notify)
    else:
        _notify = _noop                 # guarded: CPython has no dupterm/schedule

    agent = Agent(link, "/",
                  unique_id=machine.unique_id(),
                  reset=machine.reset,
                  clock=_ticks_ms,
                  notify=_notify)

    # P3: pin the interrupt char so the armed 0x03 becomes KeyboardInterrupt.
    try:
        if micropython is None:
            raise AttributeError
        micropython.kbd_intr(3)
    except AttributeError:
        pass

    # The console tee replaces the local REPL stdio (guarded for CPython).
    dupterm = getattr(os, "dupterm", None)
    if dupterm is not None:
        dupterm(agent.console)

    # BLE bring-up is main()'s alone (the Agent never starts the link): serve
    # the caps on INFO from the first read, then fix the advertised identity
    # to label-else-PyBLE-XXXX with XXXX from unique_id (P1 — never the MAC).
    link.start(agent.info_payload())
    link.set_adv_name(agent.adv_name())

    agent.autorun()                     # LAST (cold-boot safe, stoppable)

    sleep_ms = getattr(time, "sleep_ms", None)
    while True:
        try:
            agent.poll()
            if sleep_ms is not None:
                sleep_ms(5)             # yield to the BTstack scheduler node
            else:
                time.sleep(0.005)
        except KeyboardInterrupt:
            pass                        # idle 0x03 never kills the supervisor


def main():
    """Supervisor entry with the outer fault restart (H9): a supervisor-fatal
    fault rebuilds the BleLink and re-advertises — the board never needs
    BOOTSEL to recover. _boot.py guards the very first import/call so a
    bring-up image without the frozen agent still falls to the REPL."""
    import time

    while True:
        try:
            _serve_forever()            # normally never returns
        except KeyboardInterrupt:
            pass
        except Exception:
            pass
        try:
            time.sleep(1)               # never a tight fault spin
        except Exception:
            pass
