# firmware/band/esp_project — the smallest ESP-IDF project that builds the
# band.  ../esp IS the component (IDF names it after its folder, "esp"), so
# there is no main/ here: app_main lives in ../esp/band_main.c.
#
#   idf.py set-target esp32s3    # once (sdkconfig.defaults already names the target)
#   idf.py build                 # fetches espressif/esp_websocket_client into managed_components/
#   idf.py qemu                  # boots the default config: mock bus, no radio, transport in backoff
#   idf.py menuconfig            # Ziv band → mock off, SSID/password, relay URI, device key (a board)
cmake_minimum_required(VERSION 3.16)
set(EXTRA_COMPONENT_DIRS "${CMAKE_CURRENT_LIST_DIR}/../esp")
set(COMPONENTS esp)
include($ENV{IDF_PATH}/tools/cmake/project.cmake)
project(ziv_band)
