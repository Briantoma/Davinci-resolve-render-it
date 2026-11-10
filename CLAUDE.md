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
- Git remote: public repo github.com/Briantoma/Davinci-resolve-render-it
  (since 2026-11-09). README.md is the user facing doc, keep it in step. `append_it.py` (same Utility folder) is
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
  Deliver was already in. V0.07 sets the mode from a tick instead.
- On the Color page `GetSelectedClips` always lists the current clip
  first, whether it is highlighted or not. With nothing highlighted it
  returns the current clip alone. There is no way to tell a highlighted
  current clip from an unhighlighted one, so on Color the Selected clips
  scope always leaves the current clip out (Thomas, 2026-11-09). To
  include it, move the playhead off it. Other pages are untouched, their
  behaviour is untested.
- `LoadRenderPreset` does nothing when that preset is already the loaded
  one, so settings sent by an earlier run (a `CustomName`) survive it.
  `load_preset` loads another preset first to force a real reload.
- `ExportRenderPreset` lives on the Resolve object, not the project, and
  makes a folder at the given path with the preset file inside.
- `GetCurrentTimecode` returns the playhead as timeline timecode, which
  converts to the same absolute frames as `GetStart()` (V0.06 relies on
  this to find the reel under the playhead). Drop frame is untested.
- In Individual clips mode Resolve widens MarkIn/MarkOut to whole clips:
  an in/out of 91000 to 91049 was stored as 90000 to 92333, the clip it
  sits in. V0.05 reports this as a mismatch.
- Not covered: the window itself (UIManager items in 5), and the page restore run from
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

- Render mode comes from the Individual clips tick in the window, set with
  `SetCurrentRenderMode` on every run and read back; Resolve keeping
  another mode stops the queue in red. Reversed on 2026-11-09 from "the
  preset decides" (V0.05), because 21.1.2 presets do not reliably carry
  the mode, so the same preset queued differently depending on what was
  last done on Deliver. The tick is saved as `individual_clips`.
- File names follow the preset (V0.08). A preset set to Source name gets
  no `CustomName`, so it keeps source file names. A preset with a custom
  name gets the job name (reel, clip or timeline). The handover claim
  that `CustomName` is ignored in Individual clips mode was wrong: on
  21.1.2 it replaces the source names there too, which is the bug Thomas
  hit. The naming is read by exporting the preset to a temp folder and
  reading `UsePrefixAndSuffixFromSrc` (1 = Source name), since the API
  has no getter. If that cannot be read, the job name is used and the
  report says so.
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
- Current reel reports missing clip numbers (V0.10). The clip number is
  the C plus 2 to 4 digits right after the reel part of the name
  (C0003C015 gives 15), so it follows whichever reel naming preset is
  chosen. Proxy copies sharing a number count once. Every reel starts at
  C001 (Thomas, V0.13), so a reel starting at C003 is missing C001 and
  C002. Clips after the last one present cannot be seen.
- A reel with missing numbers opens a pop up before anything is queued:
  Queue anyway or Cancel (V0.13). It is a second UIManager window
  answered inside the same event loop, no nested RunLoop. Frame gaps
  between clips do not trigger it, they stay a plain text note.
- The window opens `WINDOW_START_H` (1000) tall and never asks for less
  (V0.11). Thomas saw on 21.1 that assigning `win.Geometry` does not
  resize an open window, so growing it with the preview did nothing.
  Past 1000 it tries `win.Resize`, unproven; if that fails the preview
  scrolls. The preview wants 17 px a line, capped at `PREVIEW_MAX_H`.
- One window at a time (V0.12): `ui.FindWindow("RenderItWin")` finds an
  open window and a second launch brings it forward and stops. FindWindow
  exists on 21.1.2 and returns None with no window open; finding a window
  opened by another launch is unproven.
- Return or Enter presses Add to queue, so it starts the render only when
  the Start tick is on. Ignored while a queue is running.
- In/Out range with an in point and no out point renders to the end of
  the timeline, `GetEndFrame() - 1` (V0.14, Thomas). A lone out point is
  still refused.
- The status label wraps (V0.14). Unwrapped, a long note such as the
  missing clip list set the window's minimum width past the screen edge.
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
- `Custom` is not in the factory list he pasted. If a preset by that name
  shows in the dropdown, add it.
- Background rendering cannot be requested through the API on 21.1.2
  (checked 2026-11-10): SetRenderSettings refuses BackgroundRender,
  RenderInBackground, IsBackgroundRender and Background, presets do not
  store it, the job list has no field for it and StartRendering only takes
  isInteractiveMode. Only a job status 'Ready for background render'
  exists. To render in the background, leave Start unticked and start the
  queue from Deliver.
- No UI for creating render presets, and there should not be. That is the
  Deliver page's job.
