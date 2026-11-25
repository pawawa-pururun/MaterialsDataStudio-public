# Graph Editor MCPとskills

ローカルの実験ファイルを読み、Graph Editorで再編集できる `.mdsg` と、タイトルを省いた PNG・SVG・PDF を作成します。`manifest.json` に列対応、元の単位、明示された計算、図とwaveの識別子を保存します。完成済みの個別PDFは、別のツールでタイトル・しおり付き一覧にまとめられます。

## 起動

Pythonとuvを用意します。`<repo>` はこのブランチのチェックアウト、`<experiment-root>` は実験ファイルと出力を置く既存のローカルフォルダの絶対パスです。

```sh
uv --directory "<repo>" sync --frozen --extra mcp
codex mcp add materials-data-studio -- uv --directory "<repo>" run --frozen --extra mcp materials-data-studio-mcp --workspace "<experiment-root>"
```

Codexでこのリポジトリを開くと [XRD用skill](../../.agents/skills/materials-xrd-figures/SKILL.md) と [固体物性・固体科学用skill](../../.agents/skills/materials-solid-state-figures/SKILL.md) を利用できます。別のプロジェクトで使う場合はskillフォルダをそのプロジェクトの `.agents/skills/` に配置します。ほかのMCPクライアントでも、登録したものと同じコマンドをstdioサーバーとして起動できます。

読み書き先は `--workspace` の配下です。入力はルートからの相対パスか、その配下を指す絶対パスで指定します。完成図用ディレクトリは新規名を指定します。その親ディレクトリは先に用意してください。図と文書は一式が完成した時点で公開され、同名を指定すると `output_exists` を返します。

## 依頼の例

> `scan_700.csv`、`scan_800.csv`、`scan_900.csv` の2θと強度を、焼鈍温度700・800・900 Kの順で縦積みしてください。`parent.cif` をCu Kα₁の1.5406 Åで計算し、実測の下に相対強度付きの母構造ピークを置いてください。個別図はタイトルを省き、`review.pdf` のページには「焼鈍温度別XRD」と付けてください。

> MPMSの `zfc.dat` と `fc.dat` を、各ファイルの Temperature、Magnetic Field、Long Moment の列から作図してください。試料10 mg、式量100 g/molでモル磁化率に変換し、2系列を重ねてください。

> PPMSの `cp.dat` からCp/T対T²を描いてください。試料5 mg、式量100 g/molです。試料比熱と1σの誤差列を同じ単位で換算し、誤差棒を付けてください。

## MCPツール

| ツール | 入力と結果 |
| --- | --- |
| `inspect_input` | `source` の列名、ゼロ始まりの列番号、行数を取得します。`preview: {columns: [0, 2], start: 0, count: 5}` で指定列の数行を取得できます。 |
| `create_figure` | `recipe`、新規の `output_dir`、任意の `formats` と `dpi` を指定します。`validate_only: true` で入力・単位・図の構成を検証できます。 |
| `inspect_document` | `.mdsg` の `path` と任意の `graph` 名を渡し、軸・系列・レイアウト・waveを取得します。`wave` に `root:` で始まるパスかIDを渡すと、`start` から `count` 個の保存値を確認できます。画像行列はC順で返ります。 |
| `create_review_pdf` | `output_pdf` と `pages: [{pdf, title}, …]` を渡します。ページ上部にタイトルを書き、同じ名前でしおりを設定します。日本語のページタイトルにはNoto Sans CJK JP、游ゴシック等の字形を収録したフォントを使います。 |

ツールの `structuredContent` で成功時は `ok: true`、入力不足などのエラー時は `ok: false` と `errors[].code`、`field`、`message` を返します。

## 入力と出力の対応

`recipe.sources` はCSV／TSV、区切りテキスト、Quantum Designの `[Data]` 付きテキスト、Rigaku RASX（`Data0/Profile0.txt`）を参照します。`kind` は順に `table`、`quantum_design`、`rasx`。見出しの無い表は `header: false` とし、必要に応じて `delimiter: Whitespace` や `first_record`（1始まり）を指定します。`recipe.columns` の名前が文書内のwave名になります。各列に `source`、正確な列名かゼロ始まりの `column`、確認済みの `unit` を指定します。`rows: [start, stop]` でデータ行の半開区間を選べます。既知の欠損は `missing: gap` で描画上の切れ目として保持します。

`recipe.transforms` は上から順に実行します。元の列は変換後のwaveと一緒に保存されます。`scale` は係数・オフセット、`power` は指数、`ln` は入力と同じ単位の正の基準値を取ります。`add`、`subtract`、`multiply`、`divide` は指定したwave同士を行順で対応させます。`resistivity`、`molar_cp`、`molar_susceptibility`、`magnetoresistance`、`hall_antisymmetrize` は各分野の値と単位を検査します。

| `plot.kind` | 出力する図 |
| --- | --- |
| `xrd_stack` | 条件順の縦積み、色別の凡例、縦目盛りなし。`references` に相対強度付きのピーク表または単一波長を指定したCIFを渡すと、実測の下に参照ストリップが加わります。 |
| `xrd_rietveld` | 実測と計算済み曲線、相別Bragg位置、観測−計算の残差。上下の強度縮尺は共通です。計算プロファイルは精密化済みの出力から指定します。 |
| `xrd_map` | 条件別 `scans`、`long_table`、または `flat_matrix` から作る2θ×温度／圧力マップ。色は青（弱）から赤（強）。全体最大値での規格化は `normalization: global_max` で明示します。 |
| `xy` | 変換前後の物性データや提示済みモデルの線・点・棒、Y誤差棒、条件別オフセット、反転軸、対数軸、文字目盛、ガイド線、inset、水平／垂直パネル。 |

`xy` の `plot_width_pt` と `plot_height_pt` でパネル内の描画寸法を調整できます。垂直配置では幅、水平配置では高さを各パネルでそろえます。`share_axis` を使うときは対象軸の範囲・向き・尺度を同じ値で指定します。垂直の共有X軸は最下段にラベルを表示します。

XRDの `angle_limits_deg` を省略したときは実測範囲を使います。ピーク表を使う場合は `kind: peaks` とし、`angles` と必要に応じて `intensity` にwave名を渡します。CIF参照は `kind: cif` とし、`path` と `wavelength_angstrom` を明示します。ICSDの検索や精密化結果の作成が必要な場合は、作図用の参照CIF・ピーク表・計算プロファイルを事前に用意します。各条件の角度グリッドが異なるマップでは、使用するグリッドと再サンプリングを確認し、そろえた入力を使います。

合成データを使った [基準作例の生成手順](../graph_editor_baselines/README.md) とMCPの入力例を用意しています。各JSONの入力パスと列を作業フォルダ内のファイルに合わせて、`create_figure` の引数に使えます。
固体科学の作例を既定の出力先に生成し、チェックアウトのルートを `--workspace` にすると、JSONの合成入力をそのまま使えます。

- 3条件の縦積み [XRD](examples/xrd-stack.json)
- 物性換算と条件別系列 [MPMS ZFC/FC](examples/mpms-zfc-fc.json)
- 物性換算と誤差棒 [PPMS Cp/T–T²](examples/ppms-cp.json)
