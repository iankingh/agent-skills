# 外部專案同步

原始來源由 `externals.yaml` 管理；副本放在 `external/<name>/`，不改寫上游檔案。自製技能仍放在 `skills/`。下載與校驗不會執行外部 Skill、腳本或安裝程式，也不會安裝到個人環境。

## 已收錄來源

| 名稱 | 來源與範圍 | 必須保留的內容 |
| --- | --- | --- |
| ub-mode | `unclebob/ub-mode` 的 `master`，整個專案 | README、SKILL，以及未來上游加入的其他一般檔案 |
| pstack | `cursor/plugins` 的 `main`，完整 `pstack/` | Skills、agents、assets、docs、automations、外掛設定與 LICENSE |

pstack 以 GitHub commits API 的 `path=pstack` 查詢該範圍最近的提交，再下載固定 commit 的原始碼封存檔。其他外掛的提交不會造成 pstack 副本更新。ub-mode 追蹤整個儲存庫。

`externals.lock.json` 記錄每項來源的 repository、ref、path、commit、上游提交時間，以及全部一般檔案的 SHA-256 和可執行權限。這些是來源版本與完整性資訊，不代表已試用或驗證技能效果。中文簡介、收藏理由及試用狀態只取自人工維護的 YAML，不從上游自動改寫。

同步保留上游檔案原始位元組及可執行標記，包含二進位圖片與隱藏設定；不重新摘要、翻譯或格式化。保留來源提供的授權資訊；未提供授權檔時不替上游補上授權宣告，也不將自製內容的授權套用到外部檔案。同步來源與本機安裝分開處理，實際使用依各專案文件及授權條件確認。

## 每週更新與啟用

- Workflow：`.github/workflows/sync-externals.yml`，名稱 **Sync external projects**。
- 排程：UTC 週一 01:17，即台北時間每週一 09:17；GitHub 排程可能延遲，也可按 **Run workflow** 手動執行。
- Workflow 必須存在於儲存庫預設分支，才會按週觸發。手動執行也限定預設分支。
- GitHub 儲存庫 **Settings → Actions → General → Workflow permissions** 需允許 Actions 建立 PR。Workflow 只宣告來源分支寫入與 PR 寫入所需權限，使用內建 `GITHUB_TOKEN`，不需要個人 PAT。
- 更新完成後先執行離線檢查，再由固定版本的 create-pull-request action 建立／更新 `codex/sync-external-skills`，附上來源比較與檔案增刪改數量。沒有變更時不建立提交或 PR，不自動合併。
- 同一時間只執行一個同步 workflow，避免排程與手動操作同時更新同一分支。PR 已合併且沒有新差異時，後續執行會清理這支機器人分支。
- GitHub 公開儲存庫若長時間沒有活動，排程可能被停用；可在 Actions 頁面重新啟用。完整規則見 [GitHub 排程文件](https://docs.github.com/en/actions/reference/workflows-and-actions/events-that-trigger-workflows#schedule)。

一般 PR 與推送至 main 時會執行 **Check external snapshots**。`GITHUB_TOKEN` 產生的 PR 不一定觸發其他 PR workflows，因此同步 job 在開 PR 前已執行相同測試與副本校驗，不能把未執行的 PR check 說成通過。參見 [create-pull-request token 說明](https://github.com/peter-evans/create-pull-request#token)。

## 本機操作

依 README 建立 `.venv`，再安裝固定版本同步依賴：

```sh
.venv/bin/python -m pip install -r requirements-sync.txt
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B scripts/sync_externals.py update
.venv/bin/python -B scripts/sync_externals.py check
```

`update` 會連到 GitHub 公開 API 與 codeload。需要提高 API 配額時，可以透過環境的 `GH_TOKEN` 提供 token；token 只送給 GitHub API，不送到下載主機，也不寫入檔案或輸出。

`check` 完全離線，核對全部檔案、權限、必要檔案、來源設定與 README 生成區塊。`render` 只依 YAML 和 lock 產生 README 表格；標記區外的原文不變。

若 macOS 的 Python 缺少預設 CA 憑證路徑，且系統已有 `/etc/ssl/cert.pem`，可為這次命令指定系統 CA；HTTPS 驗證仍保持開啟：

```sh
SSL_CERT_FILE=/etc/ssl/cert.pem .venv/bin/python -B scripts/sync_externals.py update
```

需要另外產生供審查的摘要時，將輸出放在儲存庫外：

```sh
.venv/bin/python -B scripts/sync_externals.py update --report /tmp/agent-skills-update.md
```

## 失敗與版本重現

- 現有副本有新增、修改、刪除、權限變更或軟連結：停止更新。先把需要保留的本機修改移到其他位置；自行改編的版本放進 `skills/` 並記錄來源，避免直接改同步副本。
- 目的地已存在但未被 lock 管理：停止，不覆蓋使用者檔案。
- 上游下載失敗、路徑消失或必要檔案缺少：整輪失敗，保留原副本與 lock。所有來源先下載／校驗，成功後才替換；替換時寫入失敗會還原。
- 上游刪除檔案：更新到新 commit 時一起移除該來源副本的舊檔；從 YAML 移除整項來源時，也只移除 lock 所管理且未被手動修改的副本。
- 壓縮檔含路徑跳脫、符號連結、硬連結、特殊檔案或超出大小限制：停止，不執行或展開這些內容。若上游開始依賴此類檔案，需先調整同步策略。
- 不編輯 lock 來掩蓋校驗失敗。要查看某個版本，依 lock 的 `repository`、`commit` 與 `path` 取得同一版本，或用本專案 Git 歷史還原相應的 `external/`、lock 與 README。

因為副本內可能有上游 `.gitignore`，CI 在提交前會強制加入已校驗的 `external/` 檔案，避免上游原本追蹤但被 ignore 規則匹配的檔案遺漏。本機第一次提交也應在 `check` 通過後執行 `git add --force -- external/`。
