# 作品目录与生图工作流

下文的 `$py` 是已通过环境自检的 Python 绝对路径，`$skill` 是安装后的 Skill 目录。在 macOS 和 Linux 中可用下列命令。在 PowerShell 中将调用形式换成 `& $py -B "$skill/scripts/sticker_workflow.py" ...`，并按需使用反引号续行。

## 初始化作品目录

```sh
workflow="$skill/scripts/sticker_workflow.py"
root="/absolute/path/to/作品项目"
"$py" -B "$workflow" init-workspace "$root" --series robots --sticker wave --character helper
work="$root/series/robots/stickers/wave/v001"
```

初始化返回实际的 `workspace`、`plan` 和 `image_service_config` 路径。系列、角色和表情 ID 使用小写字母、数字及连字符，作品根路径可以包含中文和空格。重复初始化会补齐缺项并保留内容。用 `--revision v002` 建立新的表情修订，用 `--character-version v002` 建立独立的角色版本。初始化时加 `--no-image-service-config` 可以跳过默认生图配置模板。

```text
作品项目/
├── .config/image-service.json
└── series/robots/
    ├── characters/
    │   └── helper/v001/reference.png
    └── stickers/
        └── wave/v001/
            ├── plan.json
            ├── source/
            ├── keyframes/
            ├── frames/
            ├── sticker.json
            ├── review/
            └── output/
```

`characters/` 供同系列表情复用。修订目录中的 `source/` 保存原图，`keyframes/` 保存关键帧、预览和审批，`frames/` 保存完整的标准帧，`review/` 保存成品预览和报告，`output/` 保存实际 GIF。计划里的角色图路径相对系列目录，GIF 清单里的帧路径相对清单。

## 已有完整帧集合

用 `--mode imported` 初始化。确认顺序后，把实际路径按播放顺序传给命令。用 `--durations-ms` 指定逐帧时长，用 `--duration-ms` 指定统一时长，省略时按每帧 80 ms。

```sh
"$py" -B "$workflow" init-workspace "$root" --series robots --sticker nod --mode imported
work="$root/series/robots/stickers/nod/v001"
"$py" -B "$workflow" import-frames "$work" "/path/to/start.png" "/path/to/end.png" --durations-ms 80,150
"$py" -B "$workflow" build "$work"
```

导入至少两张有可见角色、带真实透明背景的单帧 PNG。工具保留原始字节，把其他尺寸的图按整张画布等比缩放并居中补透明边到 240×240。准备素材时要使用相同源画布和动作锚点。帧序不明确时先核对，画进像素的背景需要先处理。若缺帧或要重新设计动作，建立 `generated` 修订并审核相关关键姿势。

## 从角色和动作开始

1. 以 `generated` 模式初始化，编辑 `plan.json`。填写角色特征、动作和每一帧的姿势。使用初始化生成的角色参考路径，放入一张已有的单帧 PNG，或在下节生成该图。纯文生图试画时可把 `character_reference` 设为 `null`，并在角色描述里锁定形象特征。

   ```json
   {
     "version": 1,
     "mode": "generated",
     "character_reference": "characters/helper/v001/reference.png",
     "character_description": "圆头蓝色机器人，黄色面板，固定正面视角",
     "action": "右手挥手，脚底贴同一条基线，回到起势后循环",
     "frames": [
       {"keyframe": true, "duration_ms": 80, "prompt": "手肘抬起，手掌靠近面板"},
       {"keyframe": false, "duration_ms": 80, "prompt": "手掌经过肩膀正上方"},
       {"keyframe": true, "duration_ms": 120, "prompt": "手掌向外摆到峰值，脚和躯干保持原位"}
     ]
   }
   ```

2. 有角色参考图时，先准备这一张图，运行 `review-reference`，把它单独交给用户审核。用户明确批准后，传入本次输出的实际摘要。审批绑定这张 PNG 的字节，供同系列的其他表情复用。如果用户要换角色图，开新角色版本和表情修订。纯文生图的计划可将 `character_reference` 设为 `null`，直接进入关键帧制作。

   ```sh
   "$py" -B "$workflow" review-reference "$work"
   # 用户批准这一张角色参考图后
   "$py" -B "$workflow" approve-reference "$work" --digest "$approved_reference_digest"
   ```

