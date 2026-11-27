"""Preflight a WeChat submission manifest and optionally write an upload-material ZIP."""

import argparse
import hashlib
import json
import re
import sys
import unicodedata
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory
from zipfile import ZIP_DEFLATED, BadZipFile, ZipFile, ZipInfo

from PIL import Image, ImageSequence

from sticker_gif import FRAME_COUNT, MAX_BYTES, inspect_gif

SNAPSHOT_DATE = "2026-10-28"
ARTWORK = {
    "banner": ("01-专辑详情页横幅", (750, 400), ("PNG", "JPEG"), 500_000, False),
    "cover": ("02-专辑封面", (240, 240), ("PNG",), 500_000, True),
    "icon": ("03-聊天页图标", (50, 50), ("PNG",), 100_000, True),
    "guide": ("04-赞赏引导图", (750, 560), ("PNG", "GIF"), 500_000, False),
    "thanks": ("05-赞赏致谢图", (750, 750), ("PNG", "GIF"), 500_000, False),
}
EXTENSIONS = {"PNG": "png", "JPEG": "jpg", "GIF": "gif"}


def json_text(value):
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def submission_text(value, maximum=None, minimum=1):
    if not isinstance(value, str):
        raise ValueError("expected text")
    value = unicodedata.normalize("NFC", value.strip())
    if len(value) < minimum or (maximum is not None and len(value) > maximum):
        bounds = f"{minimum}–{maximum}" if maximum is not None else f"at least {minimum}"
        raise ValueError(f"expected {bounds} characters; got {len(value)}")
    if any(unicodedata.category(char)[0] in "CS" for char in value):
        raise ValueError("text contains a control or special symbol")
    return value


def read_asset(ref, base, limit):
    if not isinstance(ref, dict):
        raise ValueError("expected a file reference with path and sha256")
    name, expected = ref.get("path"), ref.get("sha256")
    if not isinstance(name, str) or not name.strip() or Path(name).is_absolute():
        raise ValueError("path must be relative to the manifest")
    if not isinstance(expected, str) or not re.fullmatch(r"[a-fA-F0-9]{64}", expected):
        raise ValueError("sha256 must contain 64 hexadecimal digits")
    path = base / name
    with path.open("rb") as file:
        data = file.read(limit + 1)
    if len(data) > limit:
        raise ValueError(f"file exceeds {limit} bytes")
    actual = hashlib.sha256(data).hexdigest()
    if actual != expected.lower():
        raise ValueError(f"sha256 mismatch: expected {expected.lower()}, got {actual}")
    return path, actual, data


def inspect_artwork(data, key):
    stem, size, formats, _, requires_alpha = ARTWORK[key]
    with Image.open(BytesIO(data)) as image:
        kind, actual_size = image.format, image.size
        if kind not in formats:
            raise ValueError(f"expected {' or '.join(formats)}; decoded {kind}")
        if actual_size != size:
            raise ValueError(f"expected {size[0]}×{size[1]}; decoded {actual_size[0]}×{actual_size[1]}")
        frames = getattr(image, "n_frames", 1)
        if kind != "GIF" and frames != 1:
            raise ValueError("expected a single-frame image")
        alphas = [frame.convert("RGBA").getchannel("A").getextrema()
                  for frame in ImageSequence.Iterator(image)]
        if any(high == 0 for _, high in alphas):
            raise ValueError("decoded artwork has an empty frame")
        if requires_alpha and alphas[0][0] != 0:
            raise ValueError("decoded image has no fully transparent background pixels")
        details = {
            "format": kind, "width": actual_size[0], "height": actual_size[1],
            "size_bytes": len(data), "frame_count": frames,
            "has_transparency": any(low < 255 for low, _ in alphas),
        }
    return f"配图/{stem}.{EXTENSIONS[kind]}", details


