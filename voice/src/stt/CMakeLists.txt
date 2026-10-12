# =============================================================================
# Voice Service — CMake Build Configuration
# =============================================================================
# Builds the whisper.cpp library (with SDL2 + CUDA) and links the voice_service
# executable against it.
#
# Usage:
#   mkdir -p build && cd build
#   cmake ..
#   cmake --build . -j$(nproc)
#
# The whisper.cpp library is pulled in as a subdirectory and built alongside
# the service in a single CMake invocation.
# =============================================================================

cmake_minimum_required(VERSION 3.18)
project(voice_service LANGUAGES C CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_C_STANDARD 11)

# ---------------------------------------------------------------------------
# Build whisper.cpp as a subdirectory
# ---------------------------------------------------------------------------

# Path to the whisper.cpp submodule — relative to THIS file
set(WHISPER_SRC_DIR "${CMAKE_CURRENT_SOURCE_DIR}/../../third_party/whisper.cpp")

if(NOT EXISTS "${WHISPER_SRC_DIR}/CMakeLists.txt")
    message(FATAL_ERROR
        "whisper.cpp not found at ${WHISPER_SRC_DIR}\n"
        "  1. Run: git submodule update --init --recursive\n"
        "  2. Or set WHISPER_SRC_DIR to point to your whisper.cpp checkout."
    )
endif()

# Configure whisper.cpp options — MUST be set BEFORE add_subdirectory()
set(WHISPER_SDL2 ON CACHE BOOL "Enable SDL2 audio capture")
set(WHISPER_BUILD_EXAMPLES OFF CACHE BOOL "Do not build whisper.cpp examples")
set(WHISPER_BUILD_TESTS OFF CACHE BOOL "Do not build whisper.cpp tests")
set(WHISPER_BUILD_SERVER OFF CACHE BOOL "Do not build whisper.cpp server")
set(WHISPER_COMMON_FFMPEG OFF CACHE BOOL "Do not need FFmpeg")
set(GGML_CUDA ON CACHE BOOL "Enable CUDA GPU acceleration")

# Add whisper.cpp — targets will be prefixed with WHISPER_BUILD_PREFIX_
add_subdirectory(
    ${WHISPER_SRC_DIR}
    whisper_build
)

# ---------------------------------------------------------------------------
# Voice service executable
# ---------------------------------------------------------------------------

set(TARGET voice_service)

add_executable(${TARGET} service.cpp)

# Include paths:
#   - whisper.h lives in third_party/whisper.cpp/include/
#   - common.h, common-sdl.h live in third_party/whisper.cpp/examples/
target_include_directories(${TARGET} PRIVATE
    ${WHISPER_SRC_DIR}/include
    ${WHISPER_SRC_DIR}
    ${WHISPER_SRC_DIR}/examples
)

# Link libraries.
# add_subdirectory(… whisper_build) prefixes all targets in whisper.cpp:
#   whisper → whisper_build_whisper
#   ggml    → whisper_build_ggml
target_link_libraries(${TARGET} PRIVATE
    whisper_build_whisper
    whisper_build_ggml
    ${SDL2_LIBRARIES}
    Threads::Threads
    dl
)

# Set output directory
set_target_properties(${TARGET} PROPERTIES
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_BINARY_DIR}/bin"
)

# ---------------------------------------------------------------------------
# Print summary
# ---------------------------------------------------------------------------

message(STATUS "=== Voice Service Build ===")
message(STATUS "  whisper.cpp source : ${WHISPER_SRC_DIR}")
message(STATUS "  SDL2               : ${SDL2_LIBRARIES}")
message(STATUS "  CUDA               : enabled (GGML_CUDA)")
message(STATUS "  Output             : ${CMAKE_BINARY_DIR}/bin/${TARGET}")
message(STATUS "===========================")
