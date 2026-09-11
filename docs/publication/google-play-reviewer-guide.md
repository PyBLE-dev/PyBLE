# Google Play reviewer access: PyBLE

Prepared for the Android open-testing candidate `0.2.0 (8)` on 2026-09-10.
Verify the actual version in About. This guide describes the production app;
it does not describe an integration-test flavor or a simulated board.

## App access form

Choose the option for functionality requiring special access and create an
instruction named **BLE board access; no login**. Paste
[`app-access.txt`](google-play/en-US/app-access.txt) into the instructions
field. Leave credential fields unused when the Console permits it and explain
that the restriction is external hardware, not authentication. Do not invent
credentials.

The app is connection-gated. About and the offline privacy information can be
reviewed before connecting, but the editor, Files, Blocks, Run and Console need
a real BLE connection. There is no shipped demo mode. Physical board access
remains a review dependency even though PyBLE has no login.

Google requires information needed to review restricted functionality through
the app-content workflow. If the available App access fields cannot convey
the board arrangement, use Play Console support to agree a workable review
method. A recording can explain the flow but does not itself provide access to
the IDE. [Google app review preparation](https://support.google.com/googleplay/android-developer/answer/9859455?hl=en).

## Board and device setup

1. Use an Android phone or tablet with BLE and Android 7.0/API 24 or newer.
   A tablet provides the intended roomy editing layout. Use the final artifact
   device catalog to confirm actual compatibility.
2. Use a Raspberry Pi Pico 2 W, or a board matching an exact supported profile
   at [pyble.dev/flash](https://pyble.dev/flash). Profile names are
   `esp32-4mb`, `esp32-s3-n16r8`, `esp32-c3-4mb`,
   `waveshare-esp32-s3-lcd-147b`, and `rpi-pico2-w` for the independently
   qualified firmware `0.6.0`. Other firmware versions shown on the website
   keep their own release status; do not relabel a beta as qualified.
3. Back up the board before flashing. Provisioning can erase its existing
   workspace. Use a computer and data cable: supported desktop Chromium for
   the ESP installer, or BOOTSEL/UF2 copy for Pico 2 W. Follow the exact
   [setup tutorial](https://pyble.dev/learn/setup).
4. Power the prepared board and keep it near the Android device. Close other
   clients connected to it. No sensor, LED wiring, display, Wi-Fi setup or
   GitHub account is required for the core review below.
5. Enable Bluetooth. Open PyBLE and choose Connect. On Android 12 or newer,
   allow Nearby devices when requested. Android 11 and earlier may require
   the BLE scan location permission and system Location to be enabled; PyBLE
   does not derive device location.
6. Choose the expected `PyBLE-` board in the app scan list. Wait until Ready
   and verify the board identity and agent version. Do not pair it as a
   keyboard or headset in Android settings.

Hardware/setup contact: **viwat.v@chula.ac.th**. Before submission, the
maintainer must record how the reviewer will obtain and use compatible
hardware. No reviewer-hardware delivery or agreement has been recorded by
this packet.

## Core review without electrical wiring

1. Open About and check the installed app version/build and privacy policy.
   Return to the connected workspace.
2. In Files, create a disposable folder named `play_review`, then enter it.
   Choose New file, enter `hello.py`, and put the following in the editor:

   ```python
   print("Hello from PyBLE!")
   ```

3. Save, then choose Run. Console should show `Hello from PyBLE!`. Save alone
   does not execute the program. Change the message, save and run once more.
4. To exercise input, save this as another file and run it. Enter `review`
   through Console when the prompt appears:

   ```python
   name = input("Name: ")
   print("Hello", name)
   ```

5. To exercise Stop, run the following bounded-output loop and press Stop
   after a few lines. No GPIO access occurs:

   ```python
   import time

   while True:
       print("PyBLE review")
       time.sleep(1)
   ```

6. In Blocks, load a language-only bundled example, inspect its generated
   Python, create an editable copy when prompted, then save it under the
   disposable folder. Run only after review. No internet is needed.
7. In Files, make two disposable files. Select both, choose Delete selected,
   inspect the confirmation and cancel once. Repeat and confirm. The named
   files should be deleted; protected files and folders are excluded from
   bulk selection.
8. With internet access enabled, open Import examples from GitHub. Keep the
   official `https://github.com/PyBLE-dev/examples` repository and choose a
   public branch. Browse `examples/portable/basics/hello_console`, select
   `pyble_hello_console.py`, review the pinned commit and destination under
   `/play_review`, and import. The file must not open or run automatically.
   This optional step requires no GitHub login or token.
9. Disconnect and reconnect. Recheck identity and reopen the saved file from
   Files. Rotate the screen and exercise large text. Ordinary BLE operations
   should continue when internet is disabled.

If the board is absent from the scan list, verify power, exact firmware,
Bluetooth permission, whether another client is connected, and that the
device supports BLE. Stock MicroPython does not provide the PyBLE service.
The [support page](https://pyble.dev/support) contains current setup help.
