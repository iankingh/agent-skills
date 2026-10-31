# 媒體取得、音訊驗證與分段閱讀

需要取得音訊、處理字幕／語音辨識或核對來源範圍時讀本檔。先確認可用工具、來源存取與本批工作區，避免把暫存音訊或憑證寫進正式筆記與共用技能。

## 取得中繼資料、字幕與音訊

優先使用當前環境的連接器或字幕工具；YouTube oEmbed 可取標題、頻道，發布日期、長度與章節另由頁面／工具核對。頁面欄位會改變，不把 HTML 欄位名當成穩定 API；缺資料就標未取得。

若環境已有 `yt-dlp`，可依[官方選項](https://github.com/yt-dlp/yt-dlp#usage-and-options)使用下列指令。單支影片一律 `--no-playlist`；清單的順序與影片清單先另行核對，再逐集處理。先用 `yt-dlp --version` 記錄版本，選擇實際可用語言；`zh.*,en.*` 只是候選。以下路徑與網址都換成當次任務實值：

```sh
yt-dlp --no-playlist --skip-download --write-info-json \
  --write-subs --write-auto-subs --sub-langs 'zh.*,en.*' --sub-format vtt \
  --no-overwrites -o '/path/to/batch/%(id)s.%(ext)s' \
  'https://www.youtube.com/watch?v=VIDEO_ID'

yt-dlp --no-playlist -f 'bestaudio/best' --no-overwrites \
  -o '/path/to/batch/%(id)s.%(ext)s' \
  'https://www.youtube.com/watch?v=VIDEO_ID'
```

無字幕才需要音訊。取檔失敗或需要登入時，依現有工具與登入流程處理；不繞過存取限制、不自動讀取瀏覽器憑證。瀏覽器擷取只有在可用工具明確支援時採用，不假定存在舊環境的 `hook.js`、`grab.sh`、`pull.sh` 或注入 API。

## 轉檔與長度核對

環境已有 FFmpeg 時記錄 `ffmpeg -version`，按[官方音訊選項](https://www.ffmpeg.org/ffmpeg.html#Audio-Options)轉成語音辨識可讀的 16 kHz 單聲道 PCM WAV。`-n` 拒絕覆寫既有輸出，`-nostdin` 適用背景任務：

```sh
ffmpeg -nostdin -n -i /path/to/batch/input.webm \
  -vn -ac 1 -ar 16000 -c:a pcm_s16le /path/to/batch/audio.wav

python3 scripts/sources.py audio /path/to/batch/audio.wav \
  --expected-seconds 1234 --tolerance-seconds 5
```

指令從技能目錄執行。`expected-seconds` 必須來自已核對的影片片長，不填預計抓取時間。`sources.py` 的 PCM WAV 路徑會逐塊讀實際音訊樣本，核對與檔頭宣告樣本數一致；其他格式呼叫 [ffprobe](https://www.ffmpeg.org/ffprobe.html)。不支援的 WAV 格式先轉 PCM，不略過錯誤。

輸出 JSON 包含實測秒數、影片秒數、差異與 `duration_matches`；預設容許差距為 5 秒，可依已確認的片頭／片尾差異調整。退出碼 `0` 僅表示長度在容許差距內，`1` 為長度不符，`2` 為截斷、空檔、缺 ffprobe 或其他無法量測情況。`content_verified` 永遠為 `false`，內容仍需抽查。

轉錄前檢查開頭，並核對中段與結尾的語言、講者、主題及畫面。長度相同仍可能是廣告、重播或另一支影片；錯誤音訊標無效並隔離，不送完整辨識或寫成成功來源。自動播放下一支或重複擷取時，保留原素材供核對，只對已確認的有效範圍另存處理檔。

## 語音辨識與分段閱讀

可用環境既有的語音辨識工具；本技能不固定模型。若採用 [SenseVoice 的 sherpa-onnx 方案](https://k2-fsa.github.io/sherpa/onnx/sense-voice/index.html)，依其官方模型與 Python 範例準備 SenseVoice、Silero VAD、tokens 及相依。模型來源、檔名與雜湊必須來自實際下載，不能只留下舊環境的 `/data/sv/sv.py` 或硬編碼的 `LD_LIBRARY_PATH`。不得宣稱此技能已附模型或已實測該辨識引擎。

輸出有真實區段時間的 SRT、VTT 或 JSON，再分段閱讀，不將長片逐字稿一次印出：

```sh
python3 scripts/sources.py slice /path/to/batch/transcript.vtt --start 0 --end 600
python3 scripts/sources.py slice /path/to/batch/transcript.json --start 600 --end 1200
```

JSON 可為 `[{"start": 0, "end": 8.5, "text": "原文"}]` 或 `{"segments": [...]}`；每段可用 `duration` 取代 `end`。秒數須有限且遞增，沒有時間資料的純文字不能推測時間。回傳與閱讀區間重疊的完整字幕區段，保留原始起訖，不把篩選邊界當成新的來源時間。沒有重疊區段時回傳空陣列，不能據此判定該段有內容或已讀完；可能是靜音、VAD 排除或來源缺漏，須另核對。

VTT／SRT 會移除字幕顯示標籤以方便閱讀，原檔不變；滾動字幕可能重複，人工按時間軸整理，不把文字重複當成講者重複論點。背景辨識保留確切程序識別、log 及完成狀態；只處理已寫完的輸出，不廣泛終止其他程序。

## 備援與來源紀錄

同課程備援先核對講者、授課內容、集數與分 P；記錄對照，不因主題相近就取代原片。每集在筆記／總覽保存以下資料，未知項目明記：

| 影片／集數 | 要求區間 | 實際來源與方法 | 已取得區間 | 未取得／略過區間與原因 | 時間軸對照 |
| --- | --- | --- | --- | --- | --- |
| 原始標題與影片 ID | 全片或指定範圍 | 字幕、語音辨識、備援或畫面 | 依實際來源填寫 | 失敗、業配或尚待核對 | 原片／備援與偏移證據 |

分開標示「尚未取得」「取得但未閱讀」「內容無法核對」與「已確認的靜音／業配」。原片與備援未對齊時使用實際備援連結或粗略定位說明，不虛造 YouTube 時間戳。另作外部補充標「（筆記補充）」並附來源，不能補成講者原意。

## 保存與還原工具

本技能已保存 `scripts/build.py`、`scripts/chk.py`、共用 Markdown 掃描器及 `scripts/sources.py`，只依賴 Python 標準函式庫；繁中檢查另需 `requirements.txt` 的固定版 OpenCC，非 WAV 量測另需 ffprobe。完整命令與退出碼見 [tools.md](tools.md)。本機測試涵蓋樣本數、截斷與長度不符、字幕分段、連結及續作；這些測試不代表已實測 YouTube 取檔或語音辨識。

若某次任務新增擷取、轉檔或辨識腳本，將可重用程式及必要說明保存到技能或使用者指定的工具包，記錄實際檔名、完整命令、輸入／輸出、環境變數、套件與系統需求、品質檢查、已知限制及測試日期。模型不必打包大檔，但要記錄名稱／版本、官方下載來源、所需檔案與實際 SHA-256；不包憑證、登入狀態、私人路徑或無關音訊。

在新的暫存位置複製工具包，使用已有測試素材驗證還原、執行及輸出。未實際測試的下載／ASR 部分標「未實測」，未打包或未通過還原測試的新增腳本標「待完成」，不能宣稱工具已永久保存或換環境即可運作。

以上官方選項與方案於 2026-11-01 查核；影片與模型是否可取得以執行當次為準。本技能未附舊環境的音訊攔截腳本、語音模型或媒體下載二進位檔。
