# Qwen3-TTSのローカル低遅延検証

2026-10-29。RTX 5080 / Windowsで実生成を実施。結論は、**公式Pythonパッケージをそのまま使う構成は遅いが、CUDA Graphを使うFaster Qwen3-TTSでは、アプリ統合を検討できる低遅延を確認した**。

本番のモデル設定・参照音声・履歴は変更していない。現在のアプリはOmniVoiceのまま。今回の結果はPython内の推論とPCM受け取りまでで、ブラウザー再生・物理スピーカー・Discordへの出力は未測定。

## 環境と再現情報

| 項目 | 条件 |
| --- | --- |
| GPU | NVIDIA GeForce RTX 5080、16GB、ドライバー617.14 |
| Python / PyTorch | Python 3.11.9 / torch 2.10.0+cu128 |
| 重み | Qwen/Qwen3-TTS-12Hz-0.6B-Base |
| 重みrevision | 5d83992436eae1d760afd27aff78a71d676296fc |
| 公式環境 | qwen-tts 0.1.1、transformers 4.57.3、accelerate 1.12.0 |
| 高速化環境 | faster-qwen3-tts 0.5.4、qwen-tts-hf 0.1.1.post1、transformers 5.15.1 |
| 実行設定 | CUDA、bfloat16、SDPA、参照特徴を事前計算・再利用 |
| 参照 | 過去の隔離検証用の合成音声、4.92秒、24kHz、全区間と対応する全文 |
| 参照SHA256 | cb1f846a83be787dd5c116ad50f8b7162eed0390f9ea483c68073c5c6a2a0ccb |
| 比較対象 | 現行OmniVoice、float16 / SDPA、16および32ステップ |

Qwenの標準・高速化版は同じ重みを読み込む。双方ともICL音声クローン、language=Japanese、temperature=0.9、top_k=50、top_p=1.0、repetition_penalty=1.05、max_new_tokens=350。同じseed群で測ったが実装間の乱数消費は異なるため、同一波形にはならない。量子化・FlashAttentionは使っていない。

runtime/qwen3-ttsとruntime/qwen3-fastに別々のvenvを作成した。qwen-ttsとqwen-tts-hfは同じPythonモジュール名を持つため、混在させていない。重みは共用。GPU測定はモデルごとに順番に行い、ASRは測定終了後にCPUで実行した。

## 比較結果

3種類の文を、準備後に各3回生成した中央値。コールド実行は除外。18回の高速化版測定（3文×3回×2チャンクサイズ）を完走。

| 入力 | OmniVoice 16・完成 | OmniVoice 32・完成 | Qwen公式・完成 | Qwen高速化・最初のPCM | Qwen高速化・完成 |
| --- | ---: | ---: | ---: | ---: | ---: |
| にほんばしで待っています。 | 950ms | 1,946ms | 6,733ms | **208ms** | 710ms |
| 午後三時に駅の東口で会いましょう。 | 1,003ms | 1,944ms | 11,015ms | **227ms** | 1,152ms |
| 予定確認と待ち合わせの3文 | 1,017ms | 2,008ms | 31,297ms | **204ms** | 2,830ms |

高速化版はchunk_size=4（およそ320ms分の音声）を使用した表。長文では全文完成がOmniVoiceより遅くても、先頭を約0.2秒で受け取って再生を始められる点が今回の利点。

時刻の定義は、準備済みの合成呼び出し開始から、CPUで使えるPCMの取得／全生成完了まで。OmniVoiceには既存アダプター内の参照再検証・WAV/Base64変換を含み、Qwenは配列受け取りまで。厳密な同一演算のマイクロベンチマークではなく、導入候補の経路比較。HTTP・WAV保存・ブラウザー再生は含めない。

公式の表はトークン到達時刻を記録するforward hook付き。hookを外した短文3回でも6.70〜11.23秒で、高速化は確認できなかった。この補助測定中は別環境のパッケージ導入が重なったため、正式な速度比算出には使わない。CPUスレッド数1の短文中央値も6.74秒で、4から1への変更では問題を解消できなかった。

### 最初のPCMと聞こえ始める時間

