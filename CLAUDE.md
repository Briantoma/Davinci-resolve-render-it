# Render It

## What it is

A DaVinci Resolve script that adds the current reel, the selected clips, or
the in/out range to the render queue using saved render presets, without
leaving the Color page. The Quick Export window, with our presets and our
reel logic.

Current version: `Render_It_V0.05.py`, becoming `Render_It.py` from V0.06.
Launched once in Resolve (Sep 19) but nothing was checked, so nothing below
is proven against the real API. Read "Verify first".

## Environment

- DaVinci Resolve Studio 21.1, macOS, Python 3.
- Studio is mandatory. 21.1 moved all Python scripting to Studio, and
  UIManager has been Studio only since 19.1. On free Resolve the script
  cannot run at all, and there is no workaround to build.
- Install path:
  `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/`
  Utility, not Color, so it appears in Workspace > Scripts on every page.
  From V0.06 that folder holds a symlink to `Render_It.py` in this repo,
  so every commit is live in Resolve. If Resolve refuses to run a
  symlinked script, copy the file instead.
- Settings persist to `render_it_settings.json` in the Utility folder.
  It stays there across versions, never in the repo.
- Git is local only, no remote. `append_it.py` (same Utility folder) is
  a separate tool and out of scope here.

## Conventions, follow these

- The filename is fixed, `Render_It.py`, from V0.06 on. The version lives
  in `VERSION` and in the window title, and goes up on every change.
  Changelog lines at the top of the docstring, one per version, newest
  last. One commit per version.
- Ask Thomas what a new file should be called before creating it.
- No bold and no em dashes in anything he will read.
- Comments explain why, not what. If a line exists because of an API quirk,
  the comment names the quirk.
- Errors reach the user verbatim in the status line, in red. Never collapse
  a real failure into a generic message, and never swallow one.
- Refuse rather than guess. Ambiguous input gets a message saying what is
  ambiguous.
- `try/except` around anything build specific, with a working fallback.

## Shape of the file

```
settings            constants at the top, all the behaviour switches
plumbing            get_resolve, get_fusion, get_dispatcher, as_list,
                    call_any, settings load and save
timeline math       reel_key, reel_scope, selected_clips, clip_extent,
                    inout_extent, all_video_items, clips_in_range
job build           build_jobs returns job dicts, queue_jobs queues them
                    and reads each one back, start_rendering
run_gui             everything UI, one function, closures over itm
main                entry point
```

A job is a dict: `name`, `in`, `out`, `clips` (the clip names it covers),
`reel` (set only when the job is one whole reel). Frames are inclusive on
both ends. `GetEnd()` is exclusive in Resolve, `clip_extent` subtracts one.

## Verify first, these are assumptions not facts

Nothing here is a bug yet. They are things the documentation does not
answer and the stubs cannot prove.

Proven on Resolve Studio 21.1.2, 2026-11-09, through external scripting
on a 25 fps timeline starting at 01:00:00:00 (frame 90000), using the
V0.05 functions and the 00_SrcePxy preset:

- Item 1 settled: absolute frames are right, keep `MARK_FRAMES_ABSOLUTE`
  True. A reel job sent 90000 to 107739 was stored exactly so, and a
  single clip render of 91000 to 91049 came out 2.000 s, 50 frames, so
  the inclusive out and the `GetEnd() - 1` in `clip_extent` are right.
- Item 2 settled: settings applied without opening Deliver first, keep
  `TOUCH_DELIVER_PAGE` False.
- Item 3 settled: `GetMarkInOut` returns `{"video": {"in", "out"},
  "audio": {...}}` in absolute frames, and `SetMarkInOut` takes absolute
  frames.
- `StartRendering(job_ids, False)` works, `DeleteRenderJob` works.
- `LoadRenderPreset` and `SetCurrentRenderMode` switch Resolve to
  Deliver, and it stays there after rendering. The window's page restore
  at the end of `queue()` is what brings it back.
- Render mode does not reliably come from the preset. Loading "Edit"
  always gave single clip, but "00_SrcePxy" and "DNX" kept whatever mode
  Deliver was already in. This undercuts `FOLLOW_PRESET_RENDER_MODE`,
  see Open items.
- `GetCurrentTimecode` returns the playhead as timeline timecode, which
  converts to the same absolute frames as `GetStart()` (V0.06 relies on
  this to find the reel under the playhead). Drop frame is untested.
- In Individual clips mode Resolve widens MarkIn/MarkOut to whole clips:
  an in/out of 91000 to 91049 was stored as 90000 to 92333, the clip it
  sits in. V0.05 reports this as a mismatch.
- Not covered: the window itself (UIManager items in 5), selected clips
  scope (the API cannot select clips), and the page restore run from
  inside the window (6).

