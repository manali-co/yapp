# Yapp: brand

Yapp's look is decided in the Claude Design project *Yapp macOS Voice Assistant Design* and ported byte-for-byte into `src/yapp/ui/` (see `scripts/pull_design.py`). This folder holds the parts of that project you'd want outside the app: the icon at every size, the menu-bar glyphs, README art, and the avatar as an animation.

## The icon

A pebble inside a ring. The pebble is the avatar's actual idle contour, the same shape you see in the bar, and the ring is its mic meter. So the icon is what's on screen, not a metaphor for it. Matte, no gloss; on a warm paper ground so it sits next to Apple's own icons without shouting.

At 16 px the ring gap nearly closes and it reads as a peach dot in a blue circle, which is intended: the 16 and 32 px PNGs are hand-tuned with a thicker ring and a larger pebble rather than scaled down.

Ground `#F6F1E8` → `#EBE3D3`. The pebble and ring take their hues from the avatar's listening and thinking states. In the app itself nothing is a brand colour: the bar uses the system appearance, system materials and system font, and the avatar's ring follows the user's accent colour.

## The avatar

Nine states at 64 px (56 px body plus the ring): idle, listening, thinking, dictating, acting, done, unsure, refused, error. Expression comes from silhouette, tension and timing, never from a face. Motion is continuous and spring-eased; there are no cuts and idle is never static. `avatar-states.gif` walks idle → listening → thinking → acting → done and was recorded from `avatar.html` at 20 fps.

## Files

`svg/`
- `icon.svg` — the app icon, 1024 grid, as exported.
- `icon-animated.svg` — same icon, the ring draws itself in on load. CSS inside the SVG; respects `prefers-reduced-motion`.
- `menubar-glyph.svg`, `-listening`, `-paused`, `-attention` — 18 px template images; macOS tints them.
- `banner-light.svg`, `banner-dark.svg` — README header, animated (ring draws, then the name settles). `social-preview.svg` — 1280×640 card.

`png/`
- `icon-1024.png`, `icon-32.png`, `icon-16.png` — what `yapp install-app` bakes into the `.icns`. The 16 and 32 are hand-tuned.
- `icon-sheet.png` — the icon at 16/32/128/512 on light and dark, for checking.
- `avatar-states.gif` — the avatar on paper, 192 px, 10 fps. `avatar-states.webp` — the same with a transparent background.
- `banner-*.png`, `social-preview-1280x640.png` — rasters. Upload the social preview under **Settings › Social preview** on GitHub.

`design/`
- `Yapp.dc.html`, `Icon options.dc.html` — the hi-fi showcase and the six icon directions that were explored before this one. Reference only.
- `screenshots/` — the bar in a couple of states.

## Rules

Don't add a face to the pebble. Don't put the wordmark inside the icon. Don't recolour the ring to match a brand; it belongs to the user's accent colour. If something needs to change, change it in the design project and re-run the pull.
