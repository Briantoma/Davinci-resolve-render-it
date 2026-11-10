# Render It

A DaVinci Resolve script that adds the current reel, the highlighted clips or
the in/out range to the render queue with your saved render presets, without
leaving the Color page. Think of the Quick Export window, with your own
presets and reel logic.

Built for dailies, where each camera roll gets rendered as it comes in and a
missing clip or a wrong range has to be caught before it reaches the drive.

Generated with Claude.

Don't hesitate to reach out for bugs and feature requests.

<img src="docs/Render It_1.jpg" alt="The Render It window" width="700">

## Requirements

DaVinci Resolve Studio 21.1 or later. From 21.1, Python scripting and script
windows are Studio only, so the script cannot run on the free version.

Tested on Studio 21.1.2, macOS. It should work on Windows and Linux but has
not been tested there.

## Install

Copy `Render_It.py` into your Resolve scripts folder:

- macOS: `~/Library/Application Support/Blackmagic Design/DaVinci Resolve/Fusion/Scripts/Utility/`
- Windows: `%APPDATA%\Blackmagic Design\DaVinci Resolve\Support\Fusion\Scripts\Utility\`
- Linux: `~/.local/share/DaVinciResolve/Fusion/Scripts/Utility/`

It then appears under Workspace > Scripts on every page. Restart Resolve if
it does not. The filename stays the same from one version to the next, the
version shows in the window title.

## Use

Open the script, pick a preset, a selection and a destination, and press Add
to queue. Enter does the same, Escape closes. Only one window opens at a
time, launching it again brings the open one forward.

### Selection

- Current reel: every clip of the reel under the playhead, found on any
  track, so a title or adjustment clip on V2 does not get in the way.
- Selected clips: the clips highlighted in the timeline. On the Color page
  Resolve always counts the current clip as selected, so it is left out
  there. Move the playhead off a clip to include it.
- In/Out range: the timeline in and out points. With an in point and no
  out point, it renders to the end of the timeline.

Reels are detected from the clip name, with the same five naming schemes as
Append It, from `A001` camera letter plus reel number through to a custom
regular expression.

### Presets

The dropdown lists your own render presets. Factory presets are hidden by
name, untick Show custom presets only to see them all. Up to six presets can
be queued in one go with the + button. With more than one, the preset name is
added to each file name so two presets writing the same format do not
overwrite each other.

### Options

- One job per clip: a render job for each clip instead of one for the whole
  selection.
- Start rendering after adding: starts the jobs just queued, and only those.
- Individual clips: the render mode, set on every run. Resolve presets do not
  reliably carry it, so the window decides.
- Preview the clip selection: lists every clip that will be rendered.

### File names

A preset set to Source name keeps the source file names. A preset with a
custom name gets the job name instead: the reel, the clip or the timeline.

## Checks before anything renders

- Every job is read back from the render queue after it is added. If the
  frames Resolve stored are not the ones sent, nothing starts, the jobs this
  run added are removed again, and the status line says so in red.
- In Individual clips mode Resolve widens the range to whole clips. That is
  expected and reported, not treated as an error.
- A one job range is refused if a clip that is not part of the reel or the
  selection sits inside it on the same track, since it would be rendered too.
  The message names the clip.
- Clip numbers are checked from C001 up. If a reel is missing any, a pop up
  lists them and asks before queueing.
- Empty gaps between clips are noted in the status line.

## How it works with Resolve

Worth knowing if you read the code and wonder why it is not simpler. All of
this was measured on Studio 21.1.2.

- In and out points are sent as absolute timeline frames, 90000 at
  01:00:00:00 on a 25 fps timeline.
- `LoadRenderPreset` does nothing when that preset is already loaded, so
  settings from an earlier run would survive it. The script loads another
  preset first to force a real reload.
- The API has no way to read a preset's file naming, so the preset is
  exported to a temporary folder and read from there.
- Loading a preset or setting the render mode switches Resolve to the Deliver
  page. The script returns to the page you were on.
- Resizing an open script window does not work, so the window opens tall
  enough for a long clip list.

## Limitations

After a run, the Deliver page keeps the last preset loaded with the range and
name of the last job. The API cannot read every setting back, so the script
does not try to restore them.

Missing clips after the last clip of a reel cannot be detected.

## Settings

Everything you set in the window is remembered in `render_it_settings.json`,
in the scripts folder. The file is per user, not per project.

## Tests

`python3 test_render_it.py` runs the window and the job logic against fake
Resolve objects, with no Resolve and no licence. It catches wiring mistakes,
not API changes.

## Licence

MIT
