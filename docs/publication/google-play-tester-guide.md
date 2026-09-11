# PyBLE Android open-testing guide

Candidate: app `0.2.0 (8)`; confirm the version in About after installation.
This guide can be shared once the open-testing release is available. The
maintainer must insert the actual opt-in link copied from Play Console before
sending an invitation. No live open-test link is asserted here.

## Join and prepare

1. Open the maintainer's Google Play opt-in link while signed in with the same
   Google account used by Play Store on the Android device. Join the test,
   install PyBLE from Play and check About. Android 7.0/API 24 or newer and BLE
   hardware are required; Play confirms device compatibility.
2. Existing internal testers must leave the internal test before joining the
   open test. Internal-track membership overrides other test tracks. An
   installed version with a higher version code can also prevent a downgrade;
   report the installed About version if the expected build does not arrive.
   [Google testing-track rules](https://support.google.com/googleplay/android-developer/answer/9845334?hl=en).
3. Prepare a compatible MicroPython board with the PyBLE agent using
   [Setup](https://pyble.dev/learn/setup) and
   [Firmware](https://pyble.dev/flash). Use the exact board profile. Back up
   existing board files first; firmware installation can erase them. A
   computer and data cable are needed for initial provisioning.
4. Power the board nearby, enable Bluetooth and grant Nearby devices when
   Android requests it. On Android 11 or earlier, grant the legacy BLE scan
   permission and enable system Location if scanning needs it. PyBLE does not
   derive your location. Connect through the app, then verify Board info.
5. Use disposable programs in a child folder named `open_test`. Save work to
   the board before leaving; the current editor buffer is not a durable local
   project backup. Start with the wiring-free tests below.

App and firmware versions are independent. Firmware `0.6.0` is the documented
qualified five-profile baseline. The app's open-testing status does not
qualify a newer firmware beta. Note the exact firmware version and status
used in every report.

## What to test

| Area | Exercise | Expected result |
| --- | --- | --- |
| Install and identity | Fresh install, update from the earlier Play version, launch, About | Correct candidate version/build; app starts without an account. |
| Privacy | Open About and privacy while disconnected and offline | Readable policy and canonical URL; return to previous screen works. |
| Permission recovery | Deny Nearby devices, then enable it in Android settings; test Bluetooth off/on | Clear recovery guidance, no crash or invisible permission loop. |
| Connect | Scan, connect to intended board, disconnect, reconnect | Correct Board ID and firmware; connected actions appear only after Ready. |
| Editor and console | Create `hello.py`, enter `print("Hello from PyBLE!")`, Save, Run | Exact saved program runs once; Console shows the message. |
| Editor sizing | Change font size; rotate; try external-keyboard Tab and large system text | Code, line numbers, selection and unsaved state remain consistent. |
| Input and Stop | Follow the wiring-free input and loop examples in the reviewer guide | Console input reaches the board; Stop interrupts active work. |
| Files | Create folder/file; open, rename, upload and delete disposable files | Correct board and folder; honest results and refreshed listing. |
| Multiple deletion | Select two files, cancel exact confirmation, then confirm | Cancel preserves both; confirmation deletes only named eligible files. |
| Session change | Disconnect while selection or confirmation is open, then reconnect | Stale selection and previous-board actions are cleared. |
| GitHub browse | Open importer, use official repository, choose branch, try advanced ref | Visible pinned commit; changing repository/ref clears old selection. |
| GitHub import | Import `pyble_hello_console.py` into `/open_test`; repeat for overwrite | Exact source/destination review; separate overwrite consent; no automatic open/run. |
| GitHub unavailable | Disconnect internet or observe actual request-limit response | Useful error/retry state; ordinary BLE editing and Files continue. |
| Blocks | Load bundled language-only example; preview, save and reopen companion | Offline workspace works; Python and matching Blocks record survive reopen. |
| GPIO blocks | Only on suitable hardware, enter numeric GPIO or valid named pin such as `LED` | Generated Python preserves the explicit choice; no inferred wiring. |
| Android layout | Phone and tablet; portrait/landscape; keyboard; TalkBack; 2× text | Actions remain visible or accessible through named overflow menus. |
| Android lifecycle | Background/resume, screen off/on, board restart, BLE interruption | UI accurately reflects connection and recovers through reconnect. |

Detailed wiring-free examples are in the
[reviewer guide](google-play-reviewer-guide.md). The
[learning center](https://pyble.dev/learn) covers normal use.

## Known boundaries

- No board means no connected IDE workspace; there is no onboard Android
  Python interpreter or demo board.
- GitHub import is limited to selected lowercase `.py` files from the current
  public remote folder. It does not clone a repository, create the remote
  folder tree, authenticate, upload your projects or automatically run code.
- Protected root names such as `pyble_*` need a regular child-folder
  destination. Do not alter board-control files.
- Multi-delete is permanent and sequential. Earlier successful deletions can
  remain after a later failure; there is no trash or automatic rollback.
- Blocks conversion accepts a bounded Python subset; not every Python program
  can be converted back into editable blocks.
- Stop and soft reboot may require reconnect depending on firmware behavior.
  Verify the board identity again after recovery.
- Treat BLE as a nearby personal-board workflow. PBLE/1 does not guarantee an
  encrypted link; avoid credentials or sensitive information in code, console
  input and advertising labels.

## Send useful feedback

Email **viwat.v@chula.ac.th**, use the
[support page](https://pyble.dev/support), or submit a
[public bug report](https://github.com/PyBLE-dev/PyBLE/issues/new?template=bug.yml).
Google Play also provides private testing feedback. Public issues are visible
to everyone; send sensitive details privately.

Copy this report template:

```text
Subject: [Android open test] Short description
PyBLE version and build from About:
Install path: fresh / updated / switched from internal testing
Android device model and OS version:
Android System WebView version, for Blocks problems:
Board model, exact firmware profile and agent version:
Connection state when the problem began:
Steps to reproduce:
1.
2.
3.
Expected result:
Actual result and exact error:
Reproducibility: every time / sometimes / once
GitHub public repository, ref and pinned commit, if relevant:
Affected disposable filename/folder, if relevant:
Rotation, text size, TalkBack or keyboard involved:
Screenshot or short recording, with private information removed:
```

Share board identifiers only when needed to diagnose a connection issue; omit
them from public screenshots when unnecessary. Do not send secrets, private
code or tokens. PyBLE does not require a GitHub token.

## Maintainer exit criteria

Retain dated results with exact app artifact hash, device/OS, board profile and
firmware version. Before broadening distribution, pass fresh-install and
upgrade smoke tests, core BLE Save/Run/Stop/Input, Files and Blocks on physical
Android hardware, and resolve reproducible crashes, data loss, wrong-board
writes, unusable permissions or inaccessible required controls. Collect
portrait/landscape and large-text evidence plus an Android 16/API 36 run.

Automated tests and emulator screenshots do not establish radio or physical
board behavior. Existing firmware qualification and older app captures do not
prove this candidate's hardware result. If a defect appears after publication,
triage incoming reports, pause the affected track if needed, prepare a fix
with a higher version code and record its validation before the next release.
