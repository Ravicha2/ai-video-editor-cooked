# 0001: Write CapCut drafts directly, pinned to one schema

- Date: 2026-10-20
- Status: accepted

## Context

CapCut has no timeline import. Its desktop project is a folder of plain JSON on the Mac
(`draft_info.json`, `draft_meta_info.json` and media). Issue #4 read CapCut 9.5's draft loader
(`libvideoeditor.dylib`, arm64) and 18 real drafts (schema 159–187):

- The loader takes a JSON object and defaults every missing field. Nothing is required beyond a root
  object, but a useful draft needs `tracks`, `canvas_config`, `fps` and `duration`.
- Every segment points at one material and six `extra_material_refs`: speed, placeholder_info,
  canvas_color, sound_channel_mapping, material_color, vocal_separation. Whether a dangling ref is
  tolerated was not proven.
- 59.94 fps is exactly 60000/1001. Times are integer microseconds, so frame n is
  `round(n * 1_000_000 * 1001 / 60000)`; do not accumulate rounded floats.
- A draft folder is discovered at startup and merged into the user's project store. CapCut owns the
  store file and rewrites it on quit.
- The schema version (`new_version`) moves with the app: 159 to 187 in the samples.
- Verified by hand in CapCut 9.5 (2026-10-20): the startup scan only discovers a folder with
  `draft_info.json` **and** a `draft_meta_info.json` beside it: `draft_info.json` alone was skipped.
  And CapCut cannot read media under `/private/tmp`; draft media must live in the user's home.
- A caption page's position maps from the plan's `y_pct` to `clip.transform.y = (0.5 - y_pct/100) * 2`
  (half-canvas units, negative y down: a real auto-caption draft's `y -0.8` is the 90% line).

Full evidence: [`../../capcut_finding.md`](../../capcut_finding.md).

## Decision

The `capcut` export writes the draft itself, in `edits/<name>/export/capcut/<name>/`:
`draft_info.json` with the cut's pieces on one video track, each caption page as a native text
segment on a text track, and stable copies in `media/`.

- Pin `new_version` to `187.0.0`, the version this writer is built and checked against.
- Read the user's own drafts before writing. If their newest draft is newer than 187, refuse with
  "re-check after a CapCut update" rather than write a draft we cannot vouch for. Older drafts are
  safe to upgrade: the loader marks them for migration.
- Check every draft before writing: every ref resolves, times are monotone, the segments add up to
  the draft's duration, and no path leaves the export folder. `demo()` repeats the check on
  deliberately broken drafts.
- Copy the kept spans out of `<edit>/.segments` as `seg-01.mp4`..., filling a cold cache with
  `render.py --segments-only`. Never reference the cache: it is pruned when the spans change.
- Caption pages become native text segments on their own track (issue #6): the page's text, its µs
  time and its position (the plan's `y_pct`, in CapCut's half-canvas units with negative y down).
  No font, size, colour or stroke from the plan: the material carries CapCut's own plain subtitle
  defaults, as seen in a real auto-caption draft (1017), so the user styles once inside CapCut. The
  `.srt` stays unchanged for anyone who prefers CapCut's Add-captions import.
- The plan's `texts` (title, cta, list lines: the words besides the captions) become text segments
  too, one track per item because a list's lines and a cta over a title overlap and one text track may
  not. Times are the plan's seconds on the cut, placed by `y_pct` (and `x_pct` as a centre) like a
  caption. Same rule as captions: plain defaults, restyle once inside CapCut. A `stamp` is a drawn X
  with no words, so it stays a hand step.
- Cards become overlay video tracks above the main one, one per lane so overlapping cards stay legal
  (issue #7). A card that renders nothing is not a segment: it stays a hand step. An animated card
  is its ProRes `.mov` with a grayscale matte beside it, `card-01.mov.alpha.mp4`: the loader's only
  alpha mechanism is the sibling `<file>.alpha.mp4` (`lvve::isHasAlphaFile`), so move the pair
  together. A still card is its `.png` as a `photo` material (as `image`, CapCut kept the clip on
  the timeline and drew nothing: found in issue #8's install check). Two things the local drafts could not
  prove (no overlay or image sample exists); the CapCut smoke test decides, and the `.png` still is
  the documented fallback: whether the decoder keeps in-band alpha from a `.mov`, and whether a
  clip's scale 1.0 means fitted-inside-the-canvas. The card's `scale = max(w/W, h/H)` places the
  box-sized material at its box size under that reading.
- The cut's own audio becomes one more audio track, one segment at time 0: the `.segments` cache
  is video-only (`render.py` encodes spans with `-an`) and `cut.mp4` mixes its audio from those same
  spans with the same joins and fades, so `media/cut-audio.m4a` stays in sync under the pieces.
  Without it the draft opened silent (found in issue #8's install check).
- Sound cues become one audio track in the shape of a real local-music draft (0315 (2)): type
  `extract_music`, six refs including fade and beats, gaps allowed, `volume 1.0` because the level
  is already set in the rendered media (sfx.py).
- Keep `CAPCUT.md` as the by-hand path: the caption styling, the cards that did not render, and the
  re-install note for the `.mov` plus matte pairs.
- `capcut_draft.py install` does the hand-off (issue #8): it copies the generated folder into the
  project store with CapCut closed, writes the `draft_meta_info.json` the startup scan needs beside
  `draft_info.json`, lists every media file in `draft_meta_info.json`'s type-0 `draft_materials`
  (CapCut's media panel reads only that list: empty, the draft opened with an empty import section
  while its timeline played), re-points every media path under the copied folder, and appends the
  project entry to `root_meta_info.json` after keeping a `.bak`. A taken name stops and offers the first free
  numeric suffix; nothing is overwritten. The app is refused while running, because its quit
  rewrite wins. The user then opens CapCut once and confirms the draft lists, the pieces cut at the
  joins and the captions, cards and cues are editable: the acceptance test no agent can run, and the
  one to repeat after a CapCut update.

## Consequences

- The export needs no CapCut installed, and its output can be reviewed as JSON.
- A CapCut update can invalidate the writer. The guard turns that into a clear refusal instead of a
  broken project. Re-probe the loader (issue #4's method) before raising `PINNED`.
- Drafts are installed with CapCut closed: writing into the live project store can be overwritten
  when CapCut quits.
- The draft carries the cut, the caption pages, the plan's titles (cta, list lines), the rendered
  cards and the sound cues, and installs
  into the project list. The schema will grow, so re-run `capcut_draft.py demo` after those changes,
  and repeat the in-person CapCut check after an app update.
