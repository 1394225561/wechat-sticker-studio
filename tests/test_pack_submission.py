import hashlib
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from zipfile import ZipFile

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts/pack_submission.py"


class PackSubmissionTest(unittest.TestCase):
    def setUp(self):
        runtime = ROOT / ".runtime"
        runtime.mkdir(exist_ok=True)
        temporary = tempfile.TemporaryDirectory(dir=runtime, prefix="投稿 测试 ")
        self.addCleanup(temporary.cleanup)
        self.folder = Path(temporary.name)
        self.manifest = self.folder / "投稿 清单.json"
        self.output = self.folder / "验收 包.zip"

    def refer(self, path):
        return {"path": path.name, "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}

    def sticker(self, index, frames_count=12):
        frames = []
        for offset in range(frames_count):
            frame = Image.new("P", (240, 240))
            frame.putpalette([0, 0, 0, 229, 151, 85] + [0] * (768 - 6))
            left = 30 + offset * 4 + index
            ImageDraw.Draw(frame).rectangle((left, 70, left + 22, 105), fill=1)
            frames.append(frame)
        path = self.folder / f"表情 {index}.gif"
        frames[0].save(path, save_all=True, append_images=frames[1:],
                       duration=80, loop=0, transparency=0, background=0, disposal=2, optimize=False)
        return {**self.refer(path), "meaning": f"动作{index}"}

    def artwork(self, name, size, *, transparent=False):
        path = self.folder / name
        if transparent:
            image = Image.new("RGBA", size)
            ImageDraw.Draw(image).rectangle((1, 1, 15, 15), fill="yellow")
        else:
            image = Image.new("RGB", size, "green")
        image.save(path)
        return self.refer(path)

    def album(self):
        return {
            "version": 1, "type": "album", "name": "测试专辑", "description": "动作预览。",
            "copyright": "测试作者", "stickers": [self.sticker(i) for i in range(8, 0, -1)],
            "assets": {
                "banner": self.artwork("横幅.jpg", (750, 400)),
                "cover": self.artwork("封面.png", (240, 240), transparent=True),
                "icon": self.artwork("图标.png", (50, 50), transparent=True),
            },
            "appreciation": {
                "enabled": True, "message": "谢谢你来看表情",
                "guide": self.artwork("引导.png", (750, 560)),
                "thanks": self.artwork("答谢.png", (750, 750)),
            },
        }

    def cli(self, manifest, output=None, expected=0):
        self.manifest.write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
        args = [sys.executable, "-B", str(SCRIPT), self.manifest.name]
        if output is not None:
            args.extend(("--output", output.name))
        result = subprocess.run(args, cwd=self.folder, text=True, capture_output=True)
        self.assertEqual(result.returncode, expected, result.stdout + result.stderr)
        return json.loads(result.stdout)

    def test_single_zip_repeats_byte_for_byte_and_preserves_existing_output(self):
        sticker = self.sticker(1)
        data = {"version": 1, "type": "single", "tags": ["问候"], "stickers": [sticker]}
        first = self.cli(data, self.output)
        self.assertTrue(first["preflight_pass"])
        self.assertFalse(first["live_upload_form_verified"])
        with ZipFile(self.output) as archive:
            self.assertEqual(archive.namelist(), ["表情图/01.gif", "submission.json", "填写说明.md"])
            manifest = json.loads(archive.read("submission.json"))
            self.assertEqual(manifest["tags"], ["问候"])
            self.assertEqual(archive.read("表情图/01.gif"), (self.folder / sticker["path"]).read_bytes())
        second_output = self.folder / "重跑.zip"
        second = self.cli(data, second_output)
        self.assertEqual(first["zip"]["sha256"], second["zip"]["sha256"])
        before = self.output.read_bytes()
        conflict = self.cli(data, self.output, expected=1)
        self.assertIn("already exists", conflict["errors"][0]["message"])
        self.assertEqual(self.output.read_bytes(), before)

    def test_album_keeps_manifest_order_hashes_and_reward_assets(self):
        album = self.album()
        preflight = self.cli(album)
        self.assertIsNone(preflight["zip"])
        self.assertFalse(self.output.exists())
        report = self.cli(album, self.output)
        self.assertEqual(list(report["artwork"]),
                         ["assets.banner", "assets.cover", "assets.icon", "appreciation.guide", "appreciation.thanks"])
        with ZipFile(self.output) as archive:
            manifest = json.loads(archive.read("submission.json"))
            self.assertEqual([row["meaning"] for row in manifest["stickers"]],
                             [row["meaning"] for row in album["stickers"]])
            for index, row in enumerate(album["stickers"], 1):
                self.assertEqual(hashlib.sha256(archive.read(f"表情图/{index:02}.gif")).hexdigest(), row["sha256"])
            self.assertIn("配图/05-赞赏致谢图.png", archive.namelist())
            self.assertIn("谢谢你来看表情", archive.read("填写说明.md").decode("utf-8"))

    def test_missing_wrong_version_and_wrong_dimensions_block_zip(self):
        data = self.album()
        data["stickers"][1]["path"] = data["stickers"][0]["path"]
        (self.folder / data["assets"]["cover"]["path"]).unlink()
        data["assets"]["icon"] = self.artwork("尺寸错.png", (51, 50), transparent=True)
        result = self.cli(data, self.output, expected=1)
        issues = {issue["item"]: issue for issue in result["errors"]}
        self.assertIn("sha256 mismatch", issues["stickers[2]"]["message"])
        self.assertEqual(issues["assets.cover"]["path"], "封面.png")
        self.assertIn("51×50", issues["assets.icon"]["message"])
        self.assertFalse(self.output.exists())

    def test_album_text_and_missing_appreciation_are_located(self):
        data = self.album()
        data["name"] = "带标点！"
        data["stickers"][0]["meaning"] = "超过四个字"
        data["appreciation"]["message"] = "谢谢"
        del data["appreciation"]["guide"]
        result = self.cli(data, self.output, expected=1)
        self.assertEqual({issue["item"] for issue in result["errors"]},
                         {"name", "stickers[1].meaning", "appreciation.message", "appreciation.guide"})
        self.assertFalse(self.output.exists())

    def test_single_requires_tags_and_project_frame_count(self):
        data = {"version": 1, "type": "single", "stickers": [self.sticker(1, frames_count=6)]}
        result = self.cli(data, self.output, expected=1)
        self.assertTrue(any(issue["item"] == "tags" for issue in result["errors"]))
        self.assertIn("expected 12 frames, decoded 6", [issue["message"] for issue in result["errors"]])
        self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
