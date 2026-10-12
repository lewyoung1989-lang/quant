# GitHub 提交交接说明

这份文档用于交给其他 AI，让它把本项目的代码提交并推送到 GitHub。项目目录为 `/Users/liuyang/Desktop/own/quant`。

## 1. 已确认的仓库信息

| 项目 | 值 |
|---|---|
| GitHub 账号 | `lewyoung1989-lang` |
| 仓库 | `quant` |
| 仓库地址 | https://github.com/lewyoung1989-lang/quant |
| 远程名 | `origin` |
| 推送地址 | `https://github.com/lewyoung1989-lang/quant.git` |
| 默认分支 | `main` |
| 当前本地分支 | `main` |
| 最近已推送提交 | `146269372feb0676ffe2fcc1bc53aa99d8cf10d2` |

仓库可见性以 GitHub 当前设置为准。提交前先运行 `gh repo view lewyoung1989-lang/quant --json visibility,url` 检查，不要擅自修改公开或私有权限。

## 2. 认证要求

优先使用本机已有的 GitHub CLI 登录状态：

```bash
gh auth status
```

认证正常后直接使用 HTTPS 远程地址推送。不要索取、复制、打印或写入聊天记录中的 Personal Access Token、SSH 私钥、密码或浏览器 Cookie。

如果未登录，停止推送并让用户在自己的终端完成：

```bash
gh auth login -h github.com
```

登录后重新执行 `gh auth status`。其他 AI 不应代用户创建或保存新的令牌，也不应把令牌写进远程 URL、源码、`.env` 或文档。

## 3. 提交前检查

```bash
cd /Users/liuyang/Desktop/own/quant
git status --short
git branch --show-current
git remote -v
git fetch origin
git rev-list --left-right --count HEAD...origin/main
```

确认：

- 远程确实是 `lewyoung1989-lang/quant.git`。
- 当前分支是 `main`，或用户明确指定了其他分支。
- 远程没有未合并的新提交；若 `origin/main` 比本地领先，先报告并处理合并，不能直接强推。
- 变更范围与用户要求一致。
- 不提交 `.venv/`、下载行情数据、`reports/`、`mlruns/`、`backtest/`、本地账户持仓和交易流水。
- 不提交 `.env`、`.streamlit/secrets.toml`、令牌、密码、私钥和个人账户数据。

当前 `.gitignore` 已排除本地环境、生成物和大部分行情数据；仍需人工检查 `git status` 和待提交文件列表。

可做基础检查：

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python - <<'PY'
import ast
from pathlib import Path
files = [Path('app.py'), *Path('data').glob('*.py'), *Path('services').glob('*.py'), *Path('strategies').glob('*.py')]
for path in files:
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
print(f'AST syntax check passed: {len(files)} files')
PY
git diff --check
```

## 4. 标准提交流程

用户已经明确授权提交和推送时，按以下流程执行：

```bash
git add <用户要求提交的文件>
git diff --cached --stat
git diff --cached --name-only
git commit -m "<简短、准确的英文提交说明>"
git push origin main
git status --short
git rev-parse HEAD
git ls-remote origin refs/heads/main
```

提交信息应描述实际变更，例如：

```text
Add intraday signals and rebalance planning workbench
```

不要使用 `git add -A` 代替文件检查，除非已经确认工作区没有不应提交的文件。不要使用 `git push --force`、`git reset --hard` 或删除远程分支，除非用户明确要求且已说明影响。

## 5. 冲突和异常处理

### 远程有新提交

先停止推送并报告：

```bash
git log --oneline --decorate --graph HEAD..origin/main
```

通常应先获取并合并或变基，经检查后再推送。不得覆盖远程提交。

### 未登录或权限不足

把具体的 `gh auth status` 错误告诉用户，让用户在本机重新登录或确认仓库权限。不要要求用户把令牌发到聊天中。

### 推送被保护规则拒绝

检查是否需要 Pull Request、状态检查或分支保护。创建 PR 前必须得到用户明确授权；不要绕过保护规则。

### 大文件或敏感文件被暂存

停止提交，先从暂存区移除并检查来源：

```bash
git restore --staged <文件>
git status --short
```

如果敏感信息已经进入提交历史，不能只删除当前文件就声称已清除；应立即告知用户并建议轮换凭据，再按用户授权处理历史清理。

## 6. 完成后的汇报格式

其他 AI 完成后应报告：

- GitHub 仓库链接。
- 推送分支。
- 新提交的短 SHA 和提交说明。
- 实际提交的主要文件或功能。
- 运行过的检查及结果。
- 工作区是否干净。
- 若未完成，说明准确的阻塞原因和下一步，不要声称已推送。

示例：

> 已推送到 `https://github.com/lewyoung1989-lang/quant` 的 `main` 分支。新提交为 `abc1234`，已通过 Python AST 检查和 `git diff --check`，远程 SHA 与本地一致，工作区干净。

