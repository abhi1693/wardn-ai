#!/usr/bin/env bash
set -euo pipefail
npm run backend:lint
npm run backend:typecheck
