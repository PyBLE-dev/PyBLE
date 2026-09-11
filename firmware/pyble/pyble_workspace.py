# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
"""Shared, fail-closed LFS2 workspace mount authority.

All supported profiles use this helper so first-use provisioning cannot drift
between ESP and RP2.  A healthy mount is returned without inspecting storage.
Only an ``OSError`` from that first constructor admits the bounded, read-only
complete-device erased scan and its single permitted format attempt.
"""

_BDEV_IOCTL_BLOCK_COUNT = 4
_BDEV_IOCTL_BLOCK_SIZE = 5
_LFS_READ_SIZE = 32
_LFS_MIN_BLOCK_SIZE = 128

_COUNTER_LIMIT = 65535
_COUNTER_NAMES = (
    "mount_attempts", "format_attempts", "format_completions",
    "remount_attempts", "remount_completions", "program_calls", "erase_calls",
    "recovery_attempts", "recovery_emissions",
)
_RECOVERY_MESSAGE = "PyBLE workspace recovery is required; reconnect by USB."
_boot_observation = None
_observation_started = False
_unobserved_recovery_attempted = False


class _BootObservation:
    """One bounded VM-local measurement; never an admission authority."""

    def __init__(self):
        import os
        from binascii import hexlify

        identity = os.urandom(16)
        if type(identity) is not bytes or len(identity) != 16:
            raise ValueError("unavailable workspace boot identity")
        self.boot_id = hexlify(identity).decode()
        self.counts = [0] * len(_COUNTER_NAMES)
        self.workspace_attached = False
        self.complete = False
        self.fault = False
        self.overflow = False
        self.media_state = "uninspected"
        self.sealed = False
        self.mount_returned = False
        self.nonblank_refusal = False

    def increment(self, index):
        if self.sealed:
            return
        if self.counts[index] == _COUNTER_LIMIT:
            self.overflow = True
            self.fault = True
            raise OverflowError("workspace observation counter overflow")
        self.counts[index] += 1

    def mark_fault(self):
        if not self.sealed:
            self.fault = True


class _ObservedBlockDevice:
    """Observe the native program/erase boundary without copying read data."""

    def __init__(self, bdev, observation):
        # VfsLfs2 caches this original bound method directly. Reads do not
        # acquire a Python forwarding layer or qualification-owned buffer.
        self.readblocks = bdev.readblocks
        self._writeblocks = bdev.writeblocks
        self._ioctl = bdev.ioctl
        self._observation = observation

    def writeblocks(self, block, data, *offset):
        observation = self._observation
        observation.increment(5)
        try:
            result = self._writeblocks(block, data, *offset)
        except BaseException:
            observation.mark_fault()
            raise
        # Preserve the pinned VFS protocol's return value, including failed
        # and idempotent writes. A false/invalid result cannot look healthy.
        if result is False or (result is not None and result is not True and result != 0):
            observation.mark_fault()
        return result

    def ioctl(self, command, argument):
        observation = self._observation
        if command == 6:
            observation.increment(6)
        try:
            result = self._ioctl(command, argument)
        except BaseException:
            observation.mark_fault()
            raise
        if command == 6 and result is not None and result != 0:
            observation.mark_fault()
        return result


def read_boot_observation(challenge):
    """Read detached retained state; never rerun storage or change a count."""
    if (type(challenge) is not str or len(challenge) != 32 or
            any(value not in "0123456789abcdef" for value in challenge)):
        raise ValueError("invalid workspace observation challenge")
    observation = _boot_observation
    if observation is None:
        raise RuntimeError("workspace boot observation unavailable")
    value = {
        "schema_version": 1,
        "boot_id": observation.boot_id,
        "challenge": challenge,
    }
    for index in range(len(_COUNTER_NAMES)):
        value[_COUNTER_NAMES[index]] = observation.counts[index]
    value["workspace_attached"] = observation.workspace_attached
    value["complete"] = observation.complete
    value["fault"] = observation.fault
    value["overflow"] = observation.overflow
    value["media_state"] = observation.media_state
    return value


def boot_attached():
    """Seal only after the overlay's actual VFS attachment succeeded."""
    observation = _boot_observation
    if observation is None or observation.sealed:
        raise RuntimeError("workspace observation cannot attach")
    if not observation.mount_returned or observation.fault or observation.overflow:
        observation.mark_fault()
        raise RuntimeError("workspace observation is not attachable")
    observation.workspace_attached = True
    observation.complete = True
    observation.sealed = True


