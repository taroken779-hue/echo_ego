# Qwen3中心のセットアップ分離・検証記録

2026-11-03。標準セットアップをQwen3中心に変更し、CPU補助処理をOmniVoiceから分離した。

## 最終構成

- setup.bat / setup_qwen3.bat：アプリ、独立CPU補助環境、Qwen3を導入する。OmniVoiceのソース・音声モデル・音声Codecは取得しない。
- setup_omnivoice.bat：アプリとCPU補助環境を確認してからOmniVoiceを任意追加する。
- scripts/setup_app.ps1：コントローラー環境。
- scripts/setup_auxiliary.ps1：runtime/auxiliary/.venvへCPU版PyTorchと翻訳・ASR依存を導入する。
- scripts/download_auxiliary.py：OPUS-MTとWhisperだけを固定revisionで取得する。取得済みの補助モデルは旧標準位置からコピーして再利用し、旧環境は残す。
- scripts/configure_setup.py：新規では選んだTTSだけを登録する。既存ではモデル・既定モデル・独自パスを保持し、旧標準の補助パスだけ新しい場所へ変更する。

## 実行した検証

- Python回帰テスト59件が成功。新規Qwen3構成にOmniVoiceのモデル・パスが入らないこと、任意OmniVoice CPU追加、既存の独自設定保持、取得先の分離、旧モデルrevisionと元ファイルの保持、不完全な取得状態の拒否を確認した。
- PowerShellセットアップの構文解析が成功。
- runtime/auxiliaryを新規作成し、CPU版PyTorch 2.10.0、requirements-auxiliary.txtの依存を実際に導入。uv pip checkが成功した。
- 独立環境でOPUS-MTの日英翻訳とWhisperの英語文字起こしに成功し、OmniVoiceパッケージが読み込まれていないことを確認した。初回の実行で設定読み込みに必要なpydantic不足を検出し、補助環境の依存へ追加して再検証した。
- このPCでscripts/setup.ps1 -Model qwen3の全経路を完了し、アプリを再起動。既存モデルとデータを保持して、補助処理の設定をruntime/auxiliaryへ切り替えた。
- 設定とDBが空の隔離フォルダーでも実際の登録・移行コマンドを実行し、qwen3だけが登録され、初期選択もqwen3になることを確認した。モデル本体・Python環境はこのPCの導入済みファイルを検証した。
- 独立したCPU補助ワーカーで「駅で待っています。着いたら教えてください。」を英訳し、qwen3だけを登録したTTSワーカーで英語を最後まで逐次生成した。24kHzの有限・非ゼロ波形、音声長5.36秒を確認した。OmniVoice TTSワーカーは起動していない。
- 配布ZIPを再生成し、新しいセットアップ・依存ファイル・テストの収録、ZIP整合性、個人データとモデルの除外を確認した。

## 保存した証拠と確認範囲

ローカルの.runtime/setup-separation/に移行前設定、補助処理の確認結果、Qwen3連携結果、生成音声、隔離した新規設定・DBを保存した。これらの個人データ・音声・環境は配布しない。

別のPCでの全モデルの初回ネット取得、他GPUでの動作、OmniVoice環境の再インストール、人による音質・アクセント・本人類似性、Discord受信音は未検証。

今回の変更は導入と補助処理の分離であり、先の英語検証で確認した初回待ちや途中の逐次生成エラーの修正は含まない。
