import base64
import io
import json
import os
import socket
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from email.message import Message
from pathlib import Path
from unittest.mock import Mock, patch
from urllib.error import HTTPError

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "skills/wechat-sticker-studio/scripts"
EXAMPLE = ROOT / "examples/wave/frames"
with patch.object(sys, "path", [str(SCRIPTS), *sys.path]):
    import openai_images
    import sticker_workflow


def image_reply(path):
    response = io.BytesIO(json.dumps({
        "data": [{"b64_json": base64.b64encode(path.read_bytes()).decode()}],
    }).encode())
    response.headers = {"x-request-id": "req_mock"}
    return response


def url_reply(url):
    response = io.BytesIO(json.dumps({"data": [{"url": url}]}).encode())
    response.headers = {"x-request-id": "req_url"}
    return response


def http_error(code):
    headers = Message()
    headers["x-request-id"] = "req_failed"
    return HTTPError("https://image.example.test/", code, "ignored", headers, io.BytesIO(b"private response"))


class WorkflowTest(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="作品 流程 ")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.artwork = self.root / "作品 项目"
        self.config = self.root / "image-service.json"
        self.set_profile()
        environment = patch.dict(os.environ, {"TEST_STICKER_KEY": "mock-secret-key"})
        environment.start()
        self.addCleanup(environment.stop)
        opener = patch.object(openai_images, "build_opener")
        self.request = opener.start().return_value.open
        self.addCleanup(opener.stop)
        self.request.side_effect = AssertionError("unexpected image request")

    def set_profile(self, reference_count=3):
        self.config.write_text(json.dumps({
            "adapter": "openai-images",
            "baseUrl": "https://image.example.test/v1/",
            "model": "mock-model",
            "apiKeyEnv": "TEST_STICKER_KEY",
            "referenceImages": reference_count,
            "transparentBackground": True,
        }), encoding="utf-8")

    def cli(self, *args, failure=None):
        output, errors = io.StringIO(), io.StringIO()
        with patch.object(sys, "argv", ["sticker_workflow.py", *map(str, args)]):
            with redirect_stdout(output), redirect_stderr(errors):
                code = sticker_workflow.main()
        if failure:
            self.assertEqual(code, 1, errors.getvalue())
            self.assertIn(failure, errors.getvalue())
            self.assertNotIn("mock-secret-key", errors.getvalue())
            self.assertNotIn("private response", errors.getvalue())
            return
        self.assertEqual(code, 0, errors.getvalue())
        return json.loads(output.getvalue())

    def init(self, *, series="robots", mode="generated", reference=False):
        args = ["--character", "helper"] if reference else []
        result = self.cli("init-workspace", self.artwork, "--series", series, "--sticker", "wave",
                          "--mode", mode, *args)
        return Path(result["workspace"])

    def write_plan(self, work, **changes):
        path = work / "plan.json"
        plan = json.loads(path.read_text())
        plan.update(changes)
        path.write_text(json.dumps(plan), encoding="utf-8")
        return plan

    def set_motion(self, work):
        self.write_plan(work, character_description="A blue robot", action="Wave",
                        frames=[{"keyframe": True, "prompt": "start", "duration_ms": 80},
                                {"keyframe": False, "prompt": "middle", "duration_ms": 90},
                                {"keyframe": True, "prompt": "end", "duration_ms": 120}])

    def test_workspace_config_template_is_shared_and_preserves_edits(self):
        args = ("init-workspace", self.artwork, "--series", "robots", "--sticker", "wave")
        path = Path(self.cli(*args)["image_service_config"])
        self.assertEqual(path, self.artwork / ".config/image-service.json")
        starter = json.loads(path.read_text())
        self.assertEqual(starter["adapter"], "openai-images")
        self.assertEqual(set(starter["_help"]), set(starter) - {"_help"})
        for field in set(starter) - {"_help", "adapter"}:
            self.assertIsNone(starter[field])
        original = self.config.read_bytes()
        path.write_bytes(original)
        self.assertEqual(self.cli(*args)["image_service_config"], str(path))
        sibling = self.cli("init-workspace", self.artwork, "--series", "other", "--sticker", "wave",
                           "--mode", "imported")
        self.assertEqual(sibling["image_service_config"], str(path))
        self.assertEqual(path.read_bytes(), original)
        self.request.assert_not_called()

    def test_generate_reads_workspace_config_and_rejects_incomplete_values(self):
        work = self.init()
        self.set_motion(work)
        path = self.artwork / ".config/image-service.json"
        self.cli("generate", work, "--stage", "keyframes",
                 failure=f"{path}: fill in the image service configuration fields: baseUrl, model, apiKeyEnv,"
                         " referenceImages, transparentBackground")
        profile = json.loads(self.config.read_text())
        profile.update(referenceImages=0, transparentBackground="false")
        path.write_text(json.dumps(profile))
        self.cli("generate", work, "--stage", "keyframes",
                 failure=f"{path}: transparentBackground must be true or false")
        self.request.assert_not_called()
        self.assertEqual(list((work / "source").iterdir()), [])

        profile["transparentBackground"] = False
        path.write_text(json.dumps(profile))
        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (1, 3)]
        self.assertEqual(self.cli("generate", work, "--stage", "keyframes")["rendered_frames"], [1, 3])
        request = self.request.call_args.args[0]
        self.assertEqual(request.full_url, "https://image.example.test/v1/images/generations")
        self.assertNotIn("background", json.loads(request.data))

    def test_opt_out_preserves_explicit_config_and_rejects_implicit_symlink(self):
        init = self.cli("init-workspace", self.artwork, "--series", "robots", "--sticker", "wave",
                        "--no-image-service-config")
        work = Path(init["workspace"])
        self.set_motion(work)
        path = self.artwork / ".config/image-service.json"
        self.assertNotIn("image_service_config", init)
        self.assertFalse(path.parent.exists())
        self.cli("generate", work, "--stage", "keyframes",
                 failure=f"{path}: run init-workspace to create the template or pass --config")
        path.parent.mkdir()
        path.symlink_to(self.config)
        self.cli("generate", work, "--stage", "keyframes",
                 failure=f"{path}: expected a local config file")
        self.request.assert_not_called()
        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (1, 3)]
        result = self.cli("generate", work, "--stage", "keyframes", "--config", self.config)
        self.assertEqual(result["rendered_frames"], [1, 3])

    def test_remembers_default_custom_profile_across_revisions_and_directory_moves(self):
        self.init()
        path = self.artwork / ".config/image-service.json"
        custom = path.with_name("image-service.custom.json")
        custom.write_bytes(self.config.read_bytes())
        self.assertEqual(self.cli("set-image-service-config", self.artwork)["profile"], str(custom))
        self.assertEqual(json.loads(path.read_text())["profilePath"], ".config/image-service.custom.json")

        work = self.init(series="another")
        self.set_motion(work)
        relative_work = work.relative_to(self.artwork)
        moved = self.artwork.rename(self.root / "移动后 作品")
        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (1, 3)]
        result = self.cli("generate", moved / relative_work, "--stage", "keyframes")
        self.assertEqual(result["rendered_frames"], [1, 3])
        self.assertEqual(self.request.call_args.args[0].full_url, "https://image.example.test/v1/images/generations")

    def test_replaces_last_selection_recovers_unavailable_profile_and_clears_selection(self):
        work = self.init()
        self.set_motion(work)
        path = self.artwork / ".config/image-service.json"
        inline = json.loads(path.read_text())
        inline.update(json.loads(self.config.read_text()), baseUrl="https://inline.image.example.test/v1")
        path.write_text(json.dumps(inline))
        self.cli("set-image-service-config", self.artwork, "--config", self.config)
        recent = self.root / "recent provider.json"
        recent.write_bytes(self.config.read_bytes())
        self.cli("set-image-service-config", self.artwork, "--config", recent)
        self.cli("set-image-service-config", self.artwork, "--config", self.root / "missing.json",
                 failure="missing.json")
        config = json.loads(path.read_text())
        self.assertEqual(config["profilePath"], str(recent))
        self.assertEqual(config["baseUrl"], inline["baseUrl"])

        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (1, 3, 1, 3)]
        first = self.cli("generate", work, "--stage", "keyframes")
        self.assertEqual(first["rendered_frames"], [1, 3])
        self.assertEqual(self.request.call_args.args[0].full_url, "https://image.example.test/v1/images/generations")
        recent.rename(self.root / "moved profile.json")
        other = self.init(series="another")
        self.set_motion(other)
        self.cli("generate", other, "--stage", "keyframes", failure="saved profilePath is unavailable")
        recent.write_text("{", encoding="utf-8")
        self.cli("generate", other, "--stage", "keyframes", failure=f"{recent}: invalid image service configuration JSON")
        self.assertEqual(self.request.call_count, 2)
        self.cli("generate", other, "--stage", "keyframes", "--config", path)
        self.assertEqual(self.request.call_args.args[0].full_url, "https://inline.image.example.test/v1/images/generations")
        self.assertEqual(json.loads(path.read_text())["profilePath"], str(recent))
        self.cli("set-image-service-config", self.artwork, "--clear")
        self.assertIsNone(json.loads(path.read_text())["profilePath"])
        self.assertEqual(self.cli("generate", other, "--stage", "keyframes")["rendered_frames"], [])

    def test_reuses_exported_key_and_honors_temporary_environment_override(self):
        work, other = self.init(), self.init(series="another")
        self.set_motion(work)
        self.set_motion(other)
        self.cli("set-image-service-config", self.artwork, "--config", self.config)
        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (1, 3, 1, 3)]
        with patch.dict(os.environ, {"TEST_STICKER_KEY": "startup-key"}):
            self.cli("generate", work, "--stage", "keyframes")
            with patch.dict(os.environ, {"TEST_STICKER_KEY": "temporary-key"}):
                self.cli("generate", other, "--stage", "keyframes")
        authorization = [call.args[0].get_header("Authorization") for call in self.request.call_args_list]
        self.assertEqual(authorization, ["Bearer startup-key"] * 2 + ["Bearer temporary-key"] * 2)
        self.assertNotIn("temporary-key", (self.artwork / ".config/image-service.json").read_text())

    def test_import_is_offline_idempotent_and_portable(self):
        work = self.init(mode="imported")
        other = self.init(series="other", mode="imported")
        self.assertNotEqual(work, other)
        self.assertEqual(self.init(mode="imported"), work)
        self.cli("init-workspace", self.artwork, "--series", "robots", "--sticker", "wave",
                 failure="different mode")
        opaque = self.root / "opaque.png"
        Image.new("RGB", (240, 240), "white").save(opaque)
        self.cli("import-frames", work, EXAMPLE / "04.png", opaque, failure="real transparency")
        self.assertEqual(list((work / "source").iterdir()), [])
        larger = self.root / "large.png"
        with Image.open(EXAMPLE / "04.png") as image:
            image.resize((480, 480)).save(larger)
        for _ in range(2):
            self.cli("import-frames", work, larger, EXAMPLE / "03.png", "--durations-ms", "130,70")
        self.assertEqual((work / "source/0001.png").read_bytes(), larger.read_bytes())
        self.assertEqual((work / "frames/0002.png").read_bytes(), (EXAMPLE / "03.png").read_bytes())
        with Image.open(work / "frames/0001.png") as normalized:
            self.assertEqual(normalized.size, (240, 240))
        first = self.cli("build", work)
        before = Path(first["gif"]).read_bytes()
        old_root = self.artwork
        new_root = old_root.rename(self.root / "移到 这里")
        second = self.cli("build", new_root / work.relative_to(old_root))
        self.assertEqual(Path(second["gif"]).read_bytes(), before)
        self.assertEqual(json.loads(Path(second["validation"]).read_text())["durations_ms"], [130, 70])
        self.request.assert_not_called()

    def test_generated_workflow_checks_approval_reuses_frames_and_builds_gif(self):
        work = self.init(reference=True)
        self.set_motion(work)
        self.cli("generate", work, "--stage", "frames", "--config", self.config, failure="approval is required")
        self.cli("build", work, failure="approval is required")
        self.cli("add-frame", work, 2, EXAMPLE / "02.png", failure="approval is required")
        self.request.assert_not_called()
        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (4, 1, 3)]
        ref = Path(self.cli("generate", work, "--stage", "reference", "--config", self.config)["reference"])
        self.assertEqual(ref, work.parents[2] / "characters/helper/v001/reference.png")
        reference_review = self.cli("review-reference", work)
        self.cli("approve-reference", work, "--digest", reference_review["digest"])
        self.cli("generate", work, "--stage", "keyframes", "--config", self.config)
        self.assertEqual(self.request.call_count, 3)
        first, edit, _ = [call.args[0] for call in self.request.call_args_list]
        self.assertEqual(first.full_url, "https://image.example.test/v1/images/generations")
        self.assertEqual(first.get_header("Authorization"), "Bearer mock-secret-key")
        self.assertEqual(json.loads(first.data)["background"], "transparent")
        self.assertEqual(edit.full_url, "https://image.example.test/v1/images/edits")
        self.assertEqual(edit.data.count(b'name="image[]"'), 1)
        self.assertIn(ref.read_bytes(), edit.data)
        self.assertIn(b"real alpha transparency", edit.data)
        review = self.cli("review-keyframes", work)
        with Image.open(review["preview"]) as sheet:
            self.assertEqual(sheet.format, "PNG")
        self.assertEqual(list((work / "output").iterdir()), [])
        self.cli("approve-keyframes", work, "--digest", "wrong", failure="out of date")
        self.cli("approve-keyframes", work, "--digest", review["digest"])
        self.request.side_effect = [http_error(429), image_reply(EXAMPLE / "02.png")]
        self.cli("generate", work, "--stage", "frames", "--config", self.config, failure="HTTP 429")
        self.assertEqual(self.cli("prepare-frames", work)["missing"], [2])
        self.assertEqual(self.cli("generate", work, "--stage", "frames", "--config", self.config)["rendered_frames"], [2])
        self.assertEqual(self.request.call_args.args[0].data.count(b'name="image[]"'), 3)
        self.assertEqual(self.cli("generate", work, "--stage", "frames", "--config", self.config)["rendered_frames"], [])
        self.assertEqual(self.request.call_count, 5)
        for index in (1, 3):
            self.assertEqual((work / f"frames/{index:04}.png").read_bytes(),
                             (work / f"keyframes/{index:04}.png").read_bytes())
        result = self.cli("build", work)
        with Image.open(result["gif"]) as gif:
            self.assertEqual((gif.n_frames, gif.info["loop"]), (3, 0))
        self.assertTrue(Path(result["preview"]["contact_sheet"]).is_file())
        self.assertNotIn("mock-secret-key", (work / "source/frames/0002.request.json").read_text())
        self.write_plan(work, action="A different action")
        self.cli("generate", work, "--stage", "frames", "--config", self.config, failure="plan changed")
        self.cli("build", work, failure="plan changed")
        self.assertEqual(self.request.call_count, 5)

    def test_url_only_response_is_saved_as_reference(self):
        work = self.init(reference=True)
        self.set_motion(work)
        url = "https://cdn.example.test/image.png?signature=mock-signature"
        self.request.side_effect = [url_reply(url)]
        with patch.object(openai_images, "PublicImageConnection") as download:
            response = download.return_value.getresponse.return_value.__enter__.return_value
            response.status = 200
            response.read.return_value = (EXAMPLE / "01.png").read_bytes()
            result = self.cli("generate", work, "--stage", "reference", "--config", self.config)
        download.assert_called_once_with("cdn.example.test")
        download.return_value.request.assert_called_once_with("GET", "/image.png?signature=mock-signature",
                                                               headers={"Accept": "image/png"})
        response.read.assert_called_once_with(openai_images.MAX_IMAGE_BYTES + 1)
        reference = Path(result["reference"])
        self.assertEqual(reference.read_bytes(), (EXAMPLE / "01.png").read_bytes())
        receipt = (reference.parent / "source.request.json").read_text()
        self.assertIn("req_url", receipt)
        self.assertNotIn("mock-signature", receipt)

    def test_download_rejects_redirect_and_does_not_resubmit_generation(self):
        work = self.init(reference=True)
        self.set_motion(work)
        self.request.side_effect = [url_reply("https://cdn.example.test/image.png?signature=private")]
        with patch.object(openai_images, "PublicImageConnection") as download:
            response = download.return_value.getresponse.return_value.__enter__.return_value
            response.status = 302
            self.cli("generate", work, "--stage", "reference", "--config", self.config,
                     failure="image download returned HTTP 302")
            self.cli("generate", work, "--stage", "reference", "--config", self.config,
                     failure="previous request may have been accepted")
        download.return_value.request.assert_called_once()
        response.read.assert_not_called()
        self.request.assert_called_once()

    def test_inline_image_takes_precedence_over_url(self):
        work = self.init(reference=True)
        self.set_motion(work)
        image = (EXAMPLE / "01.png").read_bytes()
        reply = io.BytesIO(json.dumps({"data": [{"b64_json": base64.b64encode(image).decode(),
                                                 "url": "https://cdn.example.test/image.png"}]}).encode())
        reply.headers = {}
        self.request.side_effect = [reply]
        with patch.object(openai_images, "download_image") as download:
            result = self.cli("generate", work, "--stage", "reference", "--config", self.config)
        download.assert_not_called()
        self.assertEqual(Path(result["reference"]).read_bytes(), image)

    def test_download_rejects_unsafe_urls_and_private_dns_answers(self):
        with patch.object(openai_images, "PublicImageConnection") as connection:
            for url in ("http://cdn.example.test/image.png", "https://user:pass@cdn.example.test/image.png",
                        "https://cdn.example.test:8443/image.png", "file:///tmp/image.png"):
                with self.subTest(url=url), self.assertRaisesRegex(ValueError, "requires an HTTPS URL"):
                    openai_images.download_image(url)
            connection.assert_not_called()
        endpoints = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", (ip, 443))
                     for ip in ("8.8.8.8", "127.0.0.1")]
        with patch.object(openai_images.socket, "getaddrinfo", return_value=endpoints), \
                patch.object(openai_images.socket, "socket") as connect:
            with self.assertRaisesRegex(ValueError, "public IP addresses"):
                openai_images.download_image("https://cdn.example.test/image.png")
            connect.assert_not_called()

    def test_download_pins_validated_address_and_checks_tls_hostname(self):
        host = "cdn.example.test"
        connection = openai_images.PublicImageConnection(host)
        connection.tls_context = Mock()
        address = ("8.8.8.8", 443)
        endpoints = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", address)]
        with patch.object(openai_images.socket, "getaddrinfo", return_value=endpoints) as resolve, \
                patch.object(openai_images.socket, "socket") as connect:
            connection.connect()
        resolve.assert_called_once_with(host, 443, type=socket.SOCK_STREAM)
        connect.return_value.connect.assert_called_once_with(address)
        connection.tls_context.wrap_socket.assert_called_once_with(connect.return_value, server_hostname=host)

    def test_unapproved_reference_blocks_keyframe_generation_and_intake(self):
        work = self.init(reference=True)
        self.set_motion(work)
        reference = work.parents[2] / "characters/helper/v001/reference.png"
        reference.write_bytes((EXAMPLE / "04.png").read_bytes())
        self.request.side_effect = [image_reply(EXAMPLE / f"{index:02}.png") for index in (1, 3)]
        self.cli("generate", work, "--stage", "keyframes", "--config", self.config,
                 failure="reference approval is required")
        self.cli("add-frame", work, 1, EXAMPLE / "01.png", failure="reference approval is required")
        self.request.assert_not_called()
        review = self.cli("review-reference", work)
        reference.write_bytes((EXAMPLE / "05.png").read_bytes())
        self.cli("approve-reference", work, "--digest", review["digest"], failure="out of date")
        review = self.cli("review-reference", work)
        self.cli("approve-reference", work, "--digest", review["digest"])
        self.cli("add-frame", work, 1, EXAMPLE / "01.png")
        reference.write_bytes((EXAMPLE / "04.png").read_bytes())
        self.cli("generate", work, "--stage", "keyframes", "--config", self.config,
                 failure="approved character reference changed")
        self.cli("review-keyframes", work, failure="approved character reference changed")
        self.request.assert_not_called()

    def test_changed_keyframe_needs_a_fresh_review_and_manual_continuation_works(self):
        work = self.init()
        self.set_motion(work)
        self.cli("add-frame", work, 1, EXAMPLE / "01.png")
        self.cli("add-frame", work, 3, EXAMPLE / "03.png")
        first = self.cli("review-keyframes", work)
        (work / "keyframes/0003.png").write_bytes((EXAMPLE / "04.png").read_bytes())
        self.cli("approve-keyframes", work, "--digest", first["digest"], failure="out of date")
        updated = self.cli("review-keyframes", work)
        self.assertNotEqual(updated["digest"], first["digest"])
        self.cli("approve-keyframes", work, "--digest", updated["digest"])
        self.cli("add-frame", work, 2, EXAMPLE / "02.png")
        self.assertEqual(self.cli("build", work)["frame_count"], 3)
        self.request.assert_not_called()

    def test_preserves_uncertain_request_and_rejects_unsupported_reference(self):
        work = self.init(reference=True)
        self.set_motion(work)
        ref = work.parents[2] / "characters/helper/v001/reference.png"
        ref.write_bytes((EXAMPLE / "01.png").read_bytes())
        reference_review = self.cli("review-reference", work)
        self.cli("approve-reference", work, "--digest", reference_review["digest"])
        self.set_profile(reference_count=0)
        self.cli("generate", work, "--stage", "keyframes", "--config", self.config, failure="cannot accept")
        self.request.assert_not_called()
        self.write_plan(work, character_reference=None)
        self.request.side_effect = [http_error(503)]
        self.cli("generate", work, "--stage", "keyframes", "--config", self.config, failure="may have been accepted")
        self.cli("generate", work, "--stage", "keyframes", "--config", self.config, failure="previous request")
        self.assertEqual(self.request.call_count, 1)
        receipt = json.loads((work / "source/keyframes/0001.request.json").read_text())
        self.assertEqual(receipt["request_id"], "req_failed")
        self.assertEqual(self.request.call_args.args[0].full_url, "https://image.example.test/v1/images/generations")

    def test_missing_key_points_to_local_terminal_before_any_request(self):
        work = self.init()
        self.set_motion(work)
        with patch.dict(os.environ, {"TEST_STICKER_KEY": ""}):
            self.cli("generate", work, "--stage", "keyframes", "--config", self.config,
                     failure="TEST_STICKER_KEY is missing or invalid in this process. Set it privately in the terminal")
        self.request.assert_not_called()
        self.assertFalse((work / "source/keyframes/0001.request.json").exists())

    def test_opaque_service_output_is_kept_without_resubmitting(self):
        work = self.init()
        self.set_motion(work)
        opaque = self.root / "opaque.png"
        Image.new("RGB", (240, 240), "white").save(opaque)
        self.request.side_effect = [image_reply(opaque)]
        for _ in range(2):
            self.cli("generate", work, "--stage", "keyframes", "--config", self.config, failure="real transparency")
        self.assertEqual((work / "source/keyframes/0001.png").read_bytes(), opaque.read_bytes())
        self.assertFalse((work / "keyframes/0001.png").exists())
        self.request.assert_called_once()


if __name__ == "__main__":
    unittest.main()
