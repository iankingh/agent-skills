# agent-skills

A collection of AI agent skills I use, build, and discover.

收錄自己常用、自製或改編的 AI agent skills，以及網路上探索收集的技能資源。技能內容以繁體中文為主，每個 skill 使用獨立資料夾保存完整指令與相關檔案。

## 目錄結構

技能集中在 `skills/`，沿用 [OpenAI Skills](https://github.com/openai/skills) 與 [Anthropic Skills](https://github.com/anthropics/skills) 官方技能庫的收錄方式；外部專案則在 `external/` 保存上游完整結構。

```text
AGENTS.md                    # 專案代理工作規則
skills/
└── <skill-name>/
    ├── SKILL.md
    ├── agents/openai.yaml   # 選用：技能的顯示、呼叫與相依設定
    ├── scripts/             # 選用：技能使用的程式
    ├── references/          # 選用：補充文件
    └── assets/              # 選用：範本與資源
external/
├── ub-mode/                 # 上游專案完整副本
└── pstack/                  # 上游 pstack/ 完整副本，包含其 agents/ 與 skills/
externals.yaml               # 同步來源與人工維護的收藏資訊
externals.lock.json          # 已同步版本、檔案雜湊與權限
```

目前自製內容都是技能。未來收錄自製的獨立子代理時，本專案使用根目錄 `agents/<工具名稱>/` 保存定義，有實際內容才建立資料夾。這裡的 `skills/` 與未來的 `agents/` 是內容庫的收錄位置，實際安裝與載入位置依目標工具文件操作。維護本專案時，遵循 [AGENTS.md](AGENTS.md) 的作業規則。

## 技能索引

| Skill | 用途 | 來源 |
| --- | --- | --- |
| [obsidian-note-refiner](skills/obsidian-note-refiner/SKILL.md) | 依筆記類型整理指定 Obsidian Vault 的既有筆記，判斷輕修、重整或跳過，維持屬性規格、來源及雙向連結。 | 自製，共用版本 |
| [obsidian-literature-note-refiner](skills/obsidian-literature-note-refiner/SKILL.md) | 整理既有 Obsidian 文獻筆記的摘要、來源、作者、屬性、Markdown 與關聯導航；不處理新素材建頁或檔名批次分類。 | 自製，共用版本 |
| [literature-organizer](skills/literature-organizer/SKILL.md) | 依指定 Vault 慣例整理文獻筆記檔名、匯出識別碼、主題分類及重複候選，核對原稿並修復受影響連結。 | 自製，共用版本 |
| [tutor-setup](skills/tutor-setup/SKILL.md) | 將文件或程式碼轉成可追溯的學習筆記與練習，核對 PDF 圖表、章節索引與原文證據 | 自製，共用版本 |
| [obsidian-literature-note-enricher](skills/obsidian-literature-note-enricher/SKILL.md) | 補讀文獻、圖表與影片來源，核對作者、日期及實際閱讀範圍，區分原作、查核與整理者補充 | 自製，共用版本 |
| [code-review-workflow](skills/code-review-workflow/SKILL.md) | 依變更風險審查程式碼，驗證具體缺陷、去除重複意見並讓修正後複查收斂 | 自製 |
| [skill-research](skills/skill-research/SKILL.md) | 依工作需求搜尋與比較 Agent Skills，核對適配性、觸發重疊、維護證據、相依與資料流向，提出有來源的採用建議 | 自製 |
| [git-commit-content](skills/git-commit-content/SKILL.md) | 根據實際 Git 變更，產生、修改或檢查繁體中文提交訊息，區分 Conventional Commits 規格、專案規則與文字偏好 | 自製 |
| [obsidian-cli](skills/obsidian-cli/SKILL.md) | 操作指定 Vault，核對附件與 ZIP 的正式內容對照，依授權清理並修復連結 | 自製，共用版本 |
| [obsidian-journal-note-refiner](skills/obsidian-journal-note-refiner/SKILL.md) | 整理及還原歷史日誌，按內容去重，保留原日期、任務與計分狀態 | 自製，共用版本 |
| [ig-post-to-notes](skills/ig-post-to-notes/SKILL.md) | 整理 Instagram 單篇貼文與完整輪播，保留來源與提示詞；依要求存入 Obsidian | 自製，共用版本 |
| [yt-video-to-notes](skills/yt-video-to-notes/SKILL.md) | 將 YouTube 影片或播放清單轉成資料夾中的繁中 Markdown，單支一篇、清單建立總覽與章節；提供音訊長度核對、逐字稿分段、時間戳、繁中檢查與續作工具 | 自製，共用版本 |
| [obsidian-zettelkasten](skills/obsidian-zettelkasten/SKILL.md) | 整理文獻、永久筆記與 MOC，管理屬性及雙向連結；整套課程先沿用目的地課程結構分流 | 自製，共用版本 |

## 使用方式

### 安裝至 Codex

將想使用的**完整技能資料夾**複製到 Codex 的 skills 目錄，保留 `SKILL.md`、`agents/openai.yaml` 與技能包含的 `references/` 等支援檔案。以下指令在此 repo 根目錄執行，預設安裝至 `~/.codex/skills`；若有設定 `CODEX_HOME`，則使用該位置下的 `skills`。

先檢查目的地。同名技能若已存在，請先將原資料夾移到 skills 目錄之外的備份位置，再安裝，避免合併或覆寫現有設定。

```sh
skill_name=git-commit-content
skill_root="${CODEX_HOME:-$HOME/.codex}/skills"

if [ -e "$skill_root/$skill_name" ] || [ -L "$skill_root/$skill_name" ]; then
  printf '同名技能已存在，請先移出並備份：%s\n' "$skill_root/$skill_name"
else
  mkdir -p "$skill_root"
  cp -R "skills/$skill_name" "$skill_root/$skill_name"
fi
```

安裝其他技能時，將 `skill_name` 改為上表對應的資料夾名稱。Obsidian、IG 與 YT 共用版不預設個人筆記庫路徑；使用時指定目的地，分類、附件與備份政策沿用目標 Vault 的 `AGENTS.md` 或既有要求。Obsidian 相關技能可獨立使用，也可一併安裝；不需要同時安裝私人 Vault 的其他技能。

### 呼叫範例

依需求尋找或比較技能：

```text
使用 $skill-research，幫我找能完成〈工作需求〉的 Agent Skills。
目前使用〈代理／工具〉，請比較候選的適配性、維護證據、相依與資料流向，推薦最適合的一項。
```

也可提供單一 GitHub 技能連結，評估是否適合自己的情境。只要求研究或比較時不會安裝；已明確要求安裝指定項目時，沿用本次授權接續安裝流程。

根據目前變更產生提交訊息：

```text
使用 $git-commit-content 根據目前 Git 變更，產生符合 Conventional Commits 的繁體中文提交訊息。
```

此請求只產生訊息；實際提交或推送需另行要求。

整理 IG 貼文，在對話中取得筆記：

```text
使用 $ig-post-to-notes 整理這篇 IG 貼文的全部輪播與作者說明，逐項列出提示詞，直接在對話中提供筆記。
貼文連結：〈貼上 Instagram 貼文網址〉
```

整理並存入自己的 Obsidian 筆記庫：

```text
使用 $ig-post-to-notes 整理這篇 IG 貼文，並存入我指定的 Obsidian 筆記庫，沿用現有分類、格式及索引。
貼文連結：〈貼上 Instagram 貼文網址〉
筆記庫路徑：〈填入自己的筆記庫路徑〉
```

未提供或未確認筆記庫位置時，skill 會先詢問；僅要求整理貼文時不自行寫入 Obsidian。

整理 YouTube 影片，在對話中取得筆記：

```text
使用 $yt-video-to-notes 整理這支 YouTube 影片的重點與章節時間，註明實際讀取範圍，直接在對話中提供筆記。
影片連結：〈貼上 YouTube 影片網址〉
```

整理 YouTube 影片並存入一般資料夾：

```text
使用 $yt-video-to-notes 將這支影片整理成繁體中文 Markdown，存入指定資料夾下的「影片筆記」。
影片連結：〈貼上 YouTube 影片網址〉
目標資料夾：〈填入路徑〉
```

整理整份播放清單：

```text
使用 $yt-video-to-notes 整理這份播放清單，在指定的影片筆記目錄建立總覽與章節，記錄每集實際來源及缺口。
播放清單連結：〈貼上 playlist?list=... 網址〉
影片筆記目錄：〈填入路徑〉
```

需要寫入 Obsidian 時，可另外指定 Vault，沿用既有格式與索引。

整理並存入自己的 Obsidian 筆記庫：

```text
使用 $yt-video-to-notes 整理這支 YouTube 影片，存入我指定的 Obsidian 筆記庫，沿用現有格式，並更新既有 YT 總覽與適合的主題索引。
影片連結：〈貼上 YouTube 影片網址〉
筆記庫路徑：〈填入自己的筆記庫路徑〉
```

原文匯入已整理好的影片筆記：

```text
使用 $yt-video-to-notes 將這份已整理好的影片文稿原文匯入 Obsidian，保留完整標題與檔案內容，只加上影片前綴，不重新摘要或更新索引。
來源檔案：〈填入 Markdown 檔案路徑〉
筆記庫路徑：〈填入自己的筆記庫路徑〉
```

明確只複製、只改名或要求逐位元保留時，不加寫內容並比對雜湊。一般匯入保留正文、程式碼、表格、外部來源及閱讀限制，只做已授權或目標專案明訂的必要屬性、匯出連結及導航轉換，分開驗證保留內容與預期變更；不因同影片就合併原稿。只有明確要求重整時才套用新正文模板。

整套課程先查既有課程資料夾與模板，沿用首頁、章節及教材層級；課程數與文獻數分開計算，匯入完成不能推定已學完。`obsidian-zettelkasten` 也先做課程分流，再處理獨立文獻或永久筆記。

YT 技能以一般資料夾與 Markdown 為預設，僅在要求寫入時建立檔案；Obsidian 為選用目的地。純播放清單連結依清單處理，單支網址附帶的播放清單參數不會擴大範圍。來源不完整時揭露缺口，不保證每支影片都能取得字幕；不需 Notion。

### 附件清理與歷史日誌還原

```text
使用 $obsidian-cli 核對我指定 Vault 的附件與 ZIP，建立原檔到正式筆記的對照。
依我的清理範圍處理；區分完整收錄、只有摘要及獨有歷史版本，更新受影響連結。
```

```text
使用 $obsidian-journal-note-refiner 將這份備份中的舊日誌還原到原日期。
先比對現有日誌與候選副本，內容相同只還原一份，保留任務與勾選狀態。
```

附件判定以內容及已確認對照為準；有對應頁面不代表舊版與現有內容逐位元相同。ZIP 的清理或保留遵循當次要求，不為已依使用者意圖清理的檔案自動補建備份。日誌還原不重新配發任務，也不為補齊導航自動建立空日誌或週計畫。

### YT 輔助工具與驗證

- `build.py`：將草稿標記轉成影片時間戳及相對 Markdown 連結（另支援 Obsidian），以來源與 SHA-256 記錄章節，檢查缺集與續作狀態。
- `sources.py`：核對 WAV 實際樣本長度或 ffprobe 音訊長度，並按秒數區間讀取 SRT、VTT 與 JSON 逐字稿；不把長度相符當成內容已驗證。
- `chk.py`：唯讀檢查新撰寫內容中的疑似簡體與台灣用語，保留原文供人工判讀。

工具需 Python 3.10 以上；`chk.py` 另需 `opencc-python-reimplemented`。安裝方式與指令詳見 [YT 工具說明](skills/yt-video-to-notes/references/tools.md)。這些工具不套用於原文匯入。

確認 `python3 --version` 為 Python 3.10 以上，再從 repo 根目錄建立虛擬環境、安裝固定版本的依賴並執行完整測試：

```sh
python3 -m venv .venv
.venv/bin/python -m pip install -r skills/yt-video-to-notes/requirements.txt
.venv/bin/python -B -m unittest discover -s skills/yt-video-to-notes/tests -v
```

完整測試包含 OpenCC 整合案例；缺少依賴會失敗，不再跳過。`.venv/` 已排除於 Git，日後重跑可直接使用最後一行指令。

## 收錄慣例

- **自製或改編技能**：放在 `skills/<skill-name>/`，保存完整技能資料夾。README 記錄用途與來源；改編版本另註明原始連結、版本或 commit，以及修改內容，並保留適用的原作者授權與署名。
- **技能附屬設定**：`skills/<skill-name>/agents/openai.yaml` 依 [OpenAI 文件](https://learn.chatgpt.com/docs/build-skills) 隨技能保留，設定顯示資訊、呼叫政策、預設提示詞與工具相依；它不是獨立子代理定義，安裝技能時一併保留。
- **自製獨立子代理**：未來放在根目錄 `agents/<工具名稱>/`，依工具格式保存，並在 README 記錄用途、適用工具及安裝位置。不同工具各自維護定義，例如 [Claude Code](https://code.claude.com/docs/en/sub-agents) 的 `.claude/agents/` 與 [Cursor](https://cursor.com/docs/subagents) 的 `.cursor/agents/`；不預設同一份定義可跨工具通用，也不預先建立空資料夾。
- **外部收藏**：以 `externals.yaml` 記錄來源、追蹤範圍、用途、收藏理由與試用狀態，原始檔案同步至 `external/<name>/`；`externals.lock.json` 保存 commit、檔案 SHA-256 與可執行權限，保留上游提供的授權與署名。`external/` 僅同步上游，完整保留原有路徑與結構，不將其中的技能、代理或其他元件抽出、搬移或重新分類。
- **來源標示**：區分自製、改編與外部收藏；未實際試用的項目標示「待試用」，不宣稱已驗證。

## 外部收藏

外部專案的原始檔案保存在 `external/`，包含技能、代理、圖片、文件及上游提供的授權檔；這些副本尚未安裝到個人技能目錄，安裝與相依工具請依原始專案文件操作。

下表由 `externals.yaml` 與 lock 檔產生；中文介紹、收藏理由與試用狀態請修改 YAML，再執行 `render`。

<!-- EXTERNALS:START -->

| 項目與同步副本 | 用途 | 收藏理由 | 試用狀態 | 同步版本 |
| --- | --- | --- | --- | --- |
| [ub-mode](external/ub-mode/README.md) · [上游](https://github.com/unclebob/ub-mode) | 強調 TDD、重構與品質檢查的工程紀律 Skill，結合 Crapper、Dryer、Mutator 檢視複雜度、重複與測試品質 | 將「先做對行為、再改善結構」整理成可重複使用的開發流程，適合研究如何把品質要求轉成具體檢查 | 待試用 | [3da62bf](https://github.com/unclebob/ub-mode/commit/3da62bf3fcfd2034de41f30d920d2739e566171f) |
| [pstack](external/pstack/README.md) · [上游](https://github.com/cursor/plugins/tree/main/pstack) | 以 `/poteto-mode` 串接任務規劃、開發、驗證與多代理協作的工作流外掛；主要使用環境為 Cursor，另有官方 Claude Code 適配說明 | 依任務選擇工作流程，並把設計、平行探索、審查與實際驗證串在一起，適合研究完整的代理工作流 | 待試用 | [bf0c7cd](https://github.com/cursor/plugins/commit/bf0c7cd80abdbf7fe47b634978a7d1b4071f71a7) |

<!-- EXTERNALS:END -->

### 更新外部專案

每天台北時間 **09:17** 檢查上游（UTC 01:17），也可以在 GitHub Actions 的 **Sync external projects** 手動執行。同步透過 Git fetch 取得來源，將 agent-skills 的原有提交和上游原始提交一併保留在 Git 歷史中。有變更時建立或更新 `codex/sync-external-skills` PR，審核後以 **Create a merge commit** 合併。pstack 的工作目錄只收錄 `cursor/plugins` 的 `pstack/`，Git 歷史保留來源提交完整的父系。

同步流程會先核對現有副本，準備好各來源的 Git tree 和版本鎖定資訊後才更新分支。本機副本有手動修改或 fetch 失敗時停止。上游內容只供收錄，試用狀態仍由人工維護。

本機操作需 Git、完整的 clone 與 Python 3.10 以上。從乾淨的 Git 工作目錄執行，`update` 有變更時會建立同步提交：

```sh
.venv/bin/python -m pip install -r requirements-sync.txt
.venv/bin/python -B scripts/sync_externals.py update
.venv/bin/python -B scripts/sync_externals.py check --history
```

只修改中文介紹與試用狀態時，離線更新表格：

```sh
.venv/bin/python -B scripts/sync_externals.py render
.venv/bin/python -B scripts/sync_externals.py check
```

排程需將 workflow 放到預設分支，並在儲存庫設定允許 GitHub Actions 建立 PR；完整設定、驗證、失敗處理及版本重現方式見 [外部同步說明](docs/external-sync.md)。
