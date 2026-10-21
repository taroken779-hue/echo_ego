> 過去の設計・検証記録です。2026-10-22以降の構成は[TTS設計](TTS_BACKEND_DESIGN.md)と[検証記録](TTS_BACKEND_VALIDATION.md)を参照してください。

# 英語モード向けTTS代替候補調査

調査日: 2026-10-19。Qwen3-TTS以外の公開モデルを、Hugging Faceの提供元モデルカード、公式リポジトリ、推論実装で調査した。モデル導入・音声生成・実聴・ベンチマークは行っていない。

## 結論

今回の要件は「日本語の文を翻訳し、既存プロファイルまたは本人の声で英語を話す」。そのため、英文を読めるだけでなく、日本語の参照WAVを使った声の再現と、最初の音声を早く返せる実装を重視する。

Qwen3-TTSに決め打ちせず、次の3候補を優先して比較することを提案する。順位は今回のプロジェクトでの**実験順**であり、実測性能や音質の順位ではない。

1. **MOSS-TTS-Nano-100M / 公式ONNX版**: CPUで英語音声を動かし、GPUを翻訳や既存Irodoriへ残せるかを調べる。
2. **Fun-CosyVoice3-0.5B-2512**: クロス言語クローンの公式経路と音声ストリーミングを評価する。
3. **VoxCPM2**: 参照WAVだけを使う声の再現、音質、公式チャンク生成APIを評価する。

品質比較としてChatterbox Multilingual V3、会話向けの追加候補としてMOSS-TTS-Realtimeを加える。英語の参照録音を用意できる場合は、Pocket TTSとChatterbox Nanoも有力な軽量候補になる。

翻訳処理はどの候補でも別途必要。多言語TTSへ日本語を渡しただけで、正確な英訳を話してくれるという意味ではない。

## 比較表

「日→英の声」は、日本語参照から英語音声を生成する検証対象かどうか。日英対応だけで本人の声の類似性が保証されるわけではない。

| 候補 | 規模の公称値 | 日→英の声 | 音声を早期に受け取る根拠 | Echo Egoでの位置付け |
| --- | --- | --- | --- | --- |
| MOSS-TTS-Nano-100M | TTS 0.1B、別Codec約20M | 日英対応・参照音声クローン。クロス言語品質は要実聴 | 公式逐次生成、公式ONNX、ストリーム用サービス実装 | 軽量構成の第一実験候補 [1–4] |
| Fun-CosyVoice3-0.5B-2512 | 0.5B | 公式にcross-lingualクローン対応 | `inference_cross_lingual`、stream引数 | 要件との適合を評価する本命の一つ [5–7] |
| VoxCPM2 | 2B | 日英対応・参照WAVクローン。クロス言語品質は要実聴 | `generate_streaming()`が波形チャンクをyield | 音質と組込みやすさの比較候補 [8–9] |
| Chatterbox Multilingual V3 | 0.5B | クロス言語クローン。参照言語のアクセントが残る可能性 | 読んだ標準APIは完成波形を返す | 声の似方・安定性の比較候補 [10–11] |
| MOSS-TTS-Realtime | 1.7B + 別Codec | 日英対応・参照音声対応 | 公式ストリーミング推論例とTTFB測定 | 発話を続ける会話用途で追加比較 [12–13] |
| Pocket TTS | 小型CPUモデル | 英語出力対応。日本語参照の適合は未確認 | `generate_audio_stream()` | 英語録音または新規英語プリセット向け [14–15] |
| Chatterbox Nano | 110M表記、別の音声生成部等も必要 | 英語モデル。日本語参照の品質は未確認 | 標準generateは完成波形経路として評価 | 英語録音を使う軽量候補 [16] |
| FireRedTTS3 | 今回は総規模・VRAM未確定 | 日英を含む24言語。目標言語の参照を推奨 | 調査したAPIは完成波形返却 | 2026年8月の新しい品質比較候補 [17–18] |

公称パラメータ数はTTS本体などの数値であり、Codec・話者エンコーダ・実行メモリを含む統一基準ではない。

## 最近の情報で変わった点

