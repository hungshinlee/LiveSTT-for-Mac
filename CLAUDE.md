# CLAUDE.md

給在這個 repo 工作的 Claude Code 的指引。

## 專案是什麼

Apple Silicon Mac 上的離線即時語音轉文字：

```
麥克風 → Silero VAD 斷句 → STTEngine → [Translator] → Sink
```

選項是正交的：三種辨識引擎（Whisper / macOS 內建 / Qwen3-ASR）× 兩種輸出
（終端機 / 浮動字幕視窗）× 可選翻譯 × 可選雙語。

**專案聚焦於四種語言：英語、國語、臺灣台語、臺灣客語。**
新增功能時以這四種為準，不要為了「反正模型支援」而把其他語言加回文件或範例。

**這是 macOS 專用專案**，依賴 Apple Silicon（MLX）與多個 PyObjC 框架。
不必為其他平台保留相容路徑，也不要為了「以防萬一」加入 CUDA 或 Linux 分支。

## 常用指令

```bash
uv pip install -e ".[all,dev]"   # 安裝（含三個引擎與測試工具）
uv run pytest                    # 跑測試（快、不需麥克風、不下載模型）
uv run livestt --list            # 列出引擎與模型
uv run livestt --help            # 全部參數
uv run livestt --list-locales    # Apple 引擎支援的語言
```

手動驗證引擎時，用 `say` 產生音訊，不要把音訊檔放進 repo：

```bash
say -v Meijia -o /tmp/t.aiff "今天天氣很好"
ffmpeg -y -i /tmp/t.aiff -ar 16000 -ac 1 -c:a pcm_s16le /tmp/t.wav
```

注意 `say` 的咬字比真人清楚，用它測出來的準確度偏樂觀。

驗證浮動字幕視窗是否真的顯示（它沒有標題列，肉眼之外可以這樣確認）：

```python
import Quartz
Quartz.CGWindowListCopyWindowInfo(
    Quartz.kCGWindowListOptionAll, Quartz.kCGNullWindowID)
# 找 kCGWindowOwnerPID 相符者，layer 應為 1000
```

## 架構

三個抽象，其餘都是實作細節：

- **`STTEngine`**（`livestt/engines/base.py`）— 辨識引擎。
  生命週期是 `prepare()` → 多次 `transcribe()` → `close()`。
  `prepare()` 在背景執行緒中呼叫，可以耗時數秒（載模型、要權限）。
- **`Translator`**（`livestt/translate.py`）— 翻譯器，生命週期同上。
- **`Sink`**（`livestt/ui/base.py`）— 輸出端。`on_text` / `on_status` / `on_error`。

辨識與翻譯刻意分開：任何引擎的輸出都能再經過翻譯，
所以 `apple` 和 `qwen` 這兩個純 ASR 模型也能做翻譯，而且不限於英文。

`Pipeline`（`livestt/pipeline.py`）把兩者串起來，用生產者／消費者兩條執行緒：
錄音執行緒永遠不阻塞，辨識慢時只會在佇列堆積。佇列滿了會丟最舊的一句，
因為對即時字幕來說，落後三十秒的正確字幕不如沒有。

**音訊格式在邊界統一**：pipeline 負責把 16-bit PCM bytes 轉成 float32 numpy（16 kHz 單聲道、
值域 [-1, 1]），引擎一律收到這個格式，不要在引擎裡重複做轉換。

### 新增一個引擎

1. 在 `livestt/engines/` 新增檔案，實作 `STTEngine`
2. 在 `livestt/engines/__init__.py` 的 `ENGINES` 加一筆 `EngineSpec`
3. 在 `pyproject.toml` 的 `optional-dependencies` 加它的相依套件

CLI 的 `--engine` 選項、`--list` 輸出、翻譯能力檢查都會自動跟上，不需要改 `cli.py`。

引擎的相依套件一律在 `prepare()` 裡才 import，並在 `ImportError` 時拋出帶安裝指令的
`EngineError` —— 這樣只裝了一個引擎的使用者不會因為別的引擎缺套件而無法啟動。

## macOS 平台陷阱

