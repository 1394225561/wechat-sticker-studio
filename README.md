# WeChat Sticker Studio

把一组 PNG 做成透明、循环的微信 GIF 表情。你可以给角色画一组动作、请 Agent 制作画稿，或检查一枚已有的 GIF。成品可以在深色和浅色背景上一起预览，也可以按需整理成微信表情投稿材料。

![随包小样「挥手机器人」的一张动作帧](examples/wave/frames/05.png)

## 先做一枚挥手机器人

在 GitHub 仓库点 **Code → Download ZIP**，解压后在终端进入包含本 README 的文件夹。随包有 12 张原创 PNG，直接用它们就能跑完流程。如果下载了指定版本的源码包或 Skill 包，请按包内的 README 或 `QUICKSTART.md` 操作。 [项目发布页](https://github.com/1394225561/wechat-sticker-studio/releases)

本机制作、预览和打包需要 **Python 3.12** 和 **Pillow 13.0.0**。下方的命令会创建项目自己的 `.venv` 并安装 Pillow。普通使用只需要这两项运行依赖，已有 PNG 时可以全程在本机处理。

- 已安装 Python 3.12 时，直接运行下面的命令。需要安装时，可通过 uv 获取 3.12 系列的补丁版本。按官方说明装好 uv 后运行 `uv python install 3.12`。也可查看 Python 官方下载页的对应平台安装方式。 [uv 安装说明](https://docs.astral.sh/uv/getting-started/installation/) · [Python 官方下载](https://www.python.org/downloads/)
- Pillow 由 `pip` 按项目的依赖清单安装，首次下载需要网络。 [锁定依赖](skills/wechat-sticker-studio/requirements.txt) · [Pillow 下载页](https://pypi.org/project/pillow/13.0.0/)

在 macOS 或 Linux 的终端运行下面的命令。

```sh
python3.12 -m venv .venv
py=.venv/bin/python
"$py" -m pip install -r requirements.txt
"$py" -B skills/wechat-sticker-studio/scripts/check_environment.py
"$py" -B skills/wechat-sticker-studio/scripts/sticker_gif.py compose examples/wave/sticker.json output/phase-a/wave.gif
"$py" -B skills/wechat-sticker-studio/scripts/sticker_gif.py validate output/phase-a/wave.gif --manifest examples/wave/sticker.json --preview output/phase-a/wave-preview.gif
```

在 Windows PowerShell 中可用下面的写法。若用 uv 安装了 Python，第一行可改用 `& (uv python find 3.12) -m venv .venv`。

```powershell
py -3.12 -m venv .venv
$python = '.\.venv\Scripts\python.exe'
& $python -m pip install -r requirements.txt
& $python -B skills/wechat-sticker-studio/scripts/check_environment.py
& $python -B skills/wechat-sticker-studio/scripts/sticker_gif.py compose examples/wave/sticker.json output/phase-a/wave.gif
& $python -B skills/wechat-sticker-studio/scripts/sticker_gif.py validate output/phase-a/wave.gif --manifest examples/wave/sticker.json --preview output/phase-a/wave-preview.gif
```

打开 `output/phase-a/wave-preview.gif` 看深浅底循环。同一文件夹里的 `wave.gif` 是可使用的透明成品，共 12 帧，尺寸为 240 × 240。`wave-preview-frames.png` 标出每帧的实际时长。

自检输出 `"ok": true` 时，当前解释器和 Pillow 符合项目的环境要求。如果第一个命令提示找不到 Python，请先安装 3.12。Linux 上若创建虚拟环境时报 `ensurepip is not available`，可从系统软件源安装与 Python 3.12 对应的 `venv` 包，或使用 uv 提供的解释器。如果自检提示缺少 Pillow 或版本不同，用同一个 `.venv` 解释器重跑 `pip install` 那一步。

新建成品时，请把输出放在本机支持硬链接的磁盘上，例如 APFS、ext4 或 NTFS。若成品同名已存在，可换一个文件名，或在确认要替换时为 `compose` 加 `--replace`。

## 制作自己的表情

- **我有一组 PNG。** 准备至少两张 240 × 240 的透明单帧 PNG，按播放顺序编号。让 Agent 导入，或自己按命令生成帧清单、合成并预览。 [PNG 导入与导出](skills/wechat-sticker-studio/references/png-workflow.md)
- **我有角色和动作。** 给 Agent 一张角色参考图和要做的动作，例如「让这只机器人抬右手挥两下」。绘制需要 Agent 的图像工具或你自己的绘图工具，画稿准备好后再用本项目合成。 [角色与动作指南](skills/wechat-sticker-studio/references/character-motion.md)
- **我有一枚 GIF。** 可以让 Agent 检查尺寸、帧数、循环、透明像素和文件大小，并生成深浅底预览。附上原帧清单时，还可核对预期时长。 [GIF 检查命令](skills/wechat-sticker-studio/references/png-workflow.md)
- **我想提交到微信表情开放平台。** 可以在本机预检动态单品或专辑、生成投稿 ZIP 和填写说明。预检采用 **2026-10-28 的微信官方规则快照**，请在上传时核对平台当时的表单。 [投稿材料与组包](skills/wechat-sticker-studio/references/submission.md)

可以按动作选择帧数，例如导入 24 张 PNG 时加 `--frame-count 24`，确认素材张数符合目标。省略该选项时，工具按实际输入张数生成帧清单。合成和清单验收都会核对实际解码帧数与清单是否一致。Docker 镜像仅用于维护者的生产编码对照。

## 让 Agent 操作

### 推荐用 `npx skills` 安装

准备 Node.js 22.20 或更高版本（含 `npx`）和 Git。在你的**作品项目根目录**运行命令，按提示选择使用的 Agent。Skill 默认装到当前项目。 [Node.js 下载](https://nodejs.org/en/download) · [Skills 安装文档](https://github.com/vercel-labs/skills/blob/main/docs/commands.md#skills-add)

```sh
npx skills add 1394225561/wechat-sticker-studio --skill wechat-sticker-studio
```

### 手动安装

如果安装器没有列出你的 Agent，可以把仓库里的 `wechat-sticker-studio` 文件夹整体复制到对应的目录。若下载的是独立 Skill 包，使用解压出的同名文件夹。 [仓库中的 Skill 文件夹](skills/wechat-sticker-studio)

| Agent | 作品项目中的位置 |
| --- | --- |
| Codex | `.agents/skills/wechat-sticker-studio/` |
| Claude Code | `.claude/skills/wechat-sticker-studio/` |
| DeepSeek Harness | Git 根目录下的 `.dsh/skills/wechat-sticker-studio/` |

### 开始制作

在作品项目里打开新会话。首次运行需要 Python 3.12，可以让 Agent 按已安装 Skill 的 `requirements.txt` 在作品项目的 `.venv` 中安装 Pillow。可以直接给 Agent 下面这段话，并附上素材路径。已有虚拟环境时，一并提供其中 Python 的绝对路径。

> 使用 wechat-sticker-studio。先检查运行环境，再把 `frames/` 里的 PNG 按编号做成透明、循环的微信 GIF。目标是实际解码 24 帧。请把成品、帧清单、验收报告和深浅底预览放在 `output/` 里。

从零开始时，告诉 Agent 想要的角色和动作。配备生图工具的 Agent 可以先画角色参考图，再用同一参考画动作帧。项目目前依赖外部提供画稿，自带的工具负责把帧合成 GIF。让纯文本 Agent 调用用户自己的生图服务已列入开发计划。 [外接生图服务 TODO](README.developer.md#todo-接入用户自带的生图服务)

本机流程已在 Apple Silicon macOS、Python 3.12.14 和 Pillow 13.0.0 上验证。Codex 已跑通从角色参考开始的流程，Claude Code 2.1.330 和 DeepSeek Harness 已跑通 PNG 导入。上面的 Linux 和 Windows 命令供对应平台试用。

修改源码、跑测试、构建发布包或进行 Docker 编码对照，请看 [开发者 README](README.developer.md)。项目和原创小样采用 [Apache-2.0](LICENSE)。 [第三方声明](THIRD_PARTY_NOTICES.md)
