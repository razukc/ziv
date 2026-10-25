# Ziv QEMU boot app — ladder rung 1 (docs/QEMU_SIMULATION_LADDER.md).
#
# An ordinary ESP-IDF project; all Ziv sources are compiled by the main
# component (see main/CMakeLists.txt). Build:
#   idf.py set-target esp32s3
#   idf.py build
#   idf.py qemu monitor        # the scripted demo's HAP lines on the UART
cmake_minimum_required(VERSION 3.16)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ziv_qemu)
