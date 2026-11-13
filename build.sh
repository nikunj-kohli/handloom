#!/usr/bin/env bash
# Build the single-service deploy: FastAPI serves the built frontend.
set -euo pipefail

python -m pip install --upgrade pip
python -m pip install -r requirements.txt

cd frontend
npm ci
npm run build
cd ..

echo "Build complete: frontend/dist + backend ready"
