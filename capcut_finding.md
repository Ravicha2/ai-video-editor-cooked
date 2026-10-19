# CapCut draft reader: static findings (issue #4)

Status: answered. Research only; no plugin code changed.
Date: 2026-10-19.

Target: CapCut **9.5.0** (CFBundleVersion 9.5.0)
Binary: `/Applications/CapCut.app/Contents/Frameworks/libvideoeditor.dylib`
Universal 173 MB; arm64 slice ~84 MB; 33,853 symbols.

Method: `lipo -thin arm64`, then direct ARM64 disassembly (`xcrun llvm-objdump`)
with a small resolver for `adrp`/`add` string references and `bl` targets.
REA 6.5.0 with the Ghidra 12.1.4 provider was used to set up analysis, but the
full auto-analysis of this dylib is slow; every finding below comes from
reading function bodies directly. Static only: the app was not run and no
draft was modified.

Evidence labels used below:

- **Observed**: instruction/bytes in the binary or a real file on disk.
- **Inferred**: a reading of control flow that fits the observations but was
  not executed.
- **Unknown**: not established by this pass.

Addresses are symbol starts reported by `nm`. Some symbols in this dylib are
merged (one symbol covers several unrelated functions), so a caller mapping
can be approximate. Field names and control flow at each cited start were
checked by hand.

---

## Answer matrix

| # | Question | Answer | Go/no-go |
|---|----------|--------|----------|
| 1 | Required fields for a minimal draft | Loader needs only a JSON object. Missing fields keep constructor defaults. Registration is file-based. | **GO**: use the 12-key practical minimum already found in real drafts; add `tracks`/`canvas_config`/`fps`/`duration` for a useful draft |
| 2 | Alpha video in overlays | Alpha is a sibling sidecar named `<source path>.alpha.mp4`. No `.mov` embedded-alpha path exists in this code. | **GO with sidecar**; **NO** for `.mov` carrying alpha in-band (decoder behaviour unknown) |
| 3 | 59.94 fps rounding | Exact rational 60000/1001. Frame interval 16683.333… µs. Snap to integer frame only within **800 µs**. | **GO**: emit exact integer µs from frame counts |
| 4 | Registration mechanics | Folder + `draft_info.json` (or `draft_content.json`) + `draft_meta_info.json`. Startup scan discovers it and merges into `root_meta_info.json`. | **GO**: no manual root-meta edit |
| 5 | Rewrite on quit | Closing the store (including app quit) rewrites both `draft_meta_info.json` and `root_meta_info.json`, asynchronously. | **GO install with CapCut closed** |

---

## 1. Minimal draft: what the loader actually requires

### Observed: root type check

`lvve::Draft::patch_from_json` @ `0xccb4b8` starts by checking the JSON value
type byte:

```
ccb4e4  ldrb w8, [x1]
ccb4e8  cmp  w8, #1        ; nlohmann value_t::object
ccb4ec  b.ne 0xcd01dc      ; bail out of the patch path
```

So the root **must be a JSON object**. That is the only hard type requirement
visible at this layer.

### Observed: absent fields are skipped

Every top-level field is looked up with an inlined `nlohmann` map search. If
the search finds nothing, control jumps past that field's processing. The
freshly constructed `Draft` keeps its constructor default. There is no
required-key check and no error for a missing field.

### Observed: fields read by `patch_from_json`, in order

| Field | Notes |
|-------|-------|
| `id` | string |
| `version` | integer; stored at `Draft+0x78` |
| `new_version` | parsed, compared with `version`; if different, `version` is updated and migration flags at `Draft+0x24`/`+0x28` are set (**inferred**: marks that a version migration is needed) |
| `name` | string |
| `duration` | integer µs |
| `create_time` | integer |
| `update_time` | integer |
| `layout_inited` | bool |
| `canvas_scale` | number |
| `color_space` | integer |
| `mixed_track_mode_on` | bool |
| `render_index_track_mode_on` | bool |
| `free_render_index_mode_on` | bool |
| `fps` | number |
| `is_drop_frame_timecode` | bool |
| `config` | object |
| `canvas_config` | object |
| `tracks` | array |