高速化版4フレームでは、先頭無音も含めた単純推定（最初のPCM受信＋先頭有音位置）の中央値は短文519ms、中程度580ms、長文490ms。

**208msで人に聞こえたという意味ではない。** 実アプリでは初期バッファ、リサンプリング、ブラウザー、出力デバイスの遅延が加わる。開始バッファ100msなら上記にさらに約100msを加える設計になる。先頭無音は切除していない。

### 継続して再生できる速度

RTFは本書では「生成時間÷音声長」で、1未満なら実時間より速い。高速化版4フレームの中央値は短文0.405、中程度0.410、長文0.336。8フレームでは0.345、0.330、0.289だった。開発元READMEでは逆数をRTFとして掲載する箇所があるため、数値をそのまま比較しない。

全18回についてチャンク到着時刻と累積音声長から計算し、最初のチャンク到着時に再生開始したと仮定しても、追加待ちバッファが必要となる供給遅れは0msだった。これは机上の再生スケジュール検証であり、実際の音切れ・境界ノイズがないことの証明ではない。

8フレームの初回PCM中央値は280〜282ms。4フレームは初音優先、8フレームは総処理効率優先の候補。中程度の文で334ms（4フレーム）、412ms（8フレーム）の外れ値もあり、3回ずつではp95の安定性は判断できない。

### 準備時間とメモリー

高速化版の測定例はモデル読込35.2秒、参照特徴準備21.6秒、初回CUDA Graph構築込みのPCM取得9.24秒。これらは初回／キャッシュ／OS状態で変わるので、準備後の200ms台と分ける。モデル・声・CUDA Graphを事前準備してから「発話可能」と表示する必要がある。

高速化版のtorch.cuda.max_memory_allocatedは約2.43GiB。これはPyTorchが割り当てたテンソル領域であり、GPU全体の使用量や同時モデル常駐の保証値ではない。

## 音声内容の確認

有限値・非無音の24kHz WAVを生成した。標準版の代表3文はWhisperによるローカル再認識で内容対応を確認。OmniVoice 16の短文1件は「2.本橋」と認識され、32では「日本橋」だった。ASRの誤認識とTTSの読み違いはこの結果だけでは判別できない。

高速化版の連結WAVについても代表6件（3文×2チャンクサイズ）をローカルASRで確認した。短文と長文は内容に対応したが、中程度の文のseed=20261029は、4/8フレームの双方で「午後3時に駅の駅の東で会いましょう」と認識された。入力の「駅の東口」に対して重複・欠落の疑いがある。これは採用前に確認すべき品質上の課題であり、全件内容一致とはしない。

認識結果は.runtime/qwen3-evaluation/asr.jsonに保存。人による自然さ・語頭・チャンク境界・声の似方の試聴は別途必要。今回の参照は合成音声であり、ユーザー本人の声への類似性は未検証。

追加で同じ中程度の文の別seed 2件（4フレーム）を確認し、両方とも「午後3時に駅の東口で会いましょう」と認識された。認識上の問題はこの文の全生成で起きるわけではないが、少数試行なので発生率は推定しない。代表6件と追加2件、合計8件の高速化版ASR結果を記録した。

## 実装上の発見

1. 公式qwen-tts 0.1.1のgenerate_voice_cloneは完成波形を返す。non_streaming_mode=Falseは逐次音声出力を有効にするスイッチではない。導入済みソースのdocstringにも明記されている。
2. 標準版から4フレーム時点のトークンを取り出してデコードする実験では、初回PCM中央値1,288ms。この経路は先頭だけの実験であり、連続ストリーミング実装ではない。
3. Faster Qwen3-TTSはCUDA Graphで実際にPCMを順次yieldする。その公開APIを使い、全チャンク到着時刻を計測した。アプリ本体への組込みはまだ行っていない。
4. 高速化版にtransformers 5.21.1が入ると、Tokenizerのupsampleプロパティにsetterがないという例外で読込に失敗した。開発元が検証済みとする5.15.1へ固定して解消した。両venvのuv pip checkに成功。
5. SoX実行ファイルがない警告は出るが、今回の参照読込・クローン生成・WAV保存経路は成功した。FlashAttention非導入の警告と分けて記録する。

