---
name: wechat-sticker-studio
description: Create, import, repair, validate, or package transparent animated WeChat stickers. Use when turning ordered PNG poses or a character reference and action into a 240×240 loop, adjusting frames or timing, checking a GIF on two backgrounds, or preparing submission materials.
---

# WeChat Sticker Studio

Identify the requested output and locate the skill folder from this file. Run its bundled `scripts/sticker_gif.py` with an existing Python that has the Pillow version in `requirements.txt`. Use absolute script and interpreter paths when working in a separate artwork directory.

## Choose the starting input

- **Ordered PNGs.** Verify the order and existing timing before import. Use `import-png` for 12 ready single-frame 240×240 PNGs and pass paths in playback order. Paths in the resulting manifest are relative to the manifest. If sources need cropping or placement, preserve the originals and prepare a consistent canvas and action anchor first.
- **Character reference or description plus an action.** Read [character and motion](references/character-motion.md). Use an available host image tool for source art if requested. If drawing is external, give the user a reference, numbered pose prompts and intake path, then use the PNG route.
- **Existing GIF.** Run `validate` on the actual GIF, with the original manifest when available. Report the decoded values and named failures. Absence of a manifest means expected timing has not been checked.
- **Targeted repair.** Keep the same action, order and delays unless the user changes them. Keep the original PNG and point the selected manifest entry to the revised PNG. Compose to a new GIF or use `--replace` when asked to replace the good version.
- **Submission materials.** Read [submission preflight and ZIP packaging](references/submission.md). Lock the selected bytes in the manifest, preserve upload order and report the rules snapshot used for validation.

## Compose and review

Use [PNG import and export commands](references/png-workflow.md). Keep one manifest per sticker or revision and deliver the GIF, manifest, actual decode report, and light/dark preview. The [manifest template](assets/sticker.template.json) supports direct editing or use as a schema example.

Require 12 actual frames, 240×240, infinite looping, at most 500,000 bytes, expected delays and both subject and transparent background in each decoded frame. Twelve frames is this project's quality standard. Adjacent identical frames can merge, so assess the decoded output even when all twelve inputs were supplied. Review the preview at chat size for two loops, including action readability, identity, anchoring, seam, residual pixels and edge contrast. State any unfinished visual checks.
