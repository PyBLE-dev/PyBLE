# SPDX-License-Identifier: MIT
# Part of PyBLE (https://pyble.dev) — see /LICENSE.
#
# PyBLE native agent USER_C_MODULE (ADR-0006: native C from day one).
# build.sh passes this file as USER_C_MODULES when it exists; the esp32 port
# compiles the pble_*.c sources into the firmware image. One module list, all
# three chip targets (the agent is chip-agnostic; per-chip config is Layer 2).

add_library(usermod_pyble INTERFACE)

target_sources(usermod_pyble INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}/pble_proto.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_ble.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_info.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_device_config.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_runner.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_console.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_fs.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_lock.c
    ${CMAKE_CURRENT_LIST_DIR}/pble_boot.c
)

target_include_directories(usermod_pyble INTERFACE
    ${CMAKE_CURRENT_LIST_DIR}
)

# NOTE: the NimBLE headers are already on the include path (the esp32 port's main
# component requires `bt` when MICROPY_PY_BLUETOOTH=1); pble_ble.c only needs to
# force-include esp_nimble_cfg.h for the MYNEWT_VAL_* config (done in the source).
target_link_libraries(usermod INTERFACE usermod_pyble)
