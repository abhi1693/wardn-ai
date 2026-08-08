# Wardn AI Documentation

This directory contains the public Wardn AI documentation site. It follows the
same documentation-as-code model used by the current Rancher product docs:
Antora builds versioned AsciiDoc content into a static website.

## Local Build

Install dependencies from this directory:

```bash
cd docs
npm ci
```

Build the site:

```bash
npm run build
```

Preview the generated static site:

```bash
npm run preview
```

The preview server serves `build/site` on `http://127.0.0.1:8081`.

## Content Layout

```text
site/latest/
  antora.yml
  modules/ROOT/nav.adoc
  modules/ROOT/pages/
  modules/ROOT/attachments/openapi/
```

When adding a page, place it under `site/latest/modules/ROOT/pages/` and add it
to `site/latest/modules/ROOT/nav.adoc`. Prefer stable page paths and explicit
section anchors so external links remain durable.

## OpenAPI Reference

The API reference links to the generated FastAPI OpenAPI document. Refresh the
attached copy after regenerating the app client:

```bash
npm run sync:openapi
```

From the repository root, the equivalent command is:

```bash
npm run docs:sync:openapi
```

## Publishing Model

The Antora output in `docs/build/site` is static HTML. It can be published as a
standalone public docs site such as `https://docs.wardn.ai`, or mounted under a
main web domain such as `https://wardn.ai/docs`.