## 7. 本项目的当前状态参考

最近一次已推送提交 `1462693` 包含实时行情适配器、盘中信号计算、调仓服务、交易台页面和当日调仓计划实施文档。后续 AI 应只提交新的实际改动，不要重复上传本地行情数据、虚拟环境或运行时账户文件。

## 8. 发给其他 AI 时，需要提供哪些信息

### 必需信息

1. **明确授权与范围**：例如“请把当前项目的新代码和文档提交并推送到此仓库”。说明是否包含全部改动，或只提交指定文件。
2. **代码所在位置**：同一台电脑用上述绝对路径；其他电脑需给出那台电脑上的实际项目路径。远程 AI 无法直接访问本机目录，需要先通过它支持的工作区方式提供代码。
3. **目标仓库与分支**：仓库链接、远程地址、目标分支。本文已提供本项目的值。
4. **运行环境和认证状态**：AI 是否可以执行终端命令、访问 GitHub，以及执行环境里是否已登录有该仓库写权限的账号。
5. **提交边界**：哪些代码、文档要提交，哪些数据、凭据、运行文件要排除。以当前 .gitignore 和实际文件检查为准。

### 可选但有用的信息

- 提交说明，或允许 AI 根据实际改动拟定说明。
- 已运行的测试、启动方式与已知未解决问题。
- 是否允许在目标分支受保护时改为创建功能分支及 PR；如有偏好，在交接时直接说明。

**不需要提供密码或令牌。** 本机登录状态不会随这份 Markdown 文档迁移；换一台机器或云端环境，需要在那个环境中通过受支持的登录方式配置访问权限。

Git 提交作者身份与 GitHub 推送登录账号是两回事。提交前可查看 `git config user.name` 和 `git config user.email`。若尚未配置，让用户提供期望的提交作者信息；优先配置当前仓库，不擅自修改全局设置，也不要根据 GitHub 用户名猜测邮箱。

若其他环境尚未克隆仓库，可先执行：

```bash
git clone https://github.com/lewyoung1989-lang/quant.git
cd quant
```

克隆只能得到已经推送的内容，本机尚未提交的新代码需要另外提供，不能声称克隆后已经拥有所有本地改动。

## 9. 可直接复制给其他 AI 的提示词

```text
请把当前项目中已完成的新代码和文档提交并推送到我的 GitHub 仓库。

项目路径：/Users/liuyang/Desktop/own/quant
GitHub 账号：lewyoung1989-lang
仓库：https://github.com/lewyoung1989-lang/quant
远程名：origin
目标分支：main

先读取 docs/github_submission_handoff.md 和适用的 AGENTS.md。
检查 Git 状态、远程与认证；检查待提交内容，排除本地行情、虚拟环境、回测产物、账户数据和凭据。
对本次改动做适当验证，拟定准确的提交说明，然后提交并推送。
保留已有代码与提交，不强推、不删除、不擅自改变仓库可见性。
若本地没有新改动，应如实说明，不创建空提交。
完成后给我仓库链接、提交 SHA、主要改动、验证结果，并确认远程与本地提交一致。
```

若使用不同电脑，请将提示词中的项目路径改为该环境里的实际路径。本文中的最近提交仅是整理时参考，执行时以 Git 查询结果为准。
