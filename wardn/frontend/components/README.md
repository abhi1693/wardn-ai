# Frontend component architecture

Wardn uses atomic design as an ownership model, not as a requirement to wrap every element.

- `atoms/`: shadcn primitives and single-purpose visual elements. The shadcn CLI writes here.
- `molecules/`: small reusable controls composed from atoms, such as feedback, filters, and selectors.
- `organisms/`: feature-level sections that combine molecules and domain data.
- `templates/`: page chrome and layout contracts. Route files provide data and compose templates.

Import the narrowest component directly from its file. Avoid directory barrels: direct imports keep
client bundles explicit and reduce accidental cross-feature dependencies.
