# PNG import and GIF export

Set these variables to existing paths, then run from the artwork directory. This example uses `frames/01.png` through `frames/24.png`. Replace the arguments with an explicit ordered list if the inputs use another naming pattern. A common canvas and fixed grounding or motion path should already be present.

```sh
py=/absolute/path/to/python3
skill=/absolute/path/to/wechat-sticker-studio
"$py" -B "$skill/scripts/sticker_gif.py" import-png sticker.json frames/*.png \
  --frame-count 24 --duration-ms 40
"$py" -B "$skill/scripts/sticker_gif.py" compose sticker.json sticker.gif > compose.json
"$py" -B "$skill/scripts/sticker_gif.py" validate sticker.gif \
  --manifest sticker.json --preview review.gif > validation.json
```

Import accepts at least two PNGs and uses the number of input paths when `--frame-count` is omitted. `--duration-ms` sets a uniform delay. Use `--durations-ms` for a comma-separated list with one delay per input. Delays are set in multiples of 10 milliseconds. Import validates all inputs before creating the manifest and keeps the original PNGs in place. It accepts an Alpha threshold of 0–254, defaulting to 128. At encoding, Alpha values at or below the threshold become transparent.

The `frames` list sets the expected count for `compose` and `validate --manifest`. To check a GIF with no manifest, run `validate sticker.gif --frame-count 24` using the desired count. When neither option is supplied, `validate` reports the decoded count and records `expected_frame_count` as `null`.

Use `compose --replace` to replace an existing GIF only after the candidate passes decode checks. With a single-frame repair, a sibling version of the manifest and GIF makes the revision easy to compare. Keep a note of which frame changed. The preview combines light and dark backgrounds in one GIF and writes a labeled PNG contact sheet next to it.

If the decoder reports a merged frame, revise its pose or its timing plan and recheck actual frame count and duration. If the frame is wrong-sized, keep the source and prepare a correctly placed frame on the shared canvas. If the checker finds a visible halo or residual background, inspect the PNG at that index and the chosen threshold before re-encoding.
