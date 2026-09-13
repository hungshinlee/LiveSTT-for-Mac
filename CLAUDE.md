# CLAUDE.md

給在這個 repo 工作的 Claude Code 的指引。

## 專案是什麼

Apple Silicon Mac 上的離線即時語音轉文字。麥克風 → Silero VAD 斷句 → 辨識引擎 → 輸出。
可選三種辨識引擎（Whisper / macOS 內建 / Qwen3-ASR），兩種輸出（終端機 / 浮動字幕視窗）。

**這是 macOS 專用專案**，且依賴 Apple Silicon（MLX）與多個 PyObjC 框架。不必為其他平台保留相容路徑。

## 常用指令

```bash
uv pip install -e ".[all,dev]"   # 安裝（含三個引擎與測試工具）
uv run pytest                    # 跑測試（快、不需麥克風、不下載模型）
uv run livestt --list            # 列出引擎與模型
uv run livestt --help            # 全部參數
```

## 架構

只有兩個抽象，其餘都是實作細節：

- **`STTEngine`**（`livestt/engines/base.py`）— 辨識引擎。
  生命週期是 `prepare()` → 多次 `transcribe()` → `close()`。
  `prepare()` 在背景執行緒中呼叫，可以耗時數秒（載模型、要權限）。
- **`Sink`**（`livestt/ui/base.py`）— 輸出端。`on_text` / `on_status` / `on_error`。

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

**`AppHelper.runEventLoop()` 不會返回，連 `atexit` 都不執行。**
PyObjC 的 `stopEventLoop()` 在找不到 RunLoopStopper 時走 `NSApp.terminate_()`，
直接在 Objective-C 層結束行程，繞過整個 Python 清理機制。
所以**收尾工作一定要在停止事件迴圈之前做完** —— 寫在 `sink.run()` 之後的程式碼形同不存在。
這就是 `OverlaySink.run()` 有 `on_stop` 參數的原因，也是 overlay 模式自己裝 SIGINT handler
（而非用 `installInterrupt=True`）的原因：讓 Ctrl+C 也走同一條收尾路徑。
`cleanup()` 因此必須是冪等的。

## 各引擎的能力差異

改動與這些有關的邏輯時要記得：

- **只有 Whisper 能翻譯**，而且只能翻成英文。`create_engine()` 會擋掉其他引擎的
  `--task translate`，這是刻意的，不要改成靜默忽略。
- **熱詞機制三家不同**：Qwen 原生 `hotwords`、Apple 用 `contextualStrings`、
  Whisper 只有 `initial_prompt`（提示條件化，效果較弱且提示過長會誘發幻覺）。
  對外統一成一個 `--hotwords` 參數。
- **Apple 沒有模型可選**，`--model` 對它無意義，註冊表的 `_apple()` 會把它丟掉。
- **Qwen 認英文語言名稱**（`"Chinese"`）不是 ISO 代碼，見 `qwen_mlx.LANGUAGE_NAMES`。
  Apple 要完整 locale（`zh-TW`），Whisper 要主語言碼（`zh`）。各自在引擎內轉換。

## 簡繁轉換

`--traditional auto` 的判斷在 `cli.wants_traditional()`。關鍵規則：
**本地微調模型（例如客語）不做任何轉換**，保留模型原始輸出；翻譯任務輸出英文，也不轉。

## 測試

`tests/` 不需要麥克風、不下載模型、跑完不到五秒：

- `test_vad.py` 用假的偵測器控制「哪個 frame 是語音」，測的是斷句狀態機
- `test_pipeline.py` 用假的麥克風與引擎，測執行緒、佇列滿載、錯誤處理、關閉流程
- `test_cli.py` 測參數解析與引擎選擇邏輯

新增邏輯時沿用這個做法：**測我們自己寫的邏輯，不要測第三方模型的行為**。
需要真實音訊時可以用 macOS 內建的 `say` 產生，不要在 repo 裡塞音訊檔。

## 慣例

- 註解與 docstring 用**繁體中文**，與既有程式碼一致
- 註解說明「為什麼」，不要複述程式碼在做什麼
- 使用者看得到的訊息（錯誤、提示）也用繁體中文，錯誤訊息要附上可執行的解法
- 型別註記用 `from __future__ import annotations` 搭配新式語法（`str | None`）
