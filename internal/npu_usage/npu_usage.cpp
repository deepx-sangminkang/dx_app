/*
 * NPU Utilization Monitor
 *
 * Simple standalone tool to get NPU core utilization and temperature via IPC.
 * Requires dxrt service to be running.
 */

#include <iostream>
#include <iomanip>
#include <memory>
#include <vector>
#include <thread>
#include <chrono>
#include <csignal>
#include <algorithm>
#include <unistd.h>

#include "dxrt/device_pool.h"
#include "dxrt/device_core.h"
#include "dxrt/ipc_wrapper/ipc_client_wrapper.h"
#include "dxrt/ipc_wrapper/ipc_message.h"

namespace {
    volatile sig_atomic_t g_running = 1;

    void signalHandler(int signum) {
        g_running = 0;
    }

    // Exit codes
    constexpr int EXIT_OK = 0;
    constexpr int EXIT_ERROR = 1;
    constexpr int EXIT_USAGE_ZERO = 2;      // Utilization is 0%
    constexpr int EXIT_TEMP_HIGH = 3;       // Temperature >= 90C

    constexpr int ERROR_THRESHOLD_SEC = 10; // Error condition must persist for 10 seconds
}

class NpuUtilMonitor {
public:
    static constexpr int CORES_PER_DEVICE = 3;  // DX-M1 has 3 cores

    NpuUtilMonitor()
        : _ipcClient(dxrt::IPCDefaultType(), getpid())  // Initialize with IPC type and PID
    {
        // Initialize IPC client (false = don't enable internal callback)
        if (_ipcClient.Initialize(false) != 0) {
            throw std::runtime_error("Failed to initialize IPC client");
        }

        // Initialize device pool
        dxrt::DevicePool::GetInstance().InitCores();
        _deviceCount = dxrt::DevicePool::GetInstance().GetDeviceCount();
    }

    ~NpuUtilMonitor() {
        _ipcClient.Close();
    }

    int getDeviceCount() const {
        return _deviceCount;
    }

    double getUtilization(int deviceId, int coreId) {
        dxrt::IPCClientMessage request;
        dxrt::IPCServerMessage response;

        request.code = dxrt::REQUEST_CODE::GET_USAGE;
        request.deviceId = deviceId;
        request.data = coreId;
        request.pid = getpid();

        try {
            int result = _ipcClient.SendToServer(response, request);

            if (result == 0 && response.result == 0) {
                // Server returns value * 10, divide back and cap at 100%
                return std::min(100.0, response.data / 10.0);
            }
        } catch (const std::exception& e) {
            std::cerr << "IPC error: " << e.what() << std::endl;
        }

        return -1.0;
    }

    int32_t getTemperature(int deviceId, int coreId) {
        try {
            auto deviceCore = dxrt::DevicePool::GetInstance().GetDeviceCores(deviceId);
            if (deviceCore) {
                auto status = deviceCore->Status();
                return static_cast<int32_t>(status.temperature[coreId]);
            }
        } catch (const std::exception& e) {
            std::cerr << "Temperature error: " << e.what() << std::endl;
        }
        return -999;
    }

    void printAllUtilization() {
        std::cout << "\n";
        std::cout << std::string(50, '=') << std::endl;
        std::cout << "NPU Utilization Monitor" << std::endl;
        std::cout << std::string(50, '=') << std::endl;
        std::cout << "Devices found: " << _deviceCount << std::endl;
        std::cout << std::string(50, '-') << std::endl;

        for (int devId = 0; devId < _deviceCount; devId++) {
            std::cout << "\nDevice " << devId << ":" << std::endl;

            double totalUtil = 0.0;
            int validCores = 0;

            for (int coreId = 0; coreId < CORES_PER_DEVICE; coreId++) {
                double util = getUtilization(devId, coreId);
                int32_t temp = getTemperature(devId, coreId);

                std::cout << "  Core " << coreId << ": ";

                if (util >= 0) {
                    std::cout << std::fixed << std::setprecision(1)
                              << std::setw(5) << util << "%";
                    totalUtil += util;
                    validCores++;
                } else {
                    std::cout << "  N/A";
                }

                if (temp > -999 && temp >= -40 && temp <= 125) {
                    std::cout << "  |  " << std::setw(3) << temp << " C";
                }

                std::cout << std::endl;
            }

            if (validCores > 0) {
                std::cout << "  --------" << std::endl;
                std::cout << "  Average: " << std::fixed << std::setprecision(1)
                          << (totalUtil / validCores) << "%" << std::endl;
            }
        }

        std::cout << std::string(50, '=') << std::endl;
    }