def preflight(manifest, report):
    data = json.loads(manifest.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or type(data.get("version")) is not int or data["version"] != 1:
        raise ValueError("expected submission manifest version 1")
    kind = data.get("type")
    if kind not in ("single", "album"):
        raise ValueError("type must be single or album")
    report["type"] = kind
    portable = {"version": 1, "type": kind, "stickers": []}
    entries = {}

    def error(item, message, ref=None):
        report["errors"].append({
            "item": item, "path": ref.get("path") if isinstance(ref, dict) else None,
            "message": str(message),
        })

    def text_field(mapping, key, label, maximum=None, minimum=1):
        try:
            return submission_text(mapping.get(key), maximum, minimum)
        except ValueError as exc:
            error(label, exc)
            return ""

    def artwork(key, ref, label):
        try:
            _, digest, content = read_asset(ref, manifest.parent, ARTWORK[key][3])
            name, details = inspect_artwork(content, key)
        except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
            error(label, exc, ref)
            return None
        if details["has_transparency"] and not ARTWORK[key][4]:
            report["warnings"].append(f"{label}: translucent pixels decoded; the guide recommends an opaque background")
        entries[name] = content
        report["artwork"][label] = {**details, "path": ref["path"], "sha256": digest, "archive_path": name}
        return {"path": name, "sha256": digest}

    if kind == "single":
        if not isinstance(data.get("tags"), list) or not data["tags"]:
            error("tags", "provide at least one tag to select in the upload form")
        else:
            portable["tags"] = [
                text_field({"tag": tag}, "tag", f"tags[{index}]")
                for index, tag in enumerate(data["tags"], 1)
            ]
        if data.get("assets") or data.get("appreciation"):
            error("type", "album artwork and appreciation are only supported in album manifests")
    else:
        for key, maximum in (("name", 8), ("description", 80), ("copyright", 10)):
            portable[key] = text_field(data, key, key, maximum)
        if any(unicodedata.category(char).startswith("P") for char in portable["name"]):
            error("name", "album name must not contain punctuation")
        if re.search(r"[\u3400-\u9fff]", portable["name"]) and any(c.isspace() for c in portable["name"]):
            report["warnings"].append("name: the guide recommends avoiding spaces in Chinese album names")
        assets = data.get("assets")
        if not isinstance(assets, dict):
            error("assets", "expected album artwork references")
            assets = {}
        portable["assets"] = {key: artwork(key, assets.get(key), f"assets.{key}")
                              for key in ("banner", "cover", "icon")}
        appreciation = data.get("appreciation", {"enabled": False})
        if not isinstance(appreciation, dict) or type(appreciation.get("enabled")) is not bool:
            error("appreciation.enabled", "expected true or false")
        else:
            portable["appreciation"] = {"enabled": appreciation["enabled"]}
            if appreciation["enabled"]:
                portable["appreciation"].update({
                    "message": text_field(appreciation, "message", "appreciation.message", 15, 5),
                    "guide": artwork("guide", appreciation.get("guide"), "appreciation.guide"),
                    "thanks": artwork("thanks", appreciation.get("thanks"), "appreciation.thanks"),
                })
            elif any(key in appreciation for key in ("message", "guide", "thanks")):
                error("appreciation.enabled", "enable appreciation or remove its text and image references")

    if "ai_disclosure" in data:
        portable["ai_disclosure"] = text_field(data, "ai_disclosure", "ai_disclosure")
    if "form_notes" in data:
        if not isinstance(data["form_notes"], list):
            error("form_notes", "expected a list of text notes")
        else:
            portable["form_notes"] = [
                text_field({"note": note}, "note", f"form_notes[{index}]")
                for index, note in enumerate(data["form_notes"], 1)
            ]
    stickers = data.get("stickers")
    if not isinstance(stickers, list):
        raise ValueError("stickers must be an ordered list")
    if not (len(stickers) == 1 if kind == "single" else 8 <= len(stickers) <= 24):
        expected = "one sticker" if kind == "single" else "8–24 stickers"
        error("stickers", f"expected {expected}; got {len(stickers)}")
    if len(stickers) > 24:
        return portable, entries
    meanings, hashes = {}, {}
    for index, ref in enumerate(stickers, 1):
        label = f"stickers[{index}]"
        if not isinstance(ref, dict):
            error(label, "expected a sticker object with path, sha256 and meaning")
            continue
        meaning = text_field(ref, "meaning", f"{label}.meaning", 4)
        if any(unicodedata.category(char).startswith("P") for char in meaning):
            report["warnings"].append(f"{label}.meaning: the guide recommends avoiding punctuation")
        if meaning and meaning in meanings:
            report["warnings"].append(f"{label}.meaning: repeats stickers[{meanings[meaning]}].meaning")
        meanings.setdefault(meaning, index)
        try:
            path, digest, content = read_asset(ref, manifest.parent, MAX_BYTES)
            delays = ref.get("durations_ms")
            if delays is not None and (
                not isinstance(delays, list) or len(delays) != FRAME_COUNT
                or any(type(delay) is not int or delay < 10 or delay > 655350 or delay % 10 for delay in delays)
            ):
                raise ValueError("durations_ms must list 12 valid GIF frame delays in milliseconds")
            result, _ = inspect_gif(path, delays, data=content)
        except (OSError, ValueError) as exc:
            error(label, exc, ref)
            continue
        for issue in result["errors"]:
            error(label, issue, ref)
        if digest in hashes:
            error(label, f"identical GIF bytes to stickers[{hashes[digest]}]", ref)
        hashes.setdefault(digest, index)
        name = f"表情图/{index:02}.gif"
        entries[name] = content
        portable_ref = {"path": name, "sha256": digest, "meaning": meaning}
        if delays is not None:
            portable_ref["durations_ms"] = delays
        portable["stickers"].append(portable_ref)
        report["stickers"].append({
            "number": index, "meaning": meaning, "archive_path": name,
            **{key: result[key] for key in ("sha256", "width", "height", "frame_count", "loop_count",
                                            "size_bytes", "durations_ms", "checks")},
            "path": ref["path"],
        })
    return portable, entries


def upload_notes(portable):
    kind = "动态表情单品" if portable["type"] == "single" else "动态表情专辑"
    lines = [
        f"# {kind}填写说明", "",
        f"已按 {SNAPSHOT_DATE} 保存的微信官方制作规范快照预检。上传时以实际页面要求为准。", "",
    ]
    if portable["type"] == "single":
        lines.extend([f"标签建议：{'、'.join(portable['tags'])}。请在后台选择实际可用的标签。", ""])
    else:
        lines.extend([
            f"专辑名称：{portable['name']}", f"专辑介绍：{portable['description']}",
            f"版权信息：{portable['copyright']}", "",
            "配图按 `配图/` 内的文件名上传。动态缩略图如需选帧，请在后台选择。", "",
        ])
        appreciation = portable["appreciation"]
        if appreciation["enabled"]:
            lines.extend([f"赞赏引导语：{appreciation['message']}。请在后台核对赞赏开关和两张配图。", ""])
    if "ai_disclosure" in portable:
        lines.extend([f"生成合成内容说明：{portable['ai_disclosure']}", ""])
    if portable.get("form_notes"):
        lines.extend(["以下内容请以实际表单为准。", ""])
        lines.extend(f"- {note}" for note in portable["form_notes"])
        lines.append("")
    lines.extend(["按编号上传，含义词以本表为准。", "", "| 序号 | 文件 | 含义词 |", "| --- | --- | --- |"])
    lines.extend(f"| {index:02} | `{item['path']}` | {item['meaning']} |"
                 for index, item in enumerate(portable["stickers"], 1))
    return "\n".join(lines) + "\n"


def write_zip(output, entries):
    if output.suffix.lower() != ".zip":
        raise ValueError("use a .zip output path")
    if output.exists() or output.is_symlink():
        raise FileExistsError(f"{output}: already exists; choose a new output path")
    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        candidate = Path(staging) / "submission.zip"
        with ZipFile(candidate, "w") as archive:
            for name, content in entries.items():
                archive.writestr(ZipInfo(name), content, compress_type=ZIP_DEFLATED)
        with ZipFile(candidate) as archive:
            for name, content in entries.items():
                if archive.read(name) != content:
                    raise ValueError(f"ZIP member verification failed for {name}")
        digest = hashlib.sha256(candidate.read_bytes()).hexdigest()
        output.hardlink_to(candidate)
    return {"path": str(output), "sha256": digest, "member_count": len(entries)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("manifest", type=Path)
    parser.add_argument("--output", type=Path, help="publish a ZIP after preflight; omit to validate only")
    args = parser.parse_args()
    report = {
        "manifest": str(args.manifest), "official_snapshot_date": SNAPSHOT_DATE,
        "live_upload_form_verified": False, "stickers": [], "artwork": {},
        "warnings": [], "errors": [], "zip": None,
    }
    try:
        portable, entries = preflight(args.manifest, report)
        if not report["errors"] and args.output is not None:
            entries["submission.json"] = json_text(portable).encode("utf-8")
            entries["填写说明.md"] = upload_notes(portable).encode("utf-8")
            report["zip"] = write_zip(args.output, entries)
    except (OSError, ValueError, BadZipFile) as exc:
        report["errors"].append({"item": "submission", "path": None, "message": str(exc)})
    report["preflight_pass"] = not report["errors"]
    print(json_text(report), end="")
    return 0 if report["preflight_pass"] else 1


if __name__ == "__main__":
    sys.exit(main())
