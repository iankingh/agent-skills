# 專案代理工作規則

本專案收錄自製或改編的 Agent Skills，外部專案使用 Git submodule。內容與文件以繁體中文為主；收錄與使用方式見 [README](README.md)，同步操作見 [外部同步說明](docs/external-sync.md)。

## 目錄與收錄

- 自製或改編技能放在 `skills/<skill-name>/`，保存 `SKILL.md` 與需要的程式、參考文件、範本及其他支援檔案。新增或調整技能用途時，同步維護 README 技能索引。
- `skills/<skill-name>/agents/openai.yaml` 是技能的顯示、呼叫與相依設定，隨技能保留；不要將它當成獨立子代理搬出技能資料夾。
- 未來新增自製獨立子代理時，放在根目錄 `agents/<工具名稱>/`，依目標工具格式保存，並在 README 記錄用途、適用工具與安裝位置。有實際內容才建立資料夾。
- 本檔 `AGENTS.md` 是專案作業指引；`skills/` 與未來的 `agents/` 是可收錄、安裝的內容，實際載入位置依各工具文件操作。
- 改編內容記錄原始連結、版本或 commit 及修改內容，保留適用的授權與署名。未實際試用的收藏維持「待試用」，區分文件查核與試用結果。

## 外部專案同步

- `.gitmodules` 記錄 `external/` 下各 submodule 的上游 URL、路徑及追蹤分支。父專案以 Git gitlink 鎖定上游 commit，原始檔案及提交歷史保存在各 submodule。外部內容保留上游的結構、權限、授權與署名。
- `external/ub-mode/` 對應 `unclebob/ub-mode`。`external/cursor-plugins/` 對應完整的 `cursor/plugins`，使用 pstack 時從其中的 `pstack/` 取得技能與代理。
- `externals.yaml` 管理關注的上游子路徑、必要檔案及人工維護的收藏資訊。README 的 `EXTERNALS:START`／`EXTERNALS:END` 區塊由同步工具依 YAML 和 Git index 的 gitlink 產生。
- 從乾淨的 Git 工作目錄執行 `scripts/sync_externals.py update`，更新後以 `git submodule update --init --checkout` 套用鎖定版本，再執行 `check --checkout`。只更新收藏介紹或試用狀態時使用 `render`，再執行 `check`。同步失敗時保留本機修改，依同步文件處理。
- 外部內容的收錄與實際安裝分開處理。同步不執行上游程式、不自動安裝技能或相依工具，也不自動改變試用狀態。
- 每週一台北時間 09:17 檢查上游。有新版本時，由 GitHub Actions 建立或更新同步 PR，提交 gitlink 和 README 表格的差異供審查。
- 初次同步時，先保留 `.gitmodules` 和 `externals.yaml` 的來源設定。當 `external/` 尚無鎖定版本時，由同步工具一次建立所有 gitlink。

## 修改與驗證

- 開始前檢查 Git 狀態，保留既有未提交修改；只調整任務需要的內容。未被要求時不提交、推送或安裝到個人環境。
- 文件修改檢查相對連結與 `git diff --check`，並核對差異沒有意外搬移檔案或改動外部副本、來源設定及排程。
- 涉及收錄或同步說明時，依 README 準備 Python 環境與同步依賴，執行離線檢查：

```sh
.venv/bin/python -B scripts/sync_externals.py check
```

- 修改同步程式、來源設定或 workflow 時，另執行既有同步測試：

```sh
.venv/bin/python -B -m unittest discover -s tests -v
```

回報實際修改範圍與驗證結果；離線完整性校驗不代表已實際試用外部技能。
