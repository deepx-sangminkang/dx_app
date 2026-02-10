# NPU Utilization Monitor

Simple standalone tool to monitor NPU core utilization via IPC communication with dxserv.

## Prerequisites

- DX Runtime installed at `/usr/local` (default system installation)
- `dxrt` service running: `sudo systemctl status dxrt`
- CMake 3.16+
- C++17 compiler

## Build

```bash
cd ~/workspace/dx_app/internal/npu_usage

# Create build directory
mkdir build && cd build

# Configure (uses system-installed dxrt by default)
cmake ..

# Build
make -j$(nproc)
```

## Usage

```bash
# Print utilization once
./npu_usage

# Continuous monitoring (Ctrl+C to stop)
./npu_usage -c

# Show help
./npu_usage -h
```

## Output Example

```
==================================================
NPU Utilization Monitor
==================================================
Devices found: 1
--------------------------------------------------

Device 0:
  Core 0: 45.2%
  Core 1: 38.7%
  Core 2: 52.1%
  --------
  Average: 45.3%
==================================================
```

## How It Works

1. Initializes device pool via `DevicePool::GetInstance().InitCores()`
2. Sends `GET_USAGE` IPC request to dxserv for each core
3. dxserv returns utilization value (multiplied by 1000)
4. Displays utilization percentage per core

## Troubleshooting

**"No NPU devices found!"**
- Check if NPU hardware is connected
- Verify driver is loaded: `lsmod | grep deepx`

**"IPC error" or connection failed**
- Make sure dxrt service is running: `sudo systemctl status dxrt`
- Start if not running: `sudo systemctl start dxrt`

**Library not found at runtime**
- Verify system installation: `ls /usr/local/lib/libdxrt.so`
- Check LD_LIBRARY_PATH if using non-standard location

## Files

```
npu_usage/
├── CMakeLists.txt    # Build configuration
├── npu_usage.cpp     # Main source code
├── README.md         # This file
└── build/
    └── npu_usage      # Built executable
```

## System Paths

- Include: `/usr/local/include/dxrt/`
- Library: `/usr/local/lib/libdxrt.so`
- Service: `dxrt.service` (systemd)