3. 制作标记为 `keyframe: true` 的姿势，至少两张。用自带服务运行 `generate --stage keyframes`，或用宿主工具及外部绘图交付原 PNG，再运行 `add-frame "$work" 1 "/path/to/pose.png"`。帧号从 1 开始，对应计划中的播放位置。随后运行下列命令。把 `keyframes/review.png` 和动作计划（含循环衔接）展示给用户。

   ```sh
   "$py" -B "$workflow" review-keyframes "$work"
   ```

4. 用户明确批准这版预览后，把命令输出的实际 `digest` 传给 `approve-keyframes`。用户要求调整时，保留原图，修正受影响姿势后重新出预览。审批绑定整个计划、角色图和关键帧文件。已审批的资料发生变动时，建立新修订再审核。

   ```sh
   "$py" -B "$workflow" approve-keyframes "$work" --digest "$approved_digest"
   "$py" -B "$workflow" prepare-frames "$work"
   ```

5. 审批后再制作过渡帧。用 `generate --stage frames` 让服务生成，或用 `add-frame` 导入手工绘制、外部生图或本地变换后的 PNG。工作流直接复用已审关键帧。全部帧齐备后运行 `build`。它返回 GIF、GIF 清单、实际解码报告和深浅底预览的路径。打开预览检查实际动作、接缝、角色漂移和透明边缘。

   ```sh
   "$py" -B "$workflow" build "$work"
   ```

## 接入自己的生图服务

### 填写作品目录的配置

打开初始化生成的 `.config/image-service.json`，按 `_help` 填写服务设置。直接使用本文件时，`profilePath` 留为 `null`。配置供整个作品目录复用，已有项目可以重跑原初始化命令补建模板。缺项或格式错误时，命令会报告配置文件路径和待改字段。

