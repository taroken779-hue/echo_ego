# GitHubで配布するには
## ソースと配布ZIP
このフォルダーのソースとマニュアルを配布対象にし、個人データとモデルは含めません。scripts/package_release.pyは明示したファイルだけをZIPへ収録します。生成先はdist/echo-ego-source.zipです。GitHubへの公開・リポジトリー作成は別の操作です。
配布ZIPの作成：Pythonで「python scripts/package_release.py」を実行します。GitHubではREADME.mdを入口にし、ReleasesへこのZIPを添付する構成です。
## 配布前の確認
- 声・履歴・.runtimeログ・config.local.json・モデル・.venv・既存環境の個人パスは含めません。.gitignoreでも対象を除外します。
- .github/workflows/check.ymlで保存上限・設定検証の単体テストとJavaScript構文・配布ZIPを確認します。GPU合成・録音・音質はCIで保証しません。
- 別のWindows PCでsetup.bat・start.bat・モデル取得・発話・録音・停止を試してから正式リリースにしてください。
- 声の類似性、読み間違い、余計な発話、長い文の品質は実際に聞いて確認してください。
## データとライセンス
アプリのソースは同梱LICENSEに記載したMITライセンスです。Irodori本体・モデル・Codec・SilentCipher・依存パッケージは各提供元のライセンスと利用条件に従います。THIRD_PARTY_NOTICES.mdに参照先をまとめています。モデル本体と第三者の声はこの配布ZIPに含めません。
dataには設定・履歴音声・定型句キャッシュ・設計した声・声の特徴が入り、voicesには登録したWAVが入ります。消す前に必要な録音をバックアップしてください。ディスク履歴がオフでも録音・声の特徴・定型句は保存されます。定型句の音声は設定から削除できます。
初回setupは公式GitHub・Hugging Face・Python/PyTorch配布サイトへ接続します。オフライン設定後の通常発話に外部APIは使いません。マニュアル内の外部リンクは利用者がクリックした場合だけ外部サイトを開きます。
## 更新時の方針
ソースとモデルの固定版を変更する場合は、設定・ダウンロードスクリプト・マニュアルを同時に更新し、推論とキャッシュを確認します。setupは個人の録音や履歴を削除しません。既存環境のソース版が一致しないときは自動上書きしません。
