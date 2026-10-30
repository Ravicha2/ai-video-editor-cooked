#!/usr/bin/env python3
"""Write a CapCut desktop draft for an edit: one video track, one segment per kept span.

    python3 capcut_draft.py demo        self-check, offline
    python3 capcut_draft.py install DRAFT_DIR [--name NAME]

The reader was probed in issue #4 (see docs/adr/0001-capcut-draft-format.md): the draft folder is
plain JSON, every extra_material_ref must resolve, and timing is integer microseconds. 59.94 fps is
60000/1001, so a frame count becomes µs with round(frames * 1_000_000 * 1001 / 60000).

install copies a generated draft into CapCut's project store beside the user's own projects,
writes the draft_meta_info.json the startup scan looks for, and adds the project-store entry.
It never overwrites and refuses while CapCut is running: CapCut rewrites its store on quit.
"""
import argparse
import copy
import json
import math
import os
import shutil
import subprocess
import sys
import time
import uuid
from pathlib import Path

PINNED = "187.0.0"   # the schema version this writer is built and checked against


def drafts_root():
    """Where CapCut keeps its projects, or None when it has never run here."""
    env = os.environ.get("CAPCUT_DRAFT_ROOT")
    if env:
        return Path(env).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Movies/CapCut/User Data/Projects/com.lveditor.draft"
    if sys.platform.startswith("win"):
        base = Path(os.environ.get("LOCALAPPDATA") or Path.home() / "AppData/Local")
        return base / "CapCut/User Data/Projects/com.lveditor.draft"
    return None


def _version(text):
    return tuple(int(part) for part in text.split("."))


def pinned_version(root=None):
    """The new_version to write: PINNED unless the user's own CapCut is newer than this writer.
    Reading their drafts is the only evidence available, and writing a version we have not checked
    risks a draft CapCut refuses to open."""
    root = Path(root) if root is not None else drafts_root()
    seen = []
    if root and root.is_dir():
        for f in root.glob("*/draft_info.json"):
            try:
                v = json.loads(f.read_text(encoding="utf-8")).get("new_version") or ""
            except (OSError, json.JSONDecodeError):
                continue
            if not v:
                continue
            try:
                seen.append((_version(v), v))
            except ValueError:
                raise SystemExit(f"ERROR: {f} has an unreadable new_version {v!r}. "
                                 "Re-check after a CapCut update.")
    newest = max(seen)[1] if seen else PINNED
    if _version(newest) > _version(PINNED):
        raise SystemExit(f"ERROR: your CapCut drafts are schema {newest}; this export is built for "
                         f"{PINNED} and would not write one it cannot vouch for. Re-check after a CapCut update.")
    return PINNED


def capcut_running():
    """True when CapCut is up. Its meta writers are queued on quit, so installing then can be
    overwritten (issue #4)."""
    try:
        if sys.platform == "darwin":
            return subprocess.run(["pgrep", "-x", "CapCut"], stdout=subprocess.DEVNULL,
                                  stderr=subprocess.DEVNULL).returncode == 0
        if sys.platform.startswith("win"):
            out = subprocess.run(["tasklist", "/FI", "IMAGENAME eq CapCut.exe", "/NH"],
                                 capture_output=True, text=True)
            return "CapCut.exe" in out.stdout
    except OSError:
        return False
    return False


def _free_name(root, name):
    """The first free numeric suffix: demo, demo-2, demo-3... (never a second 'demo')."""
    n = 2
    while (root / f"{name}-{n}").exists():
        n += 1
    return f"{name}-{n}"


def _draft_materials(folder, draft, now_s):
    """draft_meta_info's type-0 list (the editor's media panel): one entry per media file, in the
    shape real drafts carry (0320). CapCut indexes only what is listed here, so a draft without
    them opens with an empty import section even though the timeline has its clips (issue #8's
    install check). Paths are relative to the draft folder, as CapCut rewrites them itself."""
    out = []
    for bucket, metetype in (("videos", "video"), ("images", "photo"), ("audios", "music")):
        for m in draft.get("materials", {}).get(bucket) or []:
            p = Path(m.get("path") or "")
            if not p.is_file():
                continue
            try:
                path = "./" + p.relative_to(folder).as_posix()
            except ValueError:
                path = str(p)
            out.append({
                "ai_group_type": "", "create_time": now_s, "duration": m.get("duration", 0),
                "enter_from": 0, "extra_info": p.name, "file_Path": path,
                "height": m.get("height", 0), "id": m["id"], "import_time": now_s,
                "import_time_ms": now_s * 1_000_000, "item_source": 1, "md5": "",
                "metetype": metetype,
                "roughcut_time_range": {"duration": m.get("duration", 0), "start": 0},
                "sub_time_range": {"duration": -1, "start": -1}, "type": 0,
                "width": m.get("width", 0),
            })
    return out


def _meta_info(name, folder, root, draft_id, draft, now_us):
    """draft_meta_info.json in CapCut 9.5's shape (issue #4, Appendix D). The startup scan only
    discovers a folder that has this beside draft_info.json."""
    size = (folder / "draft_info.json").stat().st_size
    cover = "draft_cover.jpg" if (folder / "draft_cover.jpg").is_file() else ""
    now_s = now_us // 1_000_000
    return {
        "cloud_draft_cover": False, "cloud_draft_sync": False, "cloud_package_completed_time": "",
        "draft_cloud_capcut_purchase_info": "", "draft_cloud_last_action_download": False,
        "draft_cloud_package_type": "", "draft_cloud_purchase_info": "", "draft_cloud_template_id": "",
        "draft_cloud_tutorial_info": "", "draft_cloud_videocut_purchase_info": "",
        "draft_cover": cover, "draft_deeplink_url": "",
        "draft_enterprise_info": {"draft_enterprise_extra": "", "draft_enterprise_id": "",
                                  "draft_enterprise_name": "", "enterprise_material": []},
        "draft_fold_path": str(folder), "draft_id": draft_id, "draft_is_ae_produce": False,
        "draft_is_ai_packaging_used": False, "draft_is_ai_shorts": False,
        "draft_is_ai_translate": False, "draft_is_article_video_draft": False,
        "draft_is_cloud_temp_draft": False, "draft_is_from_deeplink": "false",
        "draft_is_invisible": False, "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False,
        "draft_materials": [{"type": 0, "value": _draft_materials(folder, draft, now_s)}]
        + [{"type": t, "value": []} for t in (1, 2, 3, 6, 7, 8)],
        "draft_materials_copied_info": [], "draft_name": name, "draft_need_rename_folder": False,
        "draft_new_version": "", "draft_removable_storage_device": "", "draft_root_path": str(root),
        "draft_segment_extra_info": [], "draft_timeline_materials_size_": size,
        "draft_type": "", "draft_web_article_video_enter_from": "",
        "pippit_avatar_url": "", "pippit_extra_info": "", "pippit_id": "", "pippit_user_name": "",
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1, "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1, "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1, "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": draft.get("duration", 0),
    }


def _store_entry(name, folder, root, draft_id, draft, now_us):
    """One all_draft_store entry, in the shape the installed root_meta_info.json carries."""
    size = (folder / "draft_info.json").stat().st_size
    cover = folder / "draft_cover.jpg"
    return {
        "cloud_draft_cover": False, "cloud_draft_sync": False,
        "draft_cloud_last_action_download": False, "draft_cloud_purchase_info": "",
        "draft_cloud_template_id": "", "draft_cloud_tutorial_info": "",
        "draft_cloud_videocut_purchase_info": "",
        "draft_cover": str(cover) if cover.is_file() else "",
        "draft_fold_path": str(folder), "draft_id": draft_id, "draft_is_ai_shorts": False,
        "draft_is_cloud_temp_draft": False, "draft_is_infinite_canvas_draft": False,
        "draft_is_invisible": False, "draft_is_pippit_draft": False,
        "draft_is_web_article_video": False, "draft_json_file": str(folder / "draft_info.json"),
        "draft_name": name, "draft_new_version": "", "draft_root_path": str(root),
        "draft_timeline_materials_size": size, "draft_type": "",
        "draft_web_article_video_enter_from": "", "pippit_avatar_url": "", "pippit_extra_info": "",
        "pippit_id": "", "pippit_user_name": "", "streaming_edit_draft_ready": False,
        "tm_draft_cloud_completed": "", "tm_draft_cloud_entry_id": -1, "tm_draft_cloud_modified": 0,
        "tm_draft_cloud_parent_entry_id": -1, "tm_draft_cloud_space_id": -1,
        "tm_draft_cloud_user_id": -1, "tm_draft_create": now_us, "tm_draft_modified": now_us,
        "tm_draft_removed": 0, "tm_duration": draft.get("duration", 0),
    }


