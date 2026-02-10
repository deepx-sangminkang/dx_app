cmake_minimum_required(VERSION 3.16)
project(npu_usage VERSION 1.0.0 LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

# ============================================================================
# Configuration - Use system-installed DX Runtime
# ============================================================================

# System-installed paths
set(DX_INCLUDE_DIR "/usr/local/include" CACHE PATH "Path to dxrt include directory")
set(DX_LIB_DIR "/usr/local/lib" CACHE PATH "Path to dxrt library directory")

# ============================================================================
# Verify paths exist
# ============================================================================

if(NOT EXISTS "${DX_INCLUDE_DIR}/dxrt")
    message(FATAL_ERROR "DX Runtime include directory not found: ${DX_INCLUDE_DIR}/dxrt")
endif()

if(NOT EXISTS "${DX_LIB_DIR}/libdxrt.so")
    message(FATAL_ERROR "DX Runtime library not found: ${DX_LIB_DIR}/libdxrt.so")
endif()

message(STATUS "DX Runtime include: ${DX_INCLUDE_DIR}")
message(STATUS "DX Runtime lib: ${DX_LIB_DIR}")

# ============================================================================
# Build executable
# ============================================================================

add_executable(npu_usage npu_usage.cpp)

target_include_directories(npu_usage PRIVATE
    ${DX_INCLUDE_DIR}
)

target_link_directories(npu_usage PRIVATE
    ${DX_LIB_DIR}
)

target_link_libraries(npu_usage PRIVATE
    dxrt
    pthread
)

# Set RPATH for finding libdxrt.so at runtime
set_target_properties(npu_usage PROPERTIES
    BUILD_RPATH "${DX_LIB_DIR}"
    INSTALL_RPATH "${DX_LIB_DIR}"
)

# ============================================================================
# Install
# ============================================================================

install(TARGETS npu_usage
    RUNTIME DESTINATION bin
)
