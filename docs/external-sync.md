# 外部專案同步

原始來源由 `externals.yaml` 管理；副本放在 `external/<name>/`，不改寫上游檔案。自製技能仍放在 `skills/`。下載與校驗不會執行外部 Skill、腳本或安裝程式，也不會安裝到個人環境。

## 同步與自製內容的邊界

- `external/` 僅同步上游，完整保留追蹤範圍內的原有路徑與結構，不將 Skills、Agents、文件、資源或外掛設定抽出、搬移或重新分類。上游新增、刪除或搬移檔案時，依既有同步流程反映該版本的結構。
- pstack 的 `agents/` 與 `skills/` 保留在 `external/pstack/` 內，讓上游外掛設定中的相對路徑維持有效；不搬到本專案根目錄的 `agents/` 或 `skills/`。
- 自製技能放在 `skills/<skill-name>/`；技能內的 `agents/openai.yaml` 是附屬設定，隨技能保留。未來新增自製獨立子代理時，另放在根目錄 `agents/<工具名稱>/`，有實際內容才建立，並記錄工具所需的安裝位置。完整規則見 [README 收錄慣例](../README.md#收錄慣例)。

## 已收錄來源

| 名稱 | 來源與範圍 | 必須保留的內容 |
| --- | --- | --- |
| ub-mode | `unclebob/ub-mode` 的 `master`，整個專案 | README、SKILL，以及未來上游加入的其他一般檔案 |
| pstack | `cursor/plugins` 的 `main`，完整 `pstack/` | Skills、agents、assets、docs、automations、外掛設定與 LICENSE |

同步工具用 `git fetch` 取得來源分支。ub-mode 使用分支最新提交。pstack 使用 `git log` 查詢最近一次影響 `pstack/` 的提交，工作目錄只放入該提交的 `pstack/` Git tree。其他外掛的變更不會單獨觸發同步。

同步提交的第一個 parent 是 agent-skills 同步前的 HEAD，其餘 parent 是本分支尚未納入的上游原始提交。原始 SHA、作者與父系歷史都會保留。由於 pstack 來自 monorepo，保留原始 SHA 也會帶入該提交所能到達的 monorepo 歷史與 Git 物件。用 `git log --first-parent` 可以查看 agent-skills 自身的提交及每次同步。

`externals.lock.json` 記錄每項來源的 repository、ref、path、commit、上游提交時間，以及全部一般檔案的 SHA-256 和可執行權限。這些是來源版本與完整性資訊，不代表已試用或驗證技能效果。中文簡介、收藏理由及試用狀態只取自人工維護的 YAML，不從上游自動改寫。

同步保留上游檔案原始位元組及可執行標記，包含二進位圖片與隱藏設定；不重新摘要、翻譯或格式化。保留來源提供的授權資訊；未提供授權檔時不替上游補上授權宣告，也不將自製內容的授權套用到外部檔案。同步來源與本機安裝分開處理，實際使用依各專案文件及授權條件確認。

## 每日更新與啟用

- Workflow：`.github/workflows/sync-externals.yml`，名稱 **Sync external projects**。
- 每天台北時間 09:17（UTC 01:17）排程執行，實際啟動時間可能延遲。也可按 **Run workflow** 手動執行。
- Workflow 必須存在於儲存庫預設分支，才會按週觸發。手動執行也限定預設分支。
- GitHub 儲存庫 **Settings → Actions → General → Workflow permissions** 需允許 Actions 建立 PR。Workflow 只宣告來源分支寫入與 PR 寫入所需權限，使用內建 `GITHUB_TOKEN`，不需要個人 PAT。
- 更新完成後先執行 `check --history`，再直接把同步提交推到 `codex/sync-external-skills` 並建立或更新 PR，附上來源比較與檔案增刪改數量。首次從快照遷移時，即使檔案相同也會為缺少的 Git 歷史建立提交。後續來源版本及歷史一致時不建立新提交或 PR。
- 審查後請用 **Create a merge commit** 合併同步 PR。Squash 或 rebase 會使原本的上游提交失去通往預設分支的父系關係。儲存庫須允許 merge commits。參見 [GitHub PR 合併方式](https://docs.github.com/en/pull-requests/reference/pull-request-merges)。
- 同一時間只執行一個同步 workflow，避免排程與手動操作同時更新同一分支。PR 已合併且沒有新差異時，後續執行會清理這支機器人分支。
- GitHub 公開儲存庫若長時間沒有活動，排程可能被停用；可在 Actions 頁面重新啟用。完整規則見 [GitHub 排程文件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

一般 PR 與推送至 main 時會執行 **Check external snapshots**。同步 job 在開 PR 前會執行測試、快照校驗及上游歷史驗證。

## 本機操作

從完整的 Git clone 與乾淨的工作目錄執行。依 README 建立 `.venv`，再安裝固定版本同步依賴：

```sh
.venv/bin/python -m pip install -r requirements-sync.txt
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B scripts/sync_externals.py update
.venv/bin/python -B scripts/sync_externals.py check --history
```

`update` 從 GitHub 公開 Git remote 下載來源提交，將來源分支暫存於本機 `refs/externals/<name>`，並在目前分支建立同步提交。使用本機 Git 的作者與提交者設定，不會推送。若只想準備同步 PR，可先切到自己的同步分支再執行。

`check` 完全離線，核對全部檔案、權限、必要檔案、來源設定與 README 生成區塊。`check --history` 額外核對 lock 中的上游 SHA 是否為 HEAD 的祖先，以及提交中的快照 Git tree 是否完全相同。`render` 只依 YAML 和 lock 產生 README 表格；標記區外的原文不變。

需要另外產生供審查的摘要時，將輸出放在儲存庫外：

```sh
.venv/bin/python -B scripts/sync_externals.py update --report /tmp/agent-skills-update.md
```

## 失敗與版本重現

- 現有副本有新增、修改、刪除、權限變更或軟連結：停止更新。先把需要保留的本機修改移到其他位置；自行改編的版本放進 `skills/` 並記錄來源，避免直接改同步副本。
- 目的地已存在但未被 lock 管理：停止，不覆蓋使用者檔案。
- 上游 fetch 失敗、路徑消失或必要檔案缺少：整輪失敗，保留原分支、副本與 lock。所有 Git tree 和同步提交先準備及校驗，再以 fast-forward 更新工作目錄與分支。
- 上游刪除檔案：更新到新 commit 時一起移除該來源副本的舊檔；從 YAML 移除整項來源時，也只移除 lock 所管理且未被手動修改的副本。
- 來源 Git tree 含符號連結、submodule 或超出檔案數與大小限制：停止同步。直接匯入追蹤中的 Git tree，因此也收錄上游已追蹤、後來符合 `.gitignore` 的檔案。
- 要查看上游提交，可用 lock 中的 SHA 執行 `git show <commit>`。要還原某次同步的副本，可用 agent-skills 的第一父系歷史找到對應的同步提交與 `external/`、lock、README。