def _repoint(obj, src, dst):
    """Every absolute path under src now points under dst: media copied with the draft folder must
    follow it, or deleting the export folder would break the installed draft."""
    if isinstance(obj, dict):
        return {k: _repoint(v, src, dst) for k, v in obj.items()}
    if isinstance(obj, list):
        return [_repoint(v, src, dst) for v in obj]
    if isinstance(obj, str) and os.path.isabs(obj):
        p = Path(obj)
        if p == src or src in p.parents:
            return str(dst / p.relative_to(src))
    return obj


def _add_to_root(root, entry):
    """Append the project-store entry, keeping root_meta_info.json.bak first. CapCut owns this file
    and rewrites it on quit; writing it while the app is closed is the only safe moment."""
    p = root / "root_meta_info.json"
    if not p.is_file():
        return False   # the startup scan indexes the folder on the next launch
    shutil.copy2(p, p.with_name(p.name + ".bak"))
    data = json.loads(p.read_text(encoding="utf-8"))
    store = data.setdefault("all_draft_store", [])
    store[:] = [e for e in store if e.get("draft_fold_path") != entry["draft_fold_path"]]
    store.append(entry)
    tmp = p.with_name(p.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, p)
    return True


def install(draft_dir, root=None, name=None, running=None):
    """Copy a generated draft into CapCut's project store and add it to the project list. The
    folder, its draft_meta_info.json and the root entry all point at the installed copy, so the
    export folder can be deleted afterwards. Nothing is overwritten: a name collision stops and
    names a free numeric suffix. Returns the installed folder."""
    src = Path(draft_dir).resolve()
    if not (src / "draft_info.json").is_file():
        sys.exit(f"ERROR: {src} is not a draft folder (no draft_info.json). Export to CapCut first.")
    root = Path(root).resolve() if root is not None else drafts_root()
    if root is None or not root.is_dir():
        sys.exit("ERROR: CapCut's project store was not found. Open CapCut once, close it, "
                 "then install again.")
    if (running or capcut_running)():
        sys.exit("ERROR: CapCut is running. Quit CapCut fully, then install again: it rewrites "
                 "its project store on quit.")
    name = name or src.name
    if not name or name in (".", "..") or Path(name).name != name:
        sys.exit(f"ERROR: {name!r} is not a plain folder name.")
    folder = root / name
    if folder.exists():
        free = _free_name(root, name)
        sys.exit(f"ERROR: a draft named {name!r} is already in the project store. Nothing was "
                 f"overwritten; {free!r} is free: re-run with --name {free}.")
    draft = json.loads((src / "draft_info.json").read_text(encoding="utf-8"))
    shutil.copytree(src, folder)
    draft = _repoint(draft, src, folder)
    if draft.get("name") != name:   # the project list shows the name in the draft
        draft["name"] = name
    (folder / "draft_info.json").write_text(json.dumps(draft, ensure_ascii=False, indent=1),
                                           encoding="utf-8")
    now = int(time.time() * 1_000_000)
    draft_id = _uid()
    (folder / "draft_meta_info.json").write_text(
        json.dumps(_meta_info(name, folder, root, draft_id, draft, now), ensure_ascii=False, indent=1),
        encoding="utf-8")
    _add_to_root(root, _store_entry(name, folder, root, draft_id, draft, now))
    return folder


def _span(edit, start, length):
    """The newest cached encode of source frames start..start+length-1, or None."""
    files = list((Path(edit) / ".segments").glob(f"*/{start}-{start + length}.mp4"))
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _fill_cache(ctx):
    render = Path(__file__).resolve().parents[2] / "cut" / "scripts" / "render.py"
    print(f"filling the segment cache for {len(ctx['segs'])} spans", file=sys.stderr)
    try:
        subprocess.run([sys.executable, str(render), str(ctx["source"]), str(ctx["edit"]), "--segments-only"],
                       check=True)
    except subprocess.CalledProcessError as e:
        sys.exit(f"ERROR: could not fill the segment cache (render.py exited {e.returncode}). "
                 "Re-run the cut, then export again.")


def ensure_pieces(ctx, media, probe=None, fill=None):
    """Copy each kept span out of the pruned `.segments` cache into the draft's media folder as
    seg-01.mp4..., filling the cache with render.py when a span is gone. A draft must survive the
    cache being pruned, so the draft never points at `.segments` itself."""
    media = Path(media)
    media.mkdir(parents=True, exist_ok=True)
    spans = [(source, length) for _, source, length in ctx["segs"]]
    found = [_span(ctx["edit"], s, n) for s, n in spans]
    if None in found:
        (fill or (lambda: _fill_cache(ctx)))()
        found = [_span(ctx["edit"], s, n) for s, n in spans]
    if None in found:
        missing = ", ".join(f"{s}-{s + n}.mp4" for (s, n), p in zip(spans, found) if p is None)
        sys.exit(f"ERROR: the segment cache is missing {missing} even after filling it. "
                 "Re-run the cut, then export again.")
    if probe is None:
        from export_nle import probe as _probe
        probe = _probe
    pieces = []
    for i, src in enumerate(found, 1):
        dst = media / f"seg-{i:02d}{src.suffix}"
        shutil.copy2(src, dst)
        meta = probe(dst)
        pieces.append({"path": dst, "width": meta["width"], "height": meta["height"]})
    keep = {p["path"] for p in pieces}
    for f in media.glob("seg-*.mp4"):   # a re-cut with fewer spans leaves no orphan media behind
        if f not in keep:
            f.unlink()
    return pieces


def _probe_audio(path):
    """(duration seconds, channels) of a media file's first audio stream, or (0, None)."""
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries",
                        "format=duration:stream=codec_type,channels", "-of", "json", str(path)],
                       capture_output=True, text=True)
    if r.returncode:
        return 0.0, None
    j = json.loads(r.stdout or "{}")
    a = next((s for s in j.get("streams", []) if s.get("codec_type") == "audio"), {})
    return float((j.get("format") or {}).get("duration") or 0), a.get("channels")


def _extract_audio(src, dst):
    """Copy the cut's audio into an m4a; re-encode only when the codec cannot be copied."""
    for codec in (["-c:a", "copy"], ["-c:a", "aac", "-b:a", "192k"]):
        if subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-vn", "-map", "0:a:0",
                           *codec, str(dst)]).returncode == 0:
            return
    sys.exit("ERROR: could not take the cut's audio for the draft (ffmpeg failed). "
             "Re-run the cut, then export again.")


def ensure_audio(ctx, media, probe=None, extract=None):
    """The cut's own audio for the draft, or None when the cut has none. The segment cache is
    video-only and the pieces carry no sound; without this the draft opens silent."""
    cut = Path(ctx["edit"]) / "cut.mp4"
    if not cut.is_file():
        print(f"note: no {cut}; the draft will have no cut audio", file=sys.stderr)
        return None
    duration, channels = (probe or _probe_audio)(cut)
    if not channels or duration <= 0:
        return None
    dst = Path(media) / "cut-audio.m4a"
    (extract or _extract_audio)(cut, dst)
    return {"path": dst, "duration": round(duration * 1_000_000)}


def _uid():
    return str(uuid.uuid4()).upper()


def _us(frames, rate):
    """Exact integer microseconds from a frame count: 60000/1001 -> frames * 1_001_000 / 60."""
    return round(frames * 1_000_000 * rate[1] / rate[0])


