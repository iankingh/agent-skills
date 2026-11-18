# 外部專案同步

外部專案使用 Git submodule。父專案以 gitlink（Git 檔案模式 `160000`）記錄每個 submodule 的上游 commit。`.gitmodules` 記錄上游 URL、本機路徑及追蹤分支，`externals.yaml` 記錄關注的子目錄、必要檔案與收藏資訊。README 表格從收錄設定與 Git index 中的鎖定版本產生。

| 收藏 | Submodule 路徑 | 上游 | 鎖定方式 |
| --- | --- | --- | --- |
| ub-mode | `external/ub-mode/` | `unclebob/ub-mode` 的 `master` | 追蹤分支最新 commit |
| pstack | `external/cursor-plugins/` | `cursor/plugins` 的 `main` | 追蹤最近一次影響 `pstack/` 的 commit |

`external/cursor-plugins/` 的 submodule 指標仍連到上游 repo。本機與 Action 的 `checkout` 指令使用 sparse checkout，只展開 `external/cursor-plugins/pstack/`。同步與校驗只處理 Git 資料。實際安裝則依各上游文件及授權條件操作。

## 下載鎖定版本與查閱歷史

新舊 clone 都能在專案根目錄初始化 submodule。先準備下方的 Python 環境。之後拉取同步更新時，再執行 `checkout` 套用父專案目前鎖定的版本。

```sh
.venv/bin/python -B scripts/sync_externals.py checkout
git submodule status
git -C external/ub-mode log --oneline
git -C external/cursor-plugins log --oneline -- pstack/
```

需要重現舊版時，從擁有當時父專案提交的乾淨 clone 切換到該版本，然後依該版本的目錄結構使用外部專案。有 gitlink 的版本執行上述初始化指令。

## 每週同步

- **Sync external projects** 每週一台北時間 09:17（UTC 01:17）從預設分支執行。也可在 GitHub Actions 選擇預設分支後按 **Run workflow**。
- 在審查分支手動執行時，Action 會在執行環境中更新並校驗 submodule 指標，並把結果列在執行摘要。同步 PR 由預設分支上的執行建立。
- Workflow 取得各上游分支，在驗證候選 commit 的必要檔案後更新 gitlink 和 README。只有 `pstack/` 的上游提交會推進 pstack 的版本。
- 初次同步前，`external/` 可以是空的，README 表格會顯示「待同步」。首次執行會在同一份同步 PR 建立兩個 gitlink。合併後即可依上面的指令初始化本機。
- 有變更時，workflow 驗證 submodule 可 checkout 至鎖定的 commit，然後建立或更新 `codex/sync-external-skills` PR。PR 內附上舊版與新版的上游比較連結。
- GitHub 儲存庫 **Settings → Actions → General → Workflow permissions** 需允許 Actions 建立 PR。Workflow 使用內建 `GITHUB_TOKEN`。
- 一般 PR 與推送至 main 時，**Check external submodules** 會執行測試，確認收錄設定、gitlink、必要檔案及 README 表格一致。

## 本機更新與驗證

從乾淨的 Git 工作目錄執行。先建立 Python 3.10 以上的 `.venv`，再用以下指令更新與驗證：

```sh
.venv/bin/python -m pip install -r requirements-sync.txt
.venv/bin/python -B -m unittest discover -s tests -v
.venv/bin/python -B scripts/sync_externals.py update
.venv/bin/python -B scripts/sync_externals.py checkout
.venv/bin/python -B scripts/sync_externals.py check --checkout
```

`update` 在暫存 Git repo 取得上游物件。所有來源驗證通過後，若有變更，會用本機作者設定在目前分支建立同步提交。有需要時可加 `--report /tmp/agent-skills-update.md` 產生 PR 摘要。抓取失敗或必要檔案遺失時，父專案與 submodule 的鎖定版本維持原樣。若 submodule 有本機修改，更新前請先保留修改。

`check` 離線核對收錄設定、Git index 的 submodule 版本及 README 表格。`check --checkout` 再核對已初始化的 submodule 是否位於鎖定 commit、追蹤檔案是否乾淨，以及該 commit 是否有必要檔案。

只更新介紹、收藏理由或試用狀態時，修改 `externals.yaml` 後執行以下指令：

```sh
.venv/bin/python -B scripts/sync_externals.py render
.venv/bin/python -B scripts/sync_externals.py check
```
