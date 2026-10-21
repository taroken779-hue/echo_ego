# 音声モデルの導入と設定

## 導入

Windowsローカルで実行します。Git for Windowsとuvを用意し、setup.batを実行してください。アプリ用のruntime/app/.venvと、OmniVoice・翻訳・ASR用のruntime/omnivoice/.venvを別々に作成します。Irodoriは取得しません。既存の別アプリやシステムPythonは変更しません。

標準はCUDA 12.8用PyTorchです。CPUは「powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Cpu」で導入します。初回導入はネット接続と十分なディスク空き容量が必要です。モデルとCodec、翻訳、文字起こしを取得し、revisionをmanifestに記録します。再実行は既存revisionを保持します。

start.batで起動し、http://127.0.0.1:8100/を開きます。声の準備を済ませ、短い文から試してください。停止はstop.batまたは設定の「アプリを終了」です。

## 設定

config.local.jsonのschema_versionは3です。python_pathはアプリ用Python、modelsはモデル構成の一覧です。構成ごとにbackend、label、python_path、model_path、manifest_path、device、precision、defaultsを指定します。OmniVoiceのGPU精度はfloat16、CPUはfloat32です。port、preload、offline、presets_dirは共通です。auxiliary_python、translation_model、asr_modelは補助サービス用です。

設定画面では登録済み音声モデル、起動時読み込み、オフライン、プリセットフォルダーを変更できます。モデルパスやデバイスをファイルで変更した場合は再起動してください。未導入・未対応言語は明示し、別モデルへ自動変更しません。

## 既存環境の移行と復元

setup.batの最後に設定とDBを移行します。旧config.local.jsonはconfig.local.v1-backup.json、旧設定のDBはdata/echo-ego.before-backends.sqlite3へ保存してから変更します。元WAV、手動参照、辞書、定型句、履歴は保持します。旧Irodoriの選択だけはOmniVoiceへ移します。新しいモデル設定と手動設定を優先します。

復元はアプリを停止し、バックアップを現在のファイルと入れ替え、対応する旧ソース・環境へ戻します。移行後の履歴や設定はバックアップに含まれないため、現在ファイルも別名で保存してください。

## エラー対処

- Pythonが見つからない：setup.batを再実行し、python_pathとmodels内のpython_pathを確認します。
- モデルがない：setup_omnivoice.batで固定版の取得を再開します。
- CUDAエラー：ドライバーとCUDA用PyTorchを確認します。GPUメモリー不足では他のGPU利用状況を確認して再試行します。
- 声を使えない：「声」で区間と文字を自動入力し、試聴・修正して保存します。OmniVoiceは3〜10秒の声を含む区間が必要です。
- ポート使用中：他アプリを停止せず、config.local.jsonのportを変更します。
- 詳細は.runtime/server-error.logを確認します。ワーカーのエラー記録は例外型と発生箇所のみです。共有前に個人パス等を除いてください。

モデルのロードに失敗しても、基本Python環境が正常なら設定・マニュアルを開けます。別PCの新規導入、CPU性能、本人の実聴と通話は検証記録の確認範囲に従ってください。
