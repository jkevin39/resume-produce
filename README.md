# 简历工作台

[GitHub](https://github.com/jkevin39/resume-produce) · [Download ZIP](https://github.com/jkevin39/resume-produce/archive/refs/heads/main.zip)

把履历材料整理成可复用的经历与证据，再根据职位描述生成、编辑和导出中文简历。

这是 **macOS 本地单用户源码预览版**。下载后在自己的电脑上运行，模型 API Key 由使用者自行配置。当前功能基于 v0.11.1；完整模型质量矩阵与部分原生应用人工验收仍在进行，详见 [项目状态](PROJECT_TRACKER.md)。

## 可以做什么

- 管理基本信息、教育、经历、技能与证据材料。
- 分析中英文 JD，选择证据、调整顺序并生成中文草稿。
- 在 A4 画布中编辑文字、板块、顺序、字体和排版，支持撤销与重做。
- 导出 HTML，通过浏览器打印为 PDF；保存历史版本并复制续编。
- 本地 OCR 识别材料或 JD 图片（需构建 macOS 组件）。

## 环境

- macOS，Python 3.9 或更新版本（本次实际验证版本见验收记录）。
- Google Chrome。也可以启动时加 `--no-browser`，自行打开本机地址。
- 模型生成需要所选服务商的 API Key 和可用额度；离线 demo 不调用 API。
- OCR 与 Dock 应用入口额外需要 Xcode Command Line Tools；纯文字流程不需要构建原生组件。

## 首次使用

下载仓库 ZIP 并解压，或使用 Git 克隆仓库。在终端进入解压后的项目目录，执行：

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python -m resume_app.local init
python -m resume_app.local key
python -m resume_app.local start
```

`key` 会询问服务商，并将密钥保存在 macOS 钥匙串。初始服务商为 DeepSeek；如果配置其他服务商，请在工作台的模型设置中选择对应服务商与模型。修改密钥后重启服务。

也可以依次双击 `初始化.command`、`配置模型密钥.command`、`启动简历.command`。首次初始化的旧资料目录留空即可。若系统未允许脚本执行，请采用上面的终端命令。

默认地址是 `http://127.0.0.1:5000`。首页先填写基本信息，再粘贴履历材料，最后输入 JD 进入匹配与生成。模型调用由服务商按自己的规则计费。

数据保存在 `~/Library/Application Support/ResumeProduce`，与下载的源码分开。已存在的数据目录不会被初始化覆盖；升级源码后直接启动即可。

## 不用 Key 先体验

完成虚拟环境与依赖安装后，使用包内的合成资料创建独立 demo 数据目录：

```bash
python -m resume_app.local init --data-dir "$HOME/Library/Application Support/ResumeProduceDemo" --from-dir examples/demo
python -m resume_app.local start --data-dir "$HOME/Library/Application Support/ResumeProduceDemo" --no-keychain
```

将 `examples/demo/jd.txt` 的合成岗位文字粘贴到工作台。demo 用本地规则演示流程，生成效果不能代表真实模型效果。demo 与日常实例默认都使用 5000 端口，切换前先在终端按 Ctrl+C 停止前一个实例。

## OCR 与 Dock 入口（可选）

安装 Xcode Command Line Tools 后，在已激活虚拟环境的项目目录执行：

```bash
python tools/build_macos.py
```

它会在本机构建 OCR 组件和 `简历工作台.app`，随后可以双击应用或拖入 Dock。该入口关联当前源码目录，移动目录后需要重建。发布包不包含开发者电脑上编译的应用。

## 保存与备份

- 服务停止后，尚未保存的内存草稿会丢失。退出前正式保存，或导出 HTML。
- 导出的 HTML 可独立打开和打印；它不是可重新导入的编辑备份。
- 停止服务后，备份整个数据目录，包括 `data/`、`sources/`、`outputs/`、`config.yaml` 和 CSV（如果存在）。钥匙串密钥需另行配置。
- 导出 PDF：在 Chrome 打印中选择 A4、100% 缩放、无页边距、关闭页眉页脚，按需要打开背景图形。

## 常见问题

- **5000 端口被占用**：停止旧实例，或修改数据目录 `config.yaml` 的 `app.port` 后重启。
- **没有 Chrome**：运行 `python -m resume_app.local start --no-browser`，手动打开上面的地址。
- **想切换 demo/live**：停止服务，编辑数据目录 `config.yaml` 的 `llm.mode` 为 `demo` 或 `live`，然后重新启动。
- **模型请求失败**：检查所选服务商、模型可用性、Key、额度与网络。预览版内置模型名单，部分服务商尚未做完整真实调用验收。
- **图片识别不可用**：完成可选构建步骤；也可直接粘贴文字。

## 数据与使用范围

模型功能会将相关履历材料和 JD 发送给所选模型服务商；本地 OCR 使用 macOS Vision。详情见 [数据说明](PRIVACY.md)。

当前服务只面向单用户本机运行，没有多用户账户与数据隔离。请保留 `127.0.0.1` 监听配置。Windows/Linux 不在本次发布验收范围。

## 开发与验证

```bash
python -m tests.run_acceptance --output /tmp/resume-public-acceptance
node --test tests/*.test.cjs
```

测试使用合成资料；输出目录必须尚不存在。Node.js 仅用于 JavaScript 测试，不是应用运行依赖。[验收记录](tests/ACCEPTANCE.md)区分源码包验证与仍待完成的发布检查。

`tests/live_deepseek_acceptance.py` 提供离线测试所需的制品保存函数；直接执行该脚本会调用真实 API。脚本中的历史费用估算不代表当前账单，请以服务商账单为准。

反馈问题时请描述操作步骤、系统与 Python 版本，并使用合成资料复现，避免上传个人简历或密钥。

## 许可

本项目采用 [MIT License](LICENSE)，允许使用、修改、分发和商用；分发时保留许可和版权声明。第三方依赖遵循各自许可。