    int runContinuous() {
        std::cout << "Running continuous monitoring (Ctrl+C to stop)..." << std::endl;
        std::cout << "Exit codes: 2 = Usage 0% (10s), 3 = Temp >= 90C (10s)" << std::endl;

        // Track consecutive seconds of error conditions per device/core
        // Max 8 devices * 4 cores = 32 entries
        constexpr int MAX_DEVICES = 8;
        int zeroUtilCount[MAX_DEVICES][CORES_PER_DEVICE] = {};
        int highTempCount[MAX_DEVICES][CORES_PER_DEVICE] = {};

        while (g_running) {
            // Clear screen
            std::cout << "\033[2J\033[H";

            auto now = std::chrono::system_clock::now();
            auto time = std::chrono::system_clock::to_time_t(now);
            std::cout << "Time: " << std::ctime(&time);

            // Read all values first
            double utils[MAX_DEVICES][CORES_PER_DEVICE] = {};
            int32_t temps[MAX_DEVICES][CORES_PER_DEVICE] = {};
            for (int devId = 0; devId < _deviceCount && devId < MAX_DEVICES; devId++) {
                for (int coreId = 0; coreId < CORES_PER_DEVICE; coreId++) {
                    utils[devId][coreId] = getUtilization(devId, coreId);
                    temps[devId][coreId] = getTemperature(devId, coreId);
                }
            }

            // Print compact status line
            for (int devId = 0; devId < _deviceCount && devId < MAX_DEVICES; devId++) {
                std::cout << "Dev" << devId << ": ";
                for (int coreId = 0; coreId < CORES_PER_DEVICE; coreId++) {
                    std::cout << "C" << coreId << "=" << std::fixed << std::setprecision(1)
                              << utils[devId][coreId] << "%/" << temps[devId][coreId] << "C ";
                }
                std::cout << std::endl;
            }
            std::cout << std::endl;

            // Check all cores for error conditions
            for (int devId = 0; devId < _deviceCount && devId < MAX_DEVICES; devId++) {
                for (int coreId = 0; coreId < CORES_PER_DEVICE; coreId++) {
                    double util = utils[devId][coreId];
                    int32_t temp = temps[devId][coreId];

                    // Check for zero utilization
                    if (util >= 0 && util == 0.0) {
                        zeroUtilCount[devId][coreId]++;
                        if (zeroUtilCount[devId][coreId] >= ERROR_THRESHOLD_SEC) {
                            printAllUtilization();
                            std::cerr << "\n[ERROR] Device " << devId << " Core " << coreId
                                      << ": Utilization is 0% for " << ERROR_THRESHOLD_SEC << " seconds" << std::endl;
                            return EXIT_USAGE_ZERO;
                        }
                    } else {
                        zeroUtilCount[devId][coreId] = 0;
                    }

                    // Check for high temperature
                    if (temp >= 90) {
                        highTempCount[devId][coreId]++;
                        if (highTempCount[devId][coreId] >= ERROR_THRESHOLD_SEC) {
                            printAllUtilization();
                            std::cerr << "\n[ERROR] Device " << devId << " Core " << coreId
                                      << ": Temperature is " << temp << "C (>= 90C) for " << ERROR_THRESHOLD_SEC << " seconds" << std::endl;
                            return EXIT_TEMP_HIGH;
                        }
                    } else {
                        highTempCount[devId][coreId] = 0;
                    }
                }
            }

            // Show warning if any condition is counting up
            bool hasWarning = false;
            for (int devId = 0; devId < _deviceCount && devId < MAX_DEVICES; devId++) {
                for (int coreId = 0; coreId < CORES_PER_DEVICE; coreId++) {
                    if (zeroUtilCount[devId][coreId] > 0) {
                        std::cout << "[WARN] Device " << devId << " Core " << coreId
                                  << ": Usage 0% for " << zeroUtilCount[devId][coreId] << "s / " << ERROR_THRESHOLD_SEC << "s" << std::endl;
                        hasWarning = true;
                    }
                    if (highTempCount[devId][coreId] > 0) {
                        std::cout << "[WARN] Device " << devId << " Core " << coreId
                                  << ": Temp >= 90C for " << highTempCount[devId][coreId] << "s / " << ERROR_THRESHOLD_SEC << "s" << std::endl;
                        hasWarning = true;
                    }
                }
            }

            std::this_thread::sleep_for(std::chrono::milliseconds(1000));
        }

        std::cout << "\nMonitoring stopped." << std::endl;
        return EXIT_OK;
    }

private:
    int _deviceCount;
    dxrt::IPCClientWrapper _ipcClient;
};

void printUsage(const char* programName) {
    std::cout << "Usage: " << programName << " [OPTIONS]" << std::endl;
    std::cout << std::endl;
    std::cout << "Options:" << std::endl;
    std::cout << "  -c, --continuous    Run continuous monitoring" << std::endl;
    std::cout << "  -h, --help          Show this help message" << std::endl;
    std::cout << std::endl;
    std::cout << "Exit codes (continuous mode):" << std::endl;
    std::cout << "  0  Normal exit (Ctrl+C)" << std::endl;
    std::cout << "  1  Error" << std::endl;
    std::cout << "  2  Utilization is 0% for 10+ seconds" << std::endl;
    std::cout << "  3  Temperature >= 90C for 10+ seconds" << std::endl;
    std::cout << std::endl;
    std::cout << "Examples:" << std::endl;
    std::cout << "  " << programName << "              # Print utilization once" << std::endl;
    std::cout << "  " << programName << " -c           # Continuous monitoring" << std::endl;
}

int main(int argc, char* argv[]) {
    bool continuous = false;

    // Parse arguments
    for (int i = 1; i < argc; i++) {
        std::string arg = argv[i];

        if (arg == "-h" || arg == "--help") {
            printUsage(argv[0]);
            return 0;
        }
        else if (arg == "-c" || arg == "--continuous") {
            continuous = true;
        }
    }

    // Setup signal handler
    signal(SIGINT, signalHandler);
    signal(SIGTERM, signalHandler);

    try {
        NpuUtilMonitor monitor;

        if (monitor.getDeviceCount() == 0) {
            std::cerr << "No NPU devices found!" << std::endl;
            return 1;
        }

        if (continuous) {
            return monitor.runContinuous();
        } else {
            monitor.printAllUtilization();
        }

    } catch (const std::exception& e) {
        std::cerr << "Error: " << e.what() << std::endl;
        std::cerr << "Make sure dxrt service is running: sudo systemctl status dxrt" << std::endl;
        return 1;
    }

    return 0;
}
