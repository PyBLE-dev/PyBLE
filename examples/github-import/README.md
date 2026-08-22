<!-- SPDX-License-Identifier: MIT -->
<!-- Part of PyBLE (https://pyble.dev) — see /LICENSE. -->

# GitHub import examples

This folder contains small, fresh PyBLE examples for testing the public GitHub
import workflow. Both examples use ordinary Python output only. They assume no
particular board, chip, pin, peripheral, or provisioning profile.

To copy them to a connected board:

1. Connect PyBLE to a compatible board and open the destination directory in
   **Files**.
2. Choose **Import examples from GitHub**.
3. Enter `https://github.com/PyBLE-dev/PyBLE` as the repository. Leave the ref
   blank for the repository's default branch, or enter an explicit public
   branch, tag, or commit.
4. Browse to `examples/github-import`, select `hello.py`, `count.py`, or both,
   and continue to review.
5. Confirm the displayed pinned commit, exact board target paths, and any
   overwrite warning before importing.

Importing copies the selected files into the Files directory that was open
when the action began. PyBLE does not automatically open or run imported code;
inspect a file first, then run it explicitly when ready.