- **MOSS-TTS-Nano**: 2026-04-10公開に加え、04-17の公式更新でONNX CPU版が追加されている。GPU必須の構成だけを比較する必要がなくなった。[1]
- **VoxCPM2**: 公式の2026年4月の新モデル。初代VoxCPMの中英中心の情報を、そのままVoxCPM2へ当てはめない。現在のモデルカードは日英を含む30言語を明記する。[8]
- **Chatterbox**: 現在の提供元はMultilingual V3を推奨。ただし実装の既定値はV2であり、V3を比較するには明示指定が必要。CPU向けNanoも別に存在する。[10–11,16]
- **FireRedTTS3**: HFの更新欄では2026-08-05にBase、08-13にInstructを公開。GitHubの更新欄は08-13公開と記載され、ページ間に表記差がある。いずれにせよ8月の新候補として確認できる。[17]
- **Pocket TTS**: 現行HFカードは英語だけでなく欧州言語を含む6言語を案内している。ただし日本語は含まれず、日本語参照のクローン性能は別途確認が必要。[14]

検索エンジンの「何か月前」やクロール日はリリース日とみなさない。新しいモデルを網羅したことや、最新のものが最良であることは主張しない。

## 有力候補の評価

### MOSS-TTS-Nano: 軽量化で最初に試す

公式には日英を含む20言語、参照音声によるクローン、CPUでの逐次生成が説明されている。ONNX版はTTSと音声Tokenizerを別々に取得する構成で、推論時のPyTorch依存を外せる。[1–3]

今回の重要な利点は、**翻訳用GPUと音声生成用CPUを分ける選択肢**である。既存Irodoriの常駐やモード切替時のモデル入れ替えを減らせる可能性がある。これは構成上の推論であり、このPCでの速度は未確認。

公式のアプリ実装にはストリームジョブのaudio/status/result取得経路もある。単に「長文を分割して最後にWAVを返す」仕様だけではないことを確認した。[4]

Windowsでは公式ONNX版から小さく検証する。ONNXであることだけではWindows対応の証明にならない。日本語参照の前処理、SentencePiece、音声Codec、スレッド数を含む実行確認が必要。PyTorch版のテキスト正規化依存を既存環境へ入れない。

HFタグはApache-2.0。古い説明本文にはLICENSE未公開時の注意書きが残るが、現在の公式コードLICENSEはApache-2.0として取得できた。導入時はTTS重み、ONNX重み、別CodecのLICENSEを取得版ごとに固定する。[1–3,23]

### CosyVoice 3: クロス言語要件の中心候補

0.5Bモデルで日英を含む9言語、クロス言語クローン、テキスト入力と音声出力のストリーミングを公式に説明している。推論例では、参照音声を使う`inference_cross_lingual`と`stream`引数を確認できる。[5–7]

既存WAVを参照する経路と相性がよい。参照音声の文字起こしを使うzero-shot経路と、使わないcross-lingual経路を区別して比較する。

公称150msは提供元の条件による値で、今回の日英翻訳・Windows・RTX 5080の発話開始時間ではない。[5] Linux向け依存や高速化経路があるため、Windowsネイティブが難しい場合はWSL2の専用ワーカーに分離する。最初からvLLMやTensorRTを必須にせず、基本推論で品質を確認してから高速化する。

モデルカードとコードはApache-2.0表記。[5–6] 日本語発話の公式例にはカタカナ化に関する注意があるが、今回の出力は英語なので、日本語モードのIrodoriを置き換える必要はない。[7]

### VoxCPM2: 公式PythonチャンクAPIが強み

2B、30言語、48kHz、Apache-2.0。参照WAVだけのクローンと、参照WAV＋文字起こしの経路を持つ。公称メモリは約8GB、RTX 4090でRTF約0.30というモデルカード記載がある。[8]

RTF 0.30は、例えば生成全体の処理時間が音声長の約30%という指標であり、最初の音が300msで出る意味ではない。RTX 5080で同じ値とも限らない。

公式実装では`generate_streaming()`が波形を順次返し、参照WAVも渡せる。現在のブラウザーをチャンク再生に変更する際、独自の推論改造を減らせる見込みがある。[9]

一方、Irodori・翻訳・VoxCPM2を同時常駐できるかは実測が必要。高水準APIは呼出しごとに参照キャッシュを組み立てるため、頻繁に使う声の準備をどこまで再利用できるかも確認する。出力後の再試行を有効にすると待ち時間が変動するため、低遅延評価では再試行回数も記録する。[9]

### Chatterbox V3 / Nano: 役割を分ける

