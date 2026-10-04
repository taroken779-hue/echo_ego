# Irodori-TTSの導入と設定
## 対応構成
対象はWindows 11のローカル実行です。標準はNVIDIA CUDA GPU・BF16、CodecはFP32です。この開発PCのRTX 5080・VRAM 16GBで確認します。全GPUで同じ速度になるものではありません。CPUはFP32の互換モードで、会話用途では大きな待ち時間が想定されます。
モデル本体は約3.1GBです。Python・PyTorch・Codec・ダウンロードキャッシュも必要なので、十分な空き容量を用意してください。初回導入はネット接続が必要です。導入後はオフラインを標準にしています。
## 新しいPCに導入
- [Git for Windows](https://git-scm.com/downloads/win)と[uv](https://docs.astral.sh/uv/getting-started/installation/)を導入し、端末を開き直してください。GPU利用時は[NVIDIAのドライバー](https://www.nvidia.com/Download/index.aspx)も更新してください。
- Echo Egoを任意のフォルダーに展開し、setup.batを実行します。公式Irodoriソースを固定版で取得し、このフォルダー専用の.venvを作ります。既存StudioやシステムPython・PATHは変更しません。
- setupはIrodoriの固定uv.lockでCUDA 12.8用の推論依存を導入し、MFモデル・Tokenizer・Codec・音声透かしの重みを取得します。エラー時はメッセージを確認して再実行できます。
- PythonはWindows用SentencePieceのバイナリーがある3.11に固定します。3.12ではこの固定版のSentencePieceがビルドを要求し、標準環境で失敗するためです。
- 完了後start.batを実行し、表示されるローカルURLを開きます。準備完了になるまで待って、短い文から試してください。
- CPU環境ではPowerShellから「powershell -NoProfile -ExecutionPolicy Bypass -File scripts/setup.ps1 -Cpu」を実行します。
setupを再実行しても既存のconfig.local.jsonは上書きしません。既存の別環境を指定していた場合は、設定画面でPythonのパスを.venv/Scripts/python.exeへ変更してください。既存runtimeソースの版が違う場合は自動で書き換えず停止します。
## 環境設定の項目
「設定 → Irodori-TTSの環境設定」で以下を編集できます。保存後はstop.bat・start.batで再起動します。設定ファイルはconfig.local.jsonです。相対パスはEcho Egoフォルダーが基準です。
- python_path：起動に使うPython。標準は.venv/Scripts/python.exe。必要な依存を備えた既存環境を選択することもできます。
- source_path：固定した公式Irodoriソース。標準はruntime/Irodori-TTS。
- model_path：MFモデルのmodel.safetensors。隣のtokenizerフォルダーも必要です。ARモデルをMFとして指定しないでください。
- codec_repo：標準はAratako/Semantic-DACVAE-Japanese-32dim。ローカルのweights.pthへのパスも指定できます。
- presets_dir：追加のプリセットWAVのフォルダー。配布ZIPには第三者の声を同梱しません。
- device：cudaまたはcpu。CPUを選択するとFP32になります。
- preload：起動時にモデルを読み込む。オフの場合は設定画面の「モデルを読み込む」で読み込みます。
- offline：導入後はオンを推奨します。必要なファイルがない場合は先にsetupを実行してください。
config.local.jsonを直接編集する場合、hf_home（モデル補助キャッシュの保存先）、port（標準8100）、precision、codec_precision、compile_modelも指定できます。compile_modelは標準オフで、変更時の互換性・速度改善は未検証です。hf_homeの標準はruntime/hf-cacheです。
## 固定バージョン
- [Irodori-TTS公式ソース](https://github.com/Aratako/Irodori-TTS)：89f9d8fbd4d51ea019867ee1197725ede1df13c5
- [Irodori-TTS-v4.1-Small-MF](https://huggingface.co/Aratako/Irodori-TTS-v4.1-Small-MF)：ccc78f5d480b6e51b69b2d5042a14c4da04fea6e
- [Semantic-DACVAE-Japanese-32dim](https://huggingface.co/Aratako/Semantic-DACVAE-Japanese-32dim)：47376ee24834d7a05a48ebabfe3cde29b3c5e214
- [SilentCipher重み](https://huggingface.co/sony/silentcipher)：a1c4d021905e0dc5b24be5f68db5fc4dba410ee1
標準プリセットは説明文から生成した参照音声です。他人の録音の再配布を避ける構成です。公式ランタイムの音声透かし設定を使います。第三者コンポーネントの利用条件は各リンク先を確認してください。
## 起動できない場合
- Pythonがない：setup.batを実行するかpython_pathを修正します。
- モデルがない・オフラインキャッシュがない：setup.batを再実行します。ダウンロードだけ行う場合は「.venv\Scripts\python.exe scripts\download_model.py」を実行します。
- CUDAが使えない：設定画面のGPU検出を確認し、ドライバー・CUDA版PyTorchを確認します。CPUでの起動も選択できます。
- GPUメモリー不足：他のGPUアプリを終了し、Echo Egoも終了して再起動します。
- 準備・生成エラー：.runtime/server-error.logを確認します。設定画面の「モデルを読み込む」で再試行できます。環境設定を変更した場合は再起動が必要です。
- ポート使用中：他のアプリを勝手に停止しません。config.local.jsonのportを変更して起動してください。
- マイクが使えない：localhostの許可とブラウザーのマイク設定を確認します。WAV登録でも利用できます。
モデルを読み込めない場合もWeb画面・設定・マニュアルは開けます。ただしPython自体やFastAPI等の基本依存が壊れている場合は、setup.batから修復してください。
