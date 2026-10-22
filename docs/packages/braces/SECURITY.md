# Bounded brace parsing

This is a private, MIT-licensed copy of `braces@3.0.3` from the npm registry,
whose license and implementation are retained. The npm override applies it to
all transitive consumers, including micromatch, Next.js linting, and shadcn.

[CVE-2026-93687](https://github.com/advisories/GHSA-vfj7-8cjw-p6xm) has no patched
upstream release as of 2026-10-23. This copy adds a fixed maximum AST depth of 100
to brace and parenthesis parsing and to the compile, expand, and stringify
walkers. Excessive depth raises a controlled `SyntaxError` before stack
exhaustion. The existing input-length and expansion-range limits remain.
The limit cannot be disabled through user options. AST walker guards also cover
deep or cyclic caller-supplied nodes.

`npm run test:dependency-security` checks malicious patterns below the upstream
character cap, supplied ASTs, ordinary matching, and range behavior.
The frontend dependency Docker stage copies this package before `npm ci`.
No advisory is suppressed and the audit severity threshold is unchanged.

Replace this override with an audited upstream release once the depth fix is
published. Keep the regression tests when removing the local copy.

Provenance: retained from the existing audited `@devfeed/braces` private fork
in DevFeed, including its upstream MIT license and five regression tests.
