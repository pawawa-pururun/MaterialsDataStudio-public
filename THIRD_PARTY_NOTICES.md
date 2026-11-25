# Third-party notices / 第三者ライセンス

MDS application code is MIT licensed. External software, fonts, color maps and
reference datasets retain their original licenses. / MDS自作部分はMITですが、外部ソフト・フォント・色表・参照データには元の条件が適用されます。

The Windows distribution includes Qt/PySide6/shiboken6 under the LGPLv3 option
for its shipped modules, igor2 under LGPL-3.0-or-later, MPL-covered Gemmi,
certifi, orjson and tqdm components, as well as BSD/MIT/PSF and other components.
Complete collected notices and version metadata are under `_internal/licenses/`.
This includes NumPy/SciPy bundled numerical-library notices and upstream Qt
third-party notices. Build-tool licenses may be included for completeness.

Native Linux and macOS packages use the same corresponding-source and notice
collection. The psutil BSD-3-Clause license is included in
`resources/licenses/psutil/LICENSE`. The optional source-installed Graph Editor
MCP tools use dependencies under their own licenses, including the MIT-licensed
MCP Python SDK and BSD-3-Clause-licensed pypdf.

Windows版にはQt/PySide6/shiboken6（配布モジュールはLGPLv3を選択）、igor2（LGPL-3.0-or-later）、
MPL対象のGemmi・certifi・orjson・tqdmの部品などを含みます。版と収集した告知本文は
`_internal/licenses/` に収録します。NumPy/SciPyの数値ライブラリ、Qtの第三者部品も対象です。

Linux・macOSのパッケージでも対応ソースと告知を確認します。psutilのBSD-3-Clause
ライセンスは `resources/licenses/psutil/LICENSE` に収録します。ソース版の任意機能
Graph Editor MCP が使う MCP Python SDK と pypdf などには、各ライセンスが適用されます。

No MDS term restricts LGPL modification/relinking or reverse engineering needed
to debug such modifications. Corresponding source archives and MDS application
source are distributed with release binaries. / LGPLに基づく改変・再結合と、そのデバッグに必要なリバースエンジニアリングを禁止しません。対応ソースはReleaseのバイナリと併せて提供します。

See [English rights/source/build instructions](docs/building_and_licenses.md) /
[日本語の権利・ソース・再ビルド手順](docs/building_and_licenses_ja.md).

Velopack is MIT licensed; its upstream license remains in `resources/licenses/velopack/LICENSE`.
PyInstaller's bootloader exception permits distribution of the frozen application
under its chosen license, while dependencies retain their own conditions.

Reference databases are optional, separate downloads, not included in the
application's MIT license. See [English](docs/reference_databases.md) /
[日本語](docs/reference_databases_ja.md). Igor Pro and Quantum Design product
names identify compatibility targets; no endorsement or trademark license is implied.
