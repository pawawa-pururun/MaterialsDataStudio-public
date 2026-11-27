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

CI rebuilds both suites from the same inputs and compares graph state and rendered
pixels within each runner, including after saving and reopening the editable
documents. It also compares PNG pixels from two exports of each public MCP recipe.
CI は同じ入力から両方の作例集を再生成し、各ランナー内でグラフの状態と描画の画素を
比較します。編集用文書の保存・再読み込み後も検証し、公開 MCP レシピごとに
2 回書き出した PNG の画素が一致することを確認します。

```sh
uv run --no-sync pytest -q tests/tools/test_graph_examples.py tests/graph_mcp/test_graph_mcp.py
```

Results are written under `.test-tmp/graph-editor-baselines/` by default. Use
`--output` to select another local directory. Inspect the manifest and review PDF
alongside the editable graph documents and figures.
構成、検査結果、レビュー用 PDF、再編集用グラフ文書はローカルの出力先に生成されます。
研究データを Git に登録する際の扱いは公開用ルールに従います。
[Publication rules / 公開用ルール](../maintainers/publication_policy.md)