1. `MARK_FRAMES_ABSOLUTE`. The script sends absolute timeline frames
   (86400 at 01:00:00:00) to `SetRenderSettings`. Every job is read back
   out of `GetRenderJobList` and compared, and the status line says
   "frames came back wrong" on a mismatch. If that fires, flip the
   constant to False, which sends frames counted from the timeline start.
2. `TOUCH_DELIVER_PAGE`. Render settings may need the Deliver page to have
   been opened once in the session. Off by default because it costs a
   visible page flash. Turn on only if settings come back wrong.
3. `GetMarkInOut` shape. Assumed `{"video": {"in": n, "out": n}}`. A value
   below the timeline start frame is treated as relative and shifted.
4. `GetSelectedClips` needs 21.0.4 or newer, and may return audio items.
   The script cross references unique ids against the video tracks and
   drops anything that is not on one.
5. `ComboBox.Clear()`, assigning `win.Geometry`, `win.RecalcLayout()`,
   `fusion.RequestDir()`, and `StartRendering(job_ids, False)`. All
   guarded, all unproven on 21.1.
6. Whether Resolve stays on Color once a render is running. The script
   restores the page after starting, but Resolve may pull itself back to
   Deliver.
7. Whether a keyboard shortcut can be bound to a script in 21.1. Could not
   confirm either way. If not, a Stream Deck button sending the menu click
   is the fallback.

## Decisions already taken, do not quietly reverse them

- Render mode comes from the preset. `FOLLOW_PRESET_RENDER_MODE` is True
  and the script does not call `SetCurrentRenderMode`. A tick in the window
  was considered and rejected: it would be a third place the mode is
  decided and it would silently win over the preset. The queue report names
  the mode each preset used instead. Thomas may still ask for the tick.
- `CustomName` is only honoured in single clip mode. A preset set to
  individual clips ignores our names, which is right for dailies and wrong
  for one job per clip. The report says so when both happen together.
- Custom presets are identified by excluding a hardcoded list of the 37
  factory names from a stock 21.1 install, because the API exposes no
  origin flag. A renamed or newly added factory preset reappears in the
  list, which is a cosmetic miss, not a break.
- Two presets writing the same container would overwrite each other, so
  with more than one preset selected the preset name is appended to the
  filename. Single preset, no suffix. `SUFFIX_PRESET_NAME`.
- The same preset in two rows is refused, not deduplicated.
- Reel detection shares its five naming presets with the clip insertion
  script so a reel means the same thing in both. Changing one means
  changing the other.
- Gaps and overlaps are reported in plain text. Red is only for things
  that stopped the queue.
- Window closes on success, stays open on failure with the error visible.
- The reel chars and regex fields live on their own row. Toggling a field
  inside the dropdown's row made it render on top of the dropdown.
- Settings path is resolved lazily and never uses `__file__` at module
  level, because Resolve execs menu scripts and `__file__` is undefined.
  That crashed V0.01 on first launch.

Taken with Thomas on 2026-11-09, for V0.06:

- The frame check runs before `StartRendering`. A mismatch, or a job that
  cannot be read back, means no start, red status, window stays open.
  In that case the script deletes the jobs it added in that run, and only
  those, and says so. Jobs it did not add are never touched.
- One job mode (current reel, selected clips) refuses when a clip that is
  not part of the reel or selection sits inside the range, and names it.
  Only tracks that hold a reel or selected clip are checked, so a title
  or adjustment clip on another track does not trigger it. One job per
  clip mode is not affected.
- Current reel looks down the tracks for the first item under the
  playhead whose name matches the reel pattern, so a title or adjustment
  clip on V2 does not block it. Refuses only when nothing matches.
- With a preset in Individual clips mode, Resolve widens the range to
  whole clips. The read back accepts that range and the report says
  "widened to whole clips by Individual clips" in plain text. Anything
  else that differs is still a mismatch.
- Known side effect, accepted: after a run, the Deliver page keeps the
  last preset loaded, our in/out, `SelectAllFrames` off and our custom
  name. The API cannot read every setting back, so restoring them would
  be a guess.

## Testing

`python3 test_render_it.py` runs 37 checks with no Resolve, no licence and
no GUI. It fakes UIManager (widgets, group collection, event slots) and the
Resolve objects, drives the real `run_gui`, and asserts on what would have
been queued. It picks the newest `Render_It_V*.py` automatically, and
loads `Render_It.py` from V0.06.

Add a check for every behaviour you add. It catches wiring mistakes, not
API mistakes. Anything in "Verify first" is outside what it can see.

## Open items

- V0.06 job code is checked against Resolve 21.1.2 through external
  scripting. Still to click through by hand: the window itself, selected
  clips scope, the symlinked install, and the page restore from inside
  the window.
- Render mode: decide whether the window forces it, since presets do not
  reliably carry it (see Verify first).
- Thomas may want the individual clips tick after all.
- `Custom` is not in the factory list he pasted. If a preset by that name
  shows in the dropdown, add it.
- No UI for creating render presets, and there should not be. That is the
  Deliver page's job.
