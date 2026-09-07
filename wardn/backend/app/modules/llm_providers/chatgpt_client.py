"""Client identity shared by ChatGPT discovery and execution requests."""

import os
import platform

DEFAULT_CODEX_COMPAT_VERSION = "0.144.0"
CODEX_COMPAT_VERSION = os.getenv("WARDN_CODEX_COMPAT_VERSION", DEFAULT_CODEX_COMPAT_VERSION)
CODEX_COMPAT_ORIGINATOR = "codex_cli_rs"
CODEX_COMPAT_USER_AGENT = (
    f"{CODEX_COMPAT_ORIGINATOR}/{CODEX_COMPAT_VERSION} "
    f"({platform.system()} {platform.release()}; {platform.machine()}) wardn"
)
