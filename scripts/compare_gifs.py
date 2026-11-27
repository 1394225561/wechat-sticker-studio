"""Compare the decoded timing, transparency masks and visible RGB of two GIFs."""

import argparse
import json
from pathlib import Path

from PIL import ImageChops

from sticker_gif import inspect_gif


def compare(local, reference):
    left, local_frames = inspect_gif(local)
    right, reference_frames = inspect_gif(reference)
    same_canvas = (left["width"], left["height"]) == (right["width"], right["height"])
    same_count = left["frame_count"] == right["frame_count"]
    frames = []
    if same_canvas and same_count:
        for index, (a, b) in enumerate(zip(local_frames, reference_frames), 1):
            local_alpha, reference_alpha = a.getchannel("A"), b.getchannel("A")
            alpha_delta = ImageChops.difference(local_alpha, reference_alpha)
            shared_opaque = ImageChops.multiply(local_alpha, reference_alpha)
            delta = ImageChops.difference(a.convert("RGB"), b.convert("RGB"))
            red, green, blue = delta.split()
            max_rgb_delta = ImageChops.lighter(ImageChops.lighter(red, green), blue)
            visible_delta = ImageChops.multiply(max_rgb_delta, shared_opaque)
            histogram = visible_delta.histogram()
            frames.append({
                "frame": index,
                "different_alpha_pixels": sum(alpha_delta.histogram()[1:]),
                "different_rgb_pixels_opaque_in_both": sum(histogram[1:]),
                "max_rgb_channel_delta_opaque_in_both": visible_delta.getextrema()[1],
            })
    return {
        "local": {"path": left["path"], "sha256": left["sha256"], "size_bytes": left["size_bytes"]},
        "reference": {"path": right["path"], "sha256": right["sha256"], "size_bytes": right["size_bytes"]},
        "same_bytes": left["sha256"] == right["sha256"],
        "same_canvas": same_canvas,
        "same_frame_count": same_count,
        "same_loop": left["loop_count"] == right["loop_count"],
        "same_durations": left["durations_ms"] == right["durations_ms"],
        "different_alpha_pixels_total": sum(row["different_alpha_pixels"] for row in frames) if frames else None,
        "different_rgb_pixels_opaque_in_both_total": sum(
            row["different_rgb_pixels_opaque_in_both"] for row in frames
        ) if frames else None,
        "frames": frames,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("local", type=Path)
    parser.add_argument("reference", type=Path)
    args = parser.parse_args()
    print(json.dumps(compare(args.local, args.reference), ensure_ascii=False, indent=2))
