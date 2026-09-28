#!/bin/zsh
cd "${0:A:h}" || exit 1
export PYTHONDONTWRITEBYTECODE=1
if [[ ! -x .venv/bin/python ]]; then
  python3 -m venv .venv || { read "?无法创建 Python 环境，请安装 Python 3.9+ 后重试。按回车关闭。"; exit 1; }
fi
.venv/bin/python -m pip install -r requirements.txt || { read "?依赖安装失败，请检查网络后重试。按回车关闭。"; exit 1; }
if (( $# > 0 )); then
  .venv/bin/python -m resume_app.local init "$@"
else
  print "默认数据位置：$HOME/Library/Application Support/ResumeProduce"
  print "首次可复制旧项目资料，原件会保留；请先停止旧服务。"
  read "source_dir?旧资料所在目录（留空建立空白履历；填写完整路径，不加引号）："
  if [[ -n "$source_dir" ]]; then
    .venv/bin/python -m resume_app.local init --from-dir "$source_dir"
  else
    .venv/bin/python -m resume_app.local init
  fi
fi
result=$?
read "?按回车关闭。"
exit $result
