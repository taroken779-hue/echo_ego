# Echo Ego

日本語の短文を入力して、選んだ音声モデルで話すWindowsローカルアプリ。自分の声の録音・登録、発話キュー、生成済み定型句、読み辞書、履歴保存に対応します。

標準の新規導入はQwen3-TTS（低遅延）です。日本語と英語の逐次発話に対応します。日英翻訳・参照音声の文字起こしは独立したCPU環境へ導入します。OmniVoiceは任意で追加できます。[Qwen3導入・操作](docs/QWEN3_GUIDE.md) / [OmniVoice操作ガイド](docs/OMNIVOICE_GUIDE.md) / [モデル追加ガイド](docs/TTS_BACKEND_GUIDE.md)。

## 導入・起動

1. uvをインストールします。OmniVoiceも使う場合はGit for Windowsを用意します。
2. ソースZIPを展開、またはリポジトリーを取得し、`setup.bat` または `setup_qwen3.bat` のどちらか1つを実行します。アプリ・独立した翻訳／文字起こし環境・Qwen3を導入します。**OmniVoice本体・音声Codecは取得しません。**
3. `start.bat` で起動し、`http://127.0.0.1:8100/` を開きます。新規導入ではQwen3が選択済みです。既存環境ではモデル選択を保持するため、「設定 → 音声モデル・実行環境」で確認します。
4. 自分の声を録音するか、利用許可のある1〜30秒のWAVを登録し、「声」で3〜10秒の参照区間と一致する文字起こしを保存します。準備完了後に短い文から試します。
5. 終了は `stop.bat` または設定画面の「アプリを終了」。タブを閉じるだけでは終了しません。

Qwen3にはCUDAとbfloat16を利用できるNVIDIA GPU・対応ドライバーが必要です。OmniVoiceを追加する場合は `setup_omnivoice.bat`、OmniVoiceをCPUで導入する場合は `powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Model omnivoice -Cpu` を使います。CPUでの会話性能は未検証です。

既存環境の更新はアプリを停止してからセットアップを実行します。補助環境は `runtime/auxiliary` に分離され、従来の標準パスを新しい場所へ切り替えます。登録済みモデル・選択中の声・録音・履歴・手動パス設定を保持し、旧環境は自動削除しません。詳細は[導入手順](docs/SETUP.md)を参照してください。

## マニュアル

アプリ上部の「使い方」から同じ文書をオフラインで閲覧できます。

- [操作マニュアル](docs/USER_GUIDE.md)
- [導入・モデル設定・エラー対処](docs/SETUP.md)
- [Qwen3-TTSの追加導入・声の準備・生成設定](docs/QWEN3_GUIDE.md)
- [Discord・VB-CABLEの設定と自分の発話を聞く方法](docs/DISCORD_GUIDE.md)
- [GitHub配布・個人データ・更新の注意点](docs/DISTRIBUTION.md)
- [第三者コンポーネント](THIRD_PARTY_NOTICES.md)
- [実装・検証記録](docs/IMPLEMENTATION.md)

## 機能

- Enterで発話、Shift＋Enterで改行、Escで全停止。IME変換確定中は送信しません。入力欄・発話ボタン・定型句ボタンで、発話用Enterから1秒以内の追加Enterを無視します。
- 再生中にも次の文を生成する発話キュー。待ち文の取消と停止後の古い結果の破棄。
- 声の試聴・名前変更・お気に入り・削除。マイク録音またはWAV登録。標準声の新規デザインは、任意追加したOmniVoiceで利用できます。
- 編集・並べ替え可能な定型句とAlt＋1〜9。事前生成した音声を再利用し、設定変更時は別キャッシュにします。
- 読み辞書、再生音量、対応ブラウザーでの出力先選択。
- 生成日時付き履歴とWAV保存、個別・全件削除、直前の削除の取り消し。
- 履歴保存は初期オフ。オンならPC内に音声込みで保存し、件数・日数・容量で制限します。
- 設定画面で音声モデルを選択し、モデル固有の生成設定を調整できます。モデルの実行環境はconfig.local.jsonで指定します。

## 保存とプライバシー

`config.local.json` はPCごとの環境設定、`data/` は設定・履歴・定型句・声の特徴、`voices/` は登録WAV、`runtime/` はモデルと推論コード、`.runtime/` はログです。Gitの追跡と配布ZIPから除外します。初回導入後の通常発話はローカル推論です。参照音声の利用許可を確認してください。

## 応答時間

「送信から再生開始まで」は待ち行列を含め、ブラウザーへ再生をスケジュールするまでの時間です。物理スピーカーから音が出た瞬間の測定ではありません。先頭無音と出力機器の遅延は別途加わります。起動直後・初めての声・文の長さで時間は変わります。

初回と声の準備後では待ち時間が変わります。実装変更後の証拠と未検証項目は[検証記録](docs/TTS_BACKEND_VALIDATION.md)を参照してください。過去のIrodori測定値は現在のモデルの性能を示しません。

起動時に選択モデル・保存済みの声を先行準備します。OmniVoiceは完成した音声を再生し、詳細欄で生成ステップ32/16を比較できます。Qwen3は生成途中から再生し、音声チャンク4/8を選べます。Qwen3では話す速さの変更は無効です。[OmniVoiceの待ち時間](docs/LATENCY_IMPROVEMENTS_2026-10-22.md) / [Qwen3の性能と制約](docs/QWEN3_GUIDE.md)。

## 開発と配布

`python -m unittest discover -s tests -v` で保存処理と設定検証を確認できます。JavaScriptは `node --check static/app.js` と `node --check static/features.js`。`python scripts/package_release.py` で個人データを含まない `dist/echo-ego-source.zip` を作ります。GitHub公開は別操作です。

ソースはMITライセンス。モデル・Codec等は各提供元の利用条件に従います。別PCの初回導入、実録音、音質・声の類似性、通話相手への出力は正式リリース前に確認してください。
