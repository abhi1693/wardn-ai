# Repository automation

Common CI and image mechanics are maintained in [abhi1693/actions](https://github.com/abhi1693/actions).
Workflows use the released `@v1` reference for centrally maintained compatible updates.
See the [shared release history](https://github.com/abhi1693/actions/releases) for changes.
Repository-owned scripts, triggers, scanner exceptions and application smoke checks
remain alongside the application. Image manifests declare components rather than
copying workflow steps.

Runtime images pin current Alpine bases and apply available package security fixes.
The frontend omits npm and Yarn; the worker and MCP runtime retain patched npm
for their installation duties. Python native extensions and the MCP Node, Python
and Deno commands are checked locally, and CI runs Compose smoke tests plus the
shared native image scan gate before publication. WhatsApp bridge builds retain
the pinned upstream source and update its vulnerable Go modules explicitly.
