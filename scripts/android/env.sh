#!/usr/bin/env bash
# Source explicitly per command; nothing is added to a shell profile.
AIOA_ANDROID_SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd -P)"
if ! python3 -B "$AIOA_ANDROID_SCRIPT_DIR/toolchain_doctor.py" --json --require-installed; then
  return 2 2>/dev/null || exit 2
fi
export ANDROID_HOME=/media/l/LSC_DATA3/AIOA_ANDROID_TOOLCHAIN/sdk
export ANDROID_SDK_ROOT="$ANDROID_HOME"
export JAVA_HOME=/media/l/LSC_DATA3/AIOA_ANDROID_TOOLCHAIN/jdk-17
export GRADLE_USER_HOME=/media/l/LSC_DATA3/AIOA_ANDROID_TOOLCHAIN/gradle-cache
export ANDROID_USER_HOME="$ANDROID_HOME/.user"
export TMPDIR=/media/l/LSC_DATA3/AIOA_ANDROID_TOOLCHAIN/downloads/.tmp
export PATH="$JAVA_HOME/bin:$PATH"
