---
name: talking-head
description: The fast path for one person talking straight to camera in one take. Runs the same steps as start, cut and style-edit, but asks nothing the profile or a saved style already answers, skips creator teardown when the style exists, and ends with the CapCut draft installed and checked. Use when the user says "talking head", "edit my talking-head video", "one take to camera", "fast cut of my take" or drops one take of themselves with no style question. Not for several speakers or a podcast (clips), a video about a website (product-video), a first run with no profile and no style (start), or one step on its own (cut, style-edit).
license: MIT
compatibility: Python 3.9+, ffmpeg, Node 20+ and the Remotion renderer the setup skill installs. Runs from the full ai-editor plugin folder (uses its lib/ and remotion/).
---

# Talking head

Paths: `${CLAUDE_SKILL_DIR}` means the folder containing this SKILL.md, and `${CLAUDE_PLUGIN_ROOT}` the plugin folder two levels above it.

Read `${CLAUDE_PLUGIN_ROOT}/PRINCIPLES.md` first: the rules every video follows (where, asking, looking real, motion, story, privacy, cost).

Every question goes in the question box: the AskUserQuestion tool (2-4 options, recommended first). Only in an agent without it, ask numbered questions in text. `Attached images: <paths>` in an answer: Read each first.
Run the scripts with `python3` on Mac and Linux, `py` on Windows.

This skill is a shortcut, not a second pipeline. Each step below is the real skill; read that skill's SKILL.md
before its step and follow it. What this skill adds is the order that needs no questions, the talking-head
defaults in section 3, and section 5's CapCut hand-off, which was learned the hard way.

```
edits/<name>/cut.mp4 + cut.transcript.json + words.json   (cut)
edits/<name>/style.json                                   (profile, or the default style)
plan.json -> stills/sheet.png -> render.mp4               (style-edit)
export/capcut/<name>/ + installed draft                   (export, section 5)
```

## 0. What is already decided

Run these first. They print one line each and never open the page.

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/ai_editor/profile.py" show
python3 "${CLAUDE_PLUGIN_ROOT}/lib/ai_editor/library.py" path
```

- A profile with creators, a brand kit and taste: ask nothing about look, audience or sound.
- `creator-teardowns/<handle>/style.json` for every profile creator: skip creator-teardown entirely.
- No profile, or no style and no creator: this is not the fast path. Run `start` instead and say why in one line.
- One take, one speaker: if the take has several speakers or is a long recording to clip, run `clips` instead.

The only questions left are the ones the files cannot answer: the take's path when nothing was dropped,
and the aspect when the take is not obviously 9:16 or 16:9. Ask both in one question box, only if needed.

## 1. Cut

Follow the `cut` skill. Talking-head defaults, when its SKILL.md leaves the choice open:

| situation | do |
|---|---|
| normal take to camera | cut retakes, false starts and long pauses; no b-roll pass |
| wide take, title on top | `--max-pause 0.5 --layout letterbox` (start's step 3 says the same) |
| take longer than 5 minutes | cut's reader and verifier agents, as its SKILL.md says |

Stop at the cut page and let the user approve it (approval 1 of 2). Do not re-render for notes that only
change the look; those belong to style-edit.

## 2. Style

```bash
python3 "${CLAUDE_PLUGIN_ROOT}/lib/ai_editor/profile.py" style edits/<name>
```

Then follow the `style-edit` skill from step 1 (its inputs) to step 7 (render). Do not repeat start's intake:
the profile answers platform, creators, brand, names, assets, avoid and sound.

## 3. Talking-head defaults

These are the choices that make a one-person take read like the creators this plugin copies. The style and
the taste rules win where they disagree; these fill the gaps.

- **Captions:** 3 words a page, inside the reels safe zone, bottom line clear of the chin. Never over the face.
- **Zooms:** one smooth move every 4-5 s, on the stress word; no zoom on the first second of a sentence.
- **Cards:** only for something real the speaker names (their product's page, a post, a logo, a screenshot).
  No type cards, stock pictures or icons, and never two cards at once.
- **Titles and cta:** the hook's title and the closing ask come from `visuals.json` (`title`, `cta`); plan.py
  turns them into `plan.json` `texts`. They are the words beside the captions, so check them on the stills.
- **Speaker behind:** when the profile says `"behind": true`, run `matte.py` after the last plan.py run, as
  style-edit step 4 says.

## 4. Render and hand over

Render where the profile says, run `check.py render`, and hand over on the review page (style-edit steps 6-8).
A FAIL goes back to the plan or the cut; at most two fix rounds. Approval 2 is the render.

## 5. CapCut, when the user wants it

Only when the user asks to finish in CapCut ("send it to CapCut", "open it in CapCut"). With CapCut closed:

```bash
python3 "${CLAUDE_SKILL_DIR}/../style-edit/scripts/export_nle.py" edits/<name> --to capcut
python3 "${CLAUDE_SKILL_DIR}/../style-edit/scripts/capcut_draft.py" install edits/<name>/export/capcut/<name>
```

`install` refuses while CapCut runs, and refuses a taken name (it prints the free suffix: re-run with
`--name <that>`). It never overwrites. Then ask the user to open CapCut once. This is the one check no agent
can run; say exactly what to look for:

1. The draft is in the project list.
2. The video and the import/media panel both show the pieces, cards and audio.
3. The pieces cut at the joins, with the speech audible (`media/cut-audio.m4a`; the pieces are video-only).
4. The titles, cta and list lines are editable, on their own text tracks.
5. The cards sit on their overlay tracks; the cues on their audio tracks.

What went wrong before, so the fix is quick (all in `capcut_draft.py`, all demo-checked):

| symptom | cause |
|---|---|
| draft opens silent | cut audio missing: `ensure_audio` copies it from `cut.mp4`; re-export |
| titles/cta missing | plan `texts` not passed to `build_draft`; re-export, then reinstall |
| a still card is on the timeline but draws nothing | still written as `image`; it must be a `photo` material |
| import/media panel empty | `draft_meta_info.json` `draft_materials` empty; `install` fills it |

After a CapCut update the export refuses when the user's own drafts are newer; re-check the writer and repeat
this list. `export/CAPCUT.md` is the by-hand path for caption styling and cards that did not render.

## If a step stops

| message | do |
|---|---|
| `no cut.mp4` | run section 1 first |
| `no creator style.json found` | the style step needs a teardown: run `start` step 3.2 once, or `profile.py style` with no creators |
| `CapCut is running` | ask the user to quit CapCut, then install again |
| `a draft named ... is already in the project store` | re-run with the free `--name` it printed |
| anything else | that skill's own "If a script stops" table |
