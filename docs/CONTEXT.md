# Context

The words this repo uses for the parts of a video and the files around it. Code, skills and reviews
use these names.

## draft

A CapCut desktop project: one folder holding `draft_info.json` (the timeline and its materials) plus
media and a cover. The CapCut export writes one in `edits/<name>/export/capcut/<name>/`. See
[ADR-0001](adr/0001-capcut-draft-format.md).

## project store

The folder CapCut scans at startup for drafts. On a Mac:
`~/Movies/CapCut/User Data/Projects/com.lveditor.draft/`. CapCut keeps `root_meta_info.json` there
and rewrites it on quit, so the store belongs to CapCut: add or remove drafts with CapCut closed.

## segment piece

One kept span of the cut, encoded on its own by `render.py` and cached in
`<edit>/.segments/<key>/<start>-<end>.mp4`. The export copies it into a draft as `seg-01.mp4`,
`seg-02.mp4`... because the cache is pruned when the spans change.

## caption page

The words shown together at one moment: one chunk in `plan.json` (`captions.chunks`), and one
caption on screen. A page is filled by width (Thai) or word count (Latin) and never splits a word.
In a draft, one page is one native text segment on the text track, unstyled.
