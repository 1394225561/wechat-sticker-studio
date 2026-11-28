"""Manage a sticker's artwork, keyframe review, and GIF delivery."""

import argparse
import hashlib
import json
import re
import sys
from contextlib import contextmanager
from dataclasses import asdict
from datetime import datetime, timezone
from io import BytesIO
from pathlib import Path, PurePosixPath
from tempfile import TemporaryDirectory

from PIL import Image, ImageDraw

from openai_images import ImageRequestError, MAX_IMAGE_BYTES, make_request, parse_profile, receive_image
from sticker_gif import CANVAS, compose, import_pngs, inspect_gif, load_png, read_manifest, write_preview


FOLDERS = ("source", "keyframes", "frames", "review", "output")
IMAGE_SERVICE_CONFIG = Path(".config") / "image-service.json"
CUSTOM_IMAGE_SERVICE_CONFIG = IMAGE_SERVICE_CONFIG.with_name("image-service.custom.json")
ALPHA_THRESHOLD = 128
DEFAULT_DELAY = 80
TRANSPARENT_FRAME_PROMPT = (
    " Deliver a PNG with real alpha transparency outside the character. "
    "The transparent area should contain zero-alpha pixels, without a solid backdrop, floor, or drawn checkerboard."
)


def json_bytes(data):
    return (json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode()


def digest(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    return json.loads(path.read_text(encoding="utf-8"))


def write_bytes(path, data, *, replace=False):
    with TemporaryDirectory(dir=path.parent) as directory:
        candidate = Path(directory) / path.name
        candidate.write_bytes(data)
        if replace:
            candidate.replace(path)
        else:
            path.hardlink_to(candidate)


def keep_bytes(path, data):
    if path.is_symlink():
        raise ValueError(f"{path}: expected a regular file")
    if not path.exists():
        write_bytes(path, data)
    elif path.read_bytes() != data:
        raise ValueError(f"{path}: existing content differs; use a new revision")


def directory(path):
    if path.is_symlink() or (path.exists() and not path.is_dir()):
        raise ValueError(f"{path}: expected a directory")
    path.mkdir(exist_ok=True)
    return path


@contextmanager
def lock(path):
    marker = path / ".workflow-lock"
    try:
        marker.mkdir()
    except FileExistsError:
        raise ValueError(f"{path}: another operation or interrupted lock exists") from None
    try:
        yield
    finally:
        marker.rmdir()


def identifier(value):
    if not re.fullmatch(r"[a-z0-9]+(?:-[a-z0-9]+)*", value):
        raise argparse.ArgumentTypeError("use lowercase letters, digits and internal hyphens")
    if re.fullmatch(r"(?:con|prn|aux|nul|com[1-9]|lpt[1-9])", value):
        raise argparse.ArgumentTypeError("this name is reserved on Windows")
    return value


def revision(value):
    if not re.fullmatch(r"v[0-9]{3,}", value):
        raise argparse.ArgumentTypeError("use a revision such as v001")
    return value


def init_image_service_config(root):
    path = root / IMAGE_SERVICE_CONFIG
    directory(path.parent)
    if not path.exists():
        template = Path(__file__).resolve().parents[1] / "assets" / "image-service.template.json"
        try:
            write_bytes(path, template.read_bytes())
        except FileExistsError:
            pass  # Another series may be initialized in the same artwork root.
    if path.is_symlink() or not path.is_file():
        raise ValueError(f"{path}: expected a regular config file")
    return path


def initialize(args):
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    series = directory(directory(root / "series") / args.series)
    characters = directory(series / "characters")
    ref = None
    if args.character:
        character = directory(directory(characters / args.character) / args.character_version)
        ref = (character / "reference.png").relative_to(series).as_posix()
    work = directory(directory(directory(series / "stickers") / args.sticker) / args.revision)
    with lock(work):
        for name in FOLDERS:
            directory(work / name)
        path = work / "plan.json"
        if path.is_symlink() or (path.exists() and not path.is_file()):
            raise ValueError(f"{path}: expected a regular file")
        if not path.exists():
            plan = {"version": 1, "mode": args.mode, "frames": []}
            if args.mode == "generated":
                plan.update(character_reference=ref, character_description="", action="")
            write_bytes(path, json_bytes(plan))
        plan = read_json(path)
        if not isinstance(plan, dict) or plan.get("mode") != args.mode:
            raise ValueError(f"{path}: existing plan has a different mode")
        if ref and args.mode == "generated" and plan.get("character_reference") != ref:
            raise ValueError(f"{path}: existing plan uses a different character reference")
    result = {"workspace": str(work), "plan": str(path)}
    if not args.no_image_service_config:
        result["image_service_config"] = str(init_image_service_config(root))
    return result


def open_workspace(path):
    work = path.resolve()
    if len(work.parents) < 5 or work.parent.parent.name != "stickers" or work.parents[3].name != "series":
        raise ValueError(f"{path}: expected a sticker revision under series/<series>/stickers/<sticker>")
    for name in FOLDERS:
        child = work / name
        if child.is_symlink() or not child.is_dir():
            raise ValueError(f"{child}: initialize the workspace first")
    plan = work / "plan.json"
    if plan.is_symlink() or not plan.is_file():
        raise ValueError(f"{plan}: expected a workspace plan")
    return work


def duration(value):
    if type(value) is not int or not 10 <= value <= 655350 or value % 10:
        raise ValueError("frame delays must be 10–655350 milliseconds in 10 ms steps")
    return value


def read_plan(work, mode=None):
    plan = read_json(work / "plan.json")
    if (not isinstance(plan, dict) or type(plan.get("version")) is not int or plan["version"] != 1
            or plan.get("mode") not in ("generated", "imported") or not isinstance(plan.get("frames"), list)):
        raise ValueError("plan.json: expected a version 1 generated or imported plan")
    if mode and plan["mode"] != mode:
        raise ValueError(f"this command requires a {mode} plan")
    return plan


def frame_entries(plan):
    frames = plan["frames"]
    if len(frames) < 2:
        raise ValueError("plan.json: expected at least two frame entries")
    for index, entry in enumerate(frames, 1):
        if not isinstance(entry, dict):
            raise ValueError(f"plan.json: invalid frame entry {index}")
        duration(entry.get("duration_ms"))
        if plan["mode"] == "generated" and (type(entry.get("keyframe")) is not bool
                or not isinstance(entry.get("prompt"), str) or not entry["prompt"].strip()):
            raise ValueError(f"plan.json: frame {index} needs a keyframe flag and a pose prompt")
    if plan["mode"] == "generated" and sum(entry["keyframe"] for entry in frames) < 2:
        raise ValueError("plan.json: mark at least two poses as keyframes")
    return frames


def frame_path(folder, index):
    return folder / f"{index:04}.png"


def character_reference(work, plan):
    value = plan.get("character_reference")
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("plan.json: character_reference must be a series-relative PNG path")
    parts = PurePosixPath(value).parts
    if len(parts) != 4 or parts[0] != "characters" or parts[3] != "reference.png":
        raise ValueError("plan.json: use characters/<character>/<version>/reference.png")
    identifier(parts[1])
    revision(parts[2])
    path = work.parents[2]
    for part in parts[:-1]:
        path /= part
        if path.is_symlink() or not path.is_dir():
            raise ValueError(f"{path}: initialize this character first")
    path /= parts[-1]
    if path.is_symlink():
        raise ValueError(f"{path}: expected a regular file")
    return path


def read_png(path):
    with path.open("rb") as source:
        data = source.read(MAX_IMAGE_BYTES + 1)
    if len(data) > MAX_IMAGE_BYTES:
        raise ValueError(f"{path}: PNG exceeds the input byte limit")
    return data


def decode_png(data):
    try:
        with Image.open(BytesIO(data), formats=("PNG",)) as png:
            if png.n_frames != 1:
                raise ValueError("expected a single-frame PNG")
            png.verify()
        with Image.open(BytesIO(data), formats=("PNG",)) as png:
            return png.convert("RGBA")
    except (OSError, SyntaxError, Image.DecompressionBombError) as exc:
        raise ValueError("could not decode a single-frame PNG") from exc


def normalize(data):
    rgba = decode_png(data)
    low, high = rgba.getchannel("A").getextrema()
    if not low <= ALPHA_THRESHOLD < high:
        raise ValueError("PNG needs both visible artwork and real transparency; supply a corrected PNG")
    if rgba.size == CANVAS:
        return data
    scale = min(CANVAS[0] / rgba.width, CANVAS[1] / rgba.height)
    rgba = rgba.resize((max(1, round(rgba.width * scale)), max(1, round(rgba.height * scale))),
                       Image.Resampling.LANCZOS)
    low, high = rgba.getchannel("A").getextrema()
    if high <= ALPHA_THRESHOLD or (rgba.size == CANVAS and low > ALPHA_THRESHOLD):
        raise ValueError("PNG loses its foreground or transparency when resized")
    canvas = Image.new("RGBA", CANVAS)
    canvas.paste(rgba, ((CANVAS[0] - rgba.width) // 2, (CANVAS[1] - rgba.height) // 2))
    out = BytesIO()
    canvas.save(out, format="PNG")
    return out.getvalue()


def review_reference(work, plan, expected_digest=None):
    reference = character_reference(work, plan)
    if reference is None:
        raise ValueError("plan.json: set a character_reference path first")
    with lock(reference.parent):
        data = read_png(reference)
        decode_png(data)
        current = {"digest": digest(data)}
        pending = reference.with_suffix(".review.json")
        if expected_digest is None:
            write_bytes(pending, json_bytes(current), replace=True)
            return {"reference": str(reference), **current}
        if not pending.is_file():
            raise ValueError("run review-reference and show the candidate before approving it")
        if expected_digest != current["digest"] or read_json(pending) != current:
            raise ValueError("character reference review is out of date; show a new review")
        approval = reference.with_suffix(".approval.json")
        if approval.exists():
            require_reference_approval(reference)
        else:
            record = {**current, "approved_at": datetime.now(timezone.utc).isoformat()}
            write_bytes(approval, json_bytes(record))
        return {"approved_digest": expected_digest, "approval": str(approval)}


def require_reference_approval(reference):
    if reference is None:
        return None
    approval = reference.with_suffix(".approval.json")
    if not approval.is_file():
        raise ValueError("character reference approval is required before making or reviewing keyframes")
    data = read_png(reference)
    record = read_json(approval)
    if not isinstance(record, dict) or record.get("digest") != digest(data):
        raise ValueError("approved character reference changed; select a new character version and review it")
    return data


def review_snapshot(work, plan):
    if not all(isinstance(plan.get(field), str) and plan[field].strip()
               for field in ("character_description", "action")):
        raise ValueError("plan.json: add a character description and action")
    ref = character_reference(work, plan)
    ref_hash = None
    if ref:
        data = read_png(ref)
        decode_png(data)
        ref_hash = digest(data)
    keys = []
    for index, entry in enumerate(frame_entries(plan), 1):
        if entry["keyframe"]:
            path = frame_path(work / "keyframes", index)
            load_png(path, index, ALPHA_THRESHOLD)
            keys.append({"frame": index, "sha256": digest(read_png(path))})
    return {"plan_sha256": digest(json_bytes(plan)), "reference_sha256": ref_hash, "keyframes": keys}


def review_keyframes(work, plan):
    if not (work / "keyframes" / "approval.json").is_file():
        require_reference_approval(character_reference(work, plan))
    snapshot = review_snapshot(work, plan)
    keys = snapshot["keyframes"]
    sheet = Image.new("RGB", (720, 146 * ((len(keys) + 2) // 3)), "#ffffff")
    draw = ImageDraw.Draw(sheet)
    for position, key in enumerate(keys):
        index = key["frame"]
        rgba, _ = load_png(frame_path(work / "keyframes", index), index, ALPHA_THRESHOLD)
        rgba.thumbnail((112, 112), Image.Resampling.LANCZOS)
        x, y = (position % 3) * 240, (position // 3) * 146
        draw.rectangle((x, y, x + 119, y + 119), fill="#f7f8fa")
        draw.rectangle((x + 120, y, x + 239, y + 119), fill="#20242c")
        for left in (x, x + 120):
            sheet.paste(rgba, (left + (120 - rgba.width) // 2, y + (120 - rgba.height) // 2), rgba)
        draw.text((x + 8, y + 123), f"{index:04} / {plan['frames'][index - 1]['duration_ms']} ms", fill="#171717")
    path = work / "keyframes" / "review.png"
    out = BytesIO()
    sheet.save(out, format="PNG")
    write_bytes(path, out.getvalue(), replace=True)
    pending = {"digest": digest(json_bytes(snapshot)), "snapshot": snapshot}
    write_bytes(work / "keyframes" / "review.json", json_bytes(pending), replace=True)
    return {"preview": str(path), "digest": pending["digest"], "keyframes": keys}


def approve_keyframes(work, plan, expected_digest):
    snapshot = review_snapshot(work, plan)
    pending = read_json(work / "keyframes" / "review.json")
    current = digest(json_bytes(snapshot))
    if expected_digest != current or pending != {"digest": current, "snapshot": snapshot}:
        raise ValueError("keyframe review is out of date; generate and show a new review")
    path = work / "keyframes" / "approval.json"
    if path.exists():
        require_approval(work, plan)
    else:
        require_reference_approval(character_reference(work, plan))
        data = {**pending, "approved_at": datetime.now(timezone.utc).isoformat()}
        write_bytes(path, json_bytes(data))
    return {"approved_digest": current, "approval": str(path)}


def require_approval(work, plan):
    path = work / "keyframes" / "approval.json"
    if not path.is_file():
        raise ValueError("keyframe approval is required before completing frames or building a GIF")
    approved = read_json(path)
    current = review_snapshot(work, plan)
    if (not isinstance(approved, dict) or approved.get("snapshot") != current
            or approved.get("digest") != digest(json_bytes(current))):
        raise ValueError("approved artwork or plan changed; use a new revision and review it")
    return current["keyframes"]


def prepare_frames(work, plan):
    keys = require_approval(work, plan)
    for key in keys:
        index = key["frame"]
        keep_bytes(frame_path(work / "frames", index), read_png(frame_path(work / "keyframes", index)))
    return {
        "keyframes": [key["frame"] for key in keys],
        "missing": [index for index, _ in enumerate(plan["frames"], 1)
                    if not frame_path(work / "frames", index).is_file()],
    }


def import_frames(work, plan, sources, delays):
    frames = [{"duration_ms": duration(value)} for value in delays]
    if len(sources) < 2 or len(sources) != len(frames):
        raise ValueError("supply at least two PNGs and one delay per PNG")
    if plan["frames"] and plan["frames"] != frames:
        raise ValueError("imported frame count or timing changed; use a new revision")
    with TemporaryDirectory(dir=work) as staging:
        originals = directory(Path(staging) / "source")
        normalized = directory(Path(staging) / "frames")
        for index, source in enumerate(sources, 1):
            try:
                data = read_png(source)
                frame_path(originals, index).write_bytes(data)
                frame_path(normalized, index).write_bytes(normalize(data))
            except (OSError, ValueError) as exc:
                raise ValueError(f"frame {index} ({source}): {exc}") from None
        for dest, prepared in ((work / "source", originals), (work / "frames", normalized)):
            for asset in sorted(prepared.iterdir()):
                keep_bytes(dest / asset.name, read_png(asset))
    if not plan["frames"]:
        plan["frames"] = frames
        write_bytes(work / "plan.json", json_bytes(plan), replace=True)
    return {"frame_count": len(frames), "durations_ms": delays}


def add_frame(work, plan, index, source):
    entries = frame_entries(plan)
    if not 1 <= index <= len(entries):
        raise ValueError(f"frame index must be between 1 and {len(entries)}")
    is_keyframe = entries[index - 1]["keyframe"]
    if is_keyframe and (work / "keyframes" / "approval.json").exists():
        raise ValueError("keyframes have been approved; use a new revision for changes")
    if is_keyframe:
        require_reference_approval(character_reference(work, plan))
    else:
        require_approval(work, plan)
    stage = "keyframes" if is_keyframe else "frames"
    raw_dir = directory(directory(work / "source" / "manual") / stage)
    original = read_png(source)
    artwork = normalize(original)
    raw = frame_path(raw_dir, index)
    target = frame_path(work / stage, index)
    keep_bytes(raw, original)
    keep_bytes(target, artwork)
    return {"frame": index, "source": str(raw), "png": str(target)}


def render_image(profile, prompt, references, raw, target, *, is_frame):
    receipt = raw.with_suffix(".request.json")
    inputs = {"profile": asdict(profile), "prompt": prompt, "references": [digest(image) for image in references]}
    legacy_identity = digest(json_bytes(inputs))
    if is_frame:
        prompt += TRANSPARENT_FRAME_PROMPT
    identity = digest(json_bytes({**inputs, "prompt": prompt}))
    record = {"request_sha256": identity}
    if receipt.exists():
        existing = read_json(receipt)
        if not isinstance(existing, dict) or existing.get("request_sha256") not in (identity, legacy_identity):
            raise ValueError("generation inputs changed; use a new revision or supply artwork manually")
    if target.is_file():
        if is_frame:
            load_png(target, target.stem, ALPHA_THRESHOLD)
        else:
            decode_png(read_png(target))
        return False
    if raw.is_file():
        if not receipt.is_file():
            raise ValueError(f"{raw}: expected a matching generation record")
        image = read_png(raw)
    else:
        if receipt.exists():
            raise ValueError(f"previous request may have been accepted; resolve it before retrying ({receipt})")
        request = make_request(profile, prompt, references)
        write_bytes(receipt, json_bytes(record))
        try:
            image, identifier = receive_image(request)
        except ImageRequestError as exc:
            if exc.rejected:
                receipt.unlink()
                raise
            if exc.request_id:
                write_bytes(receipt, json_bytes({**record, "request_id": exc.request_id}), replace=True)
            raise ValueError(f"{exc}; this request may have been accepted ({receipt})") from None
        if identifier:
            write_bytes(receipt, json_bytes({**record, "request_id": identifier}), replace=True)
        write_bytes(raw, image)
    if is_frame:
        try:
            image = normalize(image)
        except ValueError as exc:
            raise ValueError(f"{raw}: {exc}") from None
    else:
        decode_png(image)
    write_bytes(target, image)
    return True


def read_image_service_config(path):
    try:
        data = read_json(path)
    except (UnicodeError, json.JSONDecodeError):
        raise ValueError(f"{path}: invalid image service configuration JSON") from None
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected an image service configuration object")
    return data


def validated_profile(path, data):
    try:
        return parse_profile(data)
    except ValueError as exc:
        raise ValueError(f"{path}: {exc}") from None


def standalone_profile(path):
    data = read_image_service_config(path)
    if data.get("profilePath") is not None:
        raise ValueError(f"{path}: expected a standalone profile with its own service settings")
    return validated_profile(path, data)


def remember_profile(root, config, clear):
    root = root.resolve()
    if not root.is_dir():
        raise ValueError(f"{root}: initialize the artwork directory first")
    selected, stored = None, None
    if not clear:
        selected = (config if config is not None else root / CUSTOM_IMAGE_SERVICE_CONFIG).resolve()
        if selected == (root / IMAGE_SERVICE_CONFIG).resolve():
            raise ValueError("use --clear to select the artwork root's image-service.json directly")
        standalone_profile(selected)
        stored = selected.relative_to(root).as_posix() if selected.is_relative_to(root) else str(selected)
    path = init_image_service_config(root)
    with lock(path.parent):
        data = read_image_service_config(path)
        if data.get("profilePath") != stored:
            data["profilePath"] = stored
            write_bytes(path, json_bytes(data), replace=True)
    return {"image_service_config": str(path), "profile": str(selected if selected is not None else path)}


def generation_profile(work, config):
    if config is not None:
        return validated_profile(config, read_image_service_config(config))
    root = work.parents[4]
    path = root / IMAGE_SERVICE_CONFIG
    if path.parent.is_symlink() or path.is_symlink():
        raise ValueError(f"{path}: expected a local config file. Use --config to select another file.")
    if not path.is_file():
        raise ValueError(f"{path}: run init-workspace to create the template or pass --config.")
    data = read_image_service_config(path)
    saved = data.get("profilePath")
    if saved is None:
        return validated_profile(path, data)
    try:
        if not isinstance(saved, str) or not saved.strip() or not saved.isprintable():
            raise ValueError("profilePath must be a non-empty file path or null")
        target = root / saved
        if target.is_symlink():
            raise ValueError(f"{target}: expected a regular profile file")
        return standalone_profile(target)
    except (OSError, ValueError) as exc:
        raise ValueError(
            f"{path}: saved profilePath is unavailable ({exc}). Restore the saved profile, clear profilePath "
            "and fill this file, or use set-image-service-config to select a new profile."
        ) from None


def generate(work, plan, config, stage):
    profile = generation_profile(work, config)
    reference = character_reference(work, plan)
    description = plan.get("character_description")
    if not isinstance(description, str) or not description.strip():
        raise ValueError("plan.json: add a character description")
    if stage == "reference":
        if reference is None:
            raise ValueError("plan.json: set a character_reference path first")
        with lock(reference.parent):
            if reference.is_file():
                decode_png(read_png(reference))
                return {"reference": str(reference), "generated": False}
            prompt = f"{description}\nCreate one full-body character reference on a square canvas."
            created = render_image(profile, prompt, [], reference.with_name("source.png"), reference, is_frame=False)
        return {"reference": str(reference), "generated": created}

    action = plan.get("action")
    if not isinstance(action, str) or not action.strip():
        raise ValueError("plan.json: add an action")
    entries = frame_entries(plan)
    keys = [index for index, entry in enumerate(entries, 1) if entry["keyframe"]]
    if stage == "frames":
        prepare_frames(work, plan)
        approved_reference = read_png(reference) if reference else None
    elif (work / "keyframes" / "approval.json").exists():
        require_approval(work, plan)
        return {"stage": stage, "rendered_frames": []}
    else:
        approved_reference = require_reference_approval(reference)
    if reference and profile.reference_images == 0:
        raise ValueError("the configured model cannot accept the character reference")
    references = [approved_reference] if approved_reference is not None else []
    for image in references:
        decode_png(image)
    raw_dir = directory(work / "source" / stage)
    rendered = []
    for index, entry in enumerate(entries, 1):
        if entry["keyframe"] != (stage == "keyframes"):
            continue
        inputs = references.copy()
        if stage == "frames" and references and profile.reference_images > 1:
            before = max((key for key in keys if key < index), default=None)
            after = min((key for key in keys if key > index), default=None)
            for key in (before, after):
                if key is not None and len(inputs) < profile.reference_images:
                    inputs.append(read_png(frame_path(work / "keyframes", key)))
        prompt = (f"{description}\nAction: {action}\nPose: {entry['prompt']}\n"
                  "Draw one pose on a square canvas with room around the silhouette. "
                  "Keep the planned character design, scale, camera and motion anchor.")
        try:
            if render_image(profile, prompt, inputs, frame_path(raw_dir, index),
                            frame_path(work / stage, index), is_frame=True):
                rendered.append(index)
        except (OSError, ValueError) as exc:
            raise ValueError(f"{stage} frame {index}: {exc}") from None
    return {"stage": stage, "rendered_frames": rendered}


def build(work, plan):
    frames = frame_entries(plan)
    if plan["mode"] == "generated":
        prepare_frames(work, plan)
    manifest = work / "sticker.json"
    paths = [frame_path(work / "frames", index) for index in range(1, len(frames) + 1)]
    delays = [entry["duration_ms"] for entry in frames]
    if manifest.exists():
        if read_manifest(manifest) != (paths, delays, ALPHA_THRESHOLD):
            raise ValueError(f"{manifest}: does not match the plan; use a new revision")
    else:
        import_pngs(paths, manifest, delays, ALPHA_THRESHOLD)
    output = work / "output" / f"{work.parent.name}.gif"
    review = work / "review"
    with TemporaryDirectory(dir=work) as directory_name:
        staging = Path(directory_name)
        candidate = staging / output.name
        composed = compose(manifest, candidate, False)
        if not composed["strict_pass"]:
            raise ValueError("GIF composition failed: " + "; ".join(composed["errors"]))
        checked, decoded = inspect_gif(candidate, delays)
        if not checked["strict_pass"]:
            raise ValueError("GIF validation failed: " + "; ".join(checked["errors"]))
        image = candidate.read_bytes()
        if output.is_symlink() or (output.exists() and output.read_bytes() != image):
            raise ValueError(f"{output}: existing content differs; use a new revision")
        files = write_preview(staging / "preview.gif", candidate, decoded, checked["durations_ms"])
        for name, source in files.items():
            path = review / Path(source).name
            write_bytes(path, Path(source).read_bytes(), replace=True)
            files[name] = str(path)
        write_bytes(review / "compose.json", json_bytes({**composed, "path": str(output)}), replace=True)
        write_bytes(review / "validation.json", json_bytes({**checked, "path": str(output), "preview": files}), replace=True)
        keep_bytes(output, image)
    return {"gif": str(output), "manifest": str(manifest), "validation": str(review / "validation.json"),
            "preview": files, "frame_count": checked["frame_count"]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    init = commands.add_parser("init-workspace", help="create a series and sticker revision")
    init.add_argument("root", type=Path)
    init.add_argument("--series", required=True, type=identifier)
    init.add_argument("--sticker", required=True, type=identifier)
    init.add_argument("--revision", type=revision, default="v001")
    init.add_argument("--mode", choices=("generated", "imported"), default="generated")
    init.add_argument("--character", type=identifier)
    init.add_argument("--character-version", type=revision, default="v001")
    init.add_argument("--no-image-service-config", action="store_true", help="skip the artwork root's config template")
    remember = commands.add_parser("set-image-service-config", help="remember a custom profile for this artwork root")
    remember.add_argument("root", type=Path)
    selection = remember.add_mutually_exclusive_group()
    selection.add_argument("--config", type=Path, help=f"select a profile (default: {CUSTOM_IMAGE_SERVICE_CONFIG.as_posix()})")
    selection.add_argument("--clear", action="store_true", help="use the artwork root's service settings directly")
    importer = commands.add_parser("import-frames", help="copy a complete ordered frame set into an imported revision")
    add = commands.add_parser("add-frame", help="prepare one manually supplied pose in a generated revision")
    generator = commands.add_parser("generate", help="generate missing images with a configured provider")
    approval = commands.add_parser("approve-keyframes", help="record explicit approval of a review digest")
    reference_approval = commands.add_parser("approve-reference", help="record explicit approval of the character image")
    for subparser in (importer, add, generator, approval, reference_approval, commands.add_parser("review-reference"),
                      commands.add_parser("review-keyframes"),
                      commands.add_parser("prepare-frames"), commands.add_parser("build")):
        subparser.add_argument("workspace", type=Path)
    importer.add_argument("pngs", type=Path, nargs="+")
    timing = importer.add_mutually_exclusive_group()
    timing.add_argument("--duration-ms", type=int, default=DEFAULT_DELAY)
    timing.add_argument("--durations-ms", type=lambda value: [int(part) for part in value.split(",")])
    add.add_argument("index", type=int)
    add.add_argument("png", type=Path)
    generator.add_argument("--stage", required=True, choices=("reference", "keyframes", "frames"))
    generator.add_argument("--config", type=Path, help=f"override the artwork root's {IMAGE_SERVICE_CONFIG.as_posix()}")
    approval.add_argument("--digest", required=True)
    reference_approval.add_argument("--digest", required=True)
    args = parser.parse_args()
    try:
        if args.command == "init-workspace":
            result = initialize(args)
        elif args.command == "set-image-service-config":
            result = remember_profile(args.root, args.config, args.clear)
        else:
            work = open_workspace(args.workspace)
            with lock(work):
                mode = {"import-frames": "imported", "build": None}.get(args.command, "generated")
                plan = read_plan(work, mode)
                if args.command == "import-frames":
                    delays = args.durations_ms or [args.duration_ms] * len(args.pngs)
                    result = import_frames(work, plan, args.pngs, delays)
                elif args.command == "add-frame":
                    result = add_frame(work, plan, args.index, args.png)
                elif args.command == "generate":
                    result = generate(work, plan, args.config, args.stage)
                elif args.command == "review-reference":
                    result = review_reference(work, plan)
                elif args.command == "approve-reference":
                    result = review_reference(work, plan, args.digest)
                elif args.command == "review-keyframes":
                    result = review_keyframes(work, plan)
                elif args.command == "approve-keyframes":
                    result = approve_keyframes(work, plan, args.digest)
                elif args.command == "prepare-frames":
                    result = prepare_frames(work, plan)
                else:
                    result = build(work, plan)
        print(json_bytes(result).decode(), end="")
        return 0
    except (OSError, ValueError, argparse.ArgumentTypeError) as exc:
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
