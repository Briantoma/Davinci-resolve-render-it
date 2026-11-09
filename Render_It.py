#!/usr/bin/env python3
"""
Render_It.py

Adds the current timeline, the in/out range, or the selected timeline clips
to the render queue using one of your saved render presets, without leaving
the page you are on.

Target: DaVinci Resolve Studio 21.1, macOS, Python 3.
Studio is required. 21.1 moved Python scripting, UIManager and external
scripting access to Studio only.

Install to:
  ~/Library/Application Support/Blackmagic Design/DaVinci Resolve/
      Fusion/Scripts/Utility/
then run from Workspace > Scripts > Render_It.
The filename stays fixed, the version is in VERSION and the window title.
Utility puts it in the menu on every page, Color included.

V0.01: first build. Explicit scope, one job per clip or one job for the
       whole selection, target directory in the window, preset list read
       from the project, every queued job verified by reading it back.
V0.02: Current reel scope, using the reel naming presets from the append
       script. Settings file no longer depends on __file__, which does not
       exist when Resolve execs the script from the Scripts menu.
V0.03: factory presets hidden, several presets queued at once, clip list
       behind a Preview tick, optional start after adding, page restored
       afterwards, reel field on its own row so it stops landing on the
       dropdown.
V0.04: the factory preset list is the real one off a 21.1 install, and
       hiding it is a tick in the window instead of a constant.
V0.05: render mode comes from the preset instead of being forced to single
       clip. Per job summary with clip counts and reel names, preview lists
       the clip names, job mode is a tick, layout moved around.
V0.06: fixed filename, version in the window title. Frames are checked
       before a render starts, and a bad run removes its own jobs. One
       job ranges refuse clips that are not part of the reel or the
       selection. The reel is found under the playhead on any track.
       Individual clips presets widen the range to whole clips, which is
       reported instead of being called a mismatch.
V0.07: Individual clips tick, applied on every run, because a preset does
       not reliably set the render mode on 21.1.2.
       A lone in or out point is named instead of an unreadable shape.

Things this build deliberately does not do:
  It starts rendering only when the Start tick is on, and never when a
  queued job read back wrong.
  It never deletes or reorders jobs it did not add in this run.

Checked on Resolve Studio 21.1.2: SetRenderSettings takes absolute
timeline frames and Deliver does not need opening first. The read back
after every AddRenderJob stays, since it is what catches a future change.
"""

import json
import os
import re

# ---------------------------------------------------------------- settings

VERSION = "0.07"

PRESET_PREFIX = ""        # optional extra filter, e.g. "SL_". Empty = off.

DEFAULT_CUSTOM_ONLY = True
# There is no API flag marking a preset as yours, so the factory ones are
# matched by name. This is the list a stock 21.1 install reports. A future
# Resolve adding a preset means one extra line in the window, not a break.
FACTORY_PRESETS = (
    "h.264 master", "hyperdeck", "h.265 master", "prores 422 hq",
    "youtube - 720p", "youtube - 1080p", "youtube - 1440p",
    "youtube - 2160p",
    "vimeo - 720p", "vimeo - 1080p", "vimeo - 2160p",
    "tiktok - 720p", "tiktok - 1080p", "presentations",
    "dropbox - 720p", "dropbox - 1080p", "dropbox - 2160p",
    "replay - 720p", "replay - 1080p", "replay - 2160p",
    "imf - generic", "imf - 20th century fox", "imf - netflix",
    "imf - sony pictures", "imf - iqiyi", "imf - hdr vivid",
    "fcp - final cut pro 7", "fcp - final cut pro x", "premiere xml",
    "audio only", "avid aaf", "pro tools",
    "tencent - imf", "tencent - mov", "tencent - mp4",
    "vr 180/360 - meta quest vr", "vr 180/360 - youtube vr",
)

SUFFIX_PRESET_NAME = True
# With more than one preset queued, two presets that share a container write
# the same filename and one silently wins. True appends the preset name.

MAX_PRESET_ROWS = 6

# Render mode is set from the Individual clips tick on every run. On 21.1.2
# a preset does not reliably carry it: "Edit" always loaded as single clip,
# others kept whatever mode Deliver was left in.
#
# Worth knowing: CustomName is only honoured in single clip mode. A preset
# set to individual clips names files from the source and ignores the names
# below, which is usually what you want for dailies and never what you want
# for a one job per clip pull.

MARK_FRAMES_ABSOLUTE = True
# True  = MarkIn/MarkOut are absolute timeline frames (86400 at 01:00:00:00).
# False = frames counted from the timeline start.
# Checked on 21.1.2: absolute is right. The read back after each job still
# compares what Resolve stored, in case a later build changes it.

TOUCH_DELIVER_PAGE = False
# True = open Deliver, queue, then return to the page you were on. Costs a
# visible page flash. Not needed on 21.1.2, settings applied without it.

CLOSE_ON_SUCCESS = True

DRY_RUN = False           # True = build and report the jobs, queue nothing

SETTINGS_NAME = "render_it_settings.json"

SETTINGS_FALLBACK = os.path.expanduser(
    "~/Library/Application Support/Blackmagic Design/DaVinci Resolve/"
    "Fusion/Scripts/Utility")


def settings_path():
    """
    Beside the script when that is knowable, the Utility folder otherwise.

    Resolve execs menu scripts rather than importing them, so __file__ is
    undefined there. This is called lazily so a bad path can never stop the
    script loading.
    """
    base = None
    try:
        base = os.path.dirname(os.path.abspath(__file__))
    except NameError:
        base = None
    for candidate in (base, SETTINGS_FALLBACK, os.path.expanduser("~")):
        if candidate and os.path.isdir(candidate):
            return os.path.join(candidate, SETTINGS_NAME)
    return os.path.join(os.path.expanduser("~"), SETTINGS_NAME)

