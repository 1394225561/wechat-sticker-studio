"""Build reproducible ZIP assets from an explicit list of public files."""

import argparse
import hashlib
import re
import stat
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, ZipFile, ZipInfo

ROOT = Path(__file__).resolve().parents[1]
PROJECT = "wechat-sticker-studio"
SKILL_ROOT = PurePosixPath("skills") / PROJECT
NOTICES = ("LICENSE", "THIRD_PARTY_NOTICES.md")
SKILL_FILES = (
    "SKILL.md", "requirements.txt",
    "scripts/sticker_gif.py", "scripts/pack_submission.py",
    "references/character-motion.md", "references/png-workflow.md", "references/submission.md",
    "assets/sticker.template.json", "assets/single-submission.template.json",
    "assets/album-submission.template.json",
)
DEMO_FILES = (
    "examples/wave/draw_frames.py", "examples/wave/sticker.json", "examples/wave/single-submission.json",
    *(f"examples/wave/frames/{index:02}.png" for index in range(1, 13)),
)
SOURCE_FILES = (
    ".gitignore", "README.md", "requirements.txt", *NOTICES,
    "scripts/sticker_gif.py", "scripts/pack_submission.py", "scripts/compare_gifs.py",
    "scripts/build_release.py", "tests/test_sticker_gif.py", "tests/test_pack_submission.py",
    *(str(SKILL_ROOT / name) for name in SKILL_FILES), *DEMO_FILES,
)
SKILL_QUICKSTART = r"""# 运行小样

从本文件所在目录执行。使用 Python 3.12 和独立虚拟环境。

```sh
python3.12 -m venv .venv
py=.venv/bin/python
"$py" -m pip install -r requirements.txt
mkdir -p output/phase-a output/phase-c
"$py" -B scripts/sticker_gif.py compose examples/wave/sticker.json output/phase-a/wave.gif
"$py" -B scripts/sticker_gif.py validate output/phase-a/wave.gif \
  --manifest examples/wave/sticker.json --preview output/phase-a/wave-preview.gif
"$py" -B scripts/pack_submission.py examples/wave/single-submission.json \
  --output output/phase-c/机器人-单品示例.zip
```

成品为透明、无限循环的 240 × 240 GIF，共 12 帧，含一次 240 毫秒停顿。
投稿预检使用 2026-10-28 保存的微信官方快照。

将整个 `wechat-sticker-studio/` 文件夹放进作品项目对应的 Skill 目录。
Codex 使用 `.agents/skills/`，Claude Code 使用 `.claude/skills/`，
DeepSeek Harness 使用 Git 项目根目录的 `.dsh/skills/`。
在新会话中指定使用 `wechat-sticker-studio`，并提供虚拟环境中 Python 的绝对路径。
"""


def add_file(archive, name, source):
    path = ROOT / source
    info = ZipInfo(name)
    info.create_system = 3
    if path.is_symlink():
        target = path.readlink()
        if target.is_absolute() or not path.resolve().is_relative_to(ROOT):
            raise ValueError(f"unsafe source symlink: {source}")
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        data = target.as_posix().encode("utf-8")
    else:
        info.external_attr = (stat.S_IFREG | 0o644) << 16
        data = path.read_bytes()
    archive.writestr(info, data, compress_type=ZIP_DEFLATED)


def build(version, output):
    stem = f"{PROJECT}-{version}"
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"{output}: choose a new output directory")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as directory:
        staged = Path(directory) / "assets"
        staged.mkdir()
        source_zip = staged / f"{stem}-source.zip"
        skill_zip = staged / f"{stem}-skill.zip"
        with ZipFile(source_zip, "w") as archive:
            for name in SOURCE_FILES:
                add_file(archive, f"{stem}/{name}", name)
        with ZipFile(skill_zip, "w") as archive:
            for name in SKILL_FILES:
                add_file(archive, f"{PROJECT}/{name}", SKILL_ROOT / name)
            for name in (*NOTICES, *DEMO_FILES):
                add_file(archive, f"{PROJECT}/{name}", name)
            archive.writestr(ZipInfo(f"{PROJECT}/QUICKSTART.md"), SKILL_QUICKSTART.encode("utf-8"),
                             compress_type=ZIP_DEFLATED)
        checksums = "".join(
            f"{hashlib.sha256(path.read_bytes()).hexdigest()}  {path.name}\n"
            for path in (source_zip, skill_zip)
        )
        (staged / "SHA256SUMS").write_text(checksums, encoding="utf-8")
        staged.rename(output)
    print(checksums, end="")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("version", help="release version, e.g. v0.1.0-rc.1")
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()
    if not re.fullmatch(r"v[0-9]+\.[0-9]+\.[0-9]+(?:-[0-9A-Za-z]+(?:[.-][0-9A-Za-z]+)*)?", args.version):
        parser.error("use a version such as v0.1.0 or v0.1.0-rc.1")
    try:
        build(args.version, args.output)
    except (OSError, ValueError) as exc:
        parser.exit(1, f"{exc}\n")


if __name__ == "__main__":
    main()
