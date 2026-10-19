#!/usr/bin/env python3
"""Write a CapCut desktop draft for an edit: one video track, one segment per kept span.

    python3 capcut_draft.py demo        self-check, offline

The reader was probed in issue #4 (see docs/adr/0001-capcut-draft-format.md): the draft folder is
plain JSON, every extra_material_ref must resolve, and timing is integer microseconds. 59.94 fps is
60000/1001, so a frame count becomes µs with round(frames * 1_000_000 * 1001 / 60000).
"""
import copy
import json
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


def _video_material(uid, path, width, height, duration):
    return {
        "id": uid, "unique_id": uuid.uuid4().hex, "type": "video", "duration": duration,
        "path": str(Path(path).resolve()), "width": width, "height": height, "has_audio": False,
        "material_name": Path(path).name, "category_name": "local", "crop_ratio": "free", "crop_scale": 1.0,
        "crop": {"upper_left_x": 0.0, "upper_left_y": 0.0, "upper_right_x": 1.0, "upper_right_y": 0.0,
                 "lower_left_x": 0.0, "lower_left_y": 1.0, "lower_right_x": 1.0, "lower_right_y": 1.0},
        "source": 0, "source_platform": 0, "check_flag": 62978047, "local_material_id": _uid(),
    }


def build_draft(ctx, pieces, version=PINNED):
    """The draft_info.json object: one video track, one segment per piece. `pieces` are dicts with
    path, width and height (from ensure_pieces); ctx["segs"] gives each span's timeline start and length."""
    rate = ctx["rate"]
    assert len(pieces) == len(ctx["segs"]), f"{len(pieces)} pieces for {len(ctx['segs'])} kept spans"
    materials = {bucket: [] for bucket in AUX}
    materials["videos"] = []
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
        "tracks": [track], "materials": materials, "relationships": [], "platform": platform,
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
    for track in draft["tracks"]:
        t = 0
        for seg in track["segments"]:
            assert seg["material_id"] in ids, f"dangling material_id {seg['material_id']}"
            for ref in seg["extra_material_refs"]:
                assert ref in ids, f"dangling extra_material_ref {ref}"
            source, target = seg["source_timerange"], seg["target_timerange"]
            assert source["start"] >= 0 and source["duration"] > 0, f"bad source times {source}"
            assert target["start"] == t, f"target times are not monotone: {target['start']} != {t}"
            assert target["duration"] > 0, f"bad target duration {target}"
            t = target["start"] + target["duration"]
        total = max(total, t)
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
    print("demo ok")


def breaks(fn, *args):
    """True when the structural self-test rejects the draft."""
    try:
        fn(*args)
    except AssertionError:
        return True
    return False


if __name__ == "__main__":
    if sys.argv[1:] == ["demo"]:
        demo()
