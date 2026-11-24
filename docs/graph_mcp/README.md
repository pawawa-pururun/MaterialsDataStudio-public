# Graph Editor MCP

The optional local MCP server reads experiment files and produces editable
Graph Editor documents plus PNG, SVG or PDF figures. Its manifest records the
selected columns, units, requested transformations and graph identifiers.

```sh
uv --directory "<checkout>" sync --frozen --extra mcp
codex mcp add materials-data-studio -- uv --directory "<checkout>" run --frozen --extra mcp materials-data-studio-mcp --workspace "<experiment-folder>"
```

Use absolute paths for the checkout and experiment folder. Files are read and written
inside the experiment folder. Supply a new output directory for each figure recipe.

| Tool | Purpose |
| --- | --- |
| `inspect_input` | Inspect column names, row counts and optional preview values. |
| `create_figure` | Generate a figure and document, or validate a recipe with `validate_only`. |
| `inspect_document` | Inspect graphs, axes, traces and the values of saved waves. |
| `create_review_pdf` | Combine single-figure PDFs into pages with headings and bookmarks. |

Recipes support stacked XRD, Rietveld plots with supplied calculated profiles,
XRD condition maps, and XY plots. Adapt the paths, column names and units in the
[XRD](examples/xrd-stack.json), [MPMS](examples/mpms-zfc-fc.json) and
[PPMS](examples/ppms-cp.json) examples to your workspace.
For Japanese review headings, install a font with the required glyphs such as
Noto Sans CJK JP. The [reproducible Graph Editor examples](../graph_editor_baselines/README.md)
generate the example inputs locally from fixed seeds and formulas. To run the
JSON recipes as written, generate the solid-state suite and use the checkout
root as the MCP workspace.

See the [Japanese guide](README_ja.md) for full recipe fields. Codex can also
use the [XRD](../../.agents/skills/materials-xrd-figures/SKILL.md) and
[solid-state figure](../../.agents/skills/materials-solid-state-figures/SKILL.md) skills.
