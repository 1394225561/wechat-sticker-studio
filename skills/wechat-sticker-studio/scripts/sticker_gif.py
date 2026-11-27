"""Compose and inspect transparent animated stickers."""

import argparse
import hashlib
import json
import os
import sys
from io import BytesIO
from pathlib import Path
from tempfile import TemporaryDirectory

from PIL import Image, ImageChops, ImageDraw, ImageSequence, __version__ as pillow_version

CANVAS = (240, 240)
MIN_FRAME_COUNT = 2
MAX_BYTES = 500_000


def read_manifest(path):
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
        version, threshold, frames = (
            manifest["version"], manifest["alpha_threshold"], manifest["frames"]
        )
        if type(version) is not int or version != 1:
            raise ValueError("expected manifest version 1")
        if type(threshold) is not int or not 0 <= threshold <= 254:
            raise ValueError("alpha_threshold must be an integer from 0 to 254")
        if not isinstance(frames, list) or len(frames) < MIN_FRAME_COUNT:
            raise ValueError(f"expected at least {MIN_FRAME_COUNT} frame entries")
        paths, durations = [], []
        for index, frame in enumerate(frames, 1):
            if not isinstance(frame, dict):
                raise ValueError(f"frame {index}: expected a path and duration_ms")
            name, duration = frame.get("path"), frame.get("duration_ms")
            if not isinstance(name, str) or not name or Path(name).is_absolute():
                raise ValueError(f"frame {index}: path must be relative to the manifest")
            if type(duration) is not int or not 10 <= duration <= 655350 or duration % 10:
                raise ValueError(f"frame {index}: duration_ms must be 10–655350 in 10 ms steps")
            paths.append(path.parent / name)
            durations.append(duration)
        return paths, durations, threshold
    except (OSError, ValueError, KeyError, TypeError) as exc:
        raise ValueError(f"{path}: {exc}") from exc


def load_png(path, index, threshold):
    try:
        with Image.open(path, formats=("PNG",)) as png:
            if png.size != CANVAS or png.n_frames != 1:
                raise ValueError(f"expected one 240×240 PNG, got {png.size} and {png.n_frames} frame(s)")
            png.verify()
        with Image.open(path, formats=("PNG",)) as png:
            rgba = png.convert("RGBA")
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError(f"frame {index} ({path}): {exc}") from exc
    mask = rgba.getchannel("A").point(lambda alpha: 255 if alpha <= threshold else 0)
    if mask.getextrema() != (0, 255):
        raise ValueError(f"frame {index} ({path}): needs both foreground and background at threshold {threshold}")
    return rgba, mask


def import_pngs(paths, manifest, durations, threshold):
    if len(paths) < MIN_FRAME_COUNT:
        raise ValueError(f"expected at least {MIN_FRAME_COUNT} PNGs")
    if len(durations) != len(paths):
        raise ValueError(f"expected {len(paths)} frame delays, got {len(durations)}")
    if not 0 <= threshold <= 254:
        raise ValueError("alpha_threshold must be an integer from 0 to 254")
    if manifest.exists() or manifest.is_symlink():
        raise FileExistsError(f"{manifest}: already exists")
    entries = []
    for index, (path, duration) in enumerate(zip(paths, durations), 1):
        if not 10 <= duration <= 655350 or duration % 10:
            raise ValueError(f"frame {index}: duration_ms must be 10–655350 in 10 ms steps")
        load_png(path, index, threshold)
        entries.append({"path": os.path.relpath(path, manifest.parent), "duration_ms": duration})
    data = {"version": 1, "alpha_threshold": threshold, "frames": entries}
    manifest.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=manifest.parent) as staging:
        candidate = Path(staging) / "sticker.json"
        candidate.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        manifest.hardlink_to(candidate)
    return {"manifest": str(manifest), "frame_count": len(entries), "durations_ms": durations}


def encode_frame(frame, transparent):
    # Use the PNG's straight RGB at retained pixels. Clear hidden RGB before quantizing.
    rgb = frame.convert("RGB")
    rgb.paste((0, 0, 0), mask=transparent)
    indexed = rgb.quantize(colors=255)
    palette = indexed.getpalette()[:765]
    indexed.putpalette(palette + [0] * (768 - len(palette)))
    indexed.paste(255, mask=transparent)
    return indexed