Multilingual V3は声の類似性と反復・余計な発話の改善を掲げる更新版。V3を選ぶには`from_pretrained(..., t3_model="v3")`が必要で、省略するとV2になる。[10–11]

今回読んだMultilingual標準APIは完成波形を返す。Turbo/Nanoという名称やサービス側の「200ms未満」を、ローカルV3のチャンク対応や速度の証拠として扱わない。

Nanoは英語用の軽量モデルで、公式には8 CPUコアで実時間の3倍速とされる。ただしこれは全文生成速度の指標。参照WAVが日本語でも英語の声が自然に似るかは未確認で、英語録音を用意できる場合に比較する。[16]

いずれも提供元はMITを表示し、標準の音声透かし処理がある。[10–11,16] 既存Irodoriの透かし設定をそのまま流用しない。

### MOSS-TTS-Realtime: 将来の連続発話まで見る候補

日英対応、1.7B、会話履歴を使った逐次生成が特徴。公式測定はL20 GPU、SDPA＋torch.compile、ウォーム後TTFB 180ms、RTF 0.51。翻訳込みの実測ではない。[12–13]

単発の「入力→英語発話」だけなら、会話状態管理を追加する負担がある。NanoやCosyVoiceで十分かを先に確認し、複数回の発話で声や調子を維持したい場合に比較する。別Codecも含めたVRAMを測る。コードLICENSEとモデルカードはApache-2.0表記だが、取得するCodecも併せて確認する。[12,24]

## 条件付き・優先度を下げる候補

| 候補 | 検討する理由 | 今回の制約 |
| --- | --- | --- |
| Pocket TTS | CPU、クローン、実際の音声チャンクAPI。公称先頭チャンク約200ms | 日本語が対応言語にない。日本語参照の品質は不明。英語参照を優先。重みCC-BY-4.0、HFアクセス同意と各プリセット声の条件が別 [14–15] |
| FireRedTTS3 | 2026年8月の新モデル。日英クローン、声の設計 | 今回確認したAPIは完成音声返却。目標言語の参照を推奨。Apache-2.0表記と別に学術研究目的という注意書きがあり、製品採用時に整合を確認 [17–18] |
| Fish Audio S2 Pro | 多言語・クローン・ストリーミング | 4B＋400Mの生成部などで重い。研究/非商用向け、商用は別ライセンス。16GBで翻訳等と併用する第一候補にはしない [19] |
| OmniVoice | 非常に広い言語範囲とクローン | コードApache-2.0に対し重みCC-BY-NC。公称RTFの速さと先頭音の遅延は別。配布・商用を視野に入れると優先度低 [20] |
| XTTS-v2 | 日英を含む既存クローン候補 | 重みはCoqui Public Model License。今回の新規採用は上記候補から始める [21] |
| Kokoro-82M | 軽量な英語の固定声を使う基準 | 標準公開モデルは任意の本人WAVからのクローン経路ではない。新しい英語プリセット専用なら比較可能 [22] |

英語専用TTSであることだけを理由に除外する必要はない。日本語の参照から本人の声を使いたい場合と、英語参照または英語の固定プリセットを使える場合で評価条件を分ける。

## アーキテクチャへの追加提案

前回の「日本語はIrodori、英語は別TTS」という方針を維持し、英語エンジンを差し替え可能にする。

```text
日本語入力 → 翻訳ワーカー → 確定英文 → 英語TTSワーカー → チャンク再生
                                         ├ CPU: MOSS Nano / Pocket
                                         └ GPU: CosyVoice / VoxCPM2 / その他
```

- 共通インターフェース: `prepare_voice`, `synthesize`, `stream`, `cancel`, `capabilities`。チャンクを返せないモデルは完成音声として扱う。
- 声情報は共通IDに、エンジン別の参照特徴・モデル版・参照音声ハッシュをひも付ける。
- 翻訳をGPU、TTSをCPUとする経路も測る。GPU競合が減ってもCPU不足や前処理で遅くなる可能性がある。
- ストリームにはsample_rate、channels、format、sequenceを持たせる。48kHzステレオのモデルもあるため、Irodori向けのモノラル前提を固定しない。
- 英語翻訳を文単位で確定してからTTSへ渡す。日本語の文末で否定や意図が変わるため、未確定英訳を話し始めない。
- 再生を開始した後は、その文を自動再翻訳・再生成して重ねて話さない。失敗時は停止状態と再試行操作を明確にする。

## 次の比較実験

