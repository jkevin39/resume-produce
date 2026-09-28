#!/bin/zsh
cd "${0:A:h}" || exit 1
export PYTHONDONTWRITEBYTECODE=1
if [[ ! -x .venv/bin/python ]]; then
  print "请先运行 初始化.command。"
  read "?按回车关闭。"
  exit 1
fi
.venv/bin/python -m resume_app.local key
result=$?
read "?按回车关闭。"
exit $result
