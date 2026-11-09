#!/usr/bin/env python3
"""
test_render_it.py

Offline tests for Render_It. No Resolve, no Studio licence, no GUI.

    python3 test_render_it.py                  # newest Render_It_V*.py
    python3 test_render_it.py Render_It_V0.05.py

It fakes two things:

  UIManager  every widget is a plain object with the attributes the script
             touches (Text, Checked, CurrentIndex, Enabled, Hidden,
             PlainText, StyleSheet) plus AddItem and Clear. AddWindow walks
             the nested group structure and collects everything with an ID,
             which is exactly what win.GetItems() returns in Resolve.
             RunLoop calls the test body instead of blocking.

  Resolve    Project, Timeline and TimelineItem stubs with only the methods
             the script calls. The project records every SetRenderSettings
             so the tests can assert on what would have been queued.

What it cannot tell you: whether Resolve accepts the MarkIn frame base,
whether ComboBox.Clear exists on your build, whether assigning win.Geometry
resizes anything, or whether a job renders. Those need the real thing.
"""

import glob
import importlib.util
import os
import sys

# ------------------------------------------------------------- fake UI


class Widget(object):
    def __init__(self, props):
        self.props = props
        self.items = []
        self.Text = props.get("Text", "")
        self.Checked = props.get("Checked", False)
        self.CurrentIndex = 0
        self.Enabled = True
        self.Hidden = False
        self.StyleSheet = ""
        self.PlainText = ""

    def AddItem(self, name):
        self.items.append(name)

    def Clear(self):
        self.items = []

    def current(self):
        return self.items[self.CurrentIndex] if self.items else None


class UIManager(object):
    def __getattr__(self, _kind):
        def make(props, children=None):
            return {"props": props, "children": children or []}
        return make


def collect(node, out):
    if isinstance(node, list):
        for child in node:
            collect(child, out)
        return
    if not isinstance(node, dict):
        return
    ident = node["props"].get("ID")
    if ident:
        out[ident] = Widget(node["props"])
    collect(node.get("children"), out)


class Slots(object):
    def __getattr__(self, name):
        return self.__dict__.setdefault(name, type("Slot", (), {})())


class Window(object):
    def __init__(self, props, children):
        self.Geometry = list(props["Geometry"])
        self.items = {}
        collect(children, self.items)
        self.On = Slots()
        self.layouts = 0

    def GetItems(self):
        return self.items

    def RecalcLayout(self):
        self.layouts += 1

    def Show(self):
        pass

    def Hide(self):
        pass


class Dispatcher(object):
    def __init__(self, bucket):
        self.bucket = bucket

    def AddWindow(self, props, children):
        window = Window(props, children)
        self.bucket["win"] = window
        return window

    def ExitLoop(self):
        self.bucket["closed"] = True

    def RunLoop(self):
        self.bucket["body"](self.bucket["win"])


class Fusion(object):
    UIManager = UIManager()

    def RequestDir(self, _current):
        return "/tmp"


# -------------------------------------------------------- fake Resolve

FACTORY = ["H.264 Master", "HyperDeck", "ProRes 422 HQ", "YouTube - 1080p",
           "Audio Only", "Premiere XML", "AVID AAF", "IMF - Netflix"]
CUSTOM = ["SL Dailies ProRes", "SL Review H264", "VFX Pull EXR"]


class Project(object):
    def __init__(self, presets=None, mode=1):
        self.presets = presets if presets is not None else FACTORY + CUSTOM
        self.mode = mode
        self.jobs = []
        self.started = None
        self.last = {}

    def GetRenderPresetList(self):
        return list(self.presets)

    def GetSetting(self, _key):
        return "25.0"

    def LoadRenderPreset(self, name):
        return name in self.presets

    def GetCurrentRenderMode(self):
        return self.mode

    def SetCurrentRenderMode(self, mode):
        self.mode = mode
        return True

    def SetRenderSettings(self, settings):
        self.last = dict(settings)
        return True

    def AddRenderJob(self):
        job_id = "job%d" % (len(self.jobs) + 1)
        record = dict(self.last)
        record["JobId"] = job_id
        self.jobs.append(record)
        return job_id

    def GetRenderJobList(self):
        return list(self.jobs)

    def StartRendering(self, job_ids, _interactive=None):
        self.started = list(job_ids)
        return True


class Item(object):
    def __init__(self, name, start, end, uid):
        self.name, self.start, self.end, self.uid = name, start, end, uid

    def GetName(self):
        return self.name

    def GetStart(self):
        return self.start

    def GetEnd(self):            # exclusive, as Resolve reports it
        return self.end

    def GetUniqueId(self):
        return self.uid


