# Sprite Sheet Prompt Experiment Notes

This document records what prompts worked and failed during development of
the sprite sheet generation feature (Issue #90).

## Approach

Single model call via OpenRouter (Gemini 2.5 Flash Image) to generate a
`3 columns × 2 rows` sprite sheet PNG, then slice with Pillow and compose
into an animated GIF server-side.

## Grid Layout

```
[0] idle/neutral  |  [1] blink       |  [2] happy
[3] sad/frown     |  [4] sick        |  [5] sleeping
```

Cell size: depends on generated image resolution (512×512 sheet → 171×256 per frame; 768×512 → 256×256 per frame).

## Prompt Design

### Working pattern (v1)

```
{style_prefix} sprite sheet, 3 columns by 2 rows grid,
thin white separator lines between cells,
transparent or solid flat magenta background #FF00FF.
Character: {canonical_appearance}, {stage_desc}.
All 6 frames show the EXACT SAME character with identical
proportions, identical colour palette, identical body shape.
Frames reading left to right then top to bottom:
[1] idle neutral pose..., [2] blink..., [3] happy...,
[4] sad..., [5] sick..., [6] sleeping...
Consistent style throughout, clean cell alignment.
```

Key findings:
- Labelling frames `[1]–[6]` (1-indexed) in the prompt description helps the
  model understand the counting convention.
- Requesting `transparent or solid flat magenta background #FF00FF` lets
  us apply the existing chroma-key removal if the model produces a flat
  background.
- Saying "EXACT SAME character" in caps improves frame consistency across
  the grid but is not a guarantee.
- The `canonical_appearance` string (stored in the DB after first generation)
  acts as a character anchor for subsequent regenerations and style updates.

### What didn't work

- Asking for a `4×2` grid without clear frame labels: model often produced
  6–7 distinct characters instead of one character in 8 poses.
- Omitting the style prefix: resulted in inconsistent art styles between cells.
- Asking for `transparent background` only (no fallback): Gemini 2.5 Flash
  frequently returned white backgrounds, requiring `remove_white_background()`
  fallback from `storage.py`.

## Grid Resolution Notes

- 512×512 total sheet → cells are ~170×256 (non-square for 3-col layouts);
  adequate for badge use.
- 1024×512 → 341×256 per cell; better aspect ratio for the character.
- Current prompt does not specify exact dimensions; the model defaults to
  its preferred output size.

## GIF Composition

- Pillow `quantize(colors=255)` + transparency index 255 approach produces
  correct animated GIFs with transparent backgrounds.
- Frame durations: idle 400 ms, blink 180 ms (short to feel natural),
  happy/sad/sick 350–500 ms, sleeping 700 ms.
- `disposal=2` (restore to background) required to avoid ghosting between
  RGBA frames in the palette-mode GIF.

## Open Questions

- Does Gemini 2.5 Flash reliably keep grid alignment? In informal testing:
  ~70% of generations produce a clean 3×2 grid; the rest either produce a
  2×3 layout or collapse all frames into a single scene. Frame extraction
  degrades gracefully (slices at equal widths regardless).
- Can an existing static sprite be passed as a style reference for subsequent
  generations? OpenRouter's vision API supports image inputs in chat messages;
  this would require switching `_call_api()` to a multimodal payload.
  Not yet implemented.
- Pixel art vs painterly: current default `kawaii` style produces pixel art;
  other styles (doom_metal, wizard) tend toward painterly. Both produce
  acceptable sprite sheet grids.
