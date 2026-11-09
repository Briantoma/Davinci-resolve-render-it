#!/usr/bin/env python3
"""
test_render_it.py

Offline tests for Render_It. No Resolve, no Studio licence, no GUI.

    python3 test_render_it.py                  # Render_It.py beside it
    python3 test_render_it.py other_copy.py

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
        self.deleted = []

    def GetRenderPresetList(self):
        return list(self.presets)

    def GetSetting(self, _key):
        return "25.0"

    def LoadRenderPreset(self, name):
        self.loads = getattr(self, "loads", []) + [name]
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

    def DeleteRenderJob(self, job_id):
        self.deleted.append(job_id)
        self.jobs = [j for j in self.jobs if j["JobId"] != job_id]
        return True

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
    """Three A001 clips with gaps, one on V2, then a slate and a B001."""

    def __init__(self):
        self.v1 = [
            Item("A001C003_230412", 86400, 86500, "1"),
            Item("A001C005_230412", 86600, 86800, "3"),
            Item("A001C007_230412", 86900, 87000, "4"),
            Item("slate.mov", 87000, 87050, "5"),
            Item("B001C001_230412", 87050, 87150, "2"),
        ]
        self.v2 = [Item("A001C009_230412", 86950, 86990, "6")]
        self.selection = []
        self.playhead = self.v1[0]
        self.tc = None
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

    def GetCurrentTimecode(self):
        return self.tc

    def GetMarkInOut(self):
        return self.marks


class App(object):
    """Presets whose name contains 'Dailies' are set to Source name."""

    def __init__(self):
        self.page = "color"

    def ExportRenderPreset(self, name, path):
        # 21.1.2 makes a folder at the path and writes the file inside it
        os.makedirs(path)
        with open(os.path.join(path, name + ".xml"), "w") as handle:
            handle.write("<UsePrefixAndSuffixFromSrc>%d"
                         "</UsePrefixAndSuffixFromSrc>"
                         % ("Dailies" in name))
        return True

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
    check("missing clip numbers reported",
          "clip numbers missing: C004, C006, C008" in note, note)
    sony = ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4)
    check("clip number after a C reel",
          m.clip_number("C0003C015_261106_175813N2_FSY48.mov", sony)
          == (15, 3))
    check("proxy copy same number", m.missing_clip_numbers(
        ["C0003C015_x.mov", "C0003C015_f0-2333.mov", "C0003C016_y.mov"],
        sony) == [])
    check("first_n clip number",
          m.clip_number("A_0001C004", ("first_n", None, 6)) == (4, 3))

    jobs, _ = m.build_jobs(timeline, "reel", True,
                           ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4))
    check("reel per clip", len(jobs) == 4)
    check("per clip has no reel", all(j["reel"] is None for j in jobs))

    timeline.selection = [timeline.v1[1], timeline.v1[0]]
    jobs, _ = m.build_jobs(timeline, "selected", False)
    check("selection sorted", jobs[0]["in"] == 86400 and
          jobs[0]["out"] == 86799)
    check("selection has no reel", jobs[0]["reel"] is None)

    jobs, _ = m.build_jobs(timeline, "inout", False)
    check("inout shifted to absolute", jobs[0]["in"] == 86500,
          str(jobs[0]["in"]))
    timeline.marks = {"video": {"out": 339}, "audio": {"out": 339}}
    try:
        m.build_jobs(timeline, "inout", False)
        check("lone out point refused", False)
    except RuntimeError as err:
        check("lone out point refused", "only an out point" in str(err),
              str(err))

    timeline.playhead = timeline.v1[3]
    try:
        m.build_jobs(timeline, "reel", False,
                     ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4))
        check("unmatched playhead refused", False)
    except RuntimeError as err:
        check("unmatched playhead refused", "slate.mov" in str(err))

    # A B camera clip dropped between A001 clips on V1
    timeline = Timeline()
    timeline.v1.insert(1, Item("B001C002_230412", 86500, 86600, "7"))
    cfg = ("cam_letter", m.DEFAULT_CUSTOM_REGEX, 4)
    try:
        m.build_jobs(timeline, "reel", False, cfg)
        check("stranger in reel refused", False)
    except RuntimeError as err:
        check("stranger in reel refused",
              "B001C002_230412" in str(err) and "reel A001" in str(err),
              str(err))
    jobs, _ = m.build_jobs(timeline, "reel", True, cfg)
    check("stranger fine per clip", len(jobs) == 4)
    timeline.selection = [timeline.v1[0], timeline.v1[2]]
    try:
        m.build_jobs(timeline, "selected", False)
        check("stranger in selection refused", False)
    except RuntimeError as err:
        check("stranger in selection refused", "not selected" in str(err),
              str(err))
    timeline.selection = [timeline.v1[0], timeline.v1[1]]
    jobs, _ = m.build_jobs(timeline, "selected", False)
    check("adjacent selection fine", jobs[0]["out"] == 86599)

    # Color page: Resolve lists the current clip first, highlighted or not
    timeline = Timeline()
    timeline.playhead = timeline.v1[2]
    timeline.selection = [timeline.v1[2], timeline.v1[0], timeline.v1[1]]
    jobs, _ = m.build_jobs(timeline, "selected", False, skip_current=True)
    check("current clip left out on Color",
          jobs[0]["clips"] == ["A001C003_230412", "A001C005_230412"],
          str(jobs[0]["clips"]))
    timeline.selection = [timeline.v1[2]]
    try:
        m.build_jobs(timeline, "selected", True, skip_current=True)
        check("only the current clip refused", False)
    except RuntimeError as err:
        check("only the current clip refused",
              "no clips highlighted" in str(err), str(err))

    # A title on V2 over everything is not a stranger to a V1 reel
    timeline = Timeline()
    timeline.v2 = [Item("Title", 86400, 87000, "8")]
    jobs, _ = m.build_jobs(timeline, "reel", False, cfg)
    check("other track ignored", jobs[0]["out"] == 86999)

    # Adjustment clip on V2 is the current item, the reel is under it on V1
    timeline.v2 = [Item("Adjustment Clip", 86400, 87000, "9")]
    timeline.playhead = timeline.v2[0]
    timeline.tc = "00:57:46:00"          # frame 86650 at 25, in A001C005
    jobs, _ = m.build_jobs(timeline, "reel", False, cfg)
    check("reel found under V2", jobs[0]["reel"] == "A001")
    timeline.tc = "00:58:02:00"          # frame 87050, B001C001
    jobs, _ = m.build_jobs(timeline, "reel", False, cfg)
    check("next track down wins", jobs[0]["reel"] == "B001",
          str(jobs[0]["reel"]))

    check("tc to frames", m.tc_to_frames("01:00:00:00", 25) == 90000)
    check("drop frame tc", m.tc_to_frames("01:00:00;00", 29.97) == 107892,
          str(m.tc_to_frames("01:00:00;00", 29.97)))


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
    check("single clip forced when unticked", project.mode == 1)
    project = Project(mode=1)
    _, lines = m.queue_jobs(project, Timeline(), ["SL Dailies ProRes"],
                            "/tmp", jobs, individual=True)
    check("individual forced when ticked",
          project.mode == 0 and "individual clips" in lines[0], lines[0])

    class Stubborn(Project):
        def SetCurrentRenderMode(self, mode):
            return False
    try:
        m.queue_jobs(Stubborn(mode=1), Timeline(), ["SL Dailies ProRes"],
                     "/tmp", jobs, individual=True)
        check("refused mode reported", False)
    except RuntimeError as err:
        check("refused mode reported", "kept render mode" in str(err),
              str(err))

    project = Project()
    m.queue_jobs(project, Timeline(), ["SL Dailies ProRes"], "/tmp", jobs)
    check("single preset not suffixed",
          project.jobs[0]["CustomName"] == "A001")

    class Widening(Project):
        def AddRenderJob(self):
            job_id = Project.AddRenderJob(self)
            self.jobs[-1].update(MarkIn=86600, MarkOut=86799)
            return job_id
    inside = [{"name": "x", "in": 86650, "out": 86699, "clips": [],
               "reel": None}]
    _, lines = m.queue_jobs(Widening(), Timeline(),
                            ["SL Dailies ProRes"], "/tmp", inside,
                            individual=True)
    check("individual widening accepted",
          "widened" in lines[1] and "MISMATCH" not in lines[1], lines[1])
    _, lines = m.queue_jobs(Widening(), Timeline(),
                            ["SL Dailies ProRes"], "/tmp", inside)
    check("single clip widening is a mismatch", "MISMATCH" in lines[1],
          lines[1])

    project = Project()
    _, lines = m.queue_jobs(project, Timeline(),
                            ["SL Dailies ProRes", "SL Review H264"], "/tmp",
                            jobs, resolve_app=App())
    check("source name preset gets no CustomName",
          "CustomName" not in project.jobs[0], str(project.jobs[0]))
    check("source name reported", "from the source" in lines[0], lines[0])
    check("source job labelled", lines[1].strip().startswith(
        "A001, source names"), lines[1])
    check("custom preset still named",
          project.jobs[1].get("CustomName") == "A001_SL Review H264",
          str(project.jobs[1]))
    check("preset reloaded through another",
          project.loads[:2] == [FACTORY[0], "SL Dailies ProRes"],
          str(project.loads))
    _, lines = m.queue_jobs(Project(), Timeline(), ["SL Dailies ProRes"],
                            "/tmp", jobs)
    check("unreadable naming said", "could not read" in lines[0], lines[0])

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
        itm["Individual"].Checked = True
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
    check("window opens tall", seen["short"] == m.WINDOW_START_H,
          str(seen["short"]))
    check("short preview fits the start height",
          seen["tall"] == m.WINDOW_START_H, str(seen["tall"]))
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
    check("tick sets individual mode", project.mode == 0)
    check("tick remembered",
          m.load_settings().get("individual_clips") is True)
    check("report names the preset",
          CUSTOM[0] in seen["report"], seen["report"])


class Shifted(Project):
    """Stores every job one frame late, like a wrong frame base would."""

    def AddRenderJob(self):
        job_id = Project.AddRenderJob(self)
        self.jobs[-1]["MarkIn"] += 1
        return job_id


def test_bad_frames_block_start(m):
    seen = {}

    def body(win):
        itm = win.items
        itm["TargetDir"].Text = "/tmp"
        itm["StartRender"].Checked = True
        win.On.QueueButton.Clicked(None)
        seen["status"] = itm["Status"].Text
        seen["red"] = bool(itm["Status"].StyleSheet)

    project = Shifted()
    project.jobs.append({"JobId": "theirs", "MarkIn": 1, "MarkOut": 2})
    win, project, _t, app = drive(m, body, project=project)
    check("bad frames: no start", project.started is None)
    check("bad frames: own job removed", project.deleted == ["job2"],
          str(project.deleted))
    check("bad frames: other jobs kept",
          [j["JobId"] for j in project.jobs] == ["theirs"])
    check("bad frames: red status",
          seen["red"] and "nothing started" in seen["status"],
          seen["status"])
    check("bad frames: page restored", app.page == "color", app.page)


def test_long_preview(m):
    seen = {}

    def body(win):
        itm = win.items
        itm["ShowPreview"].Checked = True
        win.On.ShowPreview.Clicked(None)
        seen["height"] = win.Geometry[3]
        seen["lines"] = itm["Detail"].PlainText.count("\n") + 1

    def drive_with(count):
        timeline = Timeline()
        timeline.v1 = [Item("A001C%03d_230412" % n, 86400 + n * 10,
                            86410 + n * 10, str(n)) for n in range(count)]
        timeline.v2 = []
        timeline.playhead = timeline.v1[0]
        drive(m, body, timeline=timeline)
        return dict(seen)

    short, longer, huge = drive_with(4), drive_with(40), drive_with(300)
    check("long preview grows past the start height",
          longer["height"] == m.CHROME_H + 7 * m.ROW_H
          + 40 * m.PREVIEW_LINE_H + 12,
          "%s -> %s" % (short["height"], longer["height"]))
    check("preview growth capped",
          huge["height"] - short["height"] <= m.PREVIEW_MAX_H,
          str(huge["height"]))


def main():
    if len(sys.argv) > 1:
        path = sys.argv[1]
    else:
        path = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                            "Render_It.py")

    module = load(path)
    print("testing %s (reports v%s)\n" % (os.path.basename(path),
                                          module.VERSION))
    for test in (test_reel_detection, test_jobs, test_presets,
                 test_queue, test_window, test_bad_frames_block_start,
                 test_long_preview):
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
