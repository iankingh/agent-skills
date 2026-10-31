# 新筆記的檢查與建置工具

只用於新撰寫或明確要求重整的筆記。原文匯入不跑內容建置或字詞修正；無必要轉換時比對原始位元組，有連結或屬性轉換時分開驗證保留正文與預期變更，詳見 [匯入規則](obsidian.md#原文匯入與必要轉換)。下方指令以技能目錄為工作目錄；資料與輸出路徑由當次任務決定。

## 繁中與台灣用語：chk.py

使用 Python 3.10 以上；先以 `python3 --version` 確認版本。`chk.py` 需要 `requirements.txt` 固定版本的 `opencc-python-reimplemented`。如缺少套件，在適合的虛擬環境安裝，不改系統 Python：

```sh
python3 -m venv /tmp/yt-notes-check
/tmp/yt-notes-check/bin/python -m pip install -r requirements.txt
/tmp/yt-notes-check/bin/python scripts/chk.py /path/to/new-note.md
```

可加 `--json` 取得含檔名、行、欄、原字詞及建議的報告。使用 OpenCC `s2t` 找字形差異，另檢查指定的台灣用語；不套用自動全文轉換。共同字形的實際含義仍由整理者判斷。

- 退出碼 `0`：未找到可疑項目；不保證語意正確。
- 退出碼 `1`：有疑似簡體、用語或常見誤報候選，逐項判讀；判定原文正確時可保留並記錄判斷，不必為求零警告改錯字。
- 退出碼 `2`：缺依賴、檔案不可讀或其他錯誤，檢查未完成。

檢查略過 frontmatter、Markdown 程式碼區塊、行內程式碼、HTML code/pre、網址、連結目的地與 HTML 標籤。這是保守的文字掃描器，不是完整 Markdown 語意分析器；巢狀縮排、原文引述、專有名詞仍需閱讀核對。

## 時間戳與筆記連結：build.py render

只需 Python 標準函式庫。輸入是草稿 Markdown；輸出是另一個 Markdown 檔，不能覆寫輸入。輸出已存在時預設報錯，經確認可取代的生成檔才加 `--overwrite`。

```sh
python3 scripts/build.py render /path/to/draft.md \
  --video 'https://www.youtube.com/watch?v=e0UOuQ_lCUY&list=example&index=1' \
  --map /path/to/mappings.json \
  --notes-root '/path/to/影片筆記' \
  --output '/path/to/影片筆記/課程/章節/01-筆記.md'
```

`--video` 接受影片 ID 或 YouTube watch／youtu.be／Shorts／live／embed 網址；只取該支影片 ID，不抓取或展開播放清單。`--map`、筆記根目錄只在相應標記需要時提供。程式碼與 frontmatter 中的標記保留為原文。

一般資料夾使用 `--notes-root`，預設產生相對於 `--output` 所在目錄的 Markdown 連結，保留 `.md` 並編碼路徑字元。Obsidian 使用 `--vault /path/to/vault --link-style obsidian`；相容舊指令，單獨指定 `--vault` 仍產生 wiki links。兩種根目錄參數擇一，明確的 `--link-style markdown` 可覆寫舊模式；不需安裝 Obsidian。

```json
{
  "episodes": {
    "1": "https://www.youtube.com/watch?v=e0UOuQ_lCUY",
    "2": "https://www.youtube.com/watch?v=e3DDXSMWr5w"
  },
  "mentions": {
    "solid": "notes/SOLID 設計原則"
  }
}
```

上例僅展示映射格式，不表示這兩支影片屬於同一課程。實際集數只依使用者指定的課程建立。

| 標記 | 結果 |
| --- | --- |
| `{{1:05}}` | 預設影片的 `[1:05](…&t=65s)` |
| `{{2@3:04}}` | 第 2 集的 `[第 2 集 3:04](…&t=184s)` |
| `{{ep:2}}` | `[第 2 集](第 2 集影片網址)` |
| `@@solid` | 對應實際筆記的 `[筆記名稱](相對路徑.md)`；Obsidian 模式為 `[[vault 相對路徑]]` |

分鐘可超過 59，秒數限 00–59。映射鍵使用英數字、底線或連字號；集數使用無前導零的正整數。筆記映射使用無副檔名的檔名或筆記根目錄相對路徑（也接受 `.md`）；Obsidian 模式不包含 alias 或段落。根目錄內必須有唯一對應檔案，不能用 `..` 或符號連結指向根目錄之外。缺少來源、缺少筆記、歧義或殘留標記以退出碼 `2` 報錯，且不產生輸出。

## 音訊量測與逐字稿閱讀：sources.py

只需 Python 標準函式庫，非 WAV 音訊另需 PATH 中的 ffprobe。唯讀，不下載影片、不呼叫辨識模型、不寫入筆記：

```sh
python3 scripts/sources.py audio /path/to/audio.wav --expected-seconds 120 --tolerance-seconds 5
python3 scripts/sources.py slice /path/to/subtitles.vtt --start 0 --end 60
```

`audio` 對 PCM WAV 讀取實際樣本數並偵測截斷；其他格式以 ffprobe 量測。長度相符退出 `0`、不符退出 `1`、無法量測退出 `2`。報告的 `content_verified` 固定為 `false`，還要抽查是否為廣告、重複或下一支影片。

`slice` 支援 SRT、VTT、區段 JSON，輸出重疊區段且保留原始時間；時間錯誤、空逐字稿或不支援格式退出 `2`，沒有重疊區段時輸出空陣列。格式、媒體取得、可選 ASR 及來源缺口記錄見 [media.md](media.md)。

## 播放清單完成紀錄與續作

這些指令不建立筆記、不判定內容品質。人工確認內容、時間來源、繁中與連結後，才記錄完成狀態：

```sh
python3 scripts/build.py record /path/to/chapter.md \
  --episodes 1-3 --map /path/to/mappings.json \
  --log '/path/to/batch/created.txt'

python3 scripts/build.py check \
  --expected 1-12 --map /path/to/mappings.json \
  --log '/path/to/batch/created.txt'
```

`created.txt` 是 UTF-8 JSON Lines，每行含 `path`（絕對路徑）、`episodes`（連續集數）、`sources`（影片網址對照）及 `sha256`。放在輸出筆記目錄外的本批工作區；續作使用同一份映射和紀錄。完成後將來源對照與驗收結果收斂為 Markdown 再依目標政策清理，不因工具輸出就新增正式筆記目錄內的 JSON／TXT 檔。來源實際取得範圍另記在筆記與總覽，機器紀錄不代表影片已完整讀取。

- `record` 再次記錄相同內容會跳過；重複涵蓋其他章節或檔案內容與舊紀錄不同時報錯。
- 已修改或搬移的章節須重新人工驗收，移除該行舊紀錄，再以新路徑 `record`。不能只修改雜湊來掩蓋尚未驗收的變更。
- `check` 只接受明確的集數或連續範圍。檢查漏集、範圍外集數、來源映射、檔案存在及雜湊；缺少內容退出 `1`，錯誤紀錄退出 `2`，全部一致退出 `0`。
- 部分完成時顯示缺集是預期結果；補完後再更新課程總頁的章節表格與完成狀態。工具無法證明映射是否等於遠端播放清單，仍須用實際清單來源確認。

## 維護工具時

```sh
/tmp/yt-notes-check/bin/python -B -m unittest discover -s tests -v
```

先完成前述虛擬環境與依賴安裝；完整測試包含 OpenCC 整合案例，未安裝會失敗，不再跳過。若使用其他虛擬環境，將指令中的 Python 路徑換成該環境。測試只在暫存目錄建立資料，不寫入使用者的筆記庫。

