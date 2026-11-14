#!/usr/bin/env bash
# Build the single-service deploy: FastAPI serves the built frontend.
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

# Python build images do not always ship Node. Install a pinned one when npm is absent.
NODE_VERSION="20.18.1"
if ! command -v npm >/dev/null 2>&1; then
  echo "npm not found; installing Node ${NODE_VERSION}"
  case "$(uname -m)" in
    x86_64|amd64) NODE_ARCH="linux-x64" ;;
    aarch64|arm64) NODE_ARCH="linux-arm64" ;;
    *) NODE_ARCH="linux-x64" ;;
  esac
  curl -fsSL -o /tmp/node.tar.xz "https://nodejs.org/dist/v${NODE_VERSION}/node-v${NODE_VERSION}-${NODE_ARCH}.tar.xz"
  tar -xJf /tmp/node.tar.xz -C /tmp
  export PATH="/tmp/node-v${NODE_VERSION}-${NODE_ARCH}/bin:$PATH"
fi

cd frontend
npm ci
npm run build
cd ..

echo "Build complete: frontend/dist + backend ready"
