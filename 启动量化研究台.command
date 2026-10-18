#!/bin/zsh
cd -- "$(dirname -- "$0")" || exit 1
if [[ ! -x .venv/bin/python ]]; then
  print '未找到 .venv/bin/python，请先按 README 配置项目运行环境。'
  read '?按回车关闭…'
  exit 1
fi
.venv/bin/python scripts/start_system.py
result=$?
if (( result != 0 )); then
  read '?按回车关闭…'
fi
exit $result
