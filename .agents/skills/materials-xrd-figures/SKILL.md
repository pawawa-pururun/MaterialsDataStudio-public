---
name: materials-xrd-figures
description: Create and check title-free powder XRD figures in Materials Data Studio Graph Editor from experimental diffraction scans, supplied reference peak tables or CIFs, calculated profiles, and temperature or pressure series. Use for stacked XRD, ICSD or parent-structure comparisons, Rietveld display, and condition maps.
---

# XRD作図

`materials-data-studio` MCPの `inspect_input`、`create_figure`、`inspect_document` を使う。起動手順とリクエスト例は [作図ガイド](../../../docs/graph_mcp/README_ja.md) にある。

1. 各ファイルの列を `inspect_input` で確認する。2θの単位、条件名と並び、実測・計算・参照の区別を特定する。列や測定条件を特定できなければ、どのファイルのどの情報が必要かを質問して確定する。
2. 次のいずれかの `recipe.plot` を構成する。

| 依頼 | 指定 |
| --- | --- |
| 通常XRD | `xrd_stack`。実測スキャンを下から上の順で `scans` に並べ、条件ラベルを付ける。指定された場合に `offsets` や `normalization: peak100` を使う。 |
| ICSD・母構造との比較 | `xrd_stack.references`。各参照に相名を付け、2θと相対強度の表、またはCIFと測定時の `wavelength_angstrom` を渡す。ICSD番号だけが与えられた場合は、参照CIFかピーク表の提供を依頼する。 |
| リートベルト形式 | `xrd_rietveld`。計算済みプロファイルと観測を同じ2θグリッド・単位で指定する。使用した相ごとにBragg位置表またはCIFを `phases` に渡す。観測−計算を元の強度縮尺で確かめる。 |
| 温度・圧力変化 | `xrd_map`。条件値と単位を明記し、条件別スキャン、長形式、または配列順序付きの行列から選ぶ。角度の差が許容差を超えたら、使用する共通グリッドを利用者に確認する。規格化が指定された場合は全系列共通の基準を確認する。 |

3. 波長、角度単位、相名、規格化条件がデータや依頼から確定しなければ、該当の値を質問する。CIF計算は明示された単一波長で行う。プロファイルに装置関数や二重線の指定がある場合は、対応する計算済みプロファイルまたはピーク表を選ぶ。
4. `create_figure` を `validate_only: true` で実行し、エラーの `field` を確認する。確認が済んだら新規の出力ディレクトリに保存する。
5. 保存済みMDSGを読み返し、PNGを確認する。2θの大目盛りは10°、小目盛りは2°で数字なし。通常XRDの縦軸は `Intensity / arb. units` で目盛りなし。条件別縦積みの凡例は描画範囲内の右上にまとめ、曲線に重ねない。参照ストリップは実測の下に相ごとに置く。リートベルト形式は観測＋計算、相別の位置、残差の順。条件マップは横2θ、縦に条件・単位、青から赤に強度を表示する。
6. すべての個別図にタイトルは付けない。依頼された一覧のページタイトルは `create_review_pdf` の `pages[].title` にだけ渡す。保存パスと、確認した波長・規格化・条件を利用者に伝える。