# The six auxiliary materials every segment carries (observed in CapCut 9.5, issue #4).
AUX = {
    "speeds": lambda i: {"id": i, "type": "speed", "mode": 0, "speed": 1.0, "curve_speed": None},
    "placeholder_infos": lambda i: {"id": i, "type": "placeholder_info", "meta_type": "none", "res_path": "",
                                    "res_text": "", "error_path": "", "error_text": ""},
    "canvases": lambda i: {"id": i, "type": "canvas_color", "color": "", "blur": 0.0, "image": "",
                           "album_image": "", "image_id": "", "image_name": "", "source_platform": 0, "team_id": ""},
    "sound_channel_mappings": lambda i: {"id": i, "type": "", "audio_channel_mapping": 0, "is_config_open": False},
    "material_colors": lambda i: {"id": i, "is_color_clip": False, "is_gradient": False, "solid_color": "",
                                  "gradient_colors": [], "gradient_percents": [], "gradient_angle": 90.0,
                                  "width": 0.0, "height": 0.0},
    "vocal_separations": lambda i: {"id": i, "type": "vocal_separation", "choice": 0, "removed_sounds": [],
                                    "time_range": None, "production_path": "", "final_algorithm": "", "enter_from": ""},
}


def _video_material(uid, path, width, height, duration, kind="video"):
    return {
        # CapCut names a still "photo", not "image": as "image" the clip sat on the timeline and
        # drew nothing (issue #8's install check)
        "id": uid, "unique_id": uuid.uuid4().hex,
        "type": "photo" if kind == "image" else kind, "duration": duration,
        "path": str(Path(path).resolve()), "width": width, "height": height, "has_audio": False,
        "material_name": Path(path).name, "category_name": "local", "crop_ratio": "free", "crop_scale": 1.0,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
                 "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0},
        "source": 0, "source_platform": 0, "check_flag": 62978047, "local_material_id": _uid(),
    }


def _text_material(uid, text):
    """A subtitle material with CapCut's own plain defaults (draft 1017, issue #6): the reader
    was only proven on shapes real drafts carry, and no field here reproduces the plan's styling -
    the user restyles once inside CapCut. content is the JSON string the app parses itself."""
    content = json.dumps({
        "styles": [{"fill": {"alpha": 1.0, "content": {"render_type": "solid",
                                                       "solid": {"alpha": 1.0, "color": [1.0, 1.0, 1.0]}}},
                    "font": {"id": "",
                             "path": "/Applications/CapCut.app/Contents/Resources/Font/SystemFont/en.ttf"},
                    "range": [0, len(text)], "size": 11.0}],
        "text": text,
    }, ensure_ascii=False)
    return {
        "recognize_task_id": "", "id": uid, "name": "", "recognize_text": "", "recognize_model": "",
        "punc_model": "", "type": "subtitle", "base_content": "",
        "words": {"start_time": [], "end_time": [], "text": []},
        "current_words": {"start_time": [], "end_time": [], "text": []},
        "global_alpha": 1.0, "combo_info": {"text_templates": []},
        "caption_template_info": {"resource_id": "", "third_resource_id": "", "resource_name": "",
                                  "category_id": "", "category_name": "", "effect_id": "",
                                  "request_id": "", "path": "", "is_new": False, "source_platform": 0},
        "layer_weight": 1, "letter_spacing": 0.0, "text_curve": None, "text_loop_on_path": False,
        "offset_on_path": 0.0, "enable_path_typesetting": False, "text_exceeds_path_process_type": 0,
        "text_typesetting_paths": None, "text_typesetting_paths_file": "", "text_typesetting_path_index": 0,
        "line_spacing": 0.02, "has_shadow": False, "shadow_color": "", "shadow_alpha": 0.9,
        "shadow_smoothing": 0.45, "shadow_distance": 5.0, "shadow_point": {"x": 0.6363961030678928,
                                                                          "y": -0.6363961030678927},
        "shadow_angle": -45.0, "shadow_thickness_projection_enable": False,
        "shadow_thickness_projection_angle": 0.0, "shadow_thickness_projection_distance": 0.0,
        "border_alpha": 1.0, "border_color": "", "border_width": 0.08, "border_mode": 0, "style_name": "",
        "text_color": "#FFFFFF", "text_alpha": 1.0, "font_name": "", "font_title": "none",
        "font_size": 11.0, "font_path": "", "font_id": "", "font_resource_id": "", "initial_scale": 1.0,
        "font_url": "", "typesetting": 0, "alignment": 1, "line_feed": 1,
        "use_effect_default_color": True, "is_rich_text": False, "shape_clip_x": False,
        "shape_clip_y": False, "ktv_color": "", "text_to_audio_ids": [], "bold_width": 0.0,
        "italic_degree": 0, "underline": False, "underline_width": 0.05, "underline_offset": 0.22,
        "sub_type": 0, "check_flag": 7, "text_size": 30, "font_category_name": "",
        "font_source_platform": 0, "font_third_resource_id": "", "font_category_id": "", "add_type": 2,
        "operation_type": 0, "recognize_type": 0, "fonts": [], "background_color": "",
        "background_alpha": 1.0, "background_style": 0, "background_round_radius": 0.0,
        "background_width": 0.14, "background_height": 0.14, "background_vertical_offset": 0.0,
        "background_horizontal_offset": 0.0, "background_fill": "", "single_char_bg_enable": False,
        "single_char_bg_color": "", "single_char_bg_alpha": 1.0, "single_char_bg_round_radius": 0.3,
        "single_char_bg_width": 0.0, "single_char_bg_height": 0.0, "single_char_bg_vertical_offset": 0.0,
        "single_char_bg_horizontal_offset": 0.0, "font_team_id": "", "tts_auto_update": False,
        "text_preset_resource_id": "", "group_id": "", "preset_id": "", "preset_name": "",
        "preset_category": "", "preset_category_id": "", "preset_index": 0,
        "preset_has_set_alignment": False, "force_apply_line_max_width": False, "language": "",
        "relevance_segment": [], "original_size": [], "fixed_width": -1.0, "fixed_height": -1.0,
        "line_max_width": 0.82, "oneline_cutoff": False, "cutoff_postfix": "",
        "subtitle_template_original_fontsize": 0.0, "subtitle_keywords": None, "inner_padding": -1.0,
        "multi_language_current": "none", "source_from": "", "is_lyric_effect": False,
        "lyric_group_id": "", "lyrics_template": {"resource_id": "", "resource_name": "", "panel": "",
                                                  "effect_id": "", "path": "", "category_id": "",
                                                  "category_name": "", "request_id": ""},
        "is_batch_replace": False, "is_words_linear": False, "ssml_content": "",
        "subtitle_keywords_config": None, "sub_template_id": -1, "translate_original_text": "",
        "content": content,
    }


def _text_segment(seg_uid, mid, anim_ref, start_us, end_us, y, x=0.0):
    """One caption page or label as a text segment (draft 1017): no source times, one animations
    ref, and a position in half-canvas units where negative y is down: the plan's `y_pct` from the
    top maps to `(0.5 - y_pct/100) * 2`, so CapCut's own bottom captions (y -0.8) sit at 90% of the
    frame. `x_pct` maps the same way, as a centre."""
    return {
        "id": seg_uid, "source_timerange": None,
        "target_timerange": {"start": start_us, "duration": end_us - start_us},
        "render_timerange": {"start": 0, "duration": 0}, "desc": "", "state": 0, "speed": 1.0,
        "is_loop": False, "is_tone_modify": False, "reverse": False, "intensifies_audio": False,
        "cartoon": False, "volume": 1.0, "last_nonzero_volume": 1.0,
        "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": x, "y": y},
                 "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
        "uniform_scale": {"on": True, "value": 1.0}, "material_id": mid,
        "extra_material_refs": [anim_ref], "render_index": 14000, "keyframe_refs": [],
        "enable_lut": False, "enable_adjust": False, "enable_hsl": False, "visible": True,
        "group_id": "", "enable_color_curves": True, "enable_hsl_curves": True, "track_render_index": 1,
        "hdr_settings": None, "enable_color_wheels": True, "track_attribute": 0,
        "is_placeholder": False, "template_id": "", "enable_smart_color_adjust": False,
        "template_scene": "default", "common_keyframes": [], "caption_info": None,
        "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0,
                              "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
        "enable_color_match_adjust": False, "enable_color_correct_adjust": False,
        "enable_adjust_mask": False, "raw_segment_id": "", "lyric_keyframes": None,
        "enable_video_mask": True, "digital_human_template_group_id": "", "color_correct_alg_result": "",
        "source": "segmentsourcenormal", "enable_mask_stroke": False, "enable_mask_shadow": False,
        "enable_color_adjust_pro": False,
    }