class Timeline(object):
    """Three A001 clips with a gap, one B001, one unmatched, one on V2."""

    def __init__(self):
        self.v1 = [
            Item("A001C003_230412", 86400, 86500, "1"),
            Item("B001C001_230412", 86500, 86600, "2"),
            Item("A001C005_230412", 86600, 86800, "3"),
            Item("A001C007_230412", 86900, 87000, "4"),
            Item("slate.mov", 87000, 87050, "5"),
        ]
        self.v2 = [Item("A001C009_230412", 86950, 87010, "6")]
        self.selection = []
        self.playhead = self.v1[0]
        self.marks = {"video": {"in": 100, "out": 339}}

    def GetName(self):
        return "EP01_REEL_A"

    def GetStartFrame(self):
        return 86400

    def GetSetting(self, _key):
        return "25.0"

    def GetTrackCount(self, _kind):
        return 2

    def GetItemListInTrack(self, _kind, index):
        track = self.v1 if index == 1 else self.v2
        return dict((n + 1, item) for n, item in enumerate(track))

    def GetSelectedClips(self):
        return dict((n + 1, i) for n, i in enumerate(self.selection))

    def GetCurrentVideoItem(self):
        return self.playhead

    def GetMarkInOut(self):
        return self.marks


class App(object):
    def __init__(self):
        self.page = "color"

    def GetCurrentPage(self):
        return self.page

    def OpenPage(self, page):
        self.page = page
        return True


# ------------------------------------------------------------- harness

def load(path):
    spec = importlib.util.spec_from_file_location("render_it", path)
    module = importlib.util.module_from_spec(spec)
    sys.modules["render_it"] = module
    spec.loader.exec_module(module)
    module.settings_path = lambda: "/tmp/render_it_test_settings.json"
    try:
        os.remove("/tmp/render_it_test_settings.json")
    except OSError:
        pass
    return module


def drive(module, body, project=None, timeline=None, app=None):
    """Run the window, hand the test body the widgets, return everything."""
    bucket = {"body": body}
    module.get_fusion = lambda _app: Fusion()
    module.get_dispatcher = lambda _ui: Dispatcher(bucket)
    project = project or Project()
    timeline = timeline or Timeline()
    app = app or App()
    module.run_gui(app, project, timeline)
    return bucket["win"], project, timeline, app


RESULTS = []


def check(label, condition, detail=""):
    RESULTS.append((label, bool(condition), detail))


# --------------------------------------------------------------- tests

def test_reel_detection(m):
    cfg = ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4)
    keys = [m.reel_key(n, *cfg) for n in
            ("A001C003", "A_0001C004", "B001C001", "slate.mov")]
    check("reel keys", keys == ["A001", "A0001", "B001", None], str(keys))
    check("first_n", m.reel_key("A_0001C004", "first_n", None, 6) == "A_0001")
    try:
        m.reel_key("A001", "custom", "^(?P<cam>[A-Z", 4)
        check("bad regex reported", False)
    except RuntimeError:
        check("bad regex reported", True)


def test_jobs(m):
    timeline = Timeline()
    jobs, note = m.build_jobs(timeline, "reel", False,
                              ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4))
    check("reel one job", len(jobs) == 1 and jobs[0]["reel"] == "A001")
    check("reel clip count", len(jobs[0]["clips"]) == 4,
          str(jobs[0]["clips"]))
    check("gap reported", "gap" in note, note)

    jobs, _ = m.build_jobs(timeline, "reel", True,
                           ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4))
    check("reel per clip", len(jobs) == 4)
    check("per clip has no reel", all(j["reel"] is None for j in jobs))

    timeline.selection = [timeline.v1[2], timeline.v1[0]]
    jobs, _ = m.build_jobs(timeline, "selected", False)
    check("selection sorted", jobs[0]["in"] == 86400 and
          jobs[0]["out"] == 86799)
    check("selection has no reel", jobs[0]["reel"] is None)

    jobs, _ = m.build_jobs(timeline, "inout", False)
    check("inout shifted to absolute", jobs[0]["in"] == 86500,
          str(jobs[0]["in"]))

    timeline.playhead = timeline.v1[4]
    try:
        m.build_jobs(timeline, "reel", False,
                     ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4))
        check("unmatched playhead refused", False)
    except RuntimeError as err:
        check("unmatched playhead refused", "slate.mov" in str(err))


def test_presets(m):
    names, custom = m.preset_names(Project())
    check("factory filtered", custom == CUSTOM, str(custom))
    check("full list kept", len(names) == len(FACTORY) + len(CUSTOM))
    _, none_custom = m.preset_names(Project(presets=FACTORY))
    check("no customs", none_custom == [])


