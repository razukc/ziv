# Ziv QEMU boot app — ladder rung 1 (docs/QEMU_SIMULATION_LADDER.md).
#
# An ordinary ESP-IDF project; all Ziv sources are compiled by the main
# component (see main/CMakeLists.txt). Build:
#   idf.py set-target esp32s3
#   idf.py build
#   idf.py qemu monitor        # the scripted demo's HAP lines on the UART
#
# Only `main` and what it requires are built: the image carries no esp_wifi,
# no I2S and no network stack (those return at ladder rungs 3-4), so the
# first build and the QEMU boot stay small and fast.
cmake_minimum_required(VERSION 3.16)
set(COMPONENTS main)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ziv_qemu)
