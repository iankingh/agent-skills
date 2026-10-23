# agent-skills

A collection of AI agent skills I use, build, and discover.

收錄自己常用、自製或改編的 AI agent skills，以及網路上探索收集的技能資源。技能內容以繁體中文為主，每個 skill 使用獨立資料夾保存完整指令與相關檔案。

## 技能索引

| Skill | 用途 | 來源 |
| --- | --- | --- |
| [git-commit-content](skills/git-commit-content/SKILL.md) | 根據實際 Git 變更，產生、修改或檢查繁體中文提交訊息，區分 Conventional Commits 規格、專案規則與文字偏好 | 自製 |
| [ig-post-to-notes](skills/ig-post-to-notes/SKILL.md) | 整理 Instagram 單篇貼文與完整輪播，保留來源與提示詞；依要求存入 Obsidian | 自製，共用版本 |
| [yt-video-to-notes](skills/yt-video-to-notes/SKILL.md) | 將 YouTube 影片整理成繁體中文重點筆記，保留章節時間與查核範圍；依要求存入 Obsidian 並更新既有索引 | 自製，共用版本 |

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

安裝 IG 或 YT 技能時，將 `skill_name` 改為 `ig-post-to-notes` 或 `yt-video-to-notes`。本 repo 的 IG 與 YT 版本不預設個人筆記庫路徑；使用時指定目的地，分類與索引沿用該筆記庫的慣例。

### 呼叫範例

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

整理並存入自己的 Obsidian 筆記庫：

```text
使用 $yt-video-to-notes 整理這支 YouTube 影片，存入我指定的 Obsidian 筆記庫，沿用現有格式，並更新既有 YT 總覽與適合的主題索引。
影片連結：〈貼上 YouTube 影片網址〉
筆記庫路徑：〈填入自己的筆記庫路徑〉
```

YT 技能僅在要求寫入時存入筆記庫；索引與備份位置依既有慣例或使用者指定。播放清單參數不會自動擴大成整個清單，取得內容不完整時會說明缺漏，不保證每支影片都能取得字幕。

## 收錄慣例

- **自製或改編**：放在 `skills/<skill-name>/`，保存完整技能資料夾。README 記錄用途與來源；改編版本另註明原始連結、版本或 commit，以及修改內容，並保留適用的原作者授權與署名。
- **外部收藏**：先在下方記錄原始連結、用途、收藏理由與試用狀態；確認需要維護自己的版本時，再依來源授權收錄完整檔案。
- **來源標示**：區分自製、改編與外部收藏；未實際試用的項目標示「待試用」，不宣稱已驗證。

## 外部收藏

目前尚未收錄外部 skills。