def test_queue(m):
    project = Project(mode=1)
    jobs = [{"name": "A001", "in": 86400, "out": 86799,
             "clips": ["a", "b"], "reel": "A001"}]
    queued, lines = m.queue_jobs(project, Timeline(),
                                 ["SL Dailies ProRes", "SL Review H264"],
                                 "/tmp", jobs)
    check("two presets two jobs", len(queued) == 2)
    check("preset suffixed",
          project.jobs[0]["CustomName"] == "A001_SL Dailies ProRes",
          project.jobs[0]["CustomName"])
    check("mode reported", "single clip" in lines[0], lines[0])

    project = Project(mode=0)
    m.queue_jobs(project, Timeline(), ["SL Dailies ProRes"], "/tmp", jobs)
    check("preset mode left alone", project.mode == 0)

    project = Project()
    m.queue_jobs(project, Timeline(), ["SL Dailies ProRes"], "/tmp", jobs)
    check("single preset not suffixed",
          project.jobs[0]["CustomName"] == "A001")

    class Dead(Project):
        def AddRenderJob(self):
            return None
    try:
        m.queue_jobs(Dead(), Timeline(), ["SL Dailies ProRes"], "/tmp", jobs)
        check("dead queue refused", False)
    except RuntimeError as err:
        check("dead queue refused", "AddRenderJob" in str(err))


def test_window(m):
    seen = {}

    def body(win):
        itm = win.items
        seen["presets"] = list(itm["Preset0"].items)
        seen["summary"] = itm["Summary"].PlainText
        seen["preview"] = itm["Detail"].PlainText
        seen["preview_hidden"] = itm["Detail"].Hidden
        seen["short"] = win.Geometry[3]

        itm["ShowPreview"].Checked = True
        win.On.ShowPreview.Clicked(None)
        seen["tall"] = win.Geometry[3]

        itm["CustomOnly"].Checked = False
        win.On.CustomOnly.Clicked(None)
        seen["all"] = list(itm["Preset0"].items)
        seen["kept"] = itm["Preset0"].current()

        itm["CustomOnly"].Checked = True
        win.On.CustomOnly.Clicked(None)

        win.On.AddPreset.Clicked(None)
        seen["second_row"] = itm["Preset1"].current()
        itm["Preset1"].CurrentIndex = itm["Preset0"].CurrentIndex
        win.On.RefreshButton.Clicked(None)
        seen["duplicate"] = itm["Status"].Text
        seen["duplicate_red"] = bool(itm["Status"].StyleSheet)
        win.On.RemovePreset.Clicked(None)

        itm["ReelPreset"].CurrentIndex = m.PRESET_KEYS.index("first_n")
        win.On.ReelPreset.CurrentIndexChanged(None)
        seen["chars_shown"] = not itm["ReelChars"].Hidden
        seen["regex_shown"] = not itm["ReelRegex"].Hidden
        itm["ReelPreset"].CurrentIndex = 0
        win.On.ReelPreset.CurrentIndexChanged(None)

        itm["TargetDir"].Text = "/does/not/exist"
        win.On.QueueButton.Clicked(None)
        seen["bad_dir"] = itm["Status"].Text

        itm["TargetDir"].Text = "/tmp"
        itm["StartRender"].Checked = True
        win.On.QueueButton.Clicked(None)
        seen["queued_status"] = itm["Status"].Text
        seen["report"] = itm["Summary"].PlainText

    win, project, _timeline, app = drive(m, body)

    check("custom presets only by default", seen["presets"] == CUSTOM,
          str(seen["presets"]))
    check("default is reel, one job",
          seen["summary"].startswith("A001") and "reel A001" in
          seen["summary"], seen["summary"])
    check("preview lists clip names",
          "A001C003_230412" in seen["preview"])
    check("preview hidden by default", seen["preview_hidden"])
    check("preview grows the window", seen["tall"] > seen["short"],
          "%s -> %s" % (seen["short"], seen["tall"]))
    check("untick shows everything",
          len(seen["all"]) == len(FACTORY) + len(CUSTOM))
    check("row keeps its preset across the tick",
          seen["kept"] == CUSTOM[0], str(seen["kept"]))
    check("added row picks an unused preset",
          seen["second_row"] != CUSTOM[0], str(seen["second_row"]))
    check("duplicate refused", "twice" in seen["duplicate"],
          seen["duplicate"])
    check("duplicate is red", seen["duplicate_red"])
    check("chars field for first_n",
          seen["chars_shown"] and not seen["regex_shown"])
    check("missing folder refused", "does not exist" in seen["bad_dir"],
          seen["bad_dir"])
    check("queued and rendering", "rendering" in seen["queued_status"],
          seen["queued_status"])
    check("render started", project.started is not None)
    check("page restored", app.page == "color", app.page)
    check("report names the preset",
          CUSTOM[0] in seen["report"], seen["report"])


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        here = os.path.dirname(os.path.abspath(__file__))
        found = sorted(glob.glob(os.path.join(here, "Render_It_V*.py")))
        if not found:
            print("no Render_It_V*.py next to this file")
            return 2
        path = found[-1]

    module = load(path)
    print("testing %s (reports v%s)\n" % (os.path.basename(path),
                                          module.VERSION))
    for test in (test_reel_detection, test_jobs, test_presets,
                 test_queue, test_window):
        test(module)

    failed = 0
    for label, ok, detail in RESULTS:
        if ok:
            print("  pass  %s" % label)
        else:
            failed += 1
            print("  FAIL  %s   %s" % (label, detail))
    print("\n%d checks, %d failed" % (len(RESULTS), failed))
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