def _caption_y(ctx):
    """Vertical centre of the captions, in CapCut's half-canvas units, from the plan's `y_pct`
    (percent of the frame from the top). CapCut maps x, y in half-width/height units with y
    positive up: CapCut's own bottom captions sit at y -0.8 = the 90%-line in draft 1017."""
    style = ctx["plan"].get("captions", {}).get("style") or {}
    return (0.5 - style.get("y_pct", 90) / 100) * 2


def _card_tracks(cards, rate, canvas, materials):
    """Cards as overlay video tracks, one per lane (a card per track position, so overlaps stay
    legal), above the main track: flag 1, render_index 14000. An animated card is its ProRes .mov
    with a grayscale matte beside it named <file>.mov.alpha.mp4: CapCut reads alpha only through
    that sidecar (issue #4's decompile); a still card is its .png as an image material. A card that
    renders nothing stays a hand step and is not in the draft. The media lives in the draft folder;
    the copies are made by the export."""
    W, H = canvas
    tracks = []
    kept = [c for c in (cards or []) if c.get("path") and c.get("kind") in ("video", "image")]
    kept.sort(key=lambda c: (c["lane"], c["start_f"]))
    for lane in sorted({c["lane"] for c in kept}):
        segments = []
        for c in kept:
            if c["lane"] != lane:
                continue
            start_us, end_us = _us(c["start_f"], rate), _us(c["start_f"] + c["len_f"], rate)
            mid = _uid()
            bucket = "videos" if c["kind"] == "video" else "images"
            materials[bucket].append(_video_material(mid, c["path"], c["rect"][2], c["rect"][3],
                                                     end_us - start_us, kind=c["kind"]))
            refs = []
            for b, make in AUX.items():
                ref = _uid()
                materials[b].append(make(ref))
                refs.append(ref)
            segments.append({
                "id": _uid(), "source_timerange": {"start": 0, "duration": end_us - start_us},
                "target_timerange": {"start": start_us, "duration": end_us - start_us},
                "render_timerange": {"start": 0, "duration": 0}, "speed": 1.0, "volume": 1.0,
                "material_id": mid, "extra_material_refs": refs,
                # 14000: above the main track (0), where every track's own render sits
                "render_index": 14000, "visible": True,
                "clip": {**REST_CLIP, "scale": _card_scale(c["rect"], W, H),
                         "transform": _card_transform(c["rect"], W, H)},
                "uniform_scale": {"on": True, "value": 1.0}, "keyframe_refs": [], "enable_lut": False,
                "enable_adjust": False, "group_id": "", "track_render_index": 1,
                "is_placeholder": False, "template_id": "", "source": "segmentsourcenormal",
            })
        tracks.append({"id": _uid(), "type": "video", "segments": segments, "flag": 1,
                       "attribute": 0, "name": "", "is_default_name": True})
    return tracks


def _card_transform(rect, W, H):
    """The card's centre in half-canvas units: x right, y up: the caption sign convention, so
    the plan's top-left-percent rect maps like `y_pct` does."""
    x, y, w, h = rect
    return {"x": ((x + w / 2) / W - 0.5) * 2, "y": (0.5 - (y + h / 2) / H) * 2}


def _card_scale(rect, W, H):
    """The scale that shows a box-sized material at its box size. CapCut's 1.0 inserts a clip
    fitted inside the canvas (contain): displayed = box * min(W/w, H/h), so s = 1 / that. A
    full-frame card lands on scale 1.0. Unproven against a real overlay draft; the CapCut smoke
    test decides, and the fallback is the .png still (CAPCUT.md keeps the hand tables)."""
    w, h = rect[2], rect[3]
    s = max(w / W, h / H)
    return {"x": s, "y": s}