## アプリへの採用案

次段階の候補は **Qwen3-TTS 0.6B Base＋Faster Qwen3-TTSの固定バージョン＋4フレームPCM配信**。速度面は有望だが、上記の読みの疑いを解消・評価してから本番採用を判断する。

- モデル構成IDとバックエンド実装IDを分け、qwen3_fastアダプターとして追加する。
- 専用ワーカーでモデル・参照特徴・CUDA Graphを常駐させる。参照やモデル版が変わった場合は再準備する。
- Backend v2の逐次PCM契約を実装し、ワーカー→API→AudioWorkletへ順次渡す。完成WAVだけ返す現在の経路では今回の初音短縮を活かせない。
- ローカル認証、Origin検証、取消epoch、上限付きバッファ、切断・途中失敗、履歴の最終確定を実装する。
- OmniVoiceは比較・切戻し用に残す。自動で違うモデルへ変更せず、設定で選べるようにする。
- まず各条件30回以上のp50/p95、数値・固有名詞・別の参照音声、連続送信、取消を確認し、その後ブラウザー／OSループバック／通話出力で測る。

Faster Qwen3-TTSは第三者実装。Qwen公式のモデル性能と第三者ランタイムの動作保証を混同せず、依存版・取消・EOS・長さ上限・境界品質を採用条件にする。1.7Bモデル、量子化、CPU生成は未検証。

別候補としてvLLM-Omniにも現在はPCMストリーミングAPIがある。vLLMの標準導入はLinux向けで、WindowsではWSL等が必要。既存Ubuntu-24.04の登録は確認したが、今回はvLLMの導入・実行はしていない。

## 再実行と証拠

検証スクリプト:

- scripts/benchmark_qwen3.py：公式版・OmniVoice比較、途中PCMの限定プローブ。
- scripts/benchmark_qwen3_fast.py：CUDA Graph版、4/8フレームの到着時刻と供給速度。
- scripts/check_qwen3_audio.py：代表WAVをローカルASRで再認識。既存結果はファイル名でスキップするため、同名WAVを再生成した場合はasr.jsonを別名で保存してから再実行する。

```powershell
runtime/qwen3-tts/.venv/Scripts/python.exe scripts/benchmark_qwen3.py --model qwen --repeats 3
runtime/omnivoice/.venv/Scripts/python.exe scripts/benchmark_qwen3.py --model omnivoice --repeats 3
runtime/qwen3-fast/.venv/Scripts/python.exe scripts/benchmark_qwen3_fast.py
runtime/omnivoice/.venv/Scripts/python.exe scripts/check_qwen3_audio.py
```

別PCでは公式環境と高速化環境を分け、上記固定バージョンとcu128 PyTorchを導入する。参照はbenchmark_qwen3.pyの--referenceと--reference-textで3〜10秒の全文対応音声を指定する。高速化スクリプトのREFERENCE_TEXTもその文に合わせる。重みは上記revisionで取得してruntime/qwen3-tts/model-0.6bへ配置する。

実測JSON、WAV、参照コピーは.runtime/qwen3-evaluation/、依存全バージョンは各runtime配下のrequirements.lock.txtに保存。これらはGit対象外。ソース閲覧時のrevisionは公式022e286b98fbec7e1e916cb940cdf532cd9f488e、高速化b35fdc7d71eb3e4d19e63f4b4a330a1aef31d682。実行は上記PyPIパッケージ版を使用した。

## 参照した一次資料

- [Qwen3-TTS公式](https://github.com/QwenLM/Qwen3-TTS)
- [公式APIの実装](https://github.com/QwenLM/Qwen3-TTS/blob/022e286b98fbec7e1e916cb940cdf532cd9f488e/qwen_tts/inference/qwen3_tts_model.py)
- [Faster Qwen3-TTS開発元](https://github.com/andimarafioti/faster-qwen3-tts)
- [vLLM-Omni音声API](https://docs.vllm.ai/projects/vllm-omni/en/stable/serving/speech_api/)
- [vLLM実行環境要件](https://docs.vllm.ai/en/latest/getting_started/installation/gpu/)
