# WeChat Sticker Studio 开发者 README

这里记录本机回归、发布包构建和生产编码器复测。首次制作 GIF 或接入 Agent 请看 [使用者 README](README.md)。

## 本机环境与回归

合成、验收、预览、投稿组包和回归测试使用 Python 3.12 与锁定的 Pillow。安装渠道和平台命令见 [使用者 README](README.md#先做一枚挥手机器人)。已在 Apple Silicon macOS、Python 3.12.14、Pillow 13.0.0 上验证。

下面的命令从仓库根目录运行。已有环境时，可把 `py` 指向该环境的解释器。自检可在安装前单独运行，输出实际解释器路径、Python 和 Pillow 版本及 `errors` 数组。退出码 `0` 表示通过，`1` 表示发现环境问题。自检只读取环境与锁定依赖，安装使用下面单独列出的命令。

```sh
python3.12 -m venv .venv
py=.venv/bin/python
"$py" -m pip install -r requirements.txt
"$py" -B skills/wechat-sticker-studio/scripts/check_environment.py
mkdir -p output/phase-a
"$py" -B skills/wechat-sticker-studio/scripts/sticker_gif.py compose examples/wave/sticker.json output/phase-a/wave.gif \
  > output/phase-a/wave-compose.json
"$py" -B skills/wechat-sticker-studio/scripts/sticker_gif.py validate output/phase-a/wave.gif \
  --manifest examples/wave/sticker.json --preview output/phase-a/wave-preview.gif \
  > output/phase-a/wave-validation.json
```

打开 `output/phase-a/wave-preview.gif` 查看两种背景上的同步循环。旁边的 `wave-preview-frames.png` 标出了每帧实际时长。成品为 `wave.gif`，第五帧停留 240 毫秒，其余 11 帧各 80 毫秒。

- `compose` 按[清单](examples/wave/sticker.json)中 `frames` 的条数和顺序读取 PNG 路径，并在落盘前核对实际解码帧数。路径相对于清单，时长以毫秒计，必须是 10 的正整数倍。Alpha 小于等于阈值的像素变为透明。原始 PNG 可直接使用，也可通过 `"$py" -B examples/wave/draw_frames.py` 重新生成。
- 重跑加 `--replace`，候选 GIF 通过解码检查后才替换已有成品。省略参数时已有同名文件会报错。要保留首跑报告，可将重跑输出重定向到 `output/phase-a/wave-rerun.json`。
- `validate` 从 GIF 解码画布、帧数、时长、循环与透明像素，输出 JSON。用 `--manifest` 核对帧数和时长，或用 `--frame-count` 单独核对帧数。报告用 `checks.matches_expected_frame_count` 取代 `checks.exactly_12_frames`，并在 `expected_frame_count` 中记录目标。未提供目标的检查记为 `null`。严格检查失败退出码为 1，解码成功的文件仍会报告实际指标与失败原因。

运行本机回归检查。

```sh
"$py" -B -m unittest discover -s tests -v
```

## 动态表情投稿包

运行小样后，可用下面的命令生成单品示例 ZIP。省略 `--output` 可只做预检。

```sh
mkdir -p output/phase-c
"$py" -B scripts/pack_submission.py examples/wave/single-submission.json \
  --output output/phase-c/机器人-单品示例.zip > output/phase-c/single-report.json
```

投稿工具按清单顺序编号，复核 GIF 与配图的 SHA-256，并生成填写说明。动态单品和专辑均按 **2026-10-28 微信官方快照**做本机预检，实际表单仍待复核。 [投稿清单、配图及规则](skills/wechat-sticker-studio/references/submission.md)

## 版本与兼容性

发布脚本使用 Python 标准库。从仓库根目录指定版本和一个新输出目录，即可生成源码 ZIP、独立 Skill ZIP 和 `SHA256SUMS`。

```sh
"$py" -B scripts/build_release.py v0.1.0-rc.1 --output output/release-check
```

源码包包含两份 README、可重跑的小样和测试。独立 Skill 包包含同一套运行脚本、小样和 `QUICKSTART.md`，解压后可按 [Agent 安装说明](README.md#让-agent-操作)复制整个文件夹。更换版本时先保留旧 Skill 目录，整包替换后重开 Agent 会话。如需回退，恢复原目录并沿用该版本的锁定依赖。

| 环境 | 已验证入口 |
| --- | --- |
| Apple Silicon macOS，Python 3.12.14 | 合成、逐帧解码、双底预览、投稿预检和组包 |
| Codex | 宿主用参考图完成新角色表情 |
| Claude Code 2.1.330 | 项目 Skill 的 PNG 导入 |
| DeepSeek Harness | 项目 Skill 的 PNG 导入 |

发布包含 [Apache-2.0 许可证](LICENSE)和[第三方声明](THIRD_PARTY_NOTICES.md)，涵盖项目代码、Skill 和原创机器人小样。

## TODO 接入用户自带的生图服务

给能运行本机命令、没有内置生图工具的 Agent 提供一个可选的生图命令。用户配置 `baseUrl` 和模型，命令在运行时从本机环境变量读取 API 密钥。密钥只用于向所配置服务鉴权，避免进入对话、项目文件和日志。

首版接入一种支持文生图和参考图输入的接口协议。Agent 先写角色设定和动作关键姿势，再调用服务生成角色参考图，并将同一参考图用于后续动作帧。将返回的图整理为编号、对齐的 240 × 240 透明 PNG，交给现有的导入、合成和验收流程。验收目标是在一个没有内置生图工具的 Agent 中，从一句动作描述生成可解码的 GIF 和深浅底预览。

## 维护者复测生产编码器

Docker 只用于本节。先安装并启动 Docker，再确认当前 Docker daemon 能访问锁定的镜像。基准镜像是 `linux/arm64`，运行主机需要支持该架构。 [Docker Desktop](https://docs.docker.com/desktop/) · [Linux Docker Engine](https://docs.docker.com/engine/install/)

```sh
docker version
docker image inspect --format '{{.Id}} {{.Os}}/{{.Architecture}}' \
  sha256:4bfdd31f9c2b4b84e2d9efbf3e234331c6e2558ddee75ec44112645c374e64f4
```

`compose-gif-mcp-app:latest` 是维护者的本机生产基准镜像。本仓库的发布包只提供本机 GIF 工具及小样。需要复测且本机缺少该镜像时，可向有权限的维护者取得该镜像的 `docker image save` 归档，用 `docker image load -i <归档路径>` 导入后再次核对镜像 ID。上游另有 `sprite-gen 3.15.0` 的源码，锁定提交为 `2e60c68b54c1008ee411c211f4dbe4dddcf55016`，固定镜像还包含 Pillow 12.3.0 和生产构建环境。 [Docker 镜像导出](https://docs.docker.com/reference/cli/docker/image/save/) · [Docker 镜像导入](https://docs.docker.com/reference/cli/docker/image/load/) · [sprite-gen 3.15.0 源码](https://github.com/aldegad/sprite-gen/releases/tag/v3.15.0)

先按本页生成 `output/phase-a/wave.gif` 并设置 `py`。生产服务经由 `--frame-dir` 和一基序号 `--frame-order` 接入相同 CLI。下面将第 5 帧引用三次，观察成品解码后是否合并为一帧并累加时长。容器离线运行，绑定的输入目录为只读。

```sh
(
set -e
baseline="$PWD/output/phase-a/baseline"
image=sha256:4bfdd31f9c2b4b84e2d9efbf3e234331c6e2558ddee75ec44112645c374e64f4
mkdir -p "$baseline/inputs" "$baseline/gifs"
index=0
for png in examples/wave/frames/*.png; do
  cp "$png" "$baseline/inputs/frame-$index.png"
  index=$((index + 1))
done
docker run --rm --pull=never --network=none --read-only --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$baseline/inputs,dst=/frames,readonly" \
  --mount "type=bind,src=$baseline/gifs,dst=/out" \
  --entrypoint sprite-gen "$image" compose-gif \
  --frame-dir /frames --frame-order 1,2,3,4,5,5,5,6,7,8,9,10,11,12 \
  --delay-ticks 8 --loop-count 0 --alpha-threshold 128 \
  --output /out/wave.gif --manifest-output /out/wave-sprite-gen.json
"$py" -B scripts/sticker_gif.py validate "$baseline/gifs/wave.gif" \
  --manifest examples/wave/sticker.json --preview "$baseline/wave-preview.gif" \
  > "$baseline/wave-validation.json"
"$py" -B scripts/compare_gifs.py output/phase-a/wave.gif "$baseline/gifs/wave.gif" \
  > output/phase-a/comparison.json
)
```