`attachment_info` and `source` are also consumed in this function, through
helper calls rather than the inline lookup block above.

Real `draft_info.json` files also carry `materials`, `keyframes`,
`keyframe_graph_list`, `relationships`, `platform`, cover fields, etc. Those
are read by the surrounding load/convert path, not by `patch_from_json`
itself.

### Observed: constructor defaults

`lvve::Draft::Draft(string, bool, bool)` @ `0xcc24e4`:

| Member | Default |
|--------|---------|
| `version` (`+0x78`) | `360000` (`0x57E40`) |
| `canvas_scale`-adjacent float (`+0x50`) | `1.0f` |
| fps holder (at nested `+0x130`, value at `+0x48`) | `30.0` (`0x403e000000000000`) |
| path/source strings | `"default"`, `"video"` |

`version = 360000` and `new_version = "159.0.0" … "187.0.0"` were also seen in
all real drafts.

### Observed: load/convert chain

```
lvve::from_json(string, PersistentDraft&, bool)    @ 0x14d15d8
  -> Deserializer::convert_to_runtime_draft        @ 0x3402e00
  -> RuntimeTransfer::TransferDraftFromPersistentDraft @ 0x18455c4
```

`TransferDraftFromPersistentDraft` applies field-by-field setters. It sets
only fields present in the persistent draft; it does not validate a schema.
`DraftUtil::parse_json` @ `0x329bf14` catches only `json::parse` exceptions
(string: `"json::parse failed, exception: {}"`).

### Observed: registration markers are files, not JSON keys

- `findDraftStoreFromPath` @ `0x3274fcc` checks for `draft_content.json`,
  `draft_info.json`, or a `Timelines` entry, and skips directories ending in
  `_cache`.
- `isDraftFoldValid` @ `0x3279700` builds `<folder>/draft_meta_info.json`
  and stats it. Validity is based on that file existing, not on its contents.

### Practical minimum

The prior artifact pass found a registered draft with 12 top-level keys. That
stands: at the loader level nothing else is mandatory.

For a draft that is actually editable/renderable, include at minimum:

```
id, version, new_version, name, duration, create_time, update_time,
fps, canvas_config, tracks, materials
```

and make every `extra_material_ref` point at an object that exists in
`materials`. Whether a dangling ref is tolerated was not tested; **unknown**.

**Go/no-go: GO.** A hand-written draft can load; registration is a file
layout problem, not a schema problem.

---

## 2. Alpha video: sidecar convention, not an in-band channel

### Observed: the convention is `<source path>.alpha.mp4`

`lvve::isHasAlphaFile(string const&)` @ `0x2d4bd4c`:

1. Takes the input path and its length.
2. Builds a new string of `length + 10` bytes.
3. Copies the original path, then appends the literal 10 bytes
   `.alpha.mp4`: read from `0x47ef30a` plus the halfword `0x3470`.
4. Calls `MetadataCache::instance()` and invokes the virtual method at
   vtable `+0x38` with the constructed path.
5. Returns the boolean result.

So the check is: **does the sibling file `<original path>.alpha.mp4`
exist and have media metadata?**

`lvve::toAlphaVideoFile(string const&)` @ `0x2d4ad98` builds the same
string and returns it.

The suffix is appended to the **full filename**, after the existing
extension. `card.mp4` → `card.mp4.alpha.mp4`; `card.mov` →
`card.mov.alpha.mp4`.

### Observed: callers use the sidecar

- `DraftQuery::get_video_metadata_with_alpha` @ `0x2f9126c` calls
  `isHasAlphaFile` (`0x2f912a0`) and `toAlphaVideoFile` (`0x2f912b0`):
  it loads normal metadata, then loads the sidecar's metadata when present.
- `NewVEWrapper::addClip` @ `0x2dd8e78` calls both at `0x2dd8f80` and
  `0x2dd8f98` and wires the sidecar into the clip.
- `lvve::isHasAlphaFile` has 45 BL call sites, mostly `Muxer::create`
  (export path).