def boot_recovery():
    """Emit the bounded local message once, measuring the real print call."""
    global _unobserved_recovery_attempted
    observation = _boot_observation
    if observation is None:
        # An allocation/entropy fault may precede record creation. Guidance
        # still exists, but no zero-filled or otherwise passing record does.
        if _unobserved_recovery_attempted:
            raise RuntimeError("workspace recovery already attempted")
        _unobserved_recovery_attempted = True
        print(_RECOVERY_MESSAGE)
        return
    if observation.sealed:
        raise RuntimeError("workspace recovery already sealed")
    if not observation.nonblank_refusal or observation.mount_returned:
        observation.mark_fault()
    observation.increment(7)
    try:
        print(_RECOVERY_MESSAGE)
        observation.increment(8)
    except BaseException:
        observation.mark_fault()
        observation.sealed = True
        raise
    observation.complete = True
    observation.sealed = True


def _recovery_geometry(bdev, progsize):
    """Return validated ``(count, block_size)`` for destructive recovery."""
    if type(progsize) is not int or progsize <= 0:
        raise ValueError("uncertain LFS2 program geometry")

    count = bdev.ioctl(_BDEV_IOCTL_BLOCK_COUNT, 0)
    block_size = bdev.ioctl(_BDEV_IOCTL_BLOCK_SIZE, 0)
    if (type(count) is not int or type(block_size) is not int or
            count < 2 or block_size < _LFS_MIN_BLOCK_SIZE):
        raise ValueError("uncertain block-device geometry")

    cache_size = min(
        block_size,
        4 * max(_LFS_READ_SIZE, progsize),
    )
    if (cache_size % _LFS_READ_SIZE != 0 or
            cache_size % progsize != 0 or
            block_size % cache_size != 0):
        raise ValueError("LFS2-incompatible block-device geometry")
    return count, block_size


def mount_lfs2(bdev, vfs_module, progsize=256, *, observe_boot=False):
    """Mount LFS2, formatting once only when every device byte is erased.

    Unexpected constructor faults propagate without inspection.  Invalid or
    unreadable geometry and any non-erased byte perform no write.  The original
    mount ``OSError`` is re-raised for nonblank media so the board overlay can
    enter its bounded operator-recovery path.
    """
    global _boot_observation, _observation_started
    if type(observe_boot) is not bool:
        raise ValueError("invalid workspace observation mode")
    if not observe_boot:
        return _mount_lfs2(bdev, vfs_module, progsize, None)
    if _observation_started:
        raise RuntimeError("workspace boot already observed")
    _observation_started = True
    observation = _BootObservation()
    _boot_observation = observation
    try:
        return _mount_lfs2(_ObservedBlockDevice(bdev, observation),
                          vfs_module, progsize, observation)
    except BaseException:
        if not observation.nonblank_refusal:
            observation.mark_fault()
            if observation.media_state == "uninspected":
                observation.media_state = "uncertain"
        raise


def _mount_lfs2(bdev, vfs_module, progsize, observation):
    if observation is not None:
        observation.increment(0)
    try:
        mounted = vfs_module.VfsLfs2(bdev, progsize=progsize)
    except OSError as error:
        mount_failure = error
    else:
        if observation is not None:
            observation.mount_returned = True
        return mounted

    if observation is not None:
        if observation.fault or observation.overflow:
            raise mount_failure
        observation.media_state = "uncertain"

    count, block_size = _recovery_geometry(bdev, progsize)
    block = bytearray(block_size)
    erased = True
    for block_number in range(count):
        # Poison every byte before reuse. A backend that mutates only a prefix
        # cannot leave a stale erased-looking suffix from an earlier read.
        for index in range(block_size):
            block[index] = 0
        result = bdev.readblocks(block_number, block)
        read_succeeded = (result is None or result is True or
                          (type(result) is int and result == 0))
        if not read_succeeded or len(block) != block_size:
            raise ValueError("uncertain block-device read")
        for value in block:
            if value != 0xFF:
                erased = False

    if not erased:
        if observation is not None:
            observation.media_state = "nonblank"
            observation.nonblank_refusal = True
        raise mount_failure

    if observation is not None:
        observation.media_state = "erased"
        if observation.fault or observation.overflow:
            raise RuntimeError("uncertain workspace observation")
        observation.increment(1)
    vfs_module.VfsLfs2.mkfs(bdev, progsize=progsize)
    if observation is not None:
        observation.increment(2)
        if observation.fault or observation.overflow:
            raise RuntimeError("uncertain workspace format observation")
        observation.increment(3)
    mounted = vfs_module.VfsLfs2(bdev, progsize=progsize)
    if observation is not None:
        observation.increment(4)
        observation.mount_returned = True
    return mounted