最初の実験はMOSS Nano ONNX、CosyVoice 3、VoxCPM2の3種類で十分。短い英文を固定してTTSだけ測り、その後に同じ翻訳器を接続する。

参照セットは、本人の日本語音声、既存IrodoriプリセットのWAV、本人の英語音声（ある場合）を分ける。各モデルが参照として推奨する長さへ前処理し、同じ内容・同じ話者で比較する。声の準備にかかった時間は通常の発話時間と別に記録する。

測定は、短文30件を各3回以上、コールド/ウォーム、翻訳有無、キャッシュ有無で分ける。記録項目は翻訳確定、TTS最初のチャンク、全文生成、再生開始、先頭無音、CPU/RAM/VRAM、RTF、音切れ、取消後の待ち時間。p50/p95と試行数を記載する。

性能の採用目標は前回案のウォーム短文p50 1.5秒以下・p95 3秒以下を仮置きする。これは期待値ではなく合否目標。声の似方、英文の聞き取り、否定・数字・固有名詞も評価する。自動文字起こしだけで音質や本人らしさを合格にしない。

今回、モデルは導入していない。Windowsネイティブ/WSL2の動作、RTX 5080での性能、実際のクロス言語クローン品質、通話アプリへの出力はすべて未検証。

## 参照資料

すべて2026-10-19に確認した公式資料。URLのmainは更新されるため、導入時はコミットとモデルrevisionを固定する。

1. [MOSS-TTS-Nano公式GitHub](https://github.com/OpenMOSS/MOSS-TTS-Nano)
2. [MOSS-TTS-Nano-100M公式HF](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M)
3. [MOSS-TTS-Nano公式ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Nano-100M-ONNX) / [音声Tokenizer ONNX](https://huggingface.co/OpenMOSS-Team/MOSS-Audio-Tokenizer-Nano-ONNX)
4. [MOSS Nanoサービス実装](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/app.py) / [ONNXサービス実装](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/app_onnx.py)
5. [CosyVoice 3公式HF](https://huggingface.co/FunAudioLLM/Fun-CosyVoice3-0.5B-2512)
6. [CosyVoice公式GitHub（現在QwenAudioへ転送）](https://github.com/QwenAudio/CosyVoice)
7. [CosyVoice公式推論例](https://github.com/QwenAudio/CosyVoice/blob/main/example.py)
8. [VoxCPM2公式HF](https://huggingface.co/openbmb/VoxCPM2)
9. [VoxCPM公式推論実装](https://github.com/OpenBMB/VoxCPM/blob/main/src/voxcpm/core.py)
10. [Chatterbox公式HF](https://huggingface.co/ResembleAI/chatterbox)
11. [Chatterbox Multilingual実装](https://github.com/resemble-ai/chatterbox/blob/master/src/chatterbox/mtl_tts.py)
12. [MOSS-TTS-Realtime公式HF](https://huggingface.co/OpenMOSS-Team/MOSS-TTS-Realtime)
13. [MOSS Realtime公式測定・推論例](https://github.com/OpenMOSS/MOSS-TTS/blob/main/docs/moss_tts_realtime_model_card.md)
14. [Pocket TTS公式HF](https://huggingface.co/kyutai/pocket-tts)
15. [Pocket TTS実装](https://github.com/kyutai-labs/pocket-tts/blob/main/pocket_tts/models/tts_model.py)
16. [Chatterbox Nano公式HF](https://huggingface.co/ResembleAI/chatterbox-nano)
17. [FireRedTTS3公式HF](https://huggingface.co/FireRedTeam/FireRedTTS3)
18. [FireRedTTS3実装](https://github.com/FireRedTeam/FireRedTTS3/blob/main/fireredtts3/core.py)
19. [Fish Audio S2 Pro公式HF](https://huggingface.co/fishaudio/s2-pro)
20. [OmniVoice公式HF](https://huggingface.co/k2-fsa/OmniVoice)
21. [XTTS-v2公式HF](https://huggingface.co/coqui/XTTS-v2)
22. [Kokoro-82M公式HF](https://huggingface.co/hexgrad/Kokoro-82M)
23. [MOSS NanoコードLICENSE](https://github.com/OpenMOSS/MOSS-TTS-Nano/blob/main/LICENSE)
24. [MOSS TTSコードLICENSE](https://github.com/OpenMOSS/MOSS-TTS/blob/main/LICENSE)