- `MaterialEffect::set_transparent_params` @ `0xec651c` stores a path string
  and sets dirty flags. It performs no extension check.

### Observed: `.mov` is not special

`.mov` occurs once in the whole binary's strings, inside a generic media
extension list:

```
.heic .heif .webp .bmp .gif .tiff .avif .mov .webm .mkv .avi .asset
```

That list sits next to AIGC asset suffix-correction strings. There is no
`.mov`-specific transparency branch anywhere in this pass. A `.mov` is
handled as an ordinary video file.

### What this means for animated cards

Render the card as a normal video (`.mp4` is the safe choice), render its
alpha/matte as a second video, and name the second file by appending
`.alpha.mp4` to the **complete first filename**:

```
overlay.mp4
overlay.mp4.alpha.mp4
```

Reference `overlay.mp4` in the draft. Do not try to smuggle alpha inside a
`.mov` and expect CapCut's `lvve` path to find it.

Strings-only hints about the sidecar's expected content (not verified by
execution): `alpha bake input contains no video frame`,
`alpha baked output is missing or empty`, `read gray mask failed`,
`FrameReader returned an invalid RGBA frame`, `create alpha refresh scaler
failed`. These suggest the export pipeline bakes/reads a mask or RGBA
frame, but the exact pixel format the decoder expects is **unknown**.

### Unknowns

- Sidecar pixel format: grayscale matte vs RGBA vs something else.
- Whether the sidecar must have the same duration/frame count as the source.
- Whether still images with alpha (PNG) work as overlay sources. Ordinary
  image materials clearly exist, but alpha behaviour for stills was not
  established in this pass.
- Whether the underlying VESDK decoder can read embedded alpha from `.mov`
  independently of these `lvve` functions. No evidence found either way.

**Go/no-go: GO with `.alpha.mp4` sidecar; NO for `.mov` in-band alpha as the
mechanism.**

---

## 3. 59.94 fps timing: exact rationals and an 800 µs snap

### Observed: frame rate table

`FrameRateId` accepts 1–9. The rational constants are at
`0x4689310`/`0x4689318`/`0x4689320`/`0x4689328`; `SupportedFramerates`
@ `0x2e580e8`; `FrameRateId` constructor @ `0x2e58a4c`.

| ID | fps | Exact value |
|----|-----|-------------|
| 1 | 23.976 | 24000/1001 |
| 2 | 24 | 24/1 |
| 3 | 25 | 25/1 |
| 4 | 29.97 | 30000/1001 |
| 5 | 30 | 30/1 |
| 6 | 50 | 50/1 |
| 7 | **59.94** | **60000/1001** |
| 8 | 60 | 60/1 |
| 9 | 120 | 120/1 |

`FrameRate::FrameInterval` @ `0x2e584e0` computes the frame interval as
`1,000,000 / value` in µs (member at `+0x30` = `1e6 / value`).

### Observed: `createByFps` algorithm

`FrameTimeFactory::createByFps(int64 time_us, double fps)` @ `0x2e592e8`:

```
interval = 1e6 * denominator / numerator          // µs per frame
block    = denominator * 1e6                      // µs per whole block
q        = trunc(time_us / block)
rem      = time_us - q * block
pos      = rem / interval                         // fractional frame index
r        = rint(pos)                              // frinta: nearest, ties away from zero
if abs(pos - r) < 800.0 / interval:
    pos = r
return (q * numerator, pos, interval)             // base frame, position, interval
```

The important consequences:

- At 59.94, `interval = 1,000,000 * 1001 / 60000 = 16683.333… µs`.
- `block = 1001 * 1,000,000 = 1,001,000,000 µs`, which is exactly 60,000
  frames (1001 seconds).
- The snap tolerance is **800 µs** (`800.0 / interval` where interval is in
  µs; the comparison is done in frame units, so the physical window is
  800 µs).
- If the timestamp is not within 800 µs of a frame boundary, the fractional
  position is retained rather than forced to an integer.

### Exact µs examples at 59.94

