# WeChat Sticker Studio

将角色动作或编号 PNG 制作为透明、循环的微信 GIF 表情，支持本机解码验收和深浅底预览。示例「挥手机器人」由 [绘图脚本](examples/wave/draw_frames.py) 原创绘制，12 张 PNG 随仓库提供，未使用私有角色或第三方素材。

## 在 Agent 中使用

将 [wechat-sticker-studio Skill 文件夹](skills/wechat-sticker-studio) 整体复制到作品项目。Codex 使用项目中的 `.agents/skills/wechat-sticker-studio/`，Claude Code 使用 `.claude/skills/wechat-sticker-studio/`，DeepSeek Harness 使用 Git 项目根目录中的 `.dsh/skills/wechat-sticker-studio/`。开启该项目的新会话，指定使用 `wechat-sticker-studio`，并提供角色加动作或按顺序编号的 PNG。

已备好透明 PNG 时，可以直接在作品目录执行 [导入与导出命令](skills/wechat-sticker-studio/references/png-workflow.md)。Skill 文件夹自带工具及 [清单模板](skills/wechat-sticker-studio/assets/sticker.template.json)，指向装有锁定 Pillow 的现有 Python 即可从其他目录运行。

已在 Apple Silicon macOS 上验证 Codex 的角色参考转 GIF 流程，以及 Claude Code 2.1.330 和 DeepSeek Harness 的 PNG 导入流程。

## 快速开始

下载源码包或克隆仓库后，从项目根目录执行。需要 Python 3.12 和 [锁定的 Pillow 13.0.0](requirements.txt)。已有兼容环境时，可以把 `py` 指向该环境的解释器。

```sh
python3.12 -m venv .venv
py=.venv/bin/python
"$py" -m pip install -r requirements.txt
mkdir -p output/phase-a
"$py" -B skills/wechat-sticker-studio/scripts/sticker_gif.py compose examples/wave/sticker.json output/phase-a/wave.gif \
  > output/phase-a/wave-compose.json
"$py" -B skills/wechat-sticker-studio/scripts/sticker_gif.py validate output/phase-a/wave.gif \
  --manifest examples/wave/sticker.json --preview output/phase-a/wave-preview.gif \
  > output/phase-a/wave-validation.json
```

打开 `output/phase-a/wave-preview.gif` 查看两种背景上的同步循环。旁边的 `wave-preview-frames.png` 标出了每帧实际时长。成品为 `wave.gif`，第五帧停留 240 毫秒，其余 11 帧各 80 毫秒。

- `compose` 根据[清单](examples/wave/sticker.json)按顺序读取相对于清单的 PNG 路径。时长以毫秒计，必须是 10 的正整数倍。Alpha 小于等于阈值的像素变为透明。原始 PNG 可直接使用，也可通过 `"$py" -B examples/wave/draw_frames.py` 重新生成。
- 重跑加 `--replace`，候选 GIF 通过解码检查后才替换已有成品。省略参数时已有同名文件会报错。要保留首跑报告，可将重跑输出重定向到 `output/phase-a/wave-rerun.json`。
- `validate` 从 GIF 解码画布、帧数、时长、循环与透明像素，输出 JSON。用 `--manifest` 比对预期时长。省略清单时，时长一致性记为 `null`。严格检查失败退出码为 1，解码成功的文件仍会报告实际指标与失败原因。

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

源码包包含可重跑的小样和测试。独立 Skill 包包含同一套脚本、小样和 `QUICKSTART.md`，解压后可直接按本页的 Agent 路径复制整个文件夹。更换版本时先保留旧 Skill 目录，整包替换后重开 Agent 会话。如需回退，恢复原目录并沿用该版本的锁定依赖。

| 环境 | 已验证入口 |
| --- | --- |
| Apple Silicon macOS，Python 3.12.14 | 合成、逐帧解码、双底预览、投稿预检和组包 |
| Codex | 宿主用参考图完成新角色表情 |
| Claude Code 2.1.330 | 项目 Skill 的 PNG 导入 |
| DeepSeek Harness | 项目 Skill 的 PNG 导入 |

发布包含 [Apache-2.0 许可证](LICENSE)和[第三方声明](THIRD_PARTY_NOTICES.md)，涵盖项目代码、Skill 和原创机器人小样。

## 维护者复测生产编码器

以下命令使用本机已缓存并核实的 `compose-gif-mcp-app:latest` 镜像 ID。镜像内为 `sprite-gen 3.15.0`，提交 `2e60c68b54c1008ee411c211f4dbe4dddcf55016`，Pillow 12.3.0。生产服务经由 `--frame-dir` 和一基序号 `--frame-order` 接入相同 CLI。这里将第 5 帧引用三次，观察成品是否合并为一帧并累加时长。容器离线运行，绑定的输入目录为只读。

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

本机合成和验收可独立运行，只有生产对照命令需要 Docker。
