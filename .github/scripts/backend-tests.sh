#!/usr/bin/env bash
set -euo pipefail
npm run backend:test:unit
npm run backend:test:integration
