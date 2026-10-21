# TTSバックエンドを追加する

## 実装するもの

`speech/backends/base.py`のBackendを継承し、capabilitiesとload、prepare、synthesizeを実装します。必要ならdesignも実装します。推論ライブラリーはモジュール先頭でimportせず、ワーカー内でだけ読み込みます。アプリ用環境にtorch等を追加しません。

`speech/backends/__init__.py`のBACKENDSへ明示的に登録します。登録するのはアプリに同梱する信頼済みクラスだけです。設定ファイルから任意モジュールをimportしません。

capabilitiesはversion、label、languages、reference（required、transcript_required、必要ならmin_seconds/max_seconds）、voice_design、speed（minimum/maximumまたはnull）、settingsを持ちます。settingsは型integer/number/boolean/string、default、必要に応じenum/minimum/maximum/labelを定義します。未知設定は拒否します。文字起こし不要・話速未対応・ステップなしのモデルも表現できます。

validateのreferenceがNoneの場合は、環境設定や生成設定だけの検証です。発話受付と推論には参照dictを渡し、必須の参照を省略しません。設定検証のための仮の音声区間は作りません。

## モデル構成

config.local.jsonのmodelsへ構成IDを追加します。backendが同じでも別重み・実行環境なら別構成IDにします。

```json
{
  "models": {
    "omnivoice": {
      "backend": "omnivoice",
      "label": "OmniVoice",
      "python_path": "runtime/omnivoice/.venv/Scripts/python.exe",
      "model_path": "runtime/omnivoice/model",
      "manifest_path": "runtime/omnivoice/manifest.json",
      "device": "cuda",
      "precision": "float16",
      "defaults": {"num_step": 32}
    }
  }
}
```

モデルの導入判定・版の識別がmodel.safetensors以外の場合はinstalled/identityを上書きします。identityには重みrevision、Codec、推論設定、アダプター版を含め、別モデルの特徴・音声を混用しないようにしてください。元音声の名前変更だけで識別を変更する必要はありません。

新しいPython環境の導入スクリプトをscriptsへ追加し、ソースと依存・モデルの固定版、再実行・中断再開、利用条件を記録します。翻訳・ASRはauxiliary_python側を利用するため、TTSの切替では交換不要です。モデルの精度表記はfloat16/bfloat16/float32です。

## 合成と声

合成にはtext、language、speed、settings、および必要な参照素材が渡されます。アダプターで再検証し、`speech/audio.py`のaudio_resultでPCM16モノラルWAVへ変換します。サンプルレートは元モデルの値を渡します。出力が複数チャンネルの場合はアダプターで明示的にモノラル化してください。

声の素材は共通ですが、特徴量はvoice-prompts/モデル構成ID以下へ保存し、identityと参照素材のSHA-256・区間・文字を含むキーを使います。声IDを所有者一覧に記録すれば、声削除時に共通処理で対象特徴を整理できます。

標準声のdesignは固定文とstyle、seedを受けます。元WAVが既にある場合は作り直しません。音声デザイン非対応では録音登録へ誘導し、自動的に別のモデルや声に変更しません。

## 公開APIと検証

- GET /api/v2/models：モデル構成一覧・能力・状態。/api/v2/enginesは互換エイリアス。
- POST /api/v2/speech-jobs：model_idで構成を指定。旧engineも同じIDのエイリアスとして使用可能。不一致・廃止済みIDは422。
- PUT /api/preferences：model_idとmodel_settings（構成ID→設定）を保存。
- POST /api/v2/voices/{voice_id}/prepare?model_id=...：構成別の準備。
- GET /api/v2/voices/{voice_id}/preparation?model_id=...：構成別の準備状態。
- 旧POST /api/speechは410。ジョブAPIへ移行してください。

ジョブ状態のGETはafter_stateとwait_ms（0〜1000）を指定すると、状態変更まで待機して返します。完了済み・取消済みの場合は直ちに返り、待機期限でも現在状態を返します。

`tests/test_backends.py`にモデルの能力に沿った契約テストを追加します。テスト用AlternativeBackendは参照不要・ステップなし・日本語のみ・話速変更なし・22,050Hzです。同じサービスを通り、キャッシュ分離・モデル変更検出を確認しています。アプリ共通コードへモデル名分岐を追加せずに通ることが基準です。

Qwen等の本導入時は、対象の正確なモデル名・revisionを選定して公式仕様と利用条件を確認し、導入・アダプター・契約テスト・実生成を追加します。実機性能・音質・声の似方は別途評価し、テスト用バックエンドの成功を実モデル対応の証拠にしません。