這些都是實際踩過的，改動相關程式碼前先讀：

**`SpeechAnalyzer` / `SpeechTranscriber` 從 Python 用不了。**
macOS 26 的新語音 API 是 Swift-only（只存在於 `.swiftinterface`，沒有 Objective-C header），
PyObjC 橋接的是 Objective-C，碰不到。本專案用的是舊的 `SFSpeechRecognizer`，它是 ObjC。
`Translation` framework 同理，所以「用 Apple 做翻譯」這條路在純 Python 下不通。

**Apple 引擎需要系統開啟「聽寫」。**
權限授權通過不代表能用：系統設定 → 鍵盤 → 聽寫沒開的話，辨識會回
`Siri and Dictation are disabled`。`prepare()` 末端會跑一次暖身辨識把這個問題提前攤開，
不要把那行拿掉。

**`SFSpeechRecognizer` 的 callback 預設送到「主佇列」。**
辨識跑在背景執行緒、而主執行緒沒有 run loop 在跑（終端機模式就是這樣）時，
callback 永遠不會被送達，症狀是每一句都逾時三十秒。
解法是 `recognizer.setQueue_()` 指定一條自己的 `NSOperationQueue`，
`prepare()` 裡有做這件事，不要拿掉。

**授權 callback 則不走那條佇列。**
`requestAuthorization:` 的 handler 不使用 `queue` 屬性，官方文件也只說「不保證在主佇列」。
所以 `_pump()` 仍然保留給授權用：它一邊抽送目前執行緒的 run loop、一邊等
`threading.Event`，兩種送達方式都接得住。

**`varlist.as_buffer(n)` 的 `n` 是元素個數，不是位元組數。**
`AVAudioPCMBuffer` 寫入時 `as_buffer(frames)` 才對，寫 `frames * 4` 會拿到四倍大的視圖。

**浮動字幕視窗必須在主執行緒建立，事件迴圈也在主執行緒跑。**
`cli.py` 因此對 overlay 走不同流程：`sink.build()` → `pipeline.start()` → `sink.run()`（阻塞）。
所有 UI 更新都透過 `AppHelper.callAfter` 丟回主執行緒。

**tqdm 會建立 multiprocessing 號誌，而 overlay 模式來不及釋放它。**
`mlx-audio` 內部用 tqdm 顯示進度，tqdm 預設的寫入鎖是 multiprocessing 鎖，
即使進度條停用也會在 `tqdm.__new__` 階段建好。overlay 結束時行程被
`NSApp.terminate_()` 直接砍掉，鎖來不及釋放，Python 的 resource_tracker
就會印出「leaked semaphore objects」警告，讓使用者誤以為程式有問題。
`qwen_mlx._use_thread_lock_for_progress()` 在載入模型前把它換成執行緒鎖。
只有 overlay + qwen 這個組合會觸發，單獨測試任一邊都看不到。

**`AppHelper.runEventLoop()` 不會返回，連 `atexit` 都不執行。**
PyObjC 的 `stopEventLoop()` 在找不到 RunLoopStopper 時走 `NSApp.terminate_()`，
直接在 Objective-C 層結束行程，繞過整個 Python 清理機制。
所以**收尾工作一定要在停止事件迴圈之前做完** —— 寫在 `sink.run()` 之後的程式碼形同不存在。
這就是 `OverlaySink.run()` 有 `on_stop` 參數的原因，也是 overlay 模式自己裝 SIGINT handler
（而非用 `installInterrupt=True`）的原因：讓 Ctrl+C 也走同一條收尾路徑。
`cleanup()` 因此必須是冪等的。

同樣的原因也會吃掉標準輸出：stdout 在非 TTY 時是區塊緩衝，行程被 `terminate_()`
結束時緩衝區不會被 flush，導致輸出重導向到檔案時整份內容憑空消失。
`main()` 開頭因此把 stdout 設成行緩衝，`cleanup()` 結尾也明確 flush。

## 各引擎的能力差異

改動與這些有關的邏輯時要記得：