REST_CLIP = {"rotation": 0.0, "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0}


def _audio_material(uid, path, duration):
    """A local audio material, in the shape real drafts carry for one (draft 0315 (2)): local
    music lands as type extract_music, whatever the file."""
    return {
        "id": uid, "duration": duration, "path": str(Path(path).resolve()),
        "name": Path(path).name, "type": "extract_music", "category_name": "local",
        "check_flag": 1, "music_id": uuid.uuid4().hex, "source_platform": 0,
        "local_material_id": uuid.uuid4().hex, "wave_points": [], "is_ugc": False,
        "copyright_limit_type": "none",
    }


def _audio_refs(materials):
    """The six refs an audio segment carries (draft 0315 (2)): speed, placeholder, fade, beats,
    channel mapping, vocal separation."""
    fade, beat = _uid(), _uid()
    materials["audio_fades"].append({"id": fade, "type": "audio_fade", "fade_type": 0,
                                     "fade_in_duration": 0, "fade_out_duration": 0})
    materials["beats"].append({"id": beat, "type": "beats", "mode": 404, "gear": 404,
                               "gear_count": 0, "enable_ai_beats": False, "user_beats": [],
                               "user_delete_ai_beats": None,
                               "ai_beats": {"beat_speed_infos": [], "beats_path": "",
                                            "beats_url": "", "melody_path": "",
                                            "melody_percents": [0.0], "melody_url": ""}})
    refs = [fade, beat]
    for b in ("speeds", "placeholder_infos", "sound_channel_mappings", "vocal_separations"):
        ref = _uid()
        materials[b].append(AUX[b](ref))
        refs.append(ref)
    return refs


def _audio_segment(mid, refs, start_us, end_us):
    return {
        "id": _uid(), "source_timerange": {"start": 0, "duration": end_us - start_us},
        "target_timerange": {"start": start_us, "duration": end_us - start_us},
        "render_timerange": {"start": 0, "duration": 0}, "speed": 1.0, "volume": 1.0,
        "last_nonzero_volume": 1.0, "material_id": mid, "extra_material_refs": refs,
        "render_index": 0, "keyframe_refs": [], "visible": True, "clip": None,
        "uniform_scale": None, "group_id": "", "track_render_index": 1,
        "is_placeholder": False, "template_id": "", "source": "segmentsourcenormal",
        "state": 0, "desc": "", "is_loop": False, "is_tone_modify": False, "reverse": False,
        "intensifies_audio": False, "cartoon": False, "caption_info": None,
        "enable_lut": False, "enable_adjust": False, "enable_hsl": False,
        "enable_color_curves": True, "enable_hsl_curves": True,
        "hdr_settings": None, "enable_color_wheels": True, "track_attribute": 0,
        "enable_smart_color_adjust": False, "template_scene": "default", "common_keyframes": [],
        "responsive_layout": {"enable": False, "target_follow": "", "size_layout": 0,
                              "horizontal_pos_layout": 0, "vertical_pos_layout": 0},
        "enable_color_match_adjust": False, "enable_color_correct_adjust": False,
        "enable_adjust_mask": False, "raw_segment_id": "", "lyric_keyframes": None,
        "enable_video_mask": True, "digital_human_template_group_id": "", "color_correct_alg_result": "",
        "enable_mask_stroke": False, "enable_mask_shadow": False,
    }


def _cut_audio_track(audio, materials):
    """The cut's own audio as one file on its own track. The segment cache is video-only (render.py
    encodes spans with -an) and cut.mp4's audio is mixed from the same spans with the same joins
    and 8 ms fades, so one segment at time 0 stays in sync with the pieces. Without this the draft
    opens silent: the speech is in neither the pieces nor the cues."""
    mid = _uid()
    materials["audios"].append(_audio_material(mid, audio["path"], audio["duration"]))
    return [{"id": _uid(), "type": "audio",
             "segments": [_audio_segment(mid, _audio_refs(materials), 0, audio["duration"])],
             "flag": 0, "attribute": 0, "name": "", "is_default_name": True}]


def _cues_track(cues, rate, materials):
    """Sound cues as one audio track (draft 0315 (2)'s shape): a segment per cue with six refs:
    gaps allowed between them, volume 1.0 because the level is already set in the rendered media
    (sfx.py). The media lives in the draft folder; the copies are made by the export."""
    segments = []
    for s in cues or []:
        start_us, end_us = _us(s["start_f"], rate), _us(s["start_f"] + s["len_f"], rate)
        mid = _uid()
        materials["audios"].append(_audio_material(mid, s["path"], end_us - start_us))
        segments.append(_audio_segment(mid, _audio_refs(materials), start_us, end_us))
    return [{"id": _uid(), "type": "audio", "segments": segments, "flag": 0, "attribute": 0,
             "name": "", "is_default_name": True}]


def _text_track(caps, rate, y):
    """The caption pages as one text track; the segment times are the pages' own frames, quantised
    the same way the video track quantises spans (boundaries, not durations)."""
    anim = {"id": _uid(), "type": "sticker_animation", "animations": [], "multi_language_current": "none"}
    materials, segments = [], []
    for c in caps:
        mid = _uid()
        materials.append(_text_material(mid, c["text"]))
        segments.append(_text_segment(_uid(), mid, anim["id"],
                                      _us(c["start_f"], rate), _us(c["start_f"] + c["len_f"], rate), y))
    track = {"id": _uid(), "type": "text", "segments": segments, "flag": 1, "attribute": 0,
             "name": "", "is_default_name": True}
    return track, {"texts": materials, "material_animations": [anim]}


def _label_items(x):
    """The segments one plan.json "texts" entry makes: a title or cta as one text segment (a cta's
    label on its first line), a user-typed label as it was typed, a list as one per line, numbered
    and held to the list's end. Seconds on the cut; x and y are the box's centre in % of the frame,
    since the plan gives title and list boxes by their top edge and a text segment is placed by its
    centre. A `stamp` is a drawn X with no words: no native text segment can carry it, so it is
    skipped."""
    size = x.get("size_pct") or 2.0
    if x.get("kind") == "list":
        out = []
        for j, it in enumerate(x.get("items") or []):
            if not it.get("text"):
                continue
            at = max(x.get("start", 0), it.get("at", x.get("start", 0)))
            w = (3 + len(it["text"])) * 0.55 * size * 16 / 9   # as plan.py measures
            out.append((f"{j + 1}. {it['text']}", at, x.get("end", at), x.get("x_pct", 0) + w / 2,
                        x.get("y_pct", 50) + (j + 0.5) * 1.3 * size))
        return out
    if x.get("kind") == "label" and x.get("text"):
        # the user's typed text (texts.json, plan.py typed_texts): x_pct/y_pct are already its centre,
        # as Remotion places it. Its plain/outline/box look is not carried - a native text takes
        # CapCut's own styling, one applied to all of them.
        return [(x["text"], x.get("start", 0), x.get("end", 0), x.get("x_pct", 50), x.get("y_pct", 50))]
    if x.get("kind") in ("title", "cta") and x.get("text"):
        text = f"{x['label']}\n{x['text']}" if x.get("label") else x["text"]
        # the box height as plan.py's title_bottom() measures it (74% wide, bold, 1.15 em a line,
        # plus 0.5 em of padding): half of it puts the text segment's centre inside the box
        per = max(8, int(74 * 1080 / 100 / (0.55 * size / 100 * 1920)))
        n = sum(max(1, math.ceil(len(ln) / per)) for ln in text.split("\n"))
        return [(text, x.get("start", 0), x.get("end", 0), 50,
                 x.get("y_pct", 50) + (n * 1.15 + 0.5) * size / 2)]
    return []


def _labels_tracks(labels, rate):
    """plan.json "texts" - the words besides the captions - as text tracks over the cards, one
    track per item because a list's lines, or a cta over a title, overlap and one text track may
    not. Times are seconds on the cut; x and y map like a caption's position."""
    tracks, texts, anims = [], [], []
    for x in labels or []:
        for text, start, end, x_pct, y_pct in _label_items(x):
            if end <= start:
                continue
            # the plan's seconds to exact µs: _us takes frames
            start_us, end_us = _us(start * rate[0] / rate[1], rate), _us(end * rate[0] / rate[1], rate)
            anim = {"id": _uid(), "type": "sticker_animation", "animations": [],
                    "multi_language_current": "none"}
            mid = _uid()
            texts.append(_text_material(mid, text))
            anims.append(anim)
            tracks.append({"id": _uid(), "type": "text", "flag": 1, "attribute": 0, "name": "",
                           "is_default_name": True, "segments": [
                               _text_segment(_uid(), mid, anim["id"], start_us, end_us,
                                             (0.5 - y_pct / 100) * 2, (x_pct / 100 - 0.5) * 2)]})
    return tracks, {"texts": texts, "material_animations": anims}


def _merge(*parts):
    """Materials buckets from several builders, concatenated: two builders may fill the same one."""
    out = {}
    for part in parts:
        for k, v in part.items():
            out.setdefault(k, []).extend(v)
    return out


def build_draft(ctx, pieces, version=PINNED, caps=None, cards=None, cues=None, audio=None,
                labels=None):
    """The draft_info.json object: one video track, one segment per piece, and when `caps` is given
    one text track of caption pages; when `cards` is given, one overlay video track per used lane;
    when `cues` is given one audio track (issue #7); when `audio` is given, the cut's own audio as
    one more track (a draft without it opens silent); when `labels` is given (the plan's "texts"), a
    text track per title, cta and list line. `pieces` are dicts with path, width and height (from
    ensure_pieces); ctx["segs"] gives each span's timeline start and length."""
    rate = ctx["rate"]
    assert len(pieces) == len(ctx["segs"]), f"{len(pieces)} pieces for {len(ctx['segs'])} kept spans"
    materials = {bucket: [] for bucket in AUX}
    materials["videos"] = []
    materials["images"] = []
    materials["audios"] = []
    materials["audio_fades"] = []
    materials["beats"] = []
    text_track, text_materials = _text_track(caps, rate, _caption_y(ctx)) if caps else (None, {})
    label_tracks, label_materials = _labels_tracks(labels, rate)
    card_tracks = _card_tracks(cards, rate, (ctx["plan"]["width"], ctx["plan"]["height"]), materials)
    audio_tracks = _cut_audio_track(audio, materials) if audio else []
    cue_tracks = _cues_track(cues, rate, materials) if cues else []
    segments, frame = [], 0
    for (_, _, length), piece in zip(ctx["segs"], pieces):
        # Quantise the two frame boundaries, not each duration: rounding every span on its own drifts
        # by 1 µs per join at 59.94 (frames 1 and 1 sum to 33366, frame 2 is 33367).
        start_us, end_us = _us(frame, rate), _us(frame + length, rate)
        duration = end_us - start_us
        mid = _uid()
        materials["videos"].append(_video_material(mid, piece["path"], piece["width"], piece["height"], duration))
        refs = []
        for bucket, make in AUX.items():
            ref = _uid()
            materials[bucket].append(make(ref))
            refs.append(ref)
        segments.append({
            "id": _uid(), "source_timerange": {"start": 0, "duration": duration},
            "target_timerange": {"start": start_us, "duration": duration},
            "render_timerange": {"start": 0, "duration": 0}, "speed": 1.0, "volume": 1.0,
            "material_id": mid, "extra_material_refs": refs, "render_index": 0, "visible": True,
            "clip": {"scale": {"x": 1.0, "y": 1.0}, "rotation": 0.0, "transform": {"x": 0.0, "y": 0.0},
                     "flip": {"vertical": False, "horizontal": False}, "alpha": 1.0},
            "uniform_scale": {"on": True, "value": 1.0}, "keyframe_refs": [], "enable_lut": True,
            "enable_adjust": True, "group_id": "", "track_render_index": 0, "is_placeholder": False,
            "template_id": "", "source": "segmentsourcenormal",
        })
        frame += length
    timeline = _us(frame, rate)
    track = {"id": _uid(), "type": "video", "segments": segments, "flag": 0, "attribute": 0,
             "name": "", "is_default_name": True}
    # a card whose tail (or a cue, or the cut audio's rounded length) runs past the cut's last
    # frame stretches the timeline
    timeline = max([timeline] + [s["target_timerange"]["start"] + s["target_timerange"]["duration"]
                                 for tr in card_tracks + audio_tracks + cue_tracks + label_tracks
                                 for s in tr["segments"]])
    now = int(time.time())
    platform = {"os": "mac" if sys.platform == "darwin" else
                ("windows" if sys.platform.startswith("win") else sys.platform),
                "app_id": 359289, "app_version": "9.5.0", "app_source": "cc"}
    return {
        "id": _uid(), "version": 360000, "new_version": version, "name": ctx["name"],
        "duration": timeline, "create_time": now, "update_time": now, "fps": ctx["fps"],
        "is_drop_frame_timecode": False, "color_space": 0,
        "config": {"video_mute": False, "record_audio_last_index": 1, "extract_audio_last_index": 1,
                   "original_sound_last_index": 1, "subtitle_sync": True, "lyrics_sync": True,
                   "material_save_mode": 0, "maintrack_adsorb": True, "attachment_info": [],
                   "multi_language_mode": "none", "use_float_render": False, "hdr_vivid": False},
        "canvas_config": {"ratio": "original", "width": ctx["plan"]["width"],
                          "height": ctx["plan"]["height"], "background": None},
        "tracks": [track] + card_tracks + audio_tracks + cue_tracks + label_tracks
                  + ([text_track] if text_track else []),
        "materials": _merge(materials, text_materials, label_materials),
        "relationships": [], "platform": platform,
        "last_modified_platform": platform, "mixed_track_mode_on": False,
        "render_index_track_mode_on": True, "free_render_index_mode_on": False,
        "source": "default", "path": "", "draft_type": "video",
    }


def check_draft(draft, root):
    """Structural self-test, run before writing: every ref resolves, times are monotone, the segments
    add up to the draft's duration, and no material path leaves the export folder."""
    root = Path(root).resolve()
    buckets = draft["materials"]
    ids = {m["id"] for bucket in buckets.values() for m in bucket}
    total = 0
    main_seen = False
    for track in draft["tracks"]:
        t = 0
        # the first video track is the main one: contiguous, anchored at 0. Overlay tracks and the
        # audio track may gap (cards and cues sit at their own times) but may not overlap.
        gappy = (track["type"] == "video" and main_seen) or track["type"] == "audio"
        if track["type"] == "video" and not main_seen:
            main_seen = True
        for seg in track["segments"]:
            assert seg["material_id"] in ids, f"dangling material_id {seg['material_id']}"
            for ref in seg["extra_material_refs"]:
                assert ref in ids, f"dangling extra_material_ref {ref}"
            target = seg["target_timerange"]
            if seg.get("source_timerange") is None:   # a text segment: no source, may gap but not overlap
                assert target["duration"] > 0, f"bad target duration {target}"
                assert target["start"] >= t, f"text times are not monotone: {target['start']} < {t}"
                t = target["start"] + target["duration"]
                continue
            source = seg["source_timerange"]
            assert source["start"] >= 0 and source["duration"] > 0, f"bad source times {source}"
            assert target["duration"] > 0, f"bad target duration {target}"
            if gappy:
                assert target["start"] >= t, f"track times overlap: {target['start']} < {t}"
                m = next(mm for bucket in buckets.values() for mm in bucket
                         if mm["id"] == seg["material_id"])
                # an animated card is a .mov with its grayscale matte beside it (issue #4); a still
                # card is a .png, which needs no matte
                if m["type"] == "video":
                    matte = Path(str(m["path"]) + ".alpha.mp4")
                    assert matte.is_file(), f"no alpha matte beside the card: {matte}"
            else:
                assert target["start"] == t, f"target times are not monotone: {target['start']} != {t}"
            t = target["start"] + target["duration"]
        total = max(total, t)
    for m in draft["materials"].get("texts", []):
        try:
            content = json.loads(m["content"])
        except (json.JSONDecodeError, TypeError) as e:
            raise AssertionError(f"unreadable text material content: {e}") from e
        assert content.get("text"), "a text material without text"
    assert total == draft["duration"], f"segments add to {total} µs, draft says {draft['duration']}"
    for bucket in buckets.values():
        for m in bucket:
            p = m.get("path")
            if p:
                q = Path(p).resolve()
                assert q == root or root in q.parents, f"{p} escapes the export folder {root}"


def demo():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        # no drafts on this machine yet: the pinned schema
        assert pinned_version(root) == PINNED
        # a draft from an older CapCut: CapCut migrates it up, so the pinned schema still works
        (root / "a").mkdir()
        (root / "a" / "draft_info.json").write_text(json.dumps({"new_version": "175.0.0"}), encoding="utf-8")
        assert pinned_version(root) == PINNED
        # a newer schema: refuse rather than write a draft we cannot vouch for
        (root / "b").mkdir()
        (root / "b" / "draft_info.json").write_text(json.dumps({"new_version": "200.0.0"}), encoding="utf-8")
        try:
            pinned_version(root)
        except SystemExit as e:
            assert "CapCut update" in str(e), e
        else:
            raise AssertionError("a newer draft schema must be refused")

        # --- the draft: one video track, one segment per piece, exact integer µs at 59.94 ---
        export = Path(td) / "export"
        media = export / "capcut" / "demo" / "media"
        media.mkdir(parents=True)
        ctx = {"name": "demo", "fps": 59.94, "rate": (60000, 1001),
               "segs": [(0, 0, 60), (60, 120, 30)], "total_f": 90,
               "plan": {"width": 1080, "height": 1920}}
        pieces = [{"path": media / f"seg-{i:02d}.mp4", "width": 832, "height": 1040} for i in (1, 2)]
        d = build_draft(ctx, pieces)
        assert d["version"] == 360000 and d["new_version"] == PINNED and d["fps"] == 59.94
        assert (d["canvas_config"]["width"], d["canvas_config"]["height"]) == (1080, 1920)
        assert d["duration"] == 1_501_500   # 90 frames
        assert len(d["tracks"]) == 1 and d["tracks"][0]["type"] == "video"
        segs = d["tracks"][0]["segments"]
        assert [(s["target_timerange"]["start"], s["target_timerange"]["duration"]) for s in segs] == \
            [(0, 1_001_000), (1_001_000, 500_500)]
        assert [(s["source_timerange"]["start"], s["source_timerange"]["duration"]) for s in segs] == \
            [(0, 1_001_000), (0, 500_500)]
        assert all(len(s["extra_material_refs"]) == 6 for s in segs)
        check_draft(d, export)

        # --- captions: one native text segment per caption page, times from the same frame maths ---
        caps = [{"start_f": 0, "len_f": 60, "text": "หนึ่ง สอง"},
                {"start_f": 60, "len_f": 30, "text": "สาม"}]
        d = build_draft(ctx, pieces, caps=caps)
        tt = d["tracks"][-1]
        assert tt["type"] == "text"
        ts = tt["segments"]
        assert [s["target_timerange"] for s in ts] == \
            [{"start": 0, "duration": 1_001_000}, {"start": 1_001_000, "duration": 500_500}]
        assert len(ts) == len(caps) == len(d["materials"]["texts"])
        # the shape is draft 1017's: an animations ref, no source times, the page's own text
        assert all(len(s["extra_material_refs"]) == 1 for s in ts)
        assert all(s["source_timerange"] is None and s["render_index"] == 14000 for s in ts)
        assert all(json.loads(m["content"])["text"] == c["text"]
                   for m, c in zip(d["materials"]["texts"], caps))
        assert json.loads(d["materials"]["texts"][0]["content"])["styles"][0]["range"] == [0, len(caps[0]["text"])]
        # the plan's caption line, on the plan-drawn 70%-line: half-canvas, negative y down
        assert ts[0]["clip"]["transform"]["y"] == (0.5 - 90 / 100) * 2
        d70 = build_draft({**ctx, "plan": {"width": 1080, "height": 1920,
                                           "captions": {"style": {"y_pct": 70}}}}, pieces, caps=caps)
        assert d70["tracks"][-1]["segments"][0]["clip"]["transform"]["y"] == (0.5 - 70 / 100) * 2
        check_draft(d, export)

        # --- labels: the plan's "texts" (titles, cta, list lines), each on its own track ---
        labels = [{"kind": "title", "text": "Essential\nLine Classic", "start": 0.0, "end": 1.5,
                   "y_pct": 62.6, "size_pct": 3.0},
                  {"kind": "cta", "text": "เม้น", "label": "รุ่นไหนต่อ", "start": 1.0, "end": 1.5,
                   "y_pct": 16.1, "size_pct": 5.2},
                  {"kind": "list", "items": [{"text": "หนึ่ง", "at": 0.0}, {"text": "สอง", "at": 0.5}],
                   "start": 0.0, "end": 1.5, "x_pct": 14.0, "y_pct": 40.0, "size_pct": 2.0},
                  {"kind": "stamp", "start": 0.0, "end": 1.0, "box": [0, 0, 100, 100]},
                  # the user's own typed text (texts.json): already centred on x_pct/y_pct
                  {"kind": "label", "text": "wait for it", "start": 0.5, "end": 1.0,
                   "style": "box", "x_pct": 40.0, "y_pct": 30.0, "size_pct": 6.0}]
        d = build_draft(ctx, pieces, caps=caps, labels=labels)
        lt = [t for t in d["tracks"] if t["type"] == "text"][:-1]   # the caption track comes last
        assert len(lt) == 5   # title, cta, two list lines, the typed label; the stamp has no words and is skipped
        assert all(len(t["segments"]) == 1 for t in lt)
        assert len(d["materials"]["texts"]) == len(caps) + 5
        assert len(d["materials"]["material_animations"]) == 1 + 5   # one shared for all captions
        contents = [json.loads(m["content"])["text"] for m in d["materials"]["texts"]]
        assert "รุ่นไหนต่อ\nเม้น" in contents and "1. หนึ่ง" in contents and "2. สอง" in contents
        assert "Essential\nLine Classic" in contents and "wait for it" in contents
        lab = lt[4]["segments"][0]
        assert lab["target_timerange"] == {"start": 500_000, "duration": 500_000}
        assert lab["clip"]["transform"] == {"x": (40 / 100 - 0.5) * 2, "y": (0.5 - 30 / 100) * 2}
        # plan seconds -> exact µs (1.5 s is 1_500_000, not 1_501_500: no frame drift), and the
        # plan's y_pct in CapCut's half-canvas units
        assert lt[0]["segments"][0]["target_timerange"] == {"start": 0, "duration": 1_500_000}
        # a title's y_pct is its box's top edge: the segment sits at the box's centre (2 lines,
        # 3% type, so (2 * 1.15 + 0.5) * 3 = 8.4% tall)
        assert lt[0]["segments"][0]["clip"]["transform"]["y"] == (0.5 - (62.6 + 8.4 / 2) / 100) * 2
        assert lt[2]["segments"][0]["target_timerange"] == {"start": 0, "duration": 1_500_000}
        assert lt[3]["segments"][0]["target_timerange"]["start"] == 500_000   # 0.5 s
        check_draft(d, export)

        # --- cards: one overlay track per lane above the main one, each card at its rect ---
        # A card that did not render (kind missing) stays a hand step and is not in the draft.
        cards = [{"i": 1, "kind": "video", "path": media / "card-01.mov", "start_f": 0, "len_f": 60,
                  "rect": [100, 200, 800, 400], "lane": 1, "name": "hook"},
                 {"i": 2, "kind": "image", "path": media / "card-02.png", "start_f": 30, "len_f": 30,
                  "rect": [140, 760, 800, 400], "lane": 2, "name": "race"},
                 {"i": 3, "kind": "missing", "start_f": 0, "len_f": 10,
                  "rect": [0, 0, 100, 100], "lane": 1, "name": "ghost"}]
        (media / "card-01.mov").write_bytes(b"mov")
        (media / "card-01.mov.alpha.mp4").write_bytes(b"matte")
        (media / "card-02.png").write_bytes(b"png")
        d = build_draft(ctx, pieces, caps=caps, cards=cards)
        vids = [t for t in d["tracks"] if t["type"] == "video"]
        assert len(vids) == 3   # the main track + one overlay track per used lane
        ov, segs1, segs2 = vids[1:], vids[1]["segments"], vids[2]["segments"]
        assert len(segs1) == 1 and len(segs2) == 1   # ghost stayed a hand step
        assert ov[0]["flag"] == 1   # overlay above the main track (flag 0)
        hook = segs1[0]
        assert hook["target_timerange"] == {"start": 0, "duration": 1_001_000}
        # the rect's centre in half-canvas units, x right, y up (the caption sign convention),
        # and the scale that shows an 800x400 material in an 800x400 box of a 1080x1920 canvas
        assert hook["clip"]["transform"] == {"x": -0.07407407407407407, "y": 0.5833333333333333}
        assert hook["clip"]["scale"] == {"x": 0.7407407407407407, "y": 0.7407407407407407}
        assert len(hook["extra_material_refs"]) == 6 and hook["render_index"] == 14000
        m = next(mm for mm in d["materials"]["videos"] if mm["id"] == hook["material_id"])
        assert Path(m["path"]).name == "card-01.mov" and (m["width"], m["height"]) == (800, 400)
        assert segs2[0]["target_timerange"] == {"start": 500_500, "duration": 500_500}
        # a still is a "photo" material: as "image" CapCut kept the clip on the timeline and drew
        # nothing (issue #8's install check)
        still = next(mm for mm in d["materials"]["images"] if mm["id"] == segs2[0]["material_id"])
        assert still["type"] == "photo"
        assert next(mm["path"] for mm in d["materials"]["images"]) == str((media / "card-02.png").resolve())
        check_draft(d, export)
        # a mov card without its alpha matte beside it is rejected: CapCut reads the matte there
        broken = copy.deepcopy(d)
        bad = next(mm for mm in broken["materials"]["videos"]
                   if Path(mm["path"]).name == "card-01.mov")
        bad["path"] = str((media / "no-matte.mov").resolve())
        assert breaks(check_draft, broken, export)

        # --- cues: one audio track, one segment per cue at its time; the level is in the media ---
        cues = [{"path": media / "sfx-01.wav", "start_f": 45, "len_f": 20, "channels": 2, "rate": 48000}]
        (media / "sfx-01.wav").write_bytes(b"wav")
        d = build_draft(ctx, pieces, caps=caps, cards=cards, cues=cues)
        at = next(tr for tr in d["tracks"] if tr["type"] == "audio")
        assert at["flag"] == 0
        cs = at["segments"]
        assert len(cs) == 1 and cs[0]["target_timerange"] == {"start": 750_750, "duration": 333_667}
        assert cs[0]["volume"] == 1.0 and cs[0]["clip"] is None   # the level is in the rendered media
        assert len(cs[0]["extra_material_refs"]) == 6
        ref_ids = set(cs[0]["extra_material_refs"])
        fades, beats = d["materials"]["audio_fades"], d["materials"]["beats"]
        assert len(fades) == len(beats) == 1
        assert fades[0]["id"] in ref_ids and beats[0]["id"] in ref_ids
        am = next(mm for mm in d["materials"]["audios"] if mm["id"] == cs[0]["material_id"])
        assert am["type"] == "extract_music" and Path(am["path"]).name == "sfx-01.wav"
        check_draft(d, export)
        # a card whose tail runs past the cut's last frame stretches the timeline, not the check:
        # the draft's duration is the furthest end across the tracks
        late = build_draft(ctx, pieces, cards=[{"i": 1, "kind": "video", "path": media / "card-01.mov",
                                                "start_f": 60, "len_f": 40, "rect": [0, 0, 1080, 1920],
                                                "lane": 1, "name": "outro"}])
        assert late["duration"] == _us(100, ctx["rate"])
        check_draft(late, export)
        # a broken text draft has to be rejected too
        broken = copy.deepcopy(d)
        broken["tracks"][-1]["segments"][0]["extra_material_refs"] = ["not-a-material"]
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["tracks"][-1]["segments"][1]["target_timerange"]["start"] = 0   # inside the previous page
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["tracks"][-1]["segments"][-1]["target_timerange"]["duration"] = d["duration"] * 2
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["materials"]["texts"][0]["content"] = "{not json"
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["materials"]["texts"][0]["content"] = json.dumps({"text": ""}, ensure_ascii=False)
        assert breaks(check_draft, broken, export)
        # one-frame spans: quantise the boundary, not each duration, or joins drift by 1 µs
        tiny = {**ctx, "segs": [(0, 0, 1), (1, 1, 1), (2, 2, 1)], "total_f": 3}
        one = [{"path": media / f"seg-{i:02d}.mp4", "width": 832, "height": 1040} for i in (1, 2, 3)]
        t = build_draft(tiny, one)
        assert [(s["target_timerange"]["start"], s["target_timerange"]["duration"])
                for s in t["tracks"][0]["segments"]] == [(0, 16683), (16683, 16684), (33367, 16683)]
        assert t["duration"] == 50050
        check_draft(t, export)
        # the self-test has to fail on a broken draft, or it proves nothing
        broken = copy.deepcopy(d)
        broken["tracks"][0]["segments"][0]["extra_material_refs"][0] = "not-a-material"
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["tracks"][0]["segments"][1]["target_timerange"]["start"] = 0
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["materials"]["videos"][0]["path"] = "/etc/passwd"
        assert breaks(check_draft, broken, export)
        broken = copy.deepcopy(d)
        broken["duration"] += 1
        assert breaks(check_draft, broken, export)

        # --- pieces: stable copies in the draft's own media folder, filled from the cache if cold ---
        edit = Path(td) / "edit"
        (edit / ".segments" / "abc").mkdir(parents=True)
        (edit / ".segments" / "abc" / "0-60.mp4").write_bytes(b"one")
        ctx = {**ctx, "edit": edit, "source": edit / "take.mp4"}
        filled = []
        got = ensure_pieces(ctx, media, probe=lambda p: {"width": 832, "height": 1040},
                            fill=lambda: (filled.append(1),
                                          (edit / ".segments" / "abc" / "120-150.mp4").write_bytes(b"two")))
        assert filled == [1] and [p["path"].name for p in got] == ["seg-01.mp4", "seg-02.mp4"], got
        assert (media / "seg-01.mp4").read_bytes() == b"one" and (media / "seg-02.mp4").read_bytes() == b"two"
        assert [(p["width"], p["height"]) for p in got] == [(832, 1040)] * 2
        # a warm cache copies without filling again
        assert [p["path"] for p in ensure_pieces(ctx, media, probe=lambda p: {"width": 1, "height": 1},
                                                 fill=lambda: filled.append(2))] == [p["path"] for p in got]
        assert filled == [1]

        # --- the cut's audio: one file from cut.mp4, because the cached pieces are video-only ---
        cut = edit / "cut.mp4"
        cut.write_bytes(b"cut")
        took = []
        aud = ensure_audio(ctx, media, probe=lambda p: (1.5, 2),
                           extract=lambda s, dst: (took.append((s, dst)), dst.write_bytes(b"aac")))
        assert aud == {"path": media / "cut-audio.m4a", "duration": 1_500_000}, aud
        assert took == [(cut, media / "cut-audio.m4a")]
        # no audio stream on the cut: no audio track, never a silent segment of zero length
        assert ensure_audio(ctx, media, probe=lambda p: (1.5, None), extract=lambda s, d: None) is None
        d_audio = build_draft(ctx, got, audio=aud)
        at = next(t for t in d_audio["tracks"] if t["type"] == "audio")
        assert len(at["segments"]) == 1
        assert at["segments"][0]["target_timerange"] == {"start": 0, "duration": 1_500_000}
        assert len(at["segments"][0]["extra_material_refs"]) == 6
        check_draft(d_audio, export)

        # --- install: copy into the project store, re-point media, write meta, add the root entry ---
        store = Path(td) / "store"
        store.mkdir()
        (store / "root_meta_info.json").write_text(
            json.dumps({"draft_ids": 7, "root_path": str(store), "all_draft_store": []}), encoding="utf-8")
        src = Path(td) / "export" / "capcut" / "demo"
        (src / "draft_info.json").write_text(json.dumps(build_draft(ctx, got), ensure_ascii=False),
                                             encoding="utf-8")
        # CapCut up: refuse, because its quit rewrites the store over ours
        assert exits(install, src, store, running=lambda: True)
        # no draft_info.json: that is not a draft
        assert exits(install, Path(td) / "nowhere", store, running=lambda: False)
        installed = install(src, store, running=lambda: False)
        assert installed == (store / "demo").resolve()
        meta = json.loads((installed / "draft_meta_info.json").read_text(encoding="utf-8"))
        assert meta["draft_name"] == "demo" and meta["draft_id"]
        assert meta["draft_fold_path"] == str(installed) and meta["draft_root_path"] == str(store.resolve())
        assert meta["tm_duration"] == json.loads((src / "draft_info.json").read_text(encoding="utf-8"))["duration"]
        # the media panel lists the files itself; with an empty list CapCut opened the draft with
        # an empty import section (issue #8's install check), so the paths must be relative copies
        panel = meta["draft_materials"][0]["value"]
        assert [(m["file_Path"], m["metetype"]) for m in panel] == \
            [("./media/seg-01.mp4", "video"), ("./media/seg-02.mp4", "video")], panel
        # the media is re-pointed at the copy, so the export folder can be deleted afterwards
        info = json.loads((installed / "draft_info.json").read_text(encoding="utf-8"))
        assert all(Path(m["path"]).is_file() and installed in Path(m["path"]).parents
                   for m in info["materials"]["videos"]), info["materials"]["videos"]
        assert (installed / "media" / "seg-01.mp4").read_bytes() == b"one"
        # the root entry is appended and the previous file is kept
        root = json.loads((store / "root_meta_info.json").read_text(encoding="utf-8"))
        assert root["draft_ids"] == 7 and len(root["all_draft_store"]) == 1
        e = root["all_draft_store"][0]
        assert e["draft_name"] == "demo" and e["draft_fold_path"] == str(installed)
        assert e["draft_json_file"] == str(installed / "draft_info.json")
        assert (store / "root_meta_info.json.bak").is_file()
        # a collision never overwrites: it stops and names the first free suffix
        try:
            install(src, store, running=lambda: False)
        except SystemExit as err:
            assert "demo-2" in str(err), err
        else:
            raise AssertionError("an existing draft name must be refused")
        assert (installed / "media" / "seg-01.mp4").read_bytes() == b"one"
        alt = install(src, store, name="demo-2", running=lambda: False)
        assert alt.name == "demo-2"
        assert json.loads((alt / "draft_info.json").read_text(encoding="utf-8"))["name"] == "demo-2"
        assert len(json.loads((store / "root_meta_info.json").read_text(encoding="utf-8"))["all_draft_store"]) == 2
        # a store CapCut has never written yet: the folder is installed, its startup scan indexes it
        fresh = Path(td) / "fresh"
        fresh.mkdir()
        install(src, fresh, name="solo", running=lambda: False)
        assert (fresh / "solo" / "draft_meta_info.json").is_file()
        assert not (fresh / "root_meta_info.json").exists()
    print("demo ok")


def breaks(fn, *args):
    """True when the structural self-test rejects the draft."""
    try:
        fn(*args)
    except AssertionError:
        return True
    return False


def exits(fn, *args, **kwargs):
    """True when the call refuses with a SystemExit message."""
    try:
        fn(*args, **kwargs)
    except SystemExit:
        return True
    return False


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
    elif sys.argv[1:2] == ["install"]:
        ap = argparse.ArgumentParser(description="Install a generated CapCut draft into the project store.")
        ap.add_argument("draft", help="the draft folder written by export_nle.py --to capcut")
        ap.add_argument("--name", help="project name (default: the folder's name)")
        a = ap.parse_args(sys.argv[2:])
        print(install(a.draft, name=a.name))
    else:
        sys.exit(__doc__)
