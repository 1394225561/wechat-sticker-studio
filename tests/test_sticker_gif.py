import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/sticker_gif.py"
DEMO = ROOT / "examples/wave/sticker.json"


class StickerGifTest(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / ".runtime"
        runtime.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=runtime, prefix="路径 空格 ")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.manifest = self.folder / "动作 清单.json"
        self.output = self.folder / "最终 成品.gif"
        self.frames = json.loads(DEMO.read_text(encoding="utf-8"))
        for frame in self.frames["frames"]:
            frame["path"] = os.path.relpath(DEMO.parent / frame["path"], self.folder)
        self.write_manifest()

    def write_manifest(self):
        self.manifest.write_text(json.dumps(self.frames), encoding="utf-8")

    def cli(self, *args, expected=0):
        result = subprocess.run(
            [sys.executable, "-B", str(SCRIPT), *map(str, args)], cwd=self.folder,
            text=True, capture_output=True,
        )
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return result

    def compose(self, *args, expected=0):
        return self.cli("compose", self.manifest.name, self.output.name, *args, expected=expected)

    def validate(self, *args, expected=0):
        return json.loads(self.cli("validate", self.output.name, *args, expected=expected).stdout)

    def test_compose_rerun_preview(self):
        first = json.loads(self.compose().stdout)
        first_data = self.output.read_bytes()
        self.assertTrue(first["checks"]["matches_thresholded_png_masks"])
        self.assertEqual(first["durations_ms"], [80] * 4 + [240] + [80] * 7)
        second = json.loads(self.compose("--replace").stdout)
        self.assertEqual(first["sha256"], second["sha256"])
        self.assertEqual(self.output.read_bytes(), first_data)
        report = self.validate("--manifest", self.manifest.name, "--preview", "双底 预览.gif")
        with Image.open(self.folder / report["preview"]["animation"]) as preview:
            self.assertEqual((preview.size, preview.n_frames, preview.info["loop"]), ((240, 120), 12, 0))
        self.assertTrue((self.folder / report["preview"]["contact_sheet"]).is_file())

    def test_constant_delays(self):
        for frame in self.frames["frames"]:
            frame["duration_ms"] = 80
        self.write_manifest()
        self.assertEqual(json.loads(self.compose().stdout)["durations_ms"], [80] * 12)

    def test_import_keeps_input_order_and_ms_in_a_separate_directory(self):
        output = self.folder / "导入 清单/sticker.json"
        paths = [self.folder / frame["path"] for frame in reversed(self.frames["frames"])]
        delays = [80] * 4 + [240] + [80] * 7
        self.cli("import-png", output, *paths, "--durations-ms", ",".join(map(str, delays)))
        before = output.read_bytes()
        loaded = json.loads(before)
        self.assertEqual([entry["duration_ms"] for entry in loaded["frames"]], delays)
        self.assertEqual(
            [(output.parent / entry["path"]).resolve() for entry in loaded["frames"]],
            [path.resolve() for path in paths],
        )
        self.assertEqual(
            json.loads(self.cli("compose", output, self.output).stdout)["durations_ms"], delays
        )
        self.assertIn("already exists", self.cli("import-png", output, *paths, expected=1).stderr)
        self.assertEqual(output.read_bytes(), before)

    def test_import_failure_leaves_no_manifest(self):
        output = self.folder / "新作品" / "sticker.json"
        paths = [self.folder / frame["path"] for frame in self.frames["frames"]]
        before = paths[0].read_bytes()
        invalid = self.folder / "错误 尺寸.png"
        Image.new("RGBA", (32, 32)).save(invalid)
        paths[2] = invalid
        result = self.cli("import-png", output, *paths, expected=1)
        self.assertIn("frame 3", result.stderr)
        self.assertIn("got (32, 32)", result.stderr)
        self.assertFalse(output.exists())
        self.assertEqual(paths[0].read_bytes(), before)

    def test_import_rejects_unmatched_input_counts_and_delays(self):
        output = self.folder / "新作品" / "sticker.json"
        paths = [self.folder / frame["path"] for frame in self.frames["frames"]]
        result = self.cli("import-png", output, *paths[:-1], "--frame-count", 12, expected=1)
        self.assertIn("expected 12 PNGs, got 11", result.stderr)
        result = self.cli("import-png", output, *paths, "--durations-ms", "80,240", expected=1)
        self.assertIn("12 frame delays", result.stderr)
        result = self.cli("import-png", output, paths[0], expected=1)
        self.assertIn("at least 2 PNGs", result.stderr)
        self.assertFalse(output.exists())

    def test_compose_and_validate_24_frames(self):
        paths = []
        for index in range(24):
            path = self.folder / f"{index + 1:02}.png"
            frame = Image.new("RGBA", (240, 240))
            left = 20 + index * 5
            ImageDraw.Draw(frame).rectangle((left, 90, left + 20, 110), fill="yellow")
            frame.save(path)
            paths.append(path)
        manifest = self.folder / "二十四帧.json"
        imported = json.loads(self.cli("import-png", manifest, *paths, "--duration-ms", 40).stdout)
        self.assertEqual(imported["frame_count"], 24)
        self.assertEqual(imported["durations_ms"], [40] * 24)
        composed = json.loads(self.cli("compose", manifest, self.output).stdout)
        self.assertTrue(composed["checks"]["matches_expected_frame_count"])
        self.assertTrue(composed["checks"]["matches_thresholded_png_masks"])

        report = self.validate("--manifest", manifest, "--preview", "二十四帧预览.gif")
        self.assertEqual((report["frame_count"], report["expected_frame_count"]), (24, 24))
        self.assertTrue(report["checks"]["matches_manifest_durations"])
        with Image.open(self.folder / report["preview"]["animation"]) as preview:
            self.assertEqual((preview.n_frames, preview.info["loop"]), (24, 0))
        self.assertIsNone(self.validate()["checks"]["matches_expected_frame_count"])
        self.assertTrue(self.validate("--frame-count", 24)["checks"]["matches_expected_frame_count"])
        rejected = self.validate("--frame-count", 12, expected=1)
        self.assertEqual(rejected["errors"], ["expected 12 frames, decoded 24"])

    def test_conflict_and_failed_replacement_keep_previous_output(self):
        self.compose()
        original = self.output.read_bytes()
        conflict = self.compose(expected=1)
        self.assertIn("already exists", conflict.stderr)
        source = self.folder / self.frames["frames"][4]["path"]
        before = source.read_bytes()
        self.frames["frames"][5]["path"] = self.frames["frames"][4]["path"]
        self.write_manifest()
        failed = json.loads(self.compose("--replace", expected=1).stdout)
        self.assertEqual(failed["frame_count"], 11)
        self.assertIn("expected 12 frames, decoded 11", failed["errors"])
        self.assertFalse(failed["published"])
        self.assertEqual(self.output.read_bytes(), original)
        self.assertEqual(source.read_bytes(), before)

    def test_bad_missing_and_wrong_size_png(self):
        bad = self.folder / "坏图.png"
        self.frames["frames"][2]["path"] = bad.name
        self.write_manifest()
        result = self.compose(expected=1)
        self.assertIn("frame 3 (坏图.png)", result.stderr)
        self.assertIn("No such file", result.stderr)
        bad.write_bytes(b"not a PNG")
        result = self.compose(expected=1)
        self.assertIn("frame 3 (坏图.png)", result.stderr)
        self.assertIn("cannot identify image", result.stderr)
        Image.new("RGBA", (32, 32)).save(bad)
        self.assertIn("got (32, 32)", self.compose(expected=1).stderr)
        self.assertFalse(self.output.exists())

    def test_opaque_gif_without_loop_is_reported(self):
        Image.new("RGB", (240, 240), "red").save(self.output, duration=80)
        report = self.validate(expected=1)
        self.assertIsNone(report["loop_count"])
        self.assertIn("expected loop=0; got None", report["errors"])
        self.assertIn("no transparent pixels in frame(s) [1]", report["errors"])

    def test_missing_subject_and_wrong_canvas_are_reported(self):
        Image.new("RGBA", (32, 32)).save(self.output, duration=80, loop=0)
        report = self.validate(expected=1)
        self.assertIn("no opaque pixels in frame(s) [1]", report["errors"])
        self.assertIn("expected 240×240, decoded 32×32", report["errors"])

    def test_oversize_gif_is_reported(self):
        Image.new("RGBA", (240, 240)).save(self.output, duration=80, loop=0, comment=b"x" * 500_000)
        report = self.validate(expected=1)
        self.assertFalse(report["checks"]["size_at_most_500000_bytes"])
        self.assertGreater(report["size_bytes"], 500_000)

    def test_bad_delay_and_bad_gif_are_reported(self):
        self.frames["frames"][7]["duration_ms"] = 81
        self.write_manifest()
        self.assertIn("frame 8: duration_ms", self.compose(expected=1).stderr)
        self.output.write_bytes(b"bad GIF")
        result = self.cli("validate", self.output.name, expected=1)
        self.assertIn("cannot decode GIF", result.stderr)


if __name__ == "__main__":
    unittest.main()