# window metrics
WINDOW_W = 790
LABEL_W = 176            # fits "Reel naming detection by"
FIELD_H = 26
ROW_H = 32
SUMMARY_H = 76           # three lines of per job summary
CHROME_H = 176           # title, summary, bottom strip, margins
PREVIEW_H = 130

SCOPES = [
    ("selected", "Selected clips"),
    ("inout", "In/Out range"),
    ("reel", "Current reel"),
]

# key, label, regex or None for a non regex mode. Same set as the append
# script so a reel means the same thing in both tools.
REEL_PRESETS = [
    ("cam_letter", "Camera letter + reel number (A001)",
     r"^(?P<cam>[A-Za-z]{1,2})[ _-]?(?P<reel>\d{2,4})"),
    ("cam_word", "Camera name + reel number (CAM001)",
     r"^(?P<cam>[A-Za-z]{1,4})[ _-]?(?P<reel>\d{2,4})"),
    ("number", "Reel number only (001)",
     r"^(?P<reel>\d{2,4})"),
    ("first_n", "First N characters", None),
    ("custom", "Custom regex", None),
]
PRESET_KEYS = [k for k, _, _ in REEL_PRESETS]
PRESET_REGEX = dict((k, r) for k, _, r in REEL_PRESETS)

DEFAULT_SCOPE = "reel"
DEFAULT_REEL_CHARS = 4
DEFAULT_CUSTOM_REGEX = REEL_PRESETS[0][2]

DEFAULT_PER_CLIP = False

# ---------------------------------------------------------------- plumbing


def get_resolve():
    """Works from the console, the Scripts menu, and externally."""
    try:
        return resolve                      # injected global inside Resolve
    except NameError:
        pass
    import sys
    try:
        import DaVinciResolveScript as dvr_script
    except ImportError:
        mod = os.environ.get("RESOLVE_SCRIPT_API")
        mod = os.path.join(mod, "Modules") if mod else (
            "/Library/Application Support/Blackmagic Design/"
            "DaVinci Resolve/Developer/Scripting/Modules")
        sys.path.append(mod)
        import DaVinciResolveScript as dvr_script
    return dvr_script.scriptapp("Resolve")


def get_fusion(resolve_app):
    """UIManager lives on the Fusion object. Studio only since 19.1."""
    try:
        return fu                           # injected global
    except NameError:
        pass
    try:
        return fusion                       # injected global, other builds
    except NameError:
        pass
    getter = getattr(resolve_app, "Fusion", None)
    return getter() if getter else None


def get_dispatcher(ui):
    try:
        return bmd.UIDispatcher(ui)         # injected global
    except NameError:
        pass
    import DaVinciResolveScript as dvr_script
    return dvr_script.UIDispatcher(ui)


def as_list(obj):
    """Resolve returns dicts keyed 1..n in some places, lists in others."""
    if not obj:
        return []
    if isinstance(obj, dict):
        return [obj[k] for k in sorted(obj.keys())]
    return list(obj)


def call_any(owner, names, *args):
    """First method on owner that exists, by name. Builds differ."""
    for name in names:
        method = getattr(owner, name, None)
        if method is not None:
            return method(*args)
    return None


def load_settings():
    try:
        with open(settings_path()) as handle:
            data = json.load(handle)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def save_settings(data):
    try:
        with open(settings_path(), "w") as handle:
            json.dump(data, handle, indent=2)
    except Exception:
        pass                                # never block a render on this


# ------------------------------------------------------------ timeline math


def timeline_start(timeline):
    start = call_any(timeline, ["GetStartFrame"])
    try:
        return int(start)
    except Exception:
        return 0


def video_item_ids(timeline):
    """
    Unique ids of every item on a video track.

    GetSelectedClips can hand back audio items alongside video ones, and a
    job built from an audio item has the wrong extent. Anything without a
    usable id falls through and is kept, since dropping a real clip is the
    worse failure.
    """
    ids = set()
    count = call_any(timeline, ["GetTrackCount"], "video") or 0
    for index in range(1, int(count) + 1):
        items = as_list(call_any(
            timeline, ["GetItemListInTrack", "GetItemsInTrack"],
            "video", index))
        for item in items:
            uid = call_any(item, ["GetUniqueId"])
            if uid:
                ids.add(uid)
    return ids


def selected_clips(timeline):
    """Selected video items, in timeline order. Needs 21.0.4 or newer."""
    getter = getattr(timeline, "GetSelectedClips", None)
    if getter is None:
        raise RuntimeError(
            "Timeline.GetSelectedClips is missing on this build, it needs "
            "21.0.4 or newer")
    items = as_list(getter())
    if not items:
        return []

    known = video_item_ids(timeline)
    if known:
        kept = []
        for item in items:
            uid = call_any(item, ["GetUniqueId"])
            if uid is None or uid in known:
                kept.append(item)
        items = kept

    def start_of(item):
        try:
            return int(item.GetStart())
        except Exception:
            return 0

    return sorted(items, key=start_of)


def reel_key(name, preset, custom_regex, chars):
    """
    Reel a clip name belongs to, or None if it does not match.

    Same rules as the append script: the named groups cam and reel are
    joined, first_n takes a fixed slice, custom takes your own pattern.
    """
    name = (name or "").strip()
    if not name:
        return None

    if preset == "first_n":
        try:
            count = max(1, int(chars))
        except Exception:
            count = DEFAULT_REEL_CHARS
        return (name[:count] or None) and name[:count].upper()

    pattern = custom_regex if preset == "custom" else PRESET_REGEX.get(preset)
    if not pattern:
        return None
    try:
        match = re.match(pattern, name)
    except re.error as err:
        raise RuntimeError("that regex will not compile: %s" % err)
    if not match:
        return None

    try:
        groups = match.groupdict()
    except Exception:
        groups = {}
    cam = (groups.get("cam") or "").upper()
    number = groups.get("reel") or ""
    key = (cam + number) or match.group(0)
    return key.upper() or None


