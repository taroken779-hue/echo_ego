# 音声モデルの導入と設定

## 導入

Windowsローカルで実行します。新しいPCでは次の順に導入してください。

1. Git for Windowsとuvをインストールし、インストール後にターミナルを開き直します。標準GPU構成ではNVIDIA GPUと対応ドライバーも必要です。
2. ソースZIPを展開するかリポジトリーを取得し、フォルダー内のsetup.batを実行します。処理完了の表示まで待ち、失敗した場合は先にエラーを解消します。
3. Qwen3-TTSを使う場合は、続けてsetup_qwen3.batを実行します。専用環境・モデルを追加する処理で、setup.batの代わりにはなりません。
4. start.batで起動し、http://127.0.0.1:8100/を開きます。Qwen3は「設定 → 音声モデル・実行環境」で「Qwen3-TTS（低遅延）」を選びます。選択は自動保存され、モデルの入れ替え・準備が始まります。
5. 「声」で選択モデル用の参照音声と文字起こしを保存し、発話画面の準備完了を待って短い文を試します。

アプリ用のruntime/app/.venvと、OmniVoice・翻訳・ASR用のruntime/omnivoice/.venvを別々に作成します。Qwen3はさらにruntime/qwen3-fast/.venvを使用します。Qwen3使用時も日英翻訳・参照音声の文字起こし・標準声の元音声作成にOmniVoice側の環境を使用するため、削除しないでください。既存の別アプリやシステムPythonは変更しません。

標準はCUDA 12.8用PyTorchです。CPUは「powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Cpu」で導入します。初回導入はネット接続と十分なディスク空き容量が必要です。モデルとCodec、翻訳、文字起こしを取得し、revisionをmanifestに記録します。再実行は既存revisionを保持します。

停止はstop.batまたは設定の「アプリを終了」です。タブを閉じるだけでは終了しません。既存環境にQwen3を追加するときは、アプリを停止してsetup_qwen3.batを実行し、start.batで起動し直します。追加セットアップは現在選択中のモデルを変更しません。

## 設定

config.local.jsonのschema_versionは3です。python_pathはアプリ用Python、modelsはモデル構成の一覧です。構成ごとにbackend、label、python_path、model_path、manifest_path、device、precision、defaultsを指定します。OmniVoiceのGPU精度はfloat16、CPUはfloat32です。port、preload、offline、presets_dirは共通です。auxiliary_python、translation_model、asr_modelは補助サービス用です。

設定画面では登録済み音声モデル、起動時読み込み、オフライン、プリセットフォルダーを変更できます。モデルパスやデバイスをファイルで変更した場合は再起動してください。未導入・未対応言語は明示し、別モデルへ自動変更しません。

## 既存環境の移行と復元

setup.batの最後に設定とDBを移行します。旧config.local.jsonはconfig.local.v1-backup.json、旧設定のDBはdata/echo-ego.before-backends.sqlite3へ保存してから変更します。元WAV、手動参照、辞書、定型句、履歴は保持します。旧Irodoriの選択だけはOmniVoiceへ移します。新しいモデル設定と手動設定を優先します。

復元はアプリを停止し、バックアップを現在のファイルと入れ替え、対応する旧ソース・環境へ戻します。移行後の履歴や設定はバックアップに含まれないため、現在ファイルも別名で保存してください。

## エラー対処

- Pythonが見つからない：setup.batを再実行し、python_pathとmodels内のpython_pathを確認します。
- モデルがない：OmniVoice・翻訳・文字起こしはsetup_omnivoice.bat、Qwen3はsetup_qwen3.batで固定版の取得を再開します。アプリは先に停止してください。
- CUDAエラー：ドライバーとCUDA用PyTorchを確認します。GPUメモリー不足では他のGPU利用状況を確認して再試行します。
- 声を使えない：「声」で選択モデル用の参照設定を開き、区間と文字を自動入力し、試聴・修正して保存します。OmniVoice・Qwen3とも3〜10秒の声を含む区間と、一致する文字起こしが必要です。
- ポート使用中：他アプリを停止せず、config.local.jsonのportを変更します。
- 詳細は.runtime/server-error.logを確認します。ワーカーのエラー記録は例外型と発生箇所のみです。共有前に個人パス等を除いてください。

モデルのロードに失敗しても、基本Python環境が正常なら設定・マニュアルを開けます。別PCの新規導入、CPU性能、本人の実聴と通話は検証記録の確認範囲に従ってください。

## Qwen3-TTSの追加

Qwen3低遅延版はNVIDIA CUDA GPU専用で、現在の構成はbfloat16を使います。CPU版・AMD GPU・Mac向けの導入スクリプトはありません。専用セットアップはPyTorch 2.10.0のCUDA 12.8版と固定した依存パッケージを導入し、GPU対応を確認してからモデルを取得します。GPU確認に失敗した場合はドライバーとGPU対応を確認してください。OmniVoiceのCPU導入オプションはQwen3には適用されません。

モデル選択欄にQwen3が出ない場合は、追加セットアップが最後の登録処理まで成功したか確認し、アプリを終了・起動してください。準備時間、声の設定、依存バージョンは使い方の「Qwen3-TTS（低遅延）」またはdocs/QWEN3_GUIDE.mdで確認できます。
