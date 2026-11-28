# Character reference and motion

Record a character version and the reference image path, viewing angle, shape, face/head proportions, colors, linework and identifying details. Show the exact reference image and record the user's approval before drawing key poses. Keep those invariants in each pose prompt. Record the chosen action, start, peak, landing or recovery, support point and seam before drawing.

Make a small set of key poses where limbs or expression materially change. Present the numbered poses and wait for explicit user approval before filling transitions. For a simple legless bounce or nod, one continuous master can support measured squash, stretch and translation while holding the identity fixed. Preserve the master and source poses in `source/`, the approved poses in `keyframes/`, and the complete normalized set in `frames/`. [Keyframe review and frame intake](workspace-workflow.md)

Use one common 240×240 transparent canvas. Keep support at the same position while grounded, and preserve deliberate travel elsewhere. For a fixed anchor, use the same reference point and baseline across frames even if bounding boxes change. Independently centering each pose can erase intended motion or make ground contact slide.

Write one prompt per numbered pose. State the fixed character details, the exact pose to draw, the camera and scale, and the intended location of its support point. Ask for one pose on a square canvas with a real transparent background and enough padding for the most extended silhouette. Give an external drawing tool the same art brief and expected delivery paths.
