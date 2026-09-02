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


def mount_lfs2(bdev, vfs_module, progsize=256):
    """Mount LFS2, formatting once only when every device byte is erased.

    Unexpected constructor faults propagate without inspection.  Invalid or
    unreadable geometry and any non-erased byte perform no write.  The original
    mount ``OSError`` is re-raised for nonblank media so the board overlay can
    enter its bounded operator-recovery path.
    """
    try:
        return vfs_module.VfsLfs2(bdev, progsize=progsize)
    except OSError as error:
        mount_failure = error

    count, block_size = _recovery_geometry(bdev, progsize)
    block = bytearray(block_size)
    erased = True
    for block_number in range(count):
        # Poison every byte before reuse. A backend that mutates only a prefix
        # cannot leave a stale erased-looking suffix from an earlier read.
        for index in range(block_size):
            block[index] = 0
        result = bdev.readblocks(block_number, block)
        if result not in (None, 0) or len(block) != block_size:
            raise ValueError("uncertain block-device read")
        for value in block:
            if value != 0xFF:
                erased = False

    if not erased:
        raise mount_failure

    vfs_module.VfsLfs2.mkfs(bdev, progsize=progsize)
    return vfs_module.VfsLfs2(bdev, progsize=progsize)
