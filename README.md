# llm-agent-feed

自动抓取并展示与 LLM/agent 相关的 arXiv 文章，使用 GitHub Actions 定时更新并通过 GitHub Pages 发布静态站点。

## 仓库结构
```
llm-agent-feed/
├─ .github/workflows/update_arxiv.yml
├─ scripts/fetch_arxiv.py
├─ data/papers.json
├─ index.html
├─ assets/styles.css
├─ requirements.txt
└─ README.md
```

## 快速开始（本地测试）
1. 克隆或解压本仓库。
2. 创建虚拟环境并安装依赖：
   ```bash
   python -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. 本地运行抓取脚本生成 `data/papers.json`：
   ```bash
   python scripts/fetch_arxiv.py
   ```
4. 本地启动静态服务器预览站点：
   ```bash
   python -m http.server 8000
   # 浏览 http://localhost:8000
   ```

## 配置 GitHub 部署（推荐）
1. 在 GitHub 创建一个新仓库并 push 本仓库内容到 `main` 分支。
2. 在仓库 Settings -> Pages 中选择 Source: `main` / root，然后保存（启用 GitHub Pages）。
3. GitHub Actions 会每日自动运行（或你可以手动在 Actions 页面触发），`data/papers.json` 将被更新并自动 commit & push。
4. 若你需要更频繁的更新或更复杂的处理，可调整 `.github/workflows/update_arxiv.yml`。