- **只有 Whisper 能翻譯**，而且只能翻成英文。`create_engine()` 會擋掉其他引擎的
  `--task translate`，這是刻意的，不要改成靜默忽略。
- **`--hotwords` 與 `--glossary` 作用在不同階段**，不要混為一談：
  前者偏置 ASR、後者約束翻譯。辨識階段就錯掉的詞，術語表救不回來
  （實測：英文 `Hakka` 被聽成 `hacker`，術語表的 `Hakka=…` 從未觸發）。
  翻譯情境下兩個通常都要設。
- **熱詞機制三家不同**：Qwen 原生 `hotwords`、Apple 用 `contextualStrings`、
  Whisper 只有 `initial_prompt`（提示條件化，效果較弱且提示過長會誘發幻覺）。
  對外統一成一個 `--hotwords` 參數。
- **Apple 沒有模型可選**，`--model` 對它無意義，註冊表的 `_apple()` 會把它丟掉。
- **Qwen 認英文語言名稱**（`"Chinese"`）不是 ISO 代碼，見 `qwen_mlx.LANGUAGE_NAMES`。
  Apple 要完整 locale（`zh-TW`），Whisper 要主語言碼（`zh`）。各自在引擎內轉換。

### 四種語言分別走哪條路

| 語言 | 引擎 | 備註 |
|---|---|---|
| 英語 | 三個都可以 | apple 延遲最低 |
| 國語 | 三個都可以 | qwen 最準 |
| 臺灣台語 | 只有 `qwen`（`-l nan`）| 走 Qwen 的閩南語支援，歸在 Chinese 底下 |
| 臺灣客語 | 只有 `whisper` + 微調模型 | 三個引擎都無原生支援 |

**Qwen3-ASR 的方言清單裡沒有客語。** 它支援的是閩南語、吳語等，
所以 `qwen_mlx.UNSUPPORTED` 會攔下 `-l hak` 並指向 Whisper ——
不要把 `hak` 加回 `LANGUAGE_NAMES` 映射成 `Chinese`，那會讓客語被當成國語
硬辨識，失敗得莫名其妙。

## 翻譯

兩條路徑並存，語意不同，不要混為一談：

- `--task translate` — Whisper 內建的多任務能力，單次推論，**只能翻成英文**
- `--translate-to X` — 外接 Qwen3 LLM，兩段式，三個引擎都能用，可翻成任何語言

兩者同時指定會報錯（在 `main()` 檢查，訊息說明兩者差異）。

翻譯器用的是**非 thinking 模式**（`enable_thinking=False`）。Qwen3 的 hybrid thinking
會讓延遲從零點幾秒暴增到數秒，即時字幕完全不能接受。2507 之後的 Instruct 模型
沒有 thinking 也就沒有這個參數，所以 `_build_prompt()` 用 try/except 涵蓋兩種情況。

LLM 輸出需要清洗：它偶爾會加引號、「Translation:」前綴，或在後面多附一段解釋。
`_clean()` 負責這件事，改動時記得 `tests/test_translate.py` 有對應的案例。

`--bilingual` 讓 `Sink.on_text(text, original)` 的第二個參數帶上原文。
兩段文字的簡繁轉換**各自判斷**：譯文看翻譯目標語言，原文看辨識語言，
因此 `cli.main()` 會算出 `convert_tw` 與 `convert_original` 兩個旗標。
字幕視窗在雙語模式下改用 `NSAttributedString` 才能讓兩行有不同字級與濃度，
`max_lines` 在此代表**句數**而非顯示行數，視窗高度與 `setMaximumNumberOfLines_`
都要乘上 `lines_per_entry`。

`max_tokens` 隨輸入長度縮放。固定值會截斷長句，給太大則讓模型有空間開始胡言亂語 ——
ASR 輸出破碎時（吵雜、句子被切斷）LLM 特別容易自行補完內容。

## 逐字稿

`--log` 由副檔名決定格式（`.srt` → SRT 字幕，其餘 → 帶時間戳的純文字）。
SRT **不能寫註解標頭**，否則播放器解析會失敗，`TranscriptWriter` 只在純文字格式寫標頭。

