# APOD to Notion

每天自动把 NASA Astronomy Picture of the Day 写入 Notion：抓取当日图文、按规则译成中文，并做成左英右中的对照排版。

本地运行和 GitHub Actions 定时配置见 [教程.md](教程.md)。

密钥请放在本地 `.env`，或仓库 Settings → Secrets and variables → Actions 里，不要提交到仓库。`.gitignore` 已排除 `.env`。