| Frame | Exact µs | Rounded µs |
|-------|----------|------------|
| 1 | 16683.333… | 16683 |
| 2 | 33366.666… | 33367 |
| 59 | 984316.666… | 984317 |
| 60 | 1001000.0 | 1001000 |
| 60000 | 1001000000.0 | 1001000000 |

### Writer recommendation

Compute segment/caption times from integer frame indices using rational
arithmetic:

```
time_us = round(frame * 1_001_000 / 60)      // nearest integer µs
```

Keep the unrounded rational internally if you need to compare or accumulate;
do not accumulate rounded floats. Emit exact integer µs in the draft. A
timestamp produced this way is already on the intended frame grid, so the
800 µs snap does not need to be mimicked.

### Observed but not fully resolved

`lvve::DraftUpdate::auto_align_draft_frame_time` @ `0x2fb2560` exists. Its
only clear non-inlined caller is `AutoAlignDraftFrameTime`; two apparent
callers inside `MaskUtils::removeVideoMaskShadow` are likely merged-symbol
artifacts. Whether every draft load runs automatic alignment is **unknown**.
Do not rely on CapCut to fix timing after load.

All 18 real drafts are 30 fps, so there is no empirical 59.94 sample.

**Go/no-go: GO.** The model is exact and deterministic; the only trap is
assuming a simple `1e6/59.94` float.

---

## 4. Registration: folder plus meta files, merged at startup

### Observed: discovery and merge

- `DraftStoreManager::isDraftFoldValid` @ `0x3279700`: builds
  `<folder>/draft_meta_info.json` and stats it.
- `findDraftStoreFromPath` @ `0x3274fcc`: checks `draft_content.json`,
  `draft_info.json`, and `Timelines`; skips `_cache` directories.
- `fetchDraftStoreFromRootPath` @ `0x3277f90`: logs
  `"Find {} drafts in {}"` and `"Merge {} drafts to root_meta_info.json"`,
  then calls the merge and `DraftStoreManager::writeToMetaInfoAsync`.
- `readFromMetaInfo` @ `0x326ad4c`: reads the keys `draft_ids` and
  `all_draft_store`.
- The manager constructor builds the `root_meta_info.json` path at
  `0x326a4ac`; `getRootMetaInfoJsonOldVersionFile` @ `0x3279158` returns the
  member at `+0x38`.

### Observed: root_meta_info.json shape

Real file at the drafts root:

```json
{
  "draft_ids": 26,
  "root_path": "<DRAFTS_ROOT>",
  "all_draft_store": [ { ...one entry per draft... } ]
}
```

`all_draft_store` had 18 entries while `draft_ids` was the integer `26`.
The purpose of `draft_ids` is not established; it is read by the manager, but
the merge clearly works from `all_draft_store`. **Inferred**: `draft_ids` is a
store-generation/counter value, not a list of IDs despite the name.

A typical `all_draft_store` entry:

```json
{
  "draft_id": "2816DC34-9965-4A43-B2B2-A3E440F4B338",
  "draft_fold_path": "<DRAFTS_ROOT>/1018",
  "draft_name": "1018",
  "draft_root_path": "<DRAFTS_ROOT>",
  "draft_cover": "<DRAFTS_ROOT>/1018/draft_cover.jpg",
  "draft_json_file": "draft_info.json",
  "draft_new_version": "",
  "draft_timeline_materials_size": 0,
  "draft_type": "",
  "draft_is_ai_shorts": false,
  "draft_is_cloud_temp_draft": false,
  "draft_is_infinite_canvas_draft": false,
  "draft_is_invisible": false,
  "draft_is_pippit_draft": false,
  "draft_is_web_article_video": false,
  "streaming_edit_draft_ready": false,
  "tm_draft_create": 1792319150044788,
  "tm_draft_modified": 1792323449203419,
  "tm_draft_removed": 0,
  "...cloud/pippit fields...": "..."
}
```

`tm_draft_create` / `tm_draft_modified` are **microseconds** since the Unix
epoch (observed values around `1.79e15`). `create_time` inside
`draft_info.json` is in **seconds**.

### Observed: draft_meta_info.json shape

Real files are ~2.6–3.3 KB. Full observed template (paths redacted) is in
Appendix D. The keys that matter for a hand-written draft:

```
draft_fold_path      absolute path to the draft folder
draft_id             UUID from draft_meta_info.json (see quirk below)
draft_name           display name
draft_root_path      absolute path to the drafts root
draft_cover          usually "draft_cover.jpg" relative to the folder
draft_materials      array of {type, value:[...]} buckets
draft_timeline_materials_size_   bytes
draft_new_version    "" in meta files
tm_draft_create      µs since epoch
tm_draft_modified    µs since epoch
...cloud/pippit/enterprise fields, mostly false/empty...
```

`draft_materials` buckets observed: `type` 0 (media), 1, 2 (text/SRT), 3, 6,
7, 8. Empty buckets are `{"type": N, "value": []}`.

### Observed quirk: two different IDs

In the same draft, `draft_info.json`'s `id` and
`draft_meta_info.json`'s `draft_id` were **different UUIDs**. Example
(draft `1017`):

```
draft_info.json      id       = 5D32237D-8712-4745-9ABC-18457198823B
draft_meta_info.json draft_id = 65F4A256-DEF3-450F-A30F-2820EFB71FCF
```

Do not assume they must match. Generate independent UUIDs, or copy a real
draft's convention.

### Registration recipe

1. Close CapCut.
2. Create `<DRAFTS_ROOT>/<project-name>/`.
3. Write `draft_info.json` (the timeline) and `draft_meta_info.json`
   (the index record). Optionally copy `draft_cover.jpg`.
4. Use absolute paths in `draft_fold_path`, `draft_root_path`, and any
   `file_Path` entries.
5. Do not hand-edit `root_meta_info.json`. Start CapCut; the startup scan
   discovers the folder and merges it.
6. Verify the draft appears in the project list.

`draft_info.json` is the current name. `draft_content.json` is accepted by
the discovery check but was not present in the local 9.5.0 drafts; prefer
`draft_info.json` for this version.

**Go/no-go: GO.** Registration is file layout plus a correct path; no manual
root-meta entry is required.

---

## 5. Rewrite on quit: yes, asynchronously

### Observed

- `DraftStore::writeToMetaInfoAsync` @ `0x3247b8c` writes
  `draft_meta_info.json`. 19 call sites.
- `DraftStoreManager::writeToMetaInfoAsync` @ `0x326f280` writes
  `root_meta_info.json`. 24 call sites.
- `DraftStore::close` / `closeAsync` call **both** writers.
- Startup merge also calls the manager writer.

So the app rewrites the per-draft meta file and the root store file on close,
and the root file again during the startup scan/merge.

### Hazard

The writes are **asynchronous** (posted to a message loop). **Inferred**: if
the process is killed during quit, a write may be in flight and the file may
be left stale or truncated. The safe rule is therefore:

- install/remove drafts only while CapCut is fully closed;
- after closing CapCut, give it a moment to flush before editing files;
- never assume `root_meta_info.json` is yours to maintain; treat it as
  CapCut-owned state.

Back up `root_meta_info.json` before any manual experiment. If a draft
disappears from the list, restart CapCut once so the startup scan re-merges
the folder.

**Go/no-go: GO, with CapCut closed.**

---

## Appendix A: function/address table (arm64 thin slice)