時間軸從錄音執行緒啟動起算。`Segment` 帶著 `start` / `end`：語音在 VAD 判定結束的
當下取得 `end`，往回推音訊長度得到 `start`。往回推可能得到負數，格式化時要 clamp。

每句寫完就 flush —— 簡報中途當掉時已講的部分要保得住。寫檔失敗不可中斷辨識，
`_record()` 會回報一次錯誤後把 `transcript` 設為 None。

## 簡繁轉換

**預設配置是 `s2tw`，不是 `s2twp`，這是刻意的。**
`s2twp` 會做用語在地化（`软件`→`軟體`），那是書面翻譯的邏輯，套在逐字稿上會竄改
講者原話 —— ASR 是照發音轉寫的，講者說什麼字形轉換就能還原什麼。
而且 `s2twp` 會誤轉常用詞：「客语保存工作」→「客語**儲存**工作」。
`tests/test_postprocess.py` 有守住這件事，不要為了「臺灣用語比較道地」把預設改回去。

`postprocess.EXCEPTIONS` 在 OpenCC 之後還原「台語」—— OpenCC 把「台」一律轉成
「臺」，但官方寫法是「臺灣台語」（教育部 2024 年定名，刻意混用兩字）。
這張表**只放有官方依據的例外**，不要拿它做一般性的用詞替換，那正是我們不用
s2twp 的理由。

`--traditional auto` 的判斷在 `cli.wants_traditional()`。判斷依據是
**畫面上實際會顯示什麼語言**，所以有 `--translate-to` 時看的是目標語言而非辨識語言。
其餘關鍵規則：本地微調模型（例如客語）不做任何轉換，保留模型原始輸出；
`--task translate` 輸出英文，也不轉。

## 測試

`tests/` 不需要麥克風、不下載模型、跑完不到五秒：

- `test_vad.py` 用假的偵測器控制「哪個 frame 是語音」，測的是斷句狀態機
- `test_pipeline.py` 用假的麥克風與引擎，測執行緒、佇列滿載、錯誤處理、關閉流程、雙語
- `test_cli.py` 測參數解析、引擎選擇、簡繁轉換判斷、查詢指令
- `test_translate.py` 測提示組裝、LLM 輸出清理、術語表解析
- `test_overlay_style.py` 測字幕視窗的樣式計算與顏色解析（不建立視窗）

新增邏輯時沿用這個做法：**測我們自己寫的邏輯，不要測第三方模型的行為**。
需要真實音訊時可以用 macOS 內建的 `say` 產生，不要在 repo 裡塞音訊檔。

## 慣例

- 註解與 docstring 用**繁體中文**，與既有程式碼一致
- 註解說明「為什麼」，不要複述程式碼在做什麼
- 使用者看得到的訊息（錯誤、提示）也用繁體中文，
  錯誤訊息要附上**可執行的解法**（該改哪個系統設定、該下哪個指令）
- 型別註記用 `from __future__ import annotations` 搭配新式語法（`str | None`）
- 引擎與翻譯器的相依套件一律**延遲 import**，放在 `prepare()` 裡

### Commit

沿用既有格式：conventional commit 前綴 + 繁體中文說明。
破壞性變更用 `!`（例如 `refactor!:`）。訊息本文說明**為什麼**這樣改，
不要只列出改了哪些檔案 —— 那 diff 已經講得很清楚了。

## 容易誤判的地方

- **不要因為 `--task translate` 存在就以為所有引擎都能翻譯。**
  它是 Whisper 的內建能力，只能翻成英文。跨引擎的翻譯走 `--translate-to`。
- **不要把 `--model` 套用到 Apple 引擎。** 它沒有模型可選，
  註冊表的 `_apple()` 會主動丟掉這個參數。
- **不要在 pipeline 之外做音訊格式轉換。** float32/16 kHz/單聲道的正規化
  統一在 pipeline 邊界完成，引擎收到的一律是這個格式。
- **不要為了讓測試通過而放寬斷言。** VAD 的 frame 數計算用 `round`，
  測試的期待值也要用 `round`，不要改成剛好能過的數字。
