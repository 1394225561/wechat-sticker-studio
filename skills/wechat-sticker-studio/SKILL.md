---
name: wechat-sticker-studio
description: Create, import, repair, validate, or package transparent animated WeChat stickers. Use when turning ordered PNG poses or a character reference and action into a 240×240 loop, adjusting frames or timing, checking a GIF on two backgrounds, or preparing submission materials.
---

# WeChat Sticker Studio

Identify the requested output and locate the skill folder from this file. Use absolute script and interpreter paths when working in a separate artwork directory.

## Check the local environment

Use the provided Python path, the artwork project's `.venv`, or a Python 3.12 interpreter available on the machine. Run `"$py" -B "$skill/scripts/check_environment.py"` with both paths set before invoking the GIF or submission tools. The JSON report gives the interpreter path, actual and required versions, and any errors. Continue with the same interpreter when the check exits `0`.

If Python is missing, install it through an official channel or use uv with `uv python install 3.12`. [Python downloads](https://www.python.org/downloads/) · [uv installation](https://docs.astral.sh/uv/getting-started/installation/)

If Pillow is missing or mismatched, install it in the project virtual environment with `"$py" -m pip install -r "$skill/requirements.txt"`, then rerun the check. [Pillow on PyPI](https://pypi.org/project/pillow/)

## Choose the starting input

- **Ordered PNGs.** Verify the order and existing timing before import. Pass at least two single-frame 240×240 PNGs to `import-png` in playback order. Use `--frame-count` when the user specifies the number of frames. Paths in the resulting manifest are relative to the manifest. If sources need cropping or placement, preserve the originals and prepare a consistent canvas and action anchor first.
- **Character reference or description plus an action.** Read [character and motion](references/character-motion.md). Use the requested frame count, or choose one based on the action and timing. Use an available host image tool for source art if requested. If drawing is external, give the user a reference, numbered pose prompts and intake path, then use the PNG route.
- **Existing GIF.** Run `validate` on the actual GIF with the original manifest when available. Use `--frame-count` if the target count is known and there is no manifest. Report the decoded values and named failures. Absence of a manifest means expected timing has not been checked.
- **Targeted repair.** Keep the same action, order and delays unless the user changes them. Keep the original PNG and point the selected manifest entry to the revised PNG. Compose to a new GIF or use `--replace` when asked to replace the good version.
- **Submission materials.** Read [submission preflight and ZIP packaging](references/submission.md). Lock the selected bytes in the manifest, preserve upload order and report the rules snapshot used for validation.

## Compose and review

Use [PNG import and export commands](references/png-workflow.md). Keep one manifest per sticker or revision and deliver the GIF, manifest, actual decode report, and light/dark preview. The [manifest template](assets/sticker.template.json) supports direct editing or use as a schema example.

Require at least two decoded frames, 240×240, infinite looping, at most 500,000 bytes, and both subject and transparent background in each decoded frame. Match the frame count and delays to the manifest when available. Adjacent identical frames can merge, so check the decoded output even when all planned inputs were supplied. Review the preview at chat size for two loops, including action readability, identity, anchoring, seam, residual pixels and edge contrast. State any unfinished visual checks.
