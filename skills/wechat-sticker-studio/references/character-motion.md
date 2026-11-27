# Character reference and motion

Record a character version and the reference image path, viewing angle, shape, face/head proportions, colors, linework and identifying details. Keep those invariants in each pose prompt. Record the chosen action, start, peak, landing or recovery, support point and seam before drawing.

Make a small set of key poses before filling transitions. Draw the poses where limbs or expression materially change. For a simple legless bounce or nod, one continuous master can support measured squash, stretch and translation while holding the identity fixed. Preserve the master and source poses in `source/` and normalized frames in `frames/`. A PNG with a checkerboard painted into its pixels needs real transparency before import.

Use one common 240×240 transparent canvas. Keep support at the same position while grounded, and preserve deliberate travel elsewhere. For a fixed anchor, use the same reference point and baseline across frames even if bounding boxes change. Independently centering each pose can erase intended motion or make ground contact slide.

If the input requires an external drawing tool, send an art brief with character invariants, numbered poses and in-between cues, framing and delivery paths. Ask for genuine transparent PNGs, with intact silhouettes and enough padding for the most extended pose. Verify the returned PNGs and resume the normal import path.
