#!/bin/zsh
cd "${0:A:h}" || exit 1
export PYTHONDONTWRITEBYTECODE=1
if [[ ! -x .venv/bin/python ]]; then
  print "尚未初始化环境，请先双击 初始化.command。"
  read "?按回车关闭。"
  exit 1
fi
if ! .venv/bin/python -c 'import flask, yaml, requests, waitress' >/dev/null 2>&1; then
  print "依赖缺失，请运行 .venv/bin/python -m pip install -r requirements.txt"
  read "?按回车关闭。"
  exit 1
fi
.venv/bin/python -m resume_app.local start "$@"
result=$?
if (( result != 0 )); then read "?启动未完成，按回车关闭。"; fi
exit $result
