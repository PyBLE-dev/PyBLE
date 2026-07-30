# Security policy

PyBLE flashes firmware, communicates with nearby boards over Bluetooth Low
Energy, transfers user files, and executes user-supplied MicroPython. Security
reports are treated as product-safety issues.

## Supported versions

PyBLE is currently pre-1.0. Security fixes are made on the default branch and
released in the newest app and firmware builds. Older beta builds may be
superseded rather than patched independently.

## Report a vulnerability privately

Do not open a public issue for a suspected vulnerability.

Use GitHub’s **Security → Report a vulnerability** action for this repository.
It creates a private security advisory visible only to the reporter and PyBLE
maintainers.

Include, when available:

- the affected app and firmware versions;
- the exact board and memory profile;
- impact and realistic attack prerequisites;
- reproduction steps or a minimal proof of concept;
- sanitized logs or BLE captures; and
- any suggested mitigation.

Never include private keys, provisioning profiles, personal device data, or
another person’s information.

## Response

Maintainers will acknowledge a complete report as soon as practical, normally
within seven days. We will validate the impact, coordinate a fix and release,
and credit the reporter unless anonymity is requested.

Please allow a reasonable remediation window before public disclosure. If a
report is outside PyBLE’s control, such as an upstream MicroPython, Flutter,
ESP-IDF, operating-system, or browser vulnerability, maintainers will help
route it to the appropriate upstream project.

## Scope

Useful reports include:

- PBLE/1 authentication, authorization, framing, or state-machine flaws;
- filesystem-jail escapes or unsafe path handling;
- firmware flashing integrity or target-selection failures;
- unintended remote code execution beyond the explicitly connected board;
- disclosure of local projects, BLE identifiers, or board data;
- insecure release, update, or dependency behavior; and
- denial-of-service conditions with a practical security impact.

Ordinary bugs, compatibility problems, and feature requests belong in public
issues.
