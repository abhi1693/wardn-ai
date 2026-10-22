#!/usr/bin/env bash
set -euo pipefail
npm run test:dependency-security
npm --workspace wardn/frontend run bundle:validate
