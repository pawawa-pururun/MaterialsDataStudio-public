---
name: materials-solid-state-figures
description: Create and verify editable Materials Data Studio Graph Editor figures from MPMS, PPMS, and other solid-state measurements. Use for ZFC/FC and M–H, susceptibility, resistivity, heat capacity, MR, Hall, carrier transport, spectra, bands/DOS, phonons, Nyquist, XPS and Tauc plots, and titled PDF collections of these figures.
---

# 固体物性・固体科学の作図

`materials-data-studio` MCPの `inspect_input`、`create_figure`、`inspect_document` を使う。XRDは `materials-xrd-figures` を使う。入出力と例は [作図ガイド](../../../docs/graph_mcp/README_ja.md) にある。

1. CSV・TSVには `kind: table`、Quantum Designの `[Data]` 付きテキストには `kind: quantum_design` を指定して列名を読む。区間の判断に必要な場合は `preview` で選んだ列の数行を読む。`columns` に元の列と確認済みの単位を指定する。ZFC/FC・掃引方向・PPMSの磁場条件が同一ファイルにある場合は、確定した範囲を各列の `rows: [start, stop]` に渡す。
2. 利用者が指定した量に変換する。質量・式量・形状・±Hの対応・誤差の定義が必要で、依頼とデータのどちらにも十分な根拠がなければ確認する。回帰曲線・ピーク成分・計算線は利用者が提供した配列を明示して描く。

| 図 | 変換と確認 |
| --- | --- |
| MPMS ZFC/FC・逆磁化率 | `molar_susceptibility` に moment (emu)、field (Oe)、試料質量 (mg)、式量 (g/mol) を渡す。C–W表示は明示された背景を `scale.offset` で引き、`power: -1` で逆数にする。 |
| MPMS M–H | 掃引順を保って描く。真空換算の μ₀H を表示する場合は Oe → T に 10⁻⁴ を使う。μB/f.u. にする場合は試料モル数と 5585.6947 emu/mol を使う。拡大範囲は `insets` の軸に指定する。 |
| PPMS ρ–T・Cp | 抵抗を使う場合は `resistivity` に幅・厚さ・電圧端子間距離をcmで指定する。µJ/K → J/(mol K) は `molar_cp`。Cp/T–T²では絶対温度でCpとσを割り、Tを二乗する。誤差棒は変換したσのwaveを `error_y` に指定する。 |
| MR・Hall | `magnetoresistance` は各掃引で一意の正のR(0)を使う。`hall_antisymmetrize` は同じ単位のHと−Hを行ごとに照合し、順に (raw(H)−raw(−H))/2 を計算する。 |
| Arrhenius・VRH・Tauc | `ln` の `reference` に対数の無次元化基準を入力する。指数、活性化モデル、遷移種は確認済みの前提を使い、`provenance` に記録する。Taucはαとhνを `multiply` し、指定指数を `power` で適用する。 |
| バンド／DOS・フォノン | `ticks` に高対称点、`guides` にエネルギーまたは周波数の基準値を指定する。バンド＋DOSは `layout: horizontal` と `share_axis: y` で両パネルのエネルギー範囲をそろえる。 |
| Raman・XPS・Nyquist | Ramanの条件別縦積みは `offset_y`。XPSは結合エネルギーを `reverse: true` にし、成分・背景・全モデル・残差を区別する。Nyquistは Re Z と −Im Z を明示し、`equal_units: true` を設定する。 |

3. `plot.kind: xy`、軸ラベルと単位、色・線種、凡例、確認済みの測定条件を構成する。図中の補足条件は `legend_notes` にまとめる。Insetには拡大範囲と軸ラベルを指定する。個別図のタイトルは省く。
4. `create_figure` の `validate_only` を通し、不明の条件はフィールドを示して質問する。保存後は `inspect_document` で元データ・計算列・誤差棒と図の状態を読み返し、PNGで凡例と曲線の位置を見比べる。
5. 一覧PDFの依頼があれば `create_review_pdf` に個別PDFのパスと各ページのタイトルを渡す。個別出力と一覧の保存先を案内する。
