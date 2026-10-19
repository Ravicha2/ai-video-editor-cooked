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

Full evidence: [`../../capcut_finding.md`](../../capcut_finding.md).

## Decision

The `capcut` export writes the draft itself, in `edits/<name>/export/capcut/<name>/`:
`draft_info.json` with the cut's pieces on one video track, and stable copies in `media/`.

- Pin `new_version` to `187.0.0`, the version this writer is built and checked against.
- Read the user's own drafts before writing. If their newest draft is newer than 187, refuse with
  "re-check after a CapCut update" rather than write a draft we cannot vouch for. Older drafts are
  safe to upgrade: the loader marks them for migration.
- Check every draft before writing: every ref resolves, times are monotone, the segments add up to
  the draft's duration, and no path leaves the export folder. `demo()` repeats the check on
  deliberately broken drafts.
- Copy the kept spans out of `<edit>/.segments` as `seg-01.mp4`..., filling a cold cache with
  `render.py --segments-only`. Never reference the cache: it is pruned when the spans change.
- Keep `CAPCUT.md` as the by-hand path and the record of the cards, captions and sound the draft
  does not carry yet.

## Consequences

- The export needs no CapCut installed, and its output can be reviewed as JSON.
- A CapCut update can invalidate the writer. The guard turns that into a clear refusal instead of a
  broken project. Re-probe the loader (issue #4's method) before raising `PINNED`.
- Drafts are installed with CapCut closed: writing into the live project store can be overwritten
  when CapCut quits. Installation is a later issue.
- The draft holds only the cut until the captions and cards issues land. The schema will grow, so
  re-run `capcut_draft.py demo` after those changes.