def all_video_items(timeline):
    """Every item on every video track, in timeline order."""
    items = []
    count = call_any(timeline, ["GetTrackCount"], "video") or 0
    for index in range(1, int(count) + 1):
        items.extend(as_list(call_any(
            timeline, ["GetItemListInTrack", "GetItemsInTrack"],
            "video", index)))

    def start_of(item):
        try:
            return int(item.GetStart())
        except Exception:
            return 0

    return sorted(items, key=start_of)


def tc_to_frames(tc, fps):
    """
    Absolute frame of a timeline timecode. Drop frame (';') follows the
    SMPTE count, two frames per minute at 30, four at 60, except every
    tenth minute.
    """
    base = int(round(fps))
    hours, minutes, seconds, frames = [
        int(x) for x in re.split(r"[:;.]", tc.strip())]
    total = ((hours * 60 + minutes) * 60 + seconds) * base + frames
    if ";" in tc:
        all_minutes = hours * 60 + minutes
        total -= (base // 15) * (all_minutes - all_minutes // 10)
    return total


def items_under_playhead(timeline):
    """Video items under the playhead, top track first. Empty if unknown."""
    tc = call_any(timeline, ["GetCurrentTimecode"])
    fps = timeline_fps(timeline, None)
    if not tc or not fps:
        return []
    try:
        frame = tc_to_frames(tc, fps)
    except Exception:
        return []
    hits = []
    count = call_any(timeline, ["GetTrackCount"], "video") or 0
    for index in range(int(count), 0, -1):
        for item in as_list(call_any(
                timeline, ["GetItemListInTrack", "GetItemsInTrack"],
                "video", index)):
            try:
                if int(item.GetStart()) <= frame < int(item.GetEnd()):
                    hits.append(item)
            except Exception:
                continue
    return hits


def item_key(item):
    return call_any(item, ["GetUniqueId"]) or "%s@%s" % (
        call_any(item, ["GetName"]), call_any(item, ["GetStart"]))


def strangers_in_range(timeline, items, mark_in, mark_out):
    """
    Names of clips inside mark_in..mark_out that are not in items, looking
    only at the tracks items sit on. A title on another track spanning the
    whole reel is not a stranger, a B camera clip between two A clips is.
    """
    ours = set(item_key(item) for item in items)
    names = []
    count = call_any(timeline, ["GetTrackCount"], "video") or 0
    for index in range(1, int(count) + 1):
        track = as_list(call_any(
            timeline, ["GetItemListInTrack", "GetItemsInTrack"],
            "video", index))
        keys = [item_key(item) for item in track]
        if not ours.intersection(keys):
            continue
        for item, key in zip(track, keys):
            if key in ours:
                continue
            try:
                start, end = clip_extent(item)
            except Exception:
                continue
            if end >= mark_in and start <= mark_out:
                names.append(call_any(item, ["GetName"]) or "clip")
    return names


def widen_to_clips(timeline, mark_in, mark_out):
    """
    The range an Individual clips preset really renders. Resolve 21.1.2
    stores MarkIn/MarkOut widened to the whole clips the range touches.
    """
    extents = []
    for item in all_video_items(timeline):
        try:
            start, end = clip_extent(item)
        except Exception:
            continue
        if end >= mark_in and start <= mark_out:
            extents.append((start, end))
    if not extents:
        return mark_in, mark_out
    return (min(mark_in, min(e[0] for e in extents)),
            max(mark_out, max(e[1] for e in extents)))


def reel_scope(timeline, reel_cfg):
    """
    (reel name, items on that reel, total video items).

    The reel is taken from the clip under the playhead, which on the Color
    page is the clip you are looking at. Falls back to the first selected
    clip if the playhead is over empty space.
    """
    preset, custom_regex, chars = reel_cfg
    current = call_any(timeline, ["GetCurrentVideoItem"])
    # A title or adjustment clip on V2 can be the current item, so every
    # track under the playhead is a candidate, top track first.
    candidates = ([current] if current is not None else []) + \
        items_under_playhead(timeline)
    if not candidates:
        picked = selected_clips(timeline)
        candidates = picked[:1]
    if not candidates:
        raise RuntimeError(
            "no clip under the playhead and nothing selected")

    key = None
    names = []
    for item in candidates:
        name = call_any(item, ["GetName"]) or ""
        key = reel_key(name, preset, custom_regex, chars)
        if key:
            break
        if name not in names:
            names.append(name)
    if not key:
        raise RuntimeError(
            "'%s' does not match the reel pattern" % "', '".join(names))

    items = all_video_items(timeline)
    matched = [it for it in items
               if reel_key(call_any(it, ["GetName"]) or "",
                           preset, custom_regex, chars) == key]
    if not matched:
        raise RuntimeError("no clips found on reel %s" % key)
    return key, matched, len(items)


def clip_extent(item):
    """Inclusive in, inclusive out. GetEnd is exclusive in practice."""
    start = int(item.GetStart())
    end = int(item.GetEnd())
    return start, end - 1


def inout_extent(timeline):
    """
    Inclusive in and out of the timeline in/out range, absolute frames.

    GetMarkInOut returns per media type marks. Whether those are absolute
    or counted from the timeline start is not documented, so a value below
    the start frame is treated as relative and shifted.
    """
    getter = getattr(timeline, "GetMarkInOut", None)
    if getter is None:
        raise RuntimeError(
            "Timeline.GetMarkInOut is missing on this build, so the in/out "
            "range cannot be read")
    marks = getter() or {}
    block = None
    for key in ("video", "Video", "audio", "Audio"):
        if isinstance(marks.get(key), dict):
            block = marks[key]
            break
    if not block:
        raise RuntimeError("no in/out range set on this timeline")
    # Resolve 21.1.2 returns a lone out point as {"out": n} with no "in".
    has_in = "in" in block or "In" in block
    has_out = "out" in block or "Out" in block
    if has_in != has_out:
        raise RuntimeError("only an %s point is set on this timeline, set "
                           "the %s point too"
                           % (("in", "out") if has_in else ("out", "in")))

    try:
        mark_in = int(block.get("in", block.get("In")))
        mark_out = int(block.get("out", block.get("Out")))
    except Exception:
        raise RuntimeError("in/out range came back in a shape I cannot read")

    start = timeline_start(timeline)
    if mark_in < start:
        mark_in += start
        mark_out += start
    return mark_in, mark_out


def frames_to_tc(frames, fps):
    """Rough timecode for the summary line only, never for render maths."""
    try:
        fps_round = int(round(float(fps)))
        if fps_round <= 0:
            raise ValueError
    except Exception:
        return "%d f" % frames
    seconds, rest = divmod(int(frames), fps_round)
    minutes, seconds = divmod(seconds, 60)
    hours, minutes = divmod(minutes, 60)
    return "%02d:%02d:%02d:%02d" % (hours, minutes, seconds, rest)


def timeline_fps(timeline, project):
    for owner, key in ((timeline, "GetSetting"), (project, "GetSetting")):
        try:
            value = owner.GetSetting("timelineFrameRate")
            if value:
                return float(value)
        except Exception:
            continue
    return 0.0


# ---------------------------------------------------------------- job build


def unique_name(base, used):
    """Two selected clips can share a source name. Never overwrite."""
    name = base
    suffix = 2
    while name.lower() in used:
        name = "%s_%d" % (base, suffix)
        suffix += 1
    used.add(name.lower())
    return name


def sanitise(name):
    bad = '/\\:*?"<>|'
    cleaned = "".join("_" if ch in bad else ch for ch in str(name)).strip()
    return cleaned or "clip"


def clips_in_range(timeline, mark_in, mark_out):
    """Video items that touch the range, for the summary and the preview."""
    hits = []
    for item in all_video_items(timeline):
        try:
            start, end = clip_extent(item)
        except Exception:
            continue
        if end >= mark_in and start <= mark_out:
            hits.append(call_any(item, ["GetName"]) or "clip")
    return hits


def build_jobs(timeline, scope, per_clip, reel_cfg=None):
    """
    Returns (jobs, note).

    A job is a dict: name, in, out, clips (the clip names it covers) and
    reel (set only when the job is one whole reel, None otherwise).
    """
    note = ""

    if scope == "inout":
        mark_in, mark_out = inout_extent(timeline)
        return [{"name": sanitise(timeline.GetName()),
                 "in": mark_in, "out": mark_out,
                 "clips": clips_in_range(timeline, mark_in, mark_out),
                 "reel": None}], note

    reel = None
    if scope == "reel":
        reel, items, total = reel_scope(timeline, reel_cfg or
                                        (PRESET_KEYS[0],
                                         DEFAULT_CUSTOM_REGEX,
                                         DEFAULT_REEL_CHARS))
        note = "reel %s, %d of %d clips in the timeline" % (
            reel, len(items), total)
    else:
        items = selected_clips(timeline)
        if not items:
            raise RuntimeError("no clips selected in the timeline")

    extents = [clip_extent(item) for item in items]
    names = [call_any(item, ["GetName"]) or "clip" for item in items]

    overlaps = sum(1 for earlier, later in zip(extents, extents[1:])
                   if later[0] <= earlier[1])
    if overlaps and per_clip:
        note = ("%s%d clip%s overlap in time, they are on different tracks"
                % (note + ", " if note else "", overlaps,
                   "" if overlaps == 1 else "s"))

    if per_clip:
        used = set()
        jobs = []
        for name, (mark_in, mark_out) in zip(names, extents):
            jobs.append({"name": unique_name(sanitise(name), used),
                         "in": mark_in, "out": mark_out,
                         "clips": [name], "reel": None})
        return jobs, note

    mark_in = min(pair[0] for pair in extents)
    mark_out = max(pair[1] for pair in extents)
    strangers = strangers_in_range(timeline, items, mark_in, mark_out)
    if strangers:
        raise RuntimeError(
            "%s %s inside this range but %s, so one job would render %s. "
            "Tick One job per clip, or move %s out"
            % (", ".join(strangers),
               "sits" if len(strangers) == 1 else "sit",
               ("not on reel %s" % reel) if reel else "not selected",
               "it" if len(strangers) == 1 else "them",
               "it" if len(strangers) == 1 else "them"))
    covered = 0
    reach = mark_in - 1
    for start, end in extents:
        covered += max(0, end - max(start - 1, reach))
        reach = max(reach, end)
    span = mark_out - mark_in + 1
    if span > covered:
        note = ("%s%d frames of gap are inside this range"
                % (note + ", " if note else "", span - covered))

    return [{"name": sanitise(reel or timeline.GetName()),
             "in": mark_in, "out": mark_out,
             "clips": names, "reel": reel}], note


def render_marks(mark_in, mark_out, start):
    if MARK_FRAMES_ABSOLUTE:
        return mark_in, mark_out
    return mark_in - start, mark_out - start


RENDER_MODE_NAMES = {0: "individual clips", 1: "single clip"}


def queue_jobs(project, timeline, presets, target_dir, jobs,
               individual=False):
    """
    Queues every job against every preset. Returns (job ids, report lines).

    The read back exists because AddRenderJob reports failure by returning
    nothing useful, and because the frame base for MarkIn is not documented.
    """
    lines = []
    queued = []
    start = timeline_start(timeline)
    multi = len(presets) > 1

    for preset in presets:
        if not project.LoadRenderPreset(preset):
            raise RuntimeError("Resolve refused the preset '%s'" % preset)

        wanted_mode = 0 if individual else 1
        call_any(project, ["SetCurrentRenderMode"], wanted_mode)
        mode = call_any(project, ["GetCurrentRenderMode"])
        if mode != wanted_mode:
            raise RuntimeError(
                "Resolve kept render mode %s for '%s', %d jobs queued "
                "before it" % (RENDER_MODE_NAMES.get(mode, mode), preset,
                               len(queued)))
        mode_name = RENDER_MODE_NAMES.get(mode, "render mode %s" % mode)
        warn = ""
        if mode == 0 and len(jobs) > 1:
            warn = ", Resolve names these files, not the list below"
        lines.append("%s  [%s]%s" % (preset, mode_name, warn))

        for job in jobs:
            out_name = job["name"]
            if multi and SUFFIX_PRESET_NAME:
                out_name = "%s_%s" % (out_name, sanitise(preset))
            send_in, send_out = render_marks(job["in"], job["out"], start)
            settings = {
                "SelectAllFrames": 0,
                "MarkIn": send_in,
                "MarkOut": send_out,
                "TargetDir": target_dir,
                "CustomName": out_name,
            }
            if DRY_RUN:
                lines.append("  dry run  %s  %d to %d"
                             % (out_name, send_in, send_out))
                continue

            if not project.SetRenderSettings(settings):
                raise RuntimeError(
                    "SetRenderSettings was refused for '%s', %d jobs queued "
                    "before it" % (out_name, len(queued)))

            job_id = project.AddRenderJob()
            if not job_id:
                raise RuntimeError(
                    "AddRenderJob failed for '%s', %d jobs queued before it"
                    % (out_name, len(queued)))
            queued.append(job_id)
            wanted = [(send_in, send_out)]
            if mode == 0:
                wanted.append(render_marks(
                    *widen_to_clips(timeline, job["in"], job["out"]),
                    start=start))
            lines.append("  " + read_back(project, job_id, out_name,
                                          wanted))

    return queued, lines


def read_back(project, job_id, name, wanted):
    """
    What Resolve actually stored, not what we asked for. wanted is the
    (in, out) sent, then any range Resolve may legitimately store instead.
    """
    jobs = as_list(call_any(project, ["GetRenderJobList"]))
    found = None
    for job in jobs:
        if isinstance(job, dict) and job.get("JobId") == job_id:
            found = job
            break
    if not found:
        return "%s queued, could not read it back  UNREADABLE" % name

    got_in = found.get("MarkIn")
    got_out = found.get("MarkOut")
    target = found.get("TargetDir") or "?"
    got = (got_in, got_out)
    if got == tuple(wanted[0]):
        flag = ""
    elif got in [tuple(pair) for pair in wanted[1:]]:
        flag = "  widened to whole clips by Individual clips"
    else:
        flag = "  MISMATCH"
    return "%s  %s to %s  ->  %s%s" % (
        name, got_in, got_out, target, flag)


# -------------------------------------------------------------------- main


def gather(resolve_app):
    project = resolve_app.GetProjectManager().GetCurrentProject()
    if not project:
        raise RuntimeError("no project open")
    timeline = project.GetCurrentTimeline()
    if not timeline:
        raise RuntimeError("no timeline open")
    return project, timeline


def preset_names(project):
    """(every preset the project reports, the ones that are not factory)."""
    raw = as_list(call_any(project, ["GetRenderPresetList"]))
    names = []
    for entry in raw:
        if isinstance(entry, dict):
            entry = entry.get("PresetName") or entry.get("Name")
        if entry:
            names.append(str(entry))

    custom = [n for n in names if n.strip().lower() not in FACTORY_PRESETS]
    if PRESET_PREFIX:
        custom = [n for n in custom if n.startswith(PRESET_PREFIX)]
    return names, custom


def run_gui(resolve_app, project, timeline):
    fusion_app = get_fusion(resolve_app)
    if fusion_app is None or not getattr(fusion_app, "UIManager", None):
        raise RuntimeError(
            "UIManager is unavailable, which means this is not Studio")

    ui = fusion_app.UIManager
    disp = get_dispatcher(ui)
    saved = load_settings()
    all_presets, custom_presets = preset_names(project)
    state = {"rows": 1, "presets": []}

    def fixed(width):
        return [width, FIELD_H]

    def label(text):
        return ui.Label({"Text": text, "Weight": 0,
                         "MinimumSize": fixed(LABEL_W),
                         "MaximumSize": fixed(LABEL_W)})

    # ---- preset rows, all built now, the spare ones hidden
    preset_rows = []
    for index in range(MAX_PRESET_ROWS):
        widgets = [
            label("Render preset" if index == 0 else ""),
            ui.ComboBox({"ID": "Preset%d" % index, "Weight": 1,
                         "MinimumSize": [280, FIELD_H]}),
        ]
        if index == 0:
            widgets.append(ui.Button({"ID": "AddPreset", "Text": "+",
                                      "Weight": 0,
                                      "MinimumSize": fixed(36),
                                      "MaximumSize": fixed(36)}))
            widgets.append(ui.Button({"ID": "RemovePreset", "Text": "-",
                                      "Weight": 0,
                                      "MinimumSize": fixed(36),
                                      "MaximumSize": fixed(36)}))
        else:
            widgets.append(ui.Label({"Text": "", "Weight": 0,
                                     "MinimumSize": fixed(78),
                                     "MaximumSize": fixed(78)}))
        preset_rows.append(ui.HGroup({"ID": "PresetRow%d" % index,
                                      "Weight": 0}, widgets))

    body = preset_rows + [

        ui.HGroup({"Weight": 0}, [
            label(""),
            ui.CheckBox({"ID": "CustomOnly",
                         "Text": "Show custom presets only",
                         "Checked": bool(saved.get("custom_only",
                                                   DEFAULT_CUSTOM_ONLY)),
                         "Weight": 0,
                         "MinimumSize": [240, FIELD_H]}),
            ui.Label({"Text": "", "Weight": 1}),
        ]),

        ui.HGroup({"Weight": 0}, [
            label("Selection"),
            ui.ComboBox({"ID": "Scope", "Weight": 0,
                         "MinimumSize": fixed(220),
                         "MaximumSize": fixed(220)}),
            ui.Label({"Text": "", "Weight": 1}),
        ]),

        ui.HGroup({"Weight": 0}, [
            label("Reel naming detection by"),
            ui.ComboBox({"ID": "ReelPreset", "Weight": 0,
                         "MinimumSize": fixed(300),
                         "MaximumSize": fixed(300)}),
            ui.Label({"Text": "", "Weight": 1}),
        ]),

        # own row, because a field toggled inside the dropdown row lands on
        # top of the dropdown instead of beside it
        ui.HGroup({"ID": "ReelExtraRow", "Weight": 0}, [
            label(""),
            ui.LineEdit({"ID": "ReelChars", "Weight": 0,
                         "MinimumSize": fixed(60),
                         "MaximumSize": fixed(60),
                         "Text": str(saved.get("reel_chars",
                                               DEFAULT_REEL_CHARS))}),
            ui.LineEdit({"ID": "ReelRegex", "Weight": 1,
                         "MinimumSize": [240, FIELD_H],
                         "Text": saved.get("reel_regex",
                                           DEFAULT_CUSTOM_REGEX)}),
        ]),

        ui.HGroup({"Weight": 0}, [
            label("Destination"),
            ui.LineEdit({"ID": "TargetDir", "Weight": 1,
                         "MinimumSize": [280, FIELD_H],
                         "Text": saved.get("target_dir", "")}),
            ui.Button({"ID": "BrowseButton", "Text": "Browse", "Weight": 0,
                       "MinimumSize": fixed(90),
                       "MaximumSize": fixed(90)}),
        ]),

        ui.HGroup({"Weight": 0}, [
            label("Options"),
            ui.CheckBox({"ID": "PerClip", "Text": "One job per clip",
                         "Checked": bool(saved.get("per_clip",
                                                   DEFAULT_PER_CLIP)),
                         "Weight": 0,
                         "MinimumSize": [190, FIELD_H]}),
            ui.CheckBox({"ID": "StartRender",
                         "Text": "Start rendering after adding",
                         "Checked": bool(saved.get("start_render", False)),
                         "Weight": 0,
                         "MinimumSize": [230, FIELD_H]}),
            ui.CheckBox({"ID": "Individual", "Text": "Individual clips",
                         "Checked": bool(saved.get("individual_clips",
                                                   False)),
                         "Weight": 0,
                         "MinimumSize": [160, FIELD_H]}),
            ui.Label({"Text": "", "Weight": 1}),
        ]),

        ui.HGroup({"Weight": 0}, [
            label(""),
            ui.CheckBox({"ID": "ShowPreview",
                         "Text": "Preview the clip selection",
                         "Checked": bool(saved.get("show_preview", False)),
                         "Weight": 0,
                         "MinimumSize": [250, FIELD_H]}),
            ui.Label({"Text": "", "Weight": 1}),
        ]),

        ui.TextEdit({"ID": "Summary", "Weight": 0, "ReadOnly": True,
                     "MinimumSize": [0, SUMMARY_H],
                     "MaximumSize": [16777215, SUMMARY_H]}),

        ui.TextEdit({"ID": "Detail", "Weight": 1, "ReadOnly": True,
                     "MinimumSize": [0, 70]}),

        ui.HGroup({"Weight": 0}, [
            ui.Label({"Text": "v" + VERSION, "Weight": 0,
                      "MinimumSize": fixed(46),
                      "MaximumSize": fixed(46)}),
            ui.Label({"ID": "Status", "Text": "", "Weight": 1}),
            ui.Button({"ID": "RefreshButton", "Text": "Refresh selection",
                       "Weight": 0,
                       "MinimumSize": fixed(140),
                       "MaximumSize": fixed(140)}),
            ui.Button({"ID": "CloseButton", "Text": "Close", "Weight": 0,
                       "MinimumSize": fixed(90),
                       "MaximumSize": fixed(90)}),
            ui.Button({"ID": "QueueButton", "Text": "Add to queue",
                       "Weight": 0, "Default": True,
                       "MinimumSize": fixed(130),
                       "MaximumSize": fixed(130)}),
        ]),
    ]

    win = disp.AddWindow({
        "ID": "RenderItWin",
        "WindowTitle": "Render It " + VERSION,
        "Geometry": [300, 200, WINDOW_W, CHROME_H + 6 * ROW_H],
        "Events": {"KeyPress": True},
    }, [ui.VGroup({"Spacing": 6, "Weight": 1}, body)])

    itm = win.GetItems()

    # ---- fill
    for _, text in SCOPES:
        itm["Scope"].AddItem(text)
    for _, text, _ in REEL_PRESETS:
        itm["ReelPreset"].AddItem(text)

    def set_index(widget, values, wanted, default=0):
        index = default
        for position, value in enumerate(values):
            if value == wanted:
                index = position
        try:
            itm[widget].CurrentIndex = index
        except Exception:
            pass

    scope_keys = [k for k, _ in SCOPES]

    saved_presets = saved.get("presets") or []
    state["rows"] = max(1, min(MAX_PRESET_ROWS, len(saved_presets) or 1))

    def wanted_presets():
        """What the tick asks for, unless that would empty the list."""
        if itm["CustomOnly"].Checked and custom_presets:
            return custom_presets
        return all_presets

    def fill_presets(keep=None):
        """
        Repopulate every preset row, holding each row on its own preset.

        Rebuilt rather than filtered in place because a ComboBox cannot hide
        an item. Returns a note for the status line.
        """
        names = wanted_presets()
        if keep is None:
            keep = list(saved_presets)
        state["presets"] = names

        for index in range(MAX_PRESET_ROWS):
            combo = itm["Preset%d" % index]
            try:
                combo.Clear()
            except Exception:
                pass
            for name in (names or ["no render presets found"]):
                combo.AddItem(name)
            combo.Enabled = bool(names)
            wanted = keep[index] if index < len(keep) else None
            set_index("Preset%d" % index, names, wanted, 0)

        state["rows"] = max(1, min(state["rows"], MAX_PRESET_ROWS,
                                   max(1, len(names))))
        if itm["CustomOnly"].Checked and not custom_presets:
            return ("no custom presets found, showing all %d"
                    % len(all_presets))
        return ""

    set_index("Scope", scope_keys, saved.get("scope"),
              scope_keys.index(DEFAULT_SCOPE))
    set_index("ReelPreset", PRESET_KEYS, saved.get("reel_preset"), 0)

    # ---- accessors
    def current_scope():
        return SCOPES[itm["Scope"].CurrentIndex][0]

    def per_clip_on():
        return bool(itm["PerClip"].Checked)

    def current_reel_preset():
        return PRESET_KEYS[itm["ReelPreset"].CurrentIndex]

    def reel_cfg():
        return (current_reel_preset(),
                itm["ReelRegex"].Text or DEFAULT_CUSTOM_REGEX,
                itm["ReelChars"].Text or DEFAULT_REEL_CHARS)

    def chosen_presets():
        """Refuses duplicates rather than quietly queueing a preset twice."""
        names = state["presets"]
        if not names:
            raise RuntimeError("no render presets to queue with")
        picked = []
        for index in range(state["rows"]):
            position = itm["Preset%d" % index].CurrentIndex
            name = names[min(position, len(names) - 1)]
            if name in picked:
                raise RuntimeError("'%s' is listed twice" % name)
            picked.append(name)
        return picked

    def preview_on():
        return bool(itm["ShowPreview"].Checked)

    def extra_row_on():
        return (current_scope() == "reel"
                and current_reel_preset() in ("first_n", "custom"))

    def set_status(text, error=False):
        itm["Status"].Text = text or ""
        try:
            itm["Status"].StyleSheet = "color: #ff6161;" if error else ""
        except Exception:
            pass

    def apply_layout():
        for index in range(MAX_PRESET_ROWS):
            itm["PresetRow%d" % index].Hidden = index >= state["rows"]
        itm["AddPreset"].Enabled = (bool(state["presets"])
                                    and state["rows"] < MAX_PRESET_ROWS
                                    and state["rows"] < len(state["presets"]))
        itm["RemovePreset"].Enabled = state["rows"] > 1

        itm["ReelExtraRow"].Hidden = not extra_row_on()
        itm["ReelChars"].Hidden = current_reel_preset() != "first_n"
        itm["ReelRegex"].Hidden = current_reel_preset() != "custom"
        itm["Detail"].Hidden = not preview_on()

        # preset rows + custom only, selection, reel naming, options,
        # preview tick, destination
        rows = state["rows"] + 6 + (1 if extra_row_on() else 0)
        height = CHROME_H + rows * ROW_H + (PREVIEW_H if preview_on() else 0)
        try:
            geo = win.Geometry
            win.Geometry = [geo[0], geo[1], geo[2], height]
        except Exception:
            pass
        try:
            win.RecalcLayout()
        except Exception:
            pass

    # ---- counting
    def job_line(job, fps):
        """One summary line: what it is called, how many clips, how long."""
        count = len(job["clips"])
        bits = ["%d clip%s" % (count, "" if count == 1 else "s"),
                frames_to_tc(job["out"] - job["in"] + 1, fps)]
        if job["reel"]:
            bits.append("reel " + job["reel"])
        return "%s   %s" % (job["name"], "   ".join(bits))

    def refresh(_event=None):
        """Recount without queuing. Returns the jobs or None."""
        scope = current_scope()
        itm["PerClip"].Enabled = scope in ("selected", "reel")
        itm["ReelPreset"].Enabled = scope == "reel"
        apply_layout()

        try:
            picked = chosen_presets()
            jobs, note = build_jobs(timeline, scope, per_clip_on(),
                                    reel_cfg())
        except RuntimeError as err:
            itm["Summary"].PlainText = ""
            itm["Detail"].PlainText = ""
            set_status(str(err), error=True)
            return None

        fps = timeline_fps(timeline, project)
        summary = [job_line(job, fps) for job in jobs[:200]]
        if len(picked) > 1:
            summary.insert(0, "x %d presets: %s"
                           % (len(picked), ", ".join(picked)))
        itm["Summary"].PlainText = "\n".join(summary)

        preview = []
        for job in jobs[:200]:
            # a one clip job would otherwise print its name twice
            if len(jobs) > 1 and len(job["clips"]) > 1:
                preview.append(job["name"])
                preview.extend("   " + name for name in job["clips"])
            else:
                preview.extend(job["clips"])
        itm["Detail"].PlainText = "\n".join(preview)

        set_status(note or state.get("preset_note", ""))
        return jobs

    def on_toggle(_event=None):
        apply_layout()
        refresh()

    def on_custom_only(_event=None):
        """Keep each row on its preset if that preset survives the filter."""
        try:
            keep = chosen_presets()
        except RuntimeError:
            keep = []
        state["preset_note"] = fill_presets(keep)
        apply_layout()
        refresh()

    def add_row(_event=None):
        if state["rows"] < MAX_PRESET_ROWS:
            state["rows"] += 1
            used = set()
            for index in range(state["rows"] - 1):
                used.add(itm["Preset%d" % index].CurrentIndex)
            for position in range(len(state["presets"])):
                if position not in used:
                    itm["Preset%d" % (state["rows"] - 1)].CurrentIndex = \
                        position
                    break
        refresh()

    def remove_row(_event=None):
        if state["rows"] > 1:
            state["rows"] -= 1
        refresh()

    def browse(_event=None):
        current = itm["TargetDir"].Text or ""
        picked = None
        try:
            picked = fusion_app.RequestDir(current)
        except Exception:
            picked = None
        if picked:
            itm["TargetDir"].Text = str(picked)
            refresh()
        else:
            set_status("no folder picked, type a path instead")

    def remember():
        try:
            picked = chosen_presets()
        except Exception:
            picked = []
        save_settings({
            "presets": picked,
            "scope": current_scope(),
            "per_clip": per_clip_on(),
            "target_dir": itm["TargetDir"].Text,
            "reel_preset": current_reel_preset(),
            "reel_chars": itm["ReelChars"].Text,
            "reel_regex": itm["ReelRegex"].Text,
            "start_render": bool(itm["StartRender"].Checked),
            "individual_clips": bool(itm["Individual"].Checked),
            "custom_only": bool(itm["CustomOnly"].Checked),
            "show_preview": preview_on(),
        })

    # ---- queue
    def queue(_event=None):
        target = (itm["TargetDir"].Text or "").strip()
        if not target:
            set_status("set a destination folder first", error=True)
            return
        if not os.path.isdir(target):
            set_status("destination does not exist: %s" % target, error=True)
            return

        jobs = refresh()
        if not jobs:
            return
        try:
            picked = chosen_presets()
        except RuntimeError as err:
            set_status(str(err), error=True)
            return

        itm["QueueButton"].Enabled = False
        set_status("queueing")

        page = call_any(resolve_app, ["GetCurrentPage"])
        if TOUCH_DELIVER_PAGE:
            call_any(resolve_app, ["OpenPage"], "deliver")

        try:
            queued, lines = queue_jobs(project, timeline, picked, target,
                                       jobs, bool(itm["Individual"].Checked))
        except RuntimeError as err:
            itm["QueueButton"].Enabled = True
            if page:
                call_any(resolve_app, ["OpenPage"], page)
            set_status(str(err), error=True)
            return

        itm["QueueButton"].Enabled = True
        itm["Summary"].PlainText = "\n".join(lines)
        remember()

        if DRY_RUN:
            if page:
                call_any(resolve_app, ["OpenPage"], page)
            set_status("dry run, nothing queued")
            return

        # Checked before starting: a wrong range must never reach disk.
        bad = [line.strip() for line in lines
               if "MISMATCH" in line or "UNREADABLE" in line]
        if bad:
            kept = [job_id for job_id in queued
                    if not call_any(project, ["DeleteRenderJob"], job_id)]
            if page:
                call_any(resolve_app, ["OpenPage"], page)
            message = ("frames came back wrong, nothing started, removed "
                       "the %d job%s this run added"
                       % (len(queued) - len(kept),
                          "" if len(queued) - len(kept) == 1 else "s"))
            if kept:
                message += ", could not remove %s" % ", ".join(kept)
            set_status(message, error=True)
            return

        started = None
        if itm["StartRender"].Checked and queued:
            started = start_rendering(project, queued)

        # Resolve 21.1.2 moves to Deliver as soon as a job is queued and
        # stays there through the render, so this goes last.
        if page:
            call_any(resolve_app, ["OpenPage"], page)

        message = "queued %d job%s" % (len(queued),
                                       "" if len(queued) == 1 else "s")
        if itm["StartRender"].Checked:
            message += ", rendering" if started else \
                ", render did not start"
        failed = itm["StartRender"].Checked and not started
        set_status(message, error=failed)
        if CLOSE_ON_SUCCESS and not failed:
            close()

    def close(_event=None):
        remember()
        disp.ExitLoop()

    def on_key(event):
        """Escape closes. Qt sends unhandled keys up from the fields."""
        try:
            key = event["Key"]
        except Exception:
            return
        if key == 0x01000000:               # Qt::Key_Escape
            close()

    win.On.RenderItWin.Close = close
    win.On.RenderItWin.KeyPress = on_key
    win.On.CloseButton.Clicked = close
    win.On.QueueButton.Clicked = queue
    win.On.RefreshButton.Clicked = refresh
    win.On.BrowseButton.Clicked = browse
    win.On.AddPreset.Clicked = add_row
    win.On.RemovePreset.Clicked = remove_row
    win.On.Scope.CurrentIndexChanged = on_toggle
    win.On.PerClip.Clicked = refresh
    win.On.ReelPreset.CurrentIndexChanged = on_toggle
    win.On.ShowPreview.Clicked = on_toggle
    win.On.CustomOnly.Clicked = on_custom_only
    for index in range(MAX_PRESET_ROWS):
        try:
            setattr(getattr(win.On, "Preset%d" % index),
                    "CurrentIndexChanged", refresh)
        except Exception:
            pass
    for field in ("ReelChars", "ReelRegex", "TargetDir"):
        for event in ("EditingFinished", "ReturnPressed"):
            try:
                setattr(getattr(win.On, field), event, refresh)
            except Exception:
                pass                        # not every build exposes both

    state["preset_note"] = fill_presets()
    apply_layout()
    refresh()
    win.Show()
    disp.RunLoop()
    win.Hide()


def start_rendering(project, job_ids):
    """Non interactive so a bad job cannot pop a modal behind the window."""
    for args in ((job_ids, False), (job_ids,)):
        try:
            result = project.StartRendering(*args)
            if result:
                return True
        except Exception:
            continue
    return False


def main():
    resolve_app = get_resolve()
    if not resolve_app:
        print("Render It: could not reach Resolve")
        return
    try:
        project, timeline = gather(resolve_app)
        run_gui(resolve_app, project, timeline)
    except RuntimeError as err:
        print("Render It: %s" % err)


if __name__ in ("__main__", "__builtin__", "builtins"):
    main()