| Function | Address |
|----------|---------|
| `lvve::Draft::patch_from_json` | `0xccb4b8` |
| `lvve::Draft::Draft(string,bool,bool)` | `0xcc24e4` |
| `lvve::from_json(string,PersistentDraft&,bool)` | `0x14d15d8` |
| `Deserializer::convert_to_runtime_draft` | `0x3402e00` |
| `RuntimeTransfer::TransferDraftFromPersistentDraft` | `0x18455c4` |
| `DraftUtil::parse_json` | `0x329bf14` |
| `lvve::FrameRate::FrameInterval` | `0x2e584e0` |
| `FrameTimeFactory::createByFps` | `0x2e592e8` |
| `FrameRateId` constructor | `0x2e58a4c` |
| `SupportedFramerates` | `0x2e580e8` |
| `DraftUpdate::auto_align_draft_frame_time` | `0x2fb2560` |
| `lvve::isHasAlphaFile` | `0x2d4bd4c` |
| `lvve::toAlphaVideoFile` | `0x2d4ad98` |
| `DraftQuery::get_video_metadata_with_alpha` | `0x2f9126c` |
| `NewVEWrapper::addClip` | `0x2dd8e78` |
| `MaterialEffect::set_transparent_params` | `0xec651c` |
| `MixedClient::isHasAlphaFile` (Lyra RPC wrapper) | `0x147fe8` |
| `MixedClient::toAlphaVideoFile` (Lyra RPC wrapper) | `0x147dd0` |
| `DraftStoreManager::isDraftFoldValid` | `0x3279700` |
| `findDraftStoreFromPath` | `0x3274fcc` |
| `fetchDraftStoreFromRootPath` | `0x3277f90` |
| `readFromMetaInfo` | `0x326ad4c` |
| `DraftStore::writeToMetaInfoAsync` | `0x3247b8c` |
| `DraftStoreManager::writeToMetaInfoAsync` | `0x326f280` |
| `DraftStore::writeToMetaInfo(json)` | `0x325c570` |
| `DraftStore::close` | ~`0x325644c` |
| `getRootMetaInfoJsonOldVersionFile` | `0x3279158` |
| manager constructor (root path build) | `0x326a4ac` |

Note: `MixedClient::*` are thin Lyra RPC wrappers; the local string-building
implementations are the `lvve::*` functions.

## Appendix B: reproduction

```sh
# 1. Thin the universal binary (Ghidra cannot import it directly)
lipo -thin arm64 \
  /Applications/CapCut.app/Contents/Frameworks/libvideoeditor.dylib \
  -output /tmp/capcut-re/libvideoeditor.arm64.dylib

# 2. Symbols and strings
nm -nm /tmp/capcut-re/libvideoeditor.arm64.dylib > /tmp/capcut-re/syms.txt
strings -a -n 4 /tmp/capcut-re/libvideoeditor.arm64.dylib > /tmp/capcut-re/strings.txt

# 3. Disassemble one function
xcrun llvm-objdump -d --no-show-raw-insn \
  --disassemble-symbols='<mangled symbol>' \
  /tmp/capcut-re/libvideoeditor.arm64.dylib

# 4. Optional: REA + Ghidra snapshot (slow on this binary)
REA_GHIDRA_STARTUP_TIMEOUT_MS=10800000 \
rea analyze /tmp/capcut-re/libvideoeditor.arm64.dylib \
  --snapshot "$HOME/rea-snapshots/capcut-libvideoeditor" \
  --provider ghidra --format json
```

Useful mapping fact for this slice: `__TEXT` vmaddr and fileoff are both
`0xcf20`, so virtual address == file offset for `__text`. The `__text` size
is `0x3c580f4`.

When resolving strings: `objdump` prints the absolute page in `adrp`; add the
`add` immediate to that printed page. When resolving `bl` callers:
`target = TEXT_VA + (offset - TEXT_OFF)`.

## Appendix C: `draft_info.json` observed field list

Real drafts (versions `159.0.0`–`187.0.0`) had these top-level keys:

```
id, version, new_version, name, duration, create_time, update_time,
fps, is_drop_frame_timecode, color_space, config, canvas_config,
tracks, group_container, materials, keyframes, keyframe_graph_list,
platform, last_modified_platform, mutable_config, cover, retouch_cover,
extra_info, relationships, mixed_track_mode_on,
render_index_track_mode_on, free_render_index_mode_on,
static_cover_image_path, source, time_marks
```

All local samples used `version: 360000`, `fps: 30.0`, and string
`new_version` values like `"187.0.0"`.

The minimum observed in a registered draft was 12 top-level keys. The loader
does not enforce more, but the render/edit path expects `tracks`,
`canvas_config`, `fps`, and `duration`.

## Appendix D: `draft_meta_info.json` observed template

Paths replaced with placeholders. This is the shape produced by CapCut 9.5.0;
copy it and change the per-draft values.

