# Linux・macOS対応とネイティブビルド

この実装は、共通の解析・グラフ編集・セッション保存・データ／図の出力を
Linux、Apple Silicon macOSで利用するためのものです。Windows版のローカルビルド経路は維持します。

## 対応範囲

| 対象 | 配布形式・ビルド環境 |
| --- | --- |
| Windows 10/11 x64 | Velopack Setup.exe。公開版の Windows 用ビルド手順を使用 |
| Linux x86_64 | tar.gz。自動テストはUbuntu 26.04、配布ビルドはUbuntu 22.04 |
| macOS Apple Silicon | DMG。テスト／ビルドは最新arm64ランナーの手動実行のみ |

Pythonは3.12を基本とします。固定されたQtのwheelはmacOS 13以降、Linux x86_64では
glibc 2.34以降を要求します。実際の配布物にはビルド環境と収録バイナリの要件も適用されます。
Linuxの配布ビルドは古いLinuxとの互換性のためUbuntu 22.04／glibc 2.35を維持し、
テストだけを最新OSへ更新します。Macの手動テスト／ビルドは`macos-latest`を使用し、
現在はmacOS 26 arm64です。配布物のdeployment target設定は15.0を維持します。
古いOSで使う場合は、そのOSに対応した依存一式を使ってネイティブに再ビルド・検証してください。
Intel Mac、Linux ARM、Alpine/musl、Windows ARMは対応対象に含めません。

**Python Procedureの実行はWindowsのみです。** Linux/macOSではRunボタンを無効にし、
実行入口も拒否します。ソースの表示・編集・変換、Command Windowの既存の制限付きコマンド、
通常の解析は利用できます。OSの隔離を外してPythonを実行する代替経路は設けません。
Linux向けnamespaces/seccomp等やmacOS向け隔離ヘルパーの実装は別の対応です。

## 配布版の使用

Linuxはtar.gzを展開し、フォルダ一式を保ったまま`./MaterialsDataStudio`を実行します。
最小構成のUbuntuでは、GUI実行に必要なライブラリを事前に導入します。

```sh
sudo apt-get install libegl1 libopengl0 libxkbcommon-x11-0 libxcb-cursor0
```

アプリランチャーと`.mdss`・`.mdsg`の関連付けを追加する場合は、展開先で次を実行します。

```sh
./MaterialsDataStudio --register-file-types
```

PreferencesのApplicationsタブからも登録できます。登録はユーザー単位で、既存の既定アプリは
変更しません。登録後はファイルマネージャーの「別のアプリで開く」でMDSを選択できます。
登録後に展開フォルダを移動した場合は、新しい場所で再登録してください。

macOSではApple Silicon用DMGから`.app`をApplicationsにコピーします。Finderからの
文書オープンは起動前・起動後の両方で受け付けます。署名・公証を設定していないCI成果物は
開発検証用です。一般向けの配布には下記のDeveloper ID署名・公証を行ってください。

Windowsで作成したセッションも再保存できます。元データのパスは来歴として保持し、
ZIP内のファイル名だけをOSに依存しない名前にします。

## ソースからの実行

```sh
uv sync --frozen --extra dev
uv run python -m materials_data_studio
uv run pytest
uv run ruff check .
uv run pyright
uv run pyright --project pyright-tests.json
```

MacはApple SiliconのネイティブPythonを使用します。Intel MacとRosetta上のx86_64
Pythonは対象外です。CIではApple Silicon向けwheelを利用し、Intel向けのソースビルド用
Homebrew/OpenMP準備は行いません。

