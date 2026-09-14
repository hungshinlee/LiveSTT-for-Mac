# LiveSTT for Mac

專為 Apple Silicon Mac 打造的**離線即時語音轉文字**工具。音訊完全不離開你的電腦，延遲低、可長時間運作，並提供可浮在全螢幕簡報之上的即時字幕視窗。

專注於四種語言：**英語、國語、臺灣台語、臺灣客語**。提供三種辨識引擎依場合選用 ——
追求零延遲用 macOS 內建引擎，追求國語與臺灣台語準確度用 Qwen3-ASR，
臺灣客語與翻譯成英文則用 Whisper。

![macOS](https://img.shields.io/badge/macOS-Apple%20Silicon-black?logo=apple&logoColor=white)
![Python](https://img.shields.io/badge/Python-3.10%2B-3776AB?logo=python&logoColor=white)
![MLX](https://img.shields.io/badge/MLX-Apple%20Silicon-FF6B00)
![License](https://img.shields.io/badge/license-MIT-22c55e)

---

## 目錄

- [支援的語言](#支援的語言)
- [三種引擎怎麼選](#三種引擎怎麼選)
- [離線與隱私](#離線與隱私)
- [系統需求](#系統需求)
- [安裝](#安裝)
- [快速開始](#快速開始)
- [情境配方](#情境配方)
- [引擎詳解](#引擎詳解)
- [浮動字幕視窗](#浮動字幕視窗)
- [翻譯](#翻譯)
- [逐字稿與字幕檔](#逐字稿與字幕檔)
- [熱詞](#熱詞)
- [語音偵測參數](#語音偵測參數)
- [自動簡繁轉換](#自動簡繁轉換)
- [完整參數表](#完整參數表)
- [轉換自訂模型](#轉換自訂模型)
- [擴展漢字字體](#擴展漢字字體)
- [專案結構](#專案結構)
- [開發](#開發)
- [疑難排解](#疑難排解)
- [授權](#授權)

---

## 支援的語言

| 語言 | 可用引擎 | 指令 |
|---|---|---|
| **英語** | 三個都可以 | `-e apple -l en-US`（最低延遲）|
| **國語** | 三個都可以 | `-e qwen -l zh`（最準）／`-e apple -l zh-TW`（最快）|
| **臺灣台語** | 只有 `qwen` | `-e qwen -l nan` |
| **臺灣客語** | 只有 `whisper` + 微調模型 | 見[轉換自訂模型](#轉換自訂模型) |

幾點說明：

- **臺灣台語** 走 Qwen3-ASR 的閩南語支援（臺灣台語是閩南語的一支）。
  它把閩南語歸在 Chinese 底下由模型自行判別，所以 `-l nan` 與 `-l zh` 都能用，
  差別在前者會明確提示模型。
- **臺灣客語** 三個引擎都沒有原生支援，唯一的路是用 Whisper 搭配社群微調模型
  （例如 `formospeech/whisper-large-v2-taiwanese-hakka-v1`）。
  對 `qwen` 指定 `-l hak` 會直接報錯並告訴你該怎麼做，不會默默當成國語辨識。
- **客語的字**有些位於 CJK 擴展區，一般字體顯示為方塊，需要[安裝字體](#擴展漢字字體)。

需要翻譯時，這四種語言都可以透過 [`--translate-to`](#翻譯) 翻成任何語言。

---

## 三種引擎怎麼選

| | `whisper` | `apple` | `qwen` |
|---|---|---|---|
| **內建翻譯**（`--task translate`）| ✅ 唯一支援，但只能翻成英文 | ❌ | ❌ |
| **外接 LLM 翻譯**（`--translate-to`）| ✅ | ✅ | ✅ |
| **國語準確度** | 良好 | 良好 | ✅ **最佳** |
| **臺灣台語** | ❌ | ❌ | ✅ **唯一支援** |
| **臺灣客語** | ✅ **唯一支援**（需微調模型）| ❌ | ❌ |
| **延遲** | 較高 | ✅ **最低** | 中等 |
| **需要下載** | 75 MB – 3 GB | ✅ **完全不用** | 0.4 – 3.4 GB |
| **熱詞** | ⚠️ 僅提示條件化 | ✅ `contextualStrings` | ✅ 原生支援 |
| **可微調** | ✅ 生態成熟 | ❌ | ✅ Apache-2.0 |
| **額外設定** | 無 | 需開啟系統「聽寫」 | 無 |

**一句話建議：**

- **做簡報、要最即時** → `apple`
- **國語或臺灣台語要最準** → `qwen`
- **臺灣客語，或要翻譯成英文** → `whisper`

> **關於翻譯：** Whisper 內建的 `--task translate` 只能翻成英文（模型訓練方式決定的）。
> 想翻成其他語言、或想讓 `apple` / `qwen` 也能翻譯，用 [`--translate-to`](#翻譯) 外接 LLM ——
> 三個引擎都適用，而且能翻成任何語言，包含 Whisper 做不到的「翻成中文」。

---

## 離線與隱私

**辨識與翻譯全部在本機執行，音訊不會離開這台電腦。**

精確地說：

| | 需要網路嗎 |
|---|---|
| `apple` 引擎 | **從不**。模型內建於 macOS，且強制 `requiresOnDeviceRecognition` |
| `whisper` / `qwen` 引擎 | 只有**首次**下載模型時；之後完全離線 |
| `--translate-to` 翻譯 | 同上，首次下載 LLM 後即離線 |

模型下載自 HuggingFace，快取在 `~/.cache/huggingface`。下載完成後可以整台機器斷網使用。
任何時候都不會有音訊或文字被送到外部服務。

---

## 系統需求

- macOS，Apple Silicon（M1 以上）
- Python 3.10+
- 麥克風權限（首次執行時系統會詢問）

磁碟與記憶體需求依你選用的引擎而定：

| 組合 | 下載量 | 執行時記憶體 |
|---|---|---|
| 只用 `apple` | **0** | 極少 |
| `apple` + 翻譯 | ~2.3 GB | ~3 GB |
| `whisper` large-v3 | ~3 GB | ~4 GB |
| `qwen` 1.7B + 翻譯 | ~4 GB | ~5 GB |

`apple` 引擎不需要下載任何東西，在低規格機器或磁碟吃緊時是最實際的選擇。

---

## 安裝

### 1. 系統依賴

```bash
brew install uv portaudio ffmpeg
```

<details>
<summary>還沒有 Homebrew？</summary>

```bash
/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"
echo 'eval "$(/opt/homebrew/bin/brew shellenv)"' >> ~/.zprofile
eval "$(/opt/homebrew/bin/brew shellenv)"
```

</details>

### 2. 專案本身

```bash
git clone https://github.com/hungshinlee/LiveSTT-for-Mac.git
cd LiveSTT-for-Mac
uv venv
uv pip install -e ".[all]"
```

`[all]` 會裝齊三個引擎。想省空間可以只裝需要的：

```bash
uv pip install -e ".[apple]"      # 只用 macOS 內建引擎，最輕量
uv pip install -e ".[whisper]"    # 只用 Whisper
uv pip install -e ".[qwen]"       # 只用 Qwen3-ASR
uv pip install -e ".[apple,translate]"   # macOS 引擎 + LLM 翻譯
```

### 3. 確認可以執行

```bash
uv run livestt --list
```

---

## 快速開始

```bash
# 預設：Whisper + 終端機輸出
uv run livestt

# macOS 內建引擎，零下載、延遲最低
uv run livestt --engine apple --language zh-TW

# Qwen3-ASR，中文最準
uv run livestt --engine qwen

# 翻譯成英文
uv run livestt --task translate

# 浮動字幕視窗（適合全螢幕簡報）
uv run livestt --ui overlay

# 字幕顯示在外接螢幕
uv run livestt --ui overlay --screen 1

# 翻譯成任何語言（三個引擎都適用）
uv run livestt --engine apple --translate-to ja

# 雙語字幕：原文與譯文並陳
uv run livestt --engine apple --translate-to en --bilingual
```

更多實際場合的組合見[情境配方](#情境配方)。

查詢類指令：

```bash
uv run livestt --list            # 可用引擎與模型
uv run livestt --list-locales    # Apple 引擎支援的 63 種語言
uv run livestt --list-devices    # 錄音裝置
```

---

## 情境配方

各項選項是正交的（引擎 × 輸出 × 翻譯 × 雙語），以下是幾個實際場合的組合。

### 中文簡報，要即時字幕

最低延遲，零下載：

```bash
uv run livestt -e apple -l zh-TW -u overlay --hotwords "講者名字,專案代號" \
  --log "talk-$(date +%F).srt"
```

`--log` 讓簡報結束後留下完整紀錄 —— 浮動字幕講完就消失，沒有它就什麼都不剩。

### 雙語簡報，聽眾有外國人

原文與英文譯文並陳，`--lines 2` 避免字幕佔太多畫面：

```bash
uv run livestt -e apple -l zh-TW --translate-to en --bilingual   -u overlay --lines 2 --glossary "客語=Hakka,聲學模型=acoustic model"
```

### 字幕顯示在外接螢幕，自己看講稿

```bash
uv run livestt -e apple -l zh-TW -u overlay --screen 1 --font-size 48
```

### 會議記錄，要最高辨識準確度

不在乎延遲，只要準。搭配 `tee` 保留逐字稿：

```bash
uv run livestt -e qwen -l zh 2>&1 | tee meeting-$(date +%F).txt
```

### 臺灣台語

只有 Qwen3-ASR 支援：

```bash
uv run livestt -e qwen -l nan
```

### 客語

需要先轉換微調模型（見[轉換自訂模型](#轉換自訂模型)），並安裝擴展漢字字體：

```bash
uv run python tools/convert.py formospeech/whisper-large-v2-taiwanese-hakka-v1
./scripts/install_fonts.sh
uv run livestt -m whisper-large-v2-taiwanese-hakka-v1-mlx -u overlay --font-name HanaMinA
```

### 聽英文演講，要中文字幕

Whisper 內建的翻譯只能翻成英文，做不到這個方向，必須用 `--translate-to`：

```bash
uv run livestt -e apple -l en-US --translate-to zh-TW -u overlay
```

講稿裡有專有名詞時，[熱詞與術語表兩個都要設](#熱詞與術語表的差別)：

```bash
uv run livestt -e apple -l en-US --translate-to zh-TW -u overlay \
  --hotwords "Hakka,Taiwanese" --glossary "Hakka=臺灣客語,Taiwanese=臺灣台語"
```

### 環境吵雜

提高語音判定門檻，減少把噪音當成人聲：

```bash
uv run livestt -e apple -l zh-TW --speech-threshold 0.6 --min-speech-duration 0.3
```

---

## 引擎詳解

### `whisper` — MLX Whisper

OpenAI Whisper 跑在 MLX 上，使用 Apple Silicon GPU。**唯一能翻譯**，也是使用微調模型（例如臺灣客語）的唯一路徑。

```bash
uv run livestt --engine whisper --model mlx-community/whisper-medium-mlx
uv run livestt --task translate                    # 任何語言 → 英文
uv run livestt --model whisper-large-v2-taiwanese-hakka-v1-mlx   # 本地微調模型
```

| 模型 | 大小 | 翻譯 | 建議晶片 |
|---|---|:---:|---|
| `mlx-community/whisper-large-v3-mlx` | ~3 GB | ✅ | M3/M4/M5 |
| `mlx-community/whisper-large-v3-turbo` | ~1.6 GB | ❌ | M2 以上 |
| `mlx-community/whisper-medium-mlx` | ~1.5 GB | ✅ | 全部 |
| `mlx-community/whisper-small-mlx` | ~488 MB | ✅ | 全部 |
| `mlx-community/whisper-base-mlx` | ~145 MB | ✅ | 全部 |
| `mlx-community/whisper-tiny-mlx` | ~75 MB | ✅ | 全部 |

> `turbo` 版本不支援翻譯。

### `apple` — macOS 內建語音辨識

使用 macOS 內建的 `SFSpeechRecognizer`，**完全不需要下載模型**，延遲最低。
本專案關注的語言中，它支援**國語**（`zh-TW`）與**英語**（`en-US`），
臺灣台語與客語則不支援。強制使用裝置端辨識，音訊不會上傳。

它另外支援數十種其他語言，完整清單見 `--list-locales`。

```bash
uv run livestt --engine apple --language zh-TW
uv run livestt --list-locales      # 查看全部支援語言
```

> **使用前必須開啟系統「聽寫」**：系統設定 → 鍵盤 → 聽寫，打開它，並確認語言清單中含有你要用的語言。沒開的話程式會在啟動時就明確報錯。
>
> 首次執行會跳出語音辨識權限對話框，請按允許。

**可調整的部分：** 聲學模型本身是黑盒，不能更換或微調 —— `--model` 對它沒有意義。
但 `--hotwords` 會透過 `contextualStrings` 把辨識往指定詞彙偏置，實務上對人名與專有名詞很有效。

**翻譯：** 它本身不能翻譯，但搭配 [`--translate-to`](#翻譯) 就可以，而且不限於英文。
`apple` 的低延遲加上外接翻譯，總延遲約 0.3 秒，是即時雙語字幕最實用的組合。

### `qwen` — Qwen3-ASR

阿里巴巴的開源 ASR 模型（Apache-2.0），透過 `mlx-audio` 在 Apple Silicon 上執行。
**國語準確度最佳**，而且是三個引擎中**唯一支援臺灣台語**的（走它的閩南語支援）。
原生支援熱詞。

它不支援客語 —— 指定 `-l hak` 會直接報錯並指向 Whisper，不會默默當成國語辨識。

```bash
uv run livestt --engine qwen                                    # 預設 1.7B-8bit
uv run livestt --engine qwen --model mlx-community/Qwen3-ASR-0.6B-4bit   # 更輕更快
uv run livestt --engine qwen --language nan                     # 臺灣台語
```

| 模型 | 大小 |
|---|---|
| `mlx-community/Qwen3-ASR-1.7B-8bit` | ~1.8 GB（預設，品質與速度平衡）|
| `mlx-community/Qwen3-ASR-1.7B-4bit` | ~1.0 GB |
| `mlx-community/Qwen3-ASR-1.7B-bf16` | ~3.4 GB（最高品質）|
| `mlx-community/Qwen3-ASR-0.6B-8bit` | ~700 MB |
| `mlx-community/Qwen3-ASR-0.6B-4bit` | ~400 MB（最輕量）|

它同樣不能翻譯，但可搭配 [`--translate-to`](#翻譯)。

---

## 浮動字幕視窗

`--ui overlay` 會開一個浮在**所有視窗之上（包含全螢幕簡報）**的字幕列，適合 Keynote、Google Slides 等場合。視窗可以用滑鼠直接拖動。

```bash
uv run livestt --ui overlay
uv run livestt --ui overlay --screen 1           # 顯示在外接螢幕
uv run livestt --ui overlay --font-size 48 --lines 2 --color yellow
uv run livestt --ui overlay --engine apple --language zh-TW   # 低延遲組合
```

樣式全部都是 CLI 參數，不需要改程式碼：

| 參數 | 說明 | 預設 |
|---|---|---|
| `--screen` | 顯示在第幾個螢幕（0 為主螢幕）| `0` |
| `--font-size` | 字體大小 | `36` |
| `--font-name` | 字體名稱，如 `HanaMinA` | 系統字體 |
| `--lines` | 顯示句數，最新的在最下面（雙語時每句佔兩行）| `3` |
| `--color` | `white`／`yellow`／`green`／`cyan`／`orange`／`pink`，或 `#RRGGBB` | `white` |
| `--opacity` | 背景透明度 0.0–1.0 | `0.85` |
| `--width-ratio` | 視窗寬度佔螢幕比例 | `0.8` |
| `--bottom-margin` | 距離螢幕底部的像素 | `50` |

---

## 翻譯

有兩條路，用途不同：

| | `--task translate` | `--translate-to` |
|---|---|---|
| 作法 | Whisper 內建，單次推論 | 外接 Qwen3 LLM，兩段式 |
| 目標語言 | **只能英文** | 任何語言 |
| 可用引擎 | 只有 `whisper` | **三個都可以** |
| 額外模型 | 不需要 | ~2.3 GB |
| 術語控制 | 無 | ✅ `--glossary` |

```bash
# 中文語音 → 日文字幕（Whisper 做不到）
uv run livestt -e apple -l zh-TW --translate-to ja

# 英文語音 → 繁體中文字幕（Whisper 更做不到）
uv run livestt -e apple -l en-US --translate-to zh-TW

# 搭配浮動字幕視窗，做雙語簡報
uv run livestt -e apple -l zh-TW --translate-to en -u overlay
```

### 雙語字幕

`--bilingual` 讓原文與譯文同時顯示，適合雙語簡報或語言教學。**預設關閉。**

```bash
uv run livestt -e apple -l zh-TW --translate-to en --bilingual -u overlay
```

字幕視窗中原文在上、字級較小且較淡；譯文在下、字級完整 —— 讓譯文成為視覺重點，
原文則作為對照。視窗高度會自動加大以容納兩行。終端機模式下原文以灰色顯示。

```
🎙 這次簡報會談到聲學模型與客語轉譯的部分
📝 This briefing covers the acoustic model and Hakka translation.
```

`--lines N` 在雙語模式下仍代表 **N 句**（而非 N 行），所以 `--lines 2` 會顯示
兩句、共四行。

> `--bilingual` 需要搭配 `--translate-to`。Whisper 內建的 `--task translate`
> 只會輸出英文譯文、取不到原文，因此無法雙語顯示（指定了會直接報錯）。

### 術語表

即時字幕最常見的錯誤是專有名詞。`--glossary` 可以釘死特定詞彙的譯法：

```bash
uv run livestt --translate-to en --glossary "客語=Hakka,聲學模型=acoustic model"

# 詞多的話放檔案，一行一組
uv run livestt --translate-to en --glossary glossary.txt
```

這不是錦上添花。實測同一句話：

| | 輸出 |
|---|---|
| 無術語表 | This briefing will cover the acoustic model and **Hokkien** translation… ❌ |
| 有術語表 | This briefing will cover the acoustic model and **Hakka** translation… ✅ |

模型原本把「客語」誤譯成閩南語（Hokkien），術語表零延遲成本就修正了。

### 延遲

M5 Max 上實測，ASR 加翻譯的**總延遲約 0.3 秒**：

| 組合 | 辨識 | 翻譯 | 總計 |
|---|---|---|---|
| `apple` → 英文 | 0.10s | 0.19s | **0.29s** |
| `apple` → 日文 | 0.14s | 0.20s | **0.34s** |

搭 `apple` 引擎很舒服；搭 Whisper large 就要留意延遲會疊加。

### 翻譯模型

`--translate-model` 可更換，預設 `mlx-community/Qwen3-4B-Instruct-2507-4bit`。

| 模型 | 大小 | 說明 |
|---|---|---|
| `mlx-community/Qwen3-4B-Instruct-2507-4bit` | ~2.3 GB | 預設，品質與速度平衡 |
| `mlx-community/Qwen3-4B-Instruct-2507-8bit` | ~4.3 GB | 品質略佳 |
| `mlx-community/Qwen3-1.7B-4bit` | ~1.0 GB | 更輕量，術語較易出錯 |
| `mlx-community/Qwen3-8B-4bit` | ~4.6 GB | 品質最佳 |

> **要留意的地方：** LLM 在辨識結果破碎時（環境吵雜、句子被切斷）可能自行補完內容。
> 系統提示已要求模型不要杜撰，輸出長度上限也會隨輸入縮放，但無法完全根除。
> 重要場合建議同時保留原文紀錄。

---

## 逐字稿與字幕檔

浮動字幕視窗的內容講完就消失了。`--log` 會把每一句辨識結果寫進檔案，
**格式由副檔名決定**：

```bash
# 純文字，帶時間戳
uv run livestt -u overlay --log talk.txt

# SRT 字幕檔，可直接配合錄影使用
uv run livestt -u overlay --log talk.srt

# 加上日期，避免覆蓋
uv run livestt -u overlay --log "talk-$(date +%F-%H%M).srt"
```

純文字輸出：

```
# LiveSTT 逐字稿
# 開始時間：2026-09-14 15:04:05
# 引擎：qwen

[00:00:03] 這次簡報會談到聲學模型與客語轉譯的部分。
[00:00:09] 我們用 MLX 框架在 Apple Silicon 上跑 Whisper 模型。
```

SRT 輸出（時間軸從程式啟動起算）：

```
1
00:00:03,120 --> 00:00:07,450
這次簡報會談到聲學模型與客語轉譯的部分。
```

搭配 `--bilingual` 時，原文與譯文都會記錄；SRT 會把兩者放進同一個字幕區塊，
播放時上下兩行一起顯示。

> 每辨識完一句就立即寫入並 flush，程式中途被中斷也不會遺失已辨識的內容。

> **想在終端機看到即時輸出又要存檔？** 終端機模式直接用 shell 導向即可：
> `uv run livestt -e qwen 2>&1 | tee talk.txt`。`--log` 的價值在於
> **浮動字幕模式**，因為那時終端機本來就沒有內容可導。

---

## 熱詞

把辨識結果往特定詞彙偏置，對人名、專有名詞、術語特別有效。

```bash
uv run livestt --hotwords "客語,聲學模型,轉譯,林口"

# 詞彙多的話放成檔案，一行一個
uv run livestt --hotwords hotwords.txt
```

同一個參數，三個引擎各自對應到最合適的機制：

| 引擎 | 機制 | 效果 |
|---|---|---|
| `qwen` | 原生 `hotwords` | ✅ 最好 |
| `apple` | `contextualStrings` | ✅ 好 |
| `whisper` | `initial_prompt` 提示條件化 | ⚠️ 較弱 |

> Whisper 沒有真正的熱詞 API，只能靠 prompt 誘導解碼器。詞給太多反而可能誘發幻覺，建議控制在十個以內。

### 熱詞與術語表的差別

兩者**作用在不同階段**，翻譯時通常兩個都要設：

```
語音 ──[--hotwords]──> 辨識文字 ──[--glossary]──> 譯文
```

錯誤一旦發生在辨識階段，再完整的術語表也救不回來 ——
翻譯模型只會忠實地翻譯它收到的錯誤文字。

實測「聽英文講稿、要繁中字幕」這句：
*"The acoustic model struggles with low-resource languages like Hakka and Taiwanese."*

| 設定 | 辨識結果 | 譯文 |
|---|---|---|
| 只有 `--glossary` | …like **hacker** and Taiwanese ❌ | 如**哈克語**和臺灣台語 ❌ |
| 加上 `--hotwords` | …like **Hakka** and Taiwanese ✅ | 如**臺灣客語**和臺灣台語 ✅ |

英文的 `Hakka` 被聽成 `hacker`，術語表裡的 `Hakka=臺灣客語` 因此從未被觸發。
補上 `--hotwords Hakka` 修正辨識之後，術語表才派得上用場。

```bash
uv run livestt -e apple -l en-US --translate-to zh-TW \
  --hotwords "Hakka,Taiwanese,acoustic model" \
  --glossary "Hakka=臺灣客語,Taiwanese=臺灣台語,acoustic model=聲學模型"
```

---

## 語音偵測參數

使用 [Silero VAD](https://github.com/snakers4/silero-vad) 判斷語音起訖，比單純的音量門檻準確得多，能區分人聲與鍵盤聲、冷氣聲。

| 情境 | 建議調整 |
|---|---|
| 說話較快、希望字幕更即時 | `--silence-duration 0.4` |
| 環境吵雜、誤觸發多 | `--speech-threshold 0.6` |
| 短句被忽略 | `--min-speech-duration 0.1` |
| 句首常被截掉 | `--speech-pad-duration 0.2` |

```bash
uv run livestt --silence-duration 0.4 --speech-threshold 0.6
```

---

## 自動簡繁轉換

使用 [OpenCC](https://github.com/BYVoid/OpenCC)，預設配置 **`s2tw`**：只做字形轉換，
不改動講者的用詞。

### 為什麼預設不用 `s2twp`

`s2twp` 除了字形轉換，還會做「用語在地化」（`软件`→`軟體`、`内存`→`記憶體`）。
那是給書面翻譯用的，**套在逐字稿上是錯的邏輯**：

語音辨識本來就是照發音轉寫。講者說「軟體」時 ASR 輸出的就是 `软体`，
字形轉換已足以還原成「軟體」。`s2twp` 的 `软件`→`軟體` 映射只在講者**真的說了**
「軟件」時才觸發 —— 而那時把它改掉等於竄改講者原話。

更糟的是它會誤轉常用詞：

| ASR 實際聽到 | `s2twp`（錯）| `s2tw`（預設）|
|---|---|---|
| 客语保存工作 | 客語**儲存**工作 ❌ | 客語**保存**工作 ✅ |
| 我们保存了这个文件 | 我們**儲存**了這個**檔案** ❌ | 我們保存了這個文件 ✅ |

「客語保存工作」變成「客語儲存工作」，意思完全不同。

仍然需要用語在地化時（例如轉寫大陸講者、要給臺灣讀者看），可以明確指定：

```bash
uv run livestt --opencc s2twp
```

| 配置 | 說明 |
|---|---|
| `s2tw` | 簡體 → 臺灣正體，只做字形轉換（**預設**）|
| `s2twp` | 額外轉換大陸用語。會誤轉「保存」等常用詞 |
| `s2t` | 簡體 → 繁體，不套用臺灣異體字偏好（`裏` 而非 `裡`）|

`--traditional auto`（預設）會依引擎與模型自動判斷：

| 情況 | 是否轉換 | 原因 |
|---|:---:|---|
| Whisper + HuggingFace 模型 | ✅ | 輸出可能是簡體 |
| Whisper + 本地微調模型 | ❌ | 保留原始輸出（例如客語）|
| `--task translate` | ❌ | 輸出是英文 |
| Qwen3-ASR | ✅ | 中文輸出為簡體 |
| Apple + `zh-TW` | ❌ | 本來就是繁體 |
| Apple + `zh-CN` | ✅ | 輸出為簡體 |
| 有 `--translate-to` | 看目標語言 | 依畫面實際顯示的語言判斷，而非辨識語言 |

要強制指定：`--traditional on` 或 `--traditional off`。

---

## 完整參數表

### 核心

| 參數 | 簡寫 | 說明 | 預設 |
|---|---|---|---|
| `--engine` | `-e` | `whisper`／`apple`／`qwen` | `whisper` |
| `--ui` | `-u` | `terminal`／`overlay` | `terminal` |
| `--model` | `-m` | 模型名稱（Apple 引擎不適用）| 依引擎 |
| `--task` | `-t` | `transcribe`／`translate` | `transcribe` |
| `--language` | `-l` | `zh`／`zh-TW` 國語、`en` 英語、`nan` 臺灣台語、`hak` 臺灣客語 | 自動偵測 |
| `--hotwords` | | 逗號分隔的詞，或檔案路徑 | 無 |
| `--translate-to` | | 翻譯成指定語言（`en`、`ja`、`zh-TW`…）| 不翻譯 |
| `--translate-model` | | 翻譯用的 LLM | Qwen3-4B-Instruct |
| `--glossary` | | 術語表 `原文=譯文`，或檔案路徑 | 無 |
| `--bilingual` | | 原文與譯文一起顯示（需 `--translate-to`）| 關閉 |
| `--traditional` | | `auto`／`on`／`off` | `auto` |
| `--opencc` | | `s2tw`／`s2twp`／`s2t` | `s2tw` |
| `--log` | | 逐字稿檔案（`.srt` 輸出字幕檔）| 不輸出 |
| `--device` | | 錄音裝置編號 | 系統預設 |

### 語音偵測

| 參數 | 說明 | 預設 |
|---|---|---|
| `--speech-threshold` | 語音判定門檻 0.0–1.0，越高越嚴格 | `0.5` |
| `--silence-duration` | 靜音多久算講完一句（秒）| `0.6` |
| `--min-speech-duration` | 最短語音長度（秒），更短視為雜訊 | `0.2` |
| `--speech-pad-duration` | 句首保留的緩衝（秒）| `0.1` |

### 查詢

| 參數 | 說明 |
|---|---|
| `--list` | 列出引擎與可用模型 |
| `--list-locales` | 列出 Apple 引擎支援的語言 |
| `--list-devices` | 列出錄音裝置 |

---

## 轉換自訂模型

要使用 HuggingFace 上的 Whisper 微調模型（例如特定語言的模型），先轉成 MLX 格式：

```bash
uv run python tools/convert.py formospeech/whisper-large-v2-taiwanese-hakka-v1
```

| 選項 | 說明 |
|---|---|
| `--output-dir` | 輸出目錄（預設 `models/`）|
| `--dtype` | `float16`（預設）或 `float32` |
| `--force` | 強制重新轉換，即使模型已存在 |

轉好之後：

```bash
uv run livestt --list                                             # 確認有列出來
uv run livestt --model whisper-large-v2-taiwanese-hakka-v1-mlx    # 使用它
```

> 首次轉換會從 HuggingFace 下載原始模型（large 約 3 GB），請確認磁碟空間。已轉換過的會自動跳過。
>
> 此工具只適用於 Whisper 架構。Qwen3-ASR 的轉換請用 `mlx-audio` 自己的轉換器。

---

## 擴展漢字字體

臺灣客語有些漢字位於 CJK 擴展區（Extension B–F），一般字體不支援，會顯示成方塊（豆腐字）。

```bash
./scripts/install_fonts.sh
```

| 字體 | 特色 |
|---|---|
| 花園明朝（HanaMin）| 支援最多漢字，適合臺灣客語 |
| 思源黑體（Noto Sans CJK TC）| Google／Adobe 製作，較美觀 |

安裝後讓字幕視窗使用它：

```bash
uv run livestt --ui overlay --font-name HanaMinA
```

終端機則在 iTerm2 的 Preferences → Profiles → Text → Font，或 Terminal.app 的偏好設定 → 描述檔 → 字體 中設定。

---

## 專案結構

```
LiveSTT-for-Mac/
├── livestt/
│   ├── cli.py              # 命令列入口，參數解析與組裝
│   ├── pipeline.py         # 錄音 → VAD → 辨識 → 輸出 的串接
│   ├── audio.py            # 麥克風擷取
│   ├── vad.py              # Silero VAD 斷句
│   ├── postprocess.py      # OpenCC 簡繁轉換
│   ├── translate.py        # 外接 LLM 翻譯層
│   ├── transcript.py       # 逐字稿／SRT 輸出
│   ├── engines/
│   │   ├── base.py         # STTEngine 抽象介面
│   │   ├── __init__.py     # 引擎註冊表
│   │   ├── whisper_mlx.py
│   │   ├── apple_speech.py
│   │   └── qwen_mlx.py
│   └── ui/
│       ├── base.py         # Sink 介面
│       ├── terminal.py     # 終端機輸出
│       └── overlay.py      # 浮動字幕視窗
├── tools/
│   └── convert.py          # HF Whisper → MLX 格式轉換
├── scripts/
│   └── install_fonts.sh    # 安裝擴展漢字字體
├── tests/
│   ├── test_vad.py         # 斷句狀態機
│   ├── test_pipeline.py    # 執行緒、佇列、錯誤處理
│   ├── test_cli.py         # 參數解析與引擎選擇
│   ├── test_translate.py   # 提示組裝、輸出清理、術語表
│   ├── test_transcript.py  # 逐字稿格式與時間軸
│   ├── test_postprocess.py # 簡繁轉換
│   └── test_overlay_style.py
├── models/                 # 轉換後的本地模型（權重不進版控）
├── pyproject.toml
└── CLAUDE.md               # 開發筆記與 macOS 平台陷阱
```

架構上只有三個抽象：`STTEngine`（辨識引擎）、`Translator`（翻譯器）與 `Sink`（輸出端）。
辨識與翻譯刻意分開，所以任何引擎的輸出都能再經過翻譯。新增引擎只要實作 `STTEngine` 並在 `engines/__init__.py` 的註冊表加一筆，CLI 選項與說明文字會自動跟上。

---

## 開發

```bash
uv pip install -e ".[all,dev]"
uv run pytest
```

測試**不需要麥克風、不下載模型**，幾秒內跑完。做法是替換掉外部相依：
VAD 用可控的假偵測器、pipeline 用假麥克風與假引擎、翻譯測提示組裝與輸出清理。
驗證的是本專案自己的邏輯，而不是第三方模型的行為。

需要真實音訊做手動驗證時，用 macOS 內建的 `say` 產生，不要把音訊檔放進 repo：

```bash
say -v Meijia -o /tmp/test.aiff "今天天氣很好"
ffmpeg -y -i /tmp/test.aiff -ar 16000 -ac 1 -c:a pcm_s16le /tmp/test.wav
```

開發時的注意事項與 macOS 平台陷阱記錄在 [CLAUDE.md](CLAUDE.md)。

---

## 疑難排解

**Apple 引擎報「聽寫功能未開啟」**

系統設定 → 鍵盤 → 聽寫，打開它，並確認語言清單含有你要用的語言。

**麥克風沒有反應**

- 系統設定 → 隱私權與安全性 → 麥克風 → 勾選你的終端機程式
- `uv run livestt --list-devices` 確認裝置，必要時用 `--device N` 指定

**辨識品質不佳**

- 換引擎試試：中文用 `--engine qwen`，英文用 `--engine apple`
- Whisper 換大一點的模型
- 用 `--hotwords` 補強專有名詞

**字幕延遲越來越大**

代表辨識速度跟不上說話速度。程式會自動丟掉最舊的句子並提示，但治本要：

- 換更快的引擎（`apple` 最快）或更小的模型
- 縮短 `--silence-duration`，讓句子切得更短

**翻譯結果多了原文沒有的內容**

LLM 在辨識結果破碎時（環境吵雜、句子被 VAD 切斷）可能自行補完。可以：

- 用 `--bilingual` 同時顯示原文，隨時看得出譯文有沒有偏離
- 加大 `--silence-duration`，讓句子切得完整一些
- 用 `--glossary` 釘住關鍵術語

**翻譯模型下載很慢或中斷**

模型來自 HuggingFace，快取在 `~/.cache/huggingface`。中斷後重跑會續傳。
想先下載小一點的模型試試：

```bash
uv run livestt --translate-to en --translate-model mlx-community/Qwen3-1.7B-4bit
```

**記憶體吃緊**

- 改用 `apple` 引擎（不需下載、佔用極少）
- 翻譯改用 `mlx-community/Qwen3-1.7B-4bit`
- Qwen3-ASR 改用 `0.6B-4bit`

**`--task translate` 說不支援**

只有 `whisper` 有內建翻譯。其他引擎請改用 `--translate-to`，
它三個引擎都能用而且不限英文。兩者不能同時指定。

**顯示方塊字（豆腐字）**

```bash
./scripts/install_fonts.sh
```

**`brew`／`uv` 指令找不到**

```bash
eval "$(/opt/homebrew/bin/brew shellenv)"
```

---

## 授權

[MIT License](LICENSE)

本專案使用的模型各有授權：Whisper（MIT）、Qwen3-ASR（Apache-2.0）、Silero VAD（MIT）。macOS 內建語音辨識依 Apple 的授權條款使用。