```json
{
  "cloud_draft_cover": false,
  "cloud_draft_sync": false,
  "cloud_package_completed_time": "",
  "draft_cloud_capcut_purchase_info": "",
  "draft_cloud_last_action_download": false,
  "draft_cloud_package_type": "",
  "draft_cloud_purchase_info": "",
  "draft_cloud_template_id": "",
  "draft_cloud_tutorial_info": "",
  "draft_cloud_videocut_purchase_info": "",
  "draft_cover": "draft_cover.jpg",
  "draft_deeplink_url": "",
  "draft_enterprise_info": {
    "draft_enterprise_extra": "",
    "draft_enterprise_id": "",
    "draft_enterprise_name": "",
    "enterprise_material": []
  },
  "draft_fold_path": "<DRAFTS_ROOT>/<PROJECT>",
  "draft_id": "<UUID>",
  "draft_is_ae_produce": false,
  "draft_is_ai_packaging_used": false,
  "draft_is_ai_shorts": false,
  "draft_is_ai_translate": false,
  "draft_is_article_video_draft": false,
  "draft_is_cloud_temp_draft": false,
  "draft_is_from_deeplink": "false",
  "draft_is_invisible": false,
  "draft_is_pippit_draft": false,
  "draft_is_web_article_video": false,
  "draft_materials": [
    {"type": 0, "value": []},
    {"type": 1, "value": []},
    {"type": 2, "value": []},
    {"type": 3, "value": []},
    {"type": 6, "value": []},
    {"type": 7, "value": []},
    {"type": 8, "value": []}
  ],
  "draft_materials_copied_info": [],
  "draft_name": "<PROJECT>",
  "draft_need_rename_folder": false,
  "draft_new_version": "",
  "draft_removable_storage_device": "",
  "draft_root_path": "<DRAFTS_ROOT>",
  "draft_segment_extra_info": [],
  "draft_timeline_materials_size_": 0,
  "draft_type": "",
  "draft_web_article_video_enter_from": "",
  "pippit_avatar_url": "",
  "pippit_extra_info": "",
  "pippit_id": "",
  "pippit_user_name": "",
  "tm_draft_cloud_completed": "",
  "tm_draft_cloud_entry_id": -1,
  "tm_draft_cloud_modified": 0,
  "tm_draft_cloud_parent_entry_id": -1,
  "tm_draft_cloud_space_id": -1,
  "tm_draft_cloud_user_id": -1,
  "tm_draft_create": 0,
  "tm_draft_modified": 0,
  "tm_draft_removed": 0,
  "tm_duration": 0
}
```

Media entries inside `draft_materials[].value[]` observed shape:

```json
{
  "ai_group_type": "",
  "create_time": 0,
  "duration": 0,
  "enter_from": 0,
  "extra_info": "",
  "file_Path": "<absolute path>",
  "height": 0,
  "id": "<UUID>",
  "import_time": 0,
  "import_time_ms": 0,
  "item_source": 1,
  "md5": "",
  "metetype": "none",
  "roughcut_time_range": {"duration": -1, "start": -1},
  "sub_time_range": {"duration": -1, "start": -1},
  "type": 0,
  "width": 0
}
```

For video entries, `metetype` was `"video"`, `duration` was in µs, and
`width`/`height` were populated. Note the odd capitalisation `file_Path`.

## Appendix E: unknowns / not proven

1. The exact minimum contents of `draft_meta_info.json`. Only its existence is
   checked for folder validity; the merge reads fields from it, so use the
   observed template.
2. Whether a dangling `extra_material_ref` is tolerated at load or only fails
   at edit/render time.
3. The alpha sidecar's expected pixel format, duration, and frame count.
4. Whether still images with alpha work as overlay sources.
5. Whether the VESDK decoder can read embedded alpha from `.mov`; no `lvve`
   path does.
6. Whether `auto_align_draft_frame_time` runs automatically on every load.
7. The purpose of the integer `draft_ids` in `root_meta_info.json`.
8. Whether an asynchronous meta write can be cut short by a hard quit; the
   asynchronous queue is observed, the failure mode is inferred.
