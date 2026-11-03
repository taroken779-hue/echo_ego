# 音声モデルの導入と設定

## Qwen3中心の新規導入

標準の導入はWindows用のQwen3-TTS（低遅延）です。OmniVoice本体・音声Codecは取得しません。

1. uvをインストールしてターミナルを開き直します。Qwen3にはCUDAとbfloat16を使えるNVIDIA GPU・対応ドライバーが必要です。
2. ソースZIPを展開するかリポジトリーを取得します。Git cloneを使う場合はGit for Windowsも必要です。
3. フォルダー内のsetup.bat、またはsetup_qwen3.batを実行します。どちらか1つで、アプリ・独立した翻訳／文字起こし環境・Qwen3を導入します。
4. 完了後にstart.batで起動し、http://127.0.0.1:8100/を開きます。新規導入ではQwen3が選択済みです。
5. 自分の声を録音するか、利用許可のあるWAVを登録します。「声」で声を含む3〜10秒の区間と一致する文字起こしを保存し、準備完了後に短い文を試します。

初回はネット接続と十分な空き容量が必要です。Python 3.11はuvが用意します。Qwen3のGPU用PyTorchと、補助処理のCPU用PyTorchは独立しています。CPU・AMD GPU・Mac向けのQwen3導入は非対応です。停止はstop.batまたは設定の「アプリを終了」です。タブを閉じるだけでは終了しません。

## 分離した構成

- runtime/app/.venv：アプリ・HTTP・設定と保存処理。
- runtime/qwen3-fast/.venv：Qwen3専用のGPU推論環境。
- runtime/qwen3-tts/model-0.6b：固定revisionのQwen3-TTS 0.6B Baseモデル。
- runtime/auxiliary/.venv：CPUの日英翻訳と参照音声の文字起こし。OmniVoiceパッケージを含みません。
- runtime/auxiliary/translation：OPUS-MT日英翻訳モデル。
- runtime/auxiliary/asr：Whisper文字起こしモデル。
- runtime/omnivoice：OmniVoiceを任意追加した場合、または旧環境から残っている場合の音声モデル・Codec・専用環境。

日英翻訳はOPUS-MT、自動文字起こしはWhisperを使います。新規Qwen3導入ではOmniVoice環境がなくても日本語発話・英語への翻訳発話・自動文字起こしを利用できます。

## OmniVoiceを任意で追加する

Git for Windowsを用意し、アプリを停止してsetup_omnivoice.batを実行します。アプリと独立した補助環境を確認してから、OmniVoiceのソース・音声モデル・Codecを導入します。既存のQwen3と選択中モデルは保持します。

OmniVoiceをCPUで使う場合は、powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Model omnivoice -Cpuを実行します。Qwen3に-Cpuは指定できません。CPUでの会話性能は未検証です。

Qwen3には標準声を文章から新規デザインする機能がありません。自分の録音・許可済みWAVを登録してください。標準声を新規作成したい場合はOmniVoiceを追加・選択して作成します。作成済みの元音声はQwen3の参照にも使えます。

## 既存環境の更新

1. stop.batでアプリを停止し、新しいソースへ更新します。
2. setup.batまたはsetup_qwen3.batを実行します。
3. 補助CPU環境をruntime/auxiliaryに作成します。旧OmniVoice配下の補助モデルが取得済みrevisionと一致する場合はコピーして再利用し、元データは保持します。
4. 従来の標準補助パスをruntime/auxiliaryへ変更します。手動の独自パス、登録済みモデル、選択中モデル、録音・参照設定・辞書・定型句・履歴は保持します。
5. start.batで起動し、「設定」で選択モデルを確認します。Qwen3を使う場合は「Qwen3-TTS（低遅延）」を選びます。

新規導入の初期モデルはQwen3です。既存環境のモデル選択や既定モデルはセットアップで変更しません。旧フォルダーも自動削除しません。

設定の保存前にconfig.local.v1-backup.jsonがなければ作成します。旧形式DBはdata/echo-ego.before-backends.sqlite3へ移行前バックアップを作成します。復元時はアプリを停止し、現在のファイルも控えてから対応するソース・設定・DBへ戻します。昔のバックアップに更新後の履歴は含まれません。

## 設定とエラー対処

config.local.jsonのschema_versionは3です。modelsは音声モデル一覧、default_modelは新規設定の初期選択です。Qwen3のGPU精度はbfloat16、OmniVoiceのGPU精度はfloat16、CPUはfloat32です。auxiliary_python・auxiliary_manifest・translation_model・asr_modelは独立した補助処理の設定です。パスをファイルで変更した場合は再起動します。

- Python・モデルがない：Qwen3構成はsetup.bat、OmniVoice構成はsetup_omnivoice.batをアプリ停止後に再実行します。
- 補助モデルがない：setup.batで独立した補助環境を導入します。開発者はscripts/setup_auxiliary.ps1を単独実行できますが、既存設定のパス切り替えは通常のセットアップで行います。
- CUDA・bfloat16確認で失敗：GPUとドライバーを確認します。Qwen3はCPU実行へ自動変更しません。
- モデル選択欄にない：登録処理まで成功したか確認し、アプリを終了・起動します。
- 既存Qwen3設定と異なるというエラー：手動設定を保護して停止しています。設定ファイルのパスと導入先を比較してください。
- 声を使えない：選択モデル用の3〜10秒の参照区間と文字起こしを確認して保存します。Qwen3では未作成の標準声を新規デザインできません。
- ポート使用中：他アプリを停止せずconfig.local.jsonのportを変更します。
- 初回の翻訳・モデル準備が遅い：準備後の発話時間と分けて確認します。セットアップ分離は初回待ちや英語逐次生成エラーの修正ではありません。
- 詳細は.runtime/server-error.logを確認します。共有前に個人パス・入力文などを除いてください。

モデルが読み込めなくても、アプリ環境が正常なら設定・マニュアルを開けます。別PCでの完全な初回導入、人による音質評価、Discord受信音の確認は機械検証とは別です。

導入分離の確認内容は[検証記録](SETUP_SEPARATION_VALIDATION_2026-11-03.md)にまとめています。
