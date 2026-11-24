# Reproducible Graph Editor examples / 再現可能な作図例

Both suites generate their measurements from fixed seeds and formulas. Run from
the repository root with Noto Sans CJK JP available for Japanese headings.
どちらの作例集も固定シードと数式から合成データを生成します。日本語見出しに使う
Noto Sans CJK JP を用意し、リポジトリのルートで実行してください。

```sh
uv sync --frozen --extra dev --extra mcp
uv run --no-sync python docs/graph_editor_baselines/exploratory-v1/reproducibility/build_suite.py
uv run --no-sync python docs/graph_editor_baselines/solid-state-v2/reproducibility/build_domain_baseline.py
```

- The exploratory suite covers axes, errors, fits, annotations, contours, images,
  insets and layouts. The solid-state suite covers XRD, MPMS, PPMS and related
  transformations through Graph Editor commands.
- 探索用作例は軸・誤差・フィット・注記・等高線・画像・インセット・レイアウトを扱います。
  固体科学の作例は、Graph Editor のコマンドで XRD・MPMS・PPMS の図とデータ変換を再現します。

Results are written under `.test-tmp/graph-editor-baselines/` by default. Use
`--output` to select another local directory. Inspect the manifest and review PDF
alongside the editable graph documents and figures.
構成、検査結果、レビュー用 PDF、再編集用グラフ文書はローカルの出力先に生成されます。
研究データを Git に登録する際の扱いは公開用ルールに従います。
[Publication rules / 公開用ルール](../maintainers/publication_policy.md)