def inspect_gif(path, expected_durations=None, *, expected_frame_count=None, data=None):
    if expected_frame_count is None and expected_durations is not None:
        expected_frame_count = len(expected_durations)
    try:
        if data is None:
            data = path.read_bytes()
        frames, details = [], []
        with Image.open(BytesIO(data), formats=("GIF",)) as gif:
            width, height = gif.size
            loop = gif.info.get("loop")
            for index, frame in enumerate(ImageSequence.Iterator(gif), 1):
                rgba = frame.convert("RGBA")
                histogram = rgba.getchannel("A").histogram()
                frames.append(rgba)
                details.append({
                    "frame": index,
                    "duration_ms": frame.info.get("duration", 0),
                    "disposal": frame.disposal_method,
                    "transparent_pixels": histogram[0],
                    "opaque_pixels": histogram[255],
                })
    except (OSError, ValueError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError(f"{path}: cannot decode GIF: {exc}") from exc

    durations = [frame["duration_ms"] for frame in details]
    transparent = [frame["frame"] for frame in details if not frame["transparent_pixels"]]
    empty = [frame["frame"] for frame in details if not frame["opaque_pixels"]]
    frame_count = len(frames)
    checks = {
        "canvas_240x240": (width, height) == CANVAS,
        "at_least_two_frames": frame_count >= MIN_FRAME_COUNT,
        "matches_expected_frame_count": None if expected_frame_count is None else frame_count == expected_frame_count,
        "infinite_loop": loop == 0,
        "size_at_most_500000_bytes": len(data) <= MAX_BYTES,
        "transparent_background_each_frame": not transparent,
        "visible_subject_each_frame": not empty,
        "positive_durations": all(durations),
        "matches_manifest_durations": None if expected_durations is None else durations == expected_durations,
    }
    errors = []
    for key, detail in [
        ("canvas_240x240", f"expected 240×240, decoded {width}×{height}"),
        ("at_least_two_frames", f"expected at least {MIN_FRAME_COUNT} frames, decoded {frame_count}"),
        ("matches_expected_frame_count", f"expected {expected_frame_count} frames, decoded {frame_count}"),
        ("infinite_loop", f"expected loop=0; got {loop!r}"),
        ("size_at_most_500000_bytes", f"decoded file has {len(data)} bytes; limit is {MAX_BYTES}"),
        ("transparent_background_each_frame", f"no transparent pixels in frame(s) {transparent}"),
        ("visible_subject_each_frame", f"no opaque pixels in frame(s) {empty}"),
        ("positive_durations", f"zero or missing duration in frame(s) {[i for i, d in enumerate(durations, 1) if not d]}"),
        ("matches_manifest_durations", f"expected delays {expected_durations}; decoded {durations}"),
    ]:
        if checks[key] is False:
            errors.append(detail)
    return {
        "path": str(path), "decoder": f"Pillow {pillow_version}", "sha256": hashlib.sha256(data).hexdigest(),
        "size_bytes": len(data), "width": width, "height": height, "frame_count": frame_count,
        "expected_frame_count": expected_frame_count,
        "loop_count": loop, "durations_ms": durations, "expected_durations_ms": expected_durations,
        "total_duration_ms": sum(durations), "frames": details, "checks": checks,
        "strict_pass": not errors, "errors": errors,
    }, frames


def compose(manifest, output, replace):
    paths, durations, threshold = read_manifest(manifest)
    if output.resolve() in {path.resolve() for path in [manifest, *paths]}:
        raise ValueError(f"{output}: output would replace an input")
    if not replace and (output.exists() or output.is_symlink()):
        raise FileExistsError(f"{output}: already exists; pass --replace to replace a verified output")
    frames, masks = [], []
    for index, path in enumerate(paths, 1):
        rgba, mask = load_png(path, index, threshold)
        masks.append(mask)
        frames.append(encode_frame(rgba, mask))

    output.parent.mkdir(parents=True, exist_ok=True)
    with TemporaryDirectory(dir=output.parent) as staging:
        candidate = Path(staging) / "sticker.gif"
        frames[0].save(
            candidate, save_all=True, append_images=frames[1:], duration=durations,
            loop=0, disposal=2, transparency=255, background=255, optimize=False,
        )
        report, decoded = inspect_gif(candidate, durations)
        wrong_masks = [
            index for index, (mask, frame) in enumerate(zip(masks, decoded), 1)
            if ImageChops.difference(mask, ImageChops.invert(frame.getchannel("A"))).getbbox()
        ]
        matches_masks = len(decoded) == len(masks) and not wrong_masks
        report["checks"]["matches_thresholded_png_masks"] = matches_masks
        if len(decoded) == len(masks) and wrong_masks:
            report["errors"].append(f"decoded transparency differs from the PNG in frame(s) {wrong_masks}")
        report["encoder"] = f"Pillow {pillow_version}"
        report["alpha_threshold"] = threshold
        report["path"] = str(output)
        report["strict_pass"] = not report["errors"]
        report["published"] = report["strict_pass"]
        if report["published"]:
            if replace:
                candidate.replace(output)
            else:
                output.hardlink_to(candidate)
    return report


def write_preview(path, source, frames, durations):
    sheet_path = path.with_name(f"{path.stem}-frames.png")
    if source.resolve() in {path.resolve(), sheet_path.resolve()}:
        raise ValueError("preview would overwrite its source GIF")
    panels = []
    for frame in frames:
        # The scaled artwork is centered in each 120 px chat-size panel.
        framed = frame.copy()
        framed.thumbnail((112, 112), Image.Resampling.LANCZOS)
        panel = Image.new("RGB", (240, 120), "#f7f8fa")
        panel.paste("#20242c", (120, 0, 240, 120))
        for left in (0, 120):
            point = (left + (120 - framed.width) // 2, (120 - framed.height) // 2)
            panel.paste(framed, point, framed.getchannel("A"))
        panels.append(panel)

    path.parent.mkdir(parents=True, exist_ok=True)
    panels[0].save(path, format="GIF", save_all=True, append_images=panels[1:],
                   duration=durations, loop=0, disposal=1)
    sheet = Image.new("RGB", (720, 142 * ((len(panels) + 2) // 3)), "#ffffff")
    draw = ImageDraw.Draw(sheet)
    for index, (panel, duration) in enumerate(zip(panels, durations)):
        x, y = index % 3 * 240, index // 3 * 142
        sheet.paste(panel, (x, y))
        draw.text((x + 8, y + 123), f"{index + 1:02} / {duration} ms", fill="#20242c")
    sheet.save(sheet_path)
    return {"animation": str(path), "contact_sheet": str(sheet_path)}


def frame_count_argument(value):
    try:
        count = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("frame count must be an integer") from exc
    if count < MIN_FRAME_COUNT:
        raise argparse.ArgumentTypeError(f"frame count must be at least {MIN_FRAME_COUNT}")
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    importer = sub.add_parser("import-png", help="verify ordered PNGs and create a manifest")
    importer.add_argument("manifest", type=Path)
    importer.add_argument("pngs", type=Path, nargs="+")
    importer.add_argument("--frame-count", type=frame_count_argument, help="require this many input PNGs")
    timing = importer.add_mutually_exclusive_group()
    timing.add_argument("--duration-ms", type=int, default=80, help="same delay for all frames")
    timing.add_argument("--durations-ms", help="comma-separated list of one delay per PNG")
    importer.add_argument("--alpha-threshold", type=int, default=128)
    make = sub.add_parser("compose")
    make.add_argument("manifest", type=Path)
    make.add_argument("output", type=Path)
    make.add_argument("--replace", action="store_true")
    check = sub.add_parser("validate")
    check.add_argument("gif", type=Path)
    expectation = check.add_mutually_exclusive_group()
    expectation.add_argument("--manifest", type=Path, help="check frame count and timing against this manifest")
    expectation.add_argument("--frame-count", type=frame_count_argument, help="require this many decoded frames")
    check.add_argument("--preview", type=Path, help="write an animated light/dark GIF and its PNG contact sheet")
    args = parser.parse_args()
    try:
        if args.command == "import-png":
            if args.frame_count is not None and len(args.pngs) != args.frame_count:
                raise ValueError(f"expected {args.frame_count} PNGs, got {len(args.pngs)}")
            try:
                durations = ([int(value) for value in args.durations_ms.split(",")]
                             if args.durations_ms is not None else [args.duration_ms] * len(args.pngs))
            except ValueError as exc:
                raise ValueError("--durations-ms requires comma-separated integer milliseconds") from exc
            report = import_pngs(args.pngs, args.manifest, durations, args.alpha_threshold)
            print(json.dumps(report, ensure_ascii=False, indent=2))
            return 0
        if args.command == "compose":
            report = compose(args.manifest, args.output, args.replace)
        else:
            durations = read_manifest(args.manifest)[1] if args.manifest else None
            report, frames = inspect_gif(args.gif, durations, expected_frame_count=args.frame_count)
            if args.preview:
                report["preview"] = write_preview(args.preview, args.gif, frames, report["durations_ms"])
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0 if report["strict_pass"] else 1
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
