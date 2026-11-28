---
name: wechat-sticker-studio
description: Create, import, repair, validate, or package transparent animated WeChat stickers. Use when turning ordered PNG poses or a character reference and action into a 240×240 loop, adjusting frames or timing, checking a GIF on two backgrounds, or preparing submission materials.
---

# WeChat Sticker Studio

Identify the requested output and locate the skill folder from this file. Use absolute script and interpreter paths when working in a separate artwork directory.

## Check the local environment

Use the provided Python path, the artwork project's `.venv`, or a Python 3.12 interpreter available on the machine. Run `"$py" -B "$skill/scripts/check_environment.py"` with both paths set before invoking the workflow, GIF or submission tools. The JSON report gives the interpreter path, actual and required versions, and any errors. Continue with the same interpreter when the check exits `0`.

If Python is missing, install it through an official channel or use uv with `uv python install 3.12`. [Python downloads](https://www.python.org/downloads/) · [uv installation](https://docs.astral.sh/uv/getting-started/installation/)

If Pillow is missing or mismatched, install it in the project virtual environment with `"$py" -m pip install -r "$skill/requirements.txt"`, then rerun the check. [Pillow on PyPI](https://pypi.org/project/pillow/)

## Choose the starting input

- **Complete, ordered PNGs.** Verify the expected count, playback order and existing timing. Initialize an `imported` workspace in the user's artwork directory, then use `import-frames` and `build`. Keep the source images and use a common canvas and action anchor. For work based on an existing manifest or explicitly chosen layout, use the existing [PNG commands](references/png-workflow.md).
- **Character reference or description plus an action.** Initialize a `generated` workspace and write the plan. Choose the requested frame count or derive it from the movement and timing. With a character reference, prepare that image first, run `review-reference`, show the exact image and wait for explicit approval. Record it with `approve-reference` before requesting or making any key poses. Then make and show the keyframes, wait for a second explicit approval, and record it before making in-between frames. Use the user's chosen image service, host tool or external drawings for each stage. Fill the planned frame set and run `build`. [Workspace and image service workflow](references/workspace-workflow.md) · [Character and motion](references/character-motion.md)
- **Existing GIF.** Run `validate` on the actual GIF with the original manifest when available. Use `--frame-count` if the target count is known and there is no manifest. Report the decoded values and named failures. Absence of a manifest means expected timing has not been checked.
- **Targeted repair.** Keep the same action, order and delays unless the user changes them. Keep the original PNG and point the selected manifest entry to the revised PNG. Compose to a new GIF or use `--replace` when asked to replace the good version.
- **Submission materials.** Read [submission preflight and ZIP packaging](references/submission.md). Lock the selected bytes in the manifest, preserve upload order and report the rules snapshot used for validation.

## Set up a user's image service

When the user chooses their own image service, use `.config/image-service.json` under their artwork root. If it contains a saved `profilePath`, let `generate` reuse it across sessions. For a shared or imported artwork directory, verify the service destination and key variable with the user before using a pre-existing profile. If the remembered profile is unavailable, report its path. The user can restore it, clear the saved selection and fill the root configuration, or choose another profile. For missing or invalid fields, point to the file and the fields to fix.

If the user chooses to supply settings in chat, ask only for the service URL, model, key environment variable name and known image capabilities, or the path to their existing profile. Save new settings at their requested path or at `.config/image-service.custom.json` under the artwork root. Run `set-image-service-config` to remember the selection. Use `generate --config` when the user requests a one-time override.

Use the current process environment. Ask the user to enter a key privately in their terminal only when the command reports a missing or invalid variable, or when they want to override it. If the Agent's process cannot inherit the variable, give the user the exact local `generate` command for the current stage and continue with the saved files. [Local key setup](references/workspace-workflow.md#在本机输入密钥)

## Compose and review

Keep one manifest per sticker revision and deliver the GIF, manifest, actual decode report, and light/dark preview. For direct CLI use, see the [PNG import and export commands](references/png-workflow.md) and [manifest template](assets/sticker.template.json).

Require at least two decoded frames, 240×240, infinite looping, at most 500,000 bytes, and both subject and transparent background in each decoded frame. Match the frame count and delays to the manifest when available. Adjacent identical frames can merge, so check the decoded output even when all planned inputs were supplied. Review the preview at chat size for two loops, including action readability, identity, anchoring, seam, residual pixels and edge contrast. State any unfinished visual checks.