`baseUrl` 填包含 API 前缀的地址，例如 `/v1`。工作流会继续拼接 `/images/generations` 或 `/images/edits`。客户端要求 HTTPS，回环地址也可用 HTTP。参考图会发送至该配置对应的服务。 [OpenAI 生成接口](https://developers.openai.com/api/reference/resources/images/methods/generate) · [编辑接口](https://developers.openai.com/api/reference/resources/images/methods/edit)

下面是一份填好后的配置。变量名可以自行选定，密钥值留在本机终端。使用别人发来的作品目录时，先核对其中的服务地址和变量名，再把自己的密钥设到环境里。

```json
{
  "adapter": "openai-images",
  "baseUrl": "https://api.openai.com/v1",
  "model": "gpt-image-2.5-sunburst-2026-09-08",
  "apiKeyEnv": "STICKER_IMAGE_API_KEY",
  "referenceImages": 1,
  "transparentBackground": true
}
```

### 通过对话提供配置

如果更喜欢在聊天里告诉 Agent，可以只给服务地址、模型 ID、密钥环境变量**名**，以及已知的参考图和透明背景支持情况。Agent 将这些设置保存到你指定的位置。省略位置时，默认放在作品根目录下的 `.config/image-service.custom.json`。已有配置文件也可以直接给路径。

> 使用我自己的同步 OpenAI Images 服务。地址是 `https://image.example.com/v1`，模型是 `my-image-model`，密钥变量名是 `STICKER_IMAGE_API_KEY`。服务支持 1 张参考图和透明 PNG。请另建配置并用它生图。

保存好配置后，Agent 用以下命令登记路径。第一条用于默认另存位置，第二条用于指定的已有文件。

```sh
"$py" -B "$workflow" set-image-service-config "$root"
"$py" -B "$workflow" set-image-service-config "$root" --config "/absolute/path/to/image-service.json"
```

命令把最近一次选用的路径写入作品根目录配置的 `profilePath`。在作品目录内的文件使用相对路径，目录移到别处后仍可读取。目录外的文件保留绝对路径。新会话使用同一作品目录时会自动复用，选用另一份配置只更新当前路径。

若已记住的文件被移动、删除或配置有误，生图会停止并列出路径。可以把文件恢复到原位置、再次登记新位置，或将 `profilePath` 改为 `null` 并填写根目录配置。也可以用 `set-image-service-config "$root" --clear` 取消选用自定义文件，再使用根目录的设置。

### 在本机输入密钥

如果终端启动时已通过 `~/.zshrc` 或 PowerShell 配置文件设置同名环境变量，生图命令会直接使用其继承到的值。想临时换密钥时，在启动 Agent 或生图命令前，于同一个终端覆盖该变量。若启动脚本可能重新加载，让它只在变量尚未设置时提供长期值。把密钥直接写入启动文件会在磁盘上保存明文。

需要输入或临时覆盖密钥时，在自己的终端执行以下命令。提示出现后输入密钥并回车，输入内容不会回显。配置中的 `apiKeyEnv` 要与命令里的变量名一致。

在 macOS 或 Linux 的 Bash、Zsh 中运行。

```sh
{
    printf '输入生图服务密钥: '
    IFS= read -r -s STICKER_IMAGE_API_KEY && export STICKER_IMAGE_API_KEY
    printf '\n'
}
```

在 Windows PowerShell 中运行。 [Microsoft Read-Host 文档](https://learn.microsoft.com/en-us/powershell/module/microsoft.powershell.utility/read-host)

```powershell
& {
    $stickerImageSecret = Read-Host '输入生图服务密钥' -AsSecureString
    $env:STICKER_IMAGE_API_KEY = [System.Net.NetworkCredential]::new('', $stickerImageSecret).Password
}
```

变量只对当前终端及它启动的程序可用。从这个终端启动命令行 Agent，或在同一个终端运行下节的 `generate` 命令。已经从其他地方启动的 Agent 不会收到这个终端新设的变量。如果 Agent 的执行环境拿不到密钥，可以让它给出当前阶段的命令，由你在本机运行，再告诉它素材已就绪。审核和合成可接着使用工作目录里的文件。

### 运行生图工作流

`referenceImages` 声明模型和网关接受的参考图上限。纯文生图填 `0`。填 `1` 时使用固定角色参考图。补帧且可收多张时，再按上限附加前后的已审关键帧。用户要求沿用参考图时，选支持参考图的模型，或按审核流程交付手工帧。纯文生图候选也要审核角色一致性。

请求生成一张 1024×1024 PNG。文生图走 JSON `/images/generations`，有参考图时走 multipart `/images/edits`。优先读取 `data[0].b64_json`，也兼容第三方返回的 `data[0].url`。URL 下载使用公网 HTTPS 443 直连，拒绝重定向、私网或回环地址，下载请求与生图 API 鉴权分开。服务若提供签名 URL，查询参数仅用于该次下载。 [OpenAI Images 响应格式](https://developers.openai.com/api/reference/resources/images/methods/generate)

`transparentBackground: true` 会发送透明背景参数，帧提示词也要求背景区域有真实 Alpha。只有实际像素通过检查才能转入成品帧目录。不透明的原图保留在 `source/`，可手工抠图或换一张图，再用 `add-frame` 补入对应帧。

```sh
"$py" -B "$workflow" generate "$work" --stage reference
"$py" -B "$workflow" review-reference "$work"
# 用户审核并批准角色参考图后，再执行：
"$py" -B "$workflow" approve-reference "$work" --digest "$approved_reference_digest"
"$py" -B "$workflow" generate "$work" --stage keyframes
# 按上节提交并记录关键帧审批后，再执行：
"$py" -B "$workflow" generate "$work" --stage frames
```

以上命令使用作品目录记住的自定义配置。`profilePath` 为 `null` 或尚未设置时，使用作品根目录配置中的服务设置。若只想在本次生图改用另一份配置，在命令末尾加 `--config "/absolute/path/to/image-service.json"`。

已有的合法目标帧、本次请求已保存的原图都可复用。服务明确拒绝时，修正配置或等待限流解除后重跑同一命令。受理状态不明时，查询服务端记录或手工补入该帧。只有确认可以重新提交时，才将报错指向的 `*.request.json` 移到其他位置留存，再重跑。请求记录保留可用的请求 ID。表情修订的生图参数或已保存的素材需要替换时，建立新修订并把可复用的原图或姿势导入其中。

若进程异常终止留下 `.workflow-lock`，确认该目录没有正在运行的工作流后移除空锁目录。保留对应请求记录以便核查是否已受理。
