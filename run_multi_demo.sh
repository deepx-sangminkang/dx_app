#!/bin/bash
SCRIPT_DIR=$(realpath "$(dirname "$0")")
DX_APP_PATH="/home/sangminkang/workspace/dx_app2"

# color env settings
source "${DX_APP_PATH}/scripts/color_env.sh"
source "${DX_APP_PATH}/scripts/common_util.sh"

pushd $DX_APP_PATH

echo "[INFO] DX_APP_PATH: $DX_APP_PATH" "INFO"

# Check if bin directory exists and contains files
if [ ! -d "./bin" ] || [ -z "$(ls -A ./bin 2>/dev/null)" ]; then
    echo "[INFO] dx_app is not built. Building dx_app first before running the demo."
    ./build.sh
fi

check_valid_dir_or_symlink() {
    local path="$1"
    if [ -d "$path" ] || { [ -L "$path" ] && [ -d "$(readlink -f "$path")" ]; }; then
        return 0
    else
        return 1
    fi
}

if check_valid_dir_or_symlink "./assets/models" && check_valid_dir_or_symlink "./assets/videos"; then
    echo "[INFO] Models and Videos directory already exists. Skipping download."
else
    echo "[INFO] Models and Videos not found. Downloading now via setup.sh..."
    ./setup.sh --force
fi

WRC=$DX_APP_PATH

$WRC/bin/yolo_multi -c example/yolo_multi/ppu_yolo_multi_demo.json "$@"

popd
