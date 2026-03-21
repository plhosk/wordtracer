#!/usr/bin/env bash
set -euo pipefail

MODE="${1:-}"

if [[ -z "${MODE}" ]]; then
  echo "usage: bash scripts/ci_fdroid_parity.sh <parity|release-candidate>" >&2
  exit 2
fi

if [[ "${MODE}" != "parity" && "${MODE}" != "release-candidate" ]]; then
  echo "invalid mode: ${MODE}" >&2
  exit 2
fi

if [[ -z "${RELEASE_REF:-}" ]]; then
  echo "RELEASE_REF is required" >&2
  exit 2
fi

if [[ -z "${ANDROID_SDK_ROOT:-}" ]]; then
  echo "ANDROID_SDK_ROOT is required" >&2
  exit 2
fi

if [[ -z "${ANDROID_BUILD_TOOLS:-}" ]]; then
  echo "ANDROID_BUILD_TOOLS is required" >&2
  exit 2
fi

apt-get update
apt-get install -y --no-install-recommends ca-certificates curl git python3 python3-pip default-jdk-headless unzip nodejs npm

fdroidserver=/opt/fdroidserver
mkdir -p "${fdroidserver}"
curl --silent --show-error --location https://gitlab.com/fdroid/fdroidserver/-/archive/master/fdroidserver-master.tar.gz | tar -xz --directory="${fdroidserver}" --strip-components=1
python3 -m pip install --break-system-packages --upgrade -e "${fdroidserver}"

if [[ -e .git ]]; then
  mv .git /tmp/workspace-git
  trap 'mv /tmp/workspace-git .git' EXIT
fi

mkdir -p build
rm -rf build/com.wordtracer.app
git clone --quiet --branch "${RELEASE_REF}" --depth 1 https://github.com/plhosk/wordtracer build/com.wordtracer.app

mkdir -p config
cat > config/categories.yml << "EOF"
Games:
  name: Games
EOF

cat > config.yml << "EOF"
sdk_path: /opt/android-sdk
gradle: /workspace/build/com.wordtracer.app/android/gradlew
EOF

export PATH="${ANDROID_SDK_ROOT}/build-tools/${ANDROID_BUILD_TOOLS}:$PATH"

python3 --version
"${fdroidserver}/fdroid" --version
java -version
node --version
npm --version
apksigner version

if [[ "${MODE}" == "parity" ]]; then
  "${fdroidserver}/fdroid" lint com.wordtracer.app
  "${fdroidserver}/fdroid" build -v -l --stop --test com.wordtracer.app
else
  "${fdroidserver}/fdroid" build -v -l --stop com.wordtracer.app
fi