Qtは6.11.2以降が必要です。Qt 6.11.1にはmacOS 27.2でカーソルや画像の変換時に
クラッシュする[QTBUG-147602](https://github.com/qt/qtbase/commit/08e464f8559719662c5b2207d1d4c84c251eca07)
があり、ToolsからGraph Editorを開いた際にも発生します。`uv sync --frozen --extra dev`で
修正版を導入してください。ビルド開始時に実際のQt／PySide6バージョンを表示し、古いQtは拒否します。

凍結版はフォントキャッシュを再起動後も再利用します。Macでは
`~/Library/Caches/org.kageyamalab.MaterialsDataStudio/matplotlib/system-fonts`、Linuxでは
`$XDG_CACHE_HOME/org.kageyamalab.MaterialsDataStudio/matplotlib/system-fonts`
（未設定なら`~/.cache`配下）を使用します。最初の1回はフォント走査に時間がかかる場合があります。
Graph Editorは解析を使う時点でSciPyの解析機能を読み込みます。Toolsの起動所要時間は
アプリの診断ログと`native-gui-smoke.txt`に記録します。

マーカー・線種・カラーマップの標準プレビュー224種類は、通常／Retina解像度の画像として
`resources/previews`に同梱します。標準プレビューを実行時に描き直す必要はありません。
独自の線種・パレットと、画像が利用できない場合には従来の描画経路を使用します。
生成元・Matplotlibの固定バージョン・画像のハッシュを検証し、変更があればネイティブビルド時に
再生成します。ソース変更後やwheel作成前に手動で再生成する場合は次を実行します。

```sh
uv run python scripts/render_graph_previews.py
uv run python scripts/render_graph_previews.py --check
```

wheelにはアイコン、ライセンス通知、日英の本体／Graph Viewerマニュアルと参照画像を収録します。
カレントディレクトリやソースチェックアウトに依存せず参照できます。

## Linux・macOS配布物の作成

対象OS・CPU上で実行します。Windowsで作った実行ファイルを変換する工程はありません。

```sh
uv sync --frozen --extra dev
uv run python scripts/build_desktop.py
```

ビルドは対応する公式ソースを SHA-256 で検証し、依存ライブラリの告知を収録します。
配布する場合は、同じ版のアプリケーションソースと対応ソースを併せて提供します。
[ライセンス・対応ソースの案内](building_and_licenses_ja.md)

ビルド先は`.test-tmp/desktop-build`、成果物は`release_assets`です。
ビルドは実際の凍結アプリで解析・グラフ出力・オフライン参照DB・保存のスモークテストを実行し、
Procedureが無効であることも検証します。成功した場合だけ配布物とSHA-256ファイルを作成します。
macOSではさらにCocoa上でToolsを順番に開き、Graph Editorの描画とカーソル変換を検証します。
この検査にはログイン済みのGUIセッションが必要です。`native-gui-smoke.txt`に収録Qtの
バージョン、進捗とクラッシュ時のスタックを残し、失敗した場合はDMGを作成しません。
出力先は`--work`と`--output`で変更できます。
ビルド検査は`MDS_MATPLOTLIB_CACHE_DIRECTORY`で作業ディレクトリ内のキャッシュを指定し、
ユーザーの通常キャッシュを変更しません。この指定なしで検査モードだけを手動実行する場合は一時キャッシュを使います。

ローカルビルドは検査後に完成したアプリの`--prepare-runtime-cache`を実行し、その端末の
ユーザーフォントキャッシュを初回GUI起動前に準備します。結果は`user-cache-preparation.txt`に保存します。
CIではこの工程を省略し、端末固有のキャッシュを配布物へ混入させません。
`--no-prepare-user-cache`で準備を省略でき、`--prepare-user-cache`で明示実行できます。
準備できない場合も配布物は作成し、アプリ側で必要時にキャッシュを作成します。
ダウンロードしたアプリでも、GUIを開かずにその端末のキャッシュを準備できます。

```sh
"/Applications/Materials Data Studio.app/Contents/MacOS/MaterialsDataStudio" --prepare-runtime-cache /tmp/mds-cache-preparation.txt
```

MPのデータ・検索索引は必要になる検索時に扱う方針を維持し、ビルドや登録に一括生成を追加しません。

同じバージョンを再ビルドした場合は、古いDMGを取り出してから新しいDMGを開き、
新しい`.app`をApplicationsへコピーしてください。マウント中の古いDMG内のアプリは更新されません。

macOSで署名する場合は、Developer ID証明書をキーチェーンに用意してから設定します。

```sh
export MDS_MAC_SIGN_IDENTITY='Developer ID Application: Your Organization (TEAMID)'
export MACOSX_DEPLOYMENT_TARGET=15.0
uv run python scripts/build_desktop.py --notary-profile your-notarytool-profile
```

`--notary-profile`は事前に`xcrun notarytool store-credentials`で作成したプロファイルです。
アプリの検証、公証・チケットの添付、DMGの作成・署名・公証を経てからチェックサムを作成します。
署名を設定せずにビルドした場合は、開発用の署名状態のままになります。

## CI と配布ビルド

プルリクエストでは Windows の Python 3.12・3.14 と Linux の Python 3.12 を検証します。
Linux と macOS のテストは `ci.yml` の手動実行でも選択できます。
macOS は Apple Silicon ランナーを使用します。

```sh
gh workflow run ci.yml --ref main -f platform=macos
gh workflow run desktop-packages.yml --ref main -f platform=macos
```

`desktop-packages.yml` は選択した対象をネイティブにビルドし、チェックサムとともに
Actions の成果物に保存します。Linux のビルドは ABI 互換性のため Ubuntu 22.04 を使います。
正式配布では [Desktop release](maintainers/releases.md) を選び、パッケージを対応ソースとともに
リリースページへ掲載します。配布の承認は [公開用ルール](maintainers/publication_policy.md) に従います。

署名・公証が未設定のDMGは開発検証用です。配布用DMGにはDeveloper ID Application証明書の
`MDS_MAC_CERTIFICATE_P12_BASE64`、`MDS_MAC_CERTIFICATE_PASSWORD`、署名IDの `MDS_MAC_SIGN_IDENTITY` を
GitHub ActionsのSecretsに設定します。公証用には `MDS_MAC_NOTARY_APPLE_ID`、`MDS_MAC_NOTARY_TEAM_ID`、
`MDS_MAC_NOTARY_PASSWORD`（アプリ用パスワード）を設定します。ワークフローは一時キーチェーンを作成し、
終了時に署名用ファイルとキーチェーンを削除します。

## 検証上の区別

Linux上のテストやMac向け分岐の単体テストは、macOS実機での検証の代わりにはなりません。
macOS版は手動のmacOSテストと配布ビルドの成功を確認してから配布対象として扱ってください。
Igor Proの実機転送は別途確認が必要です。macOSの`.app`起動とファイル関連付けに対応し、
Linuxでは互換ランチャーの明示設定かH5XPへの書き出しを利用します。
