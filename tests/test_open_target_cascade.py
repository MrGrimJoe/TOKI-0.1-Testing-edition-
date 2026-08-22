"""
test_open_target_cascade.py -- pins the "app -> file/folder -> ask"
cascade added to fix a real, reproduced bug: "open steam"/"open vscode"/
"open obs" all lost to OPEN_ITEM under the old single one-shot
classification (OPEN_ITEM only knows how to look on Desktop/D:\\, so it
asked "which file or folder?" instead of launching the app).

Covers two layers:
  1. extractor.resolve_open_target() -- the cascade decision logic itself,
     pure Python, app existence injected via a fake callable (no
     subprocess/PowerShell needed).
  2. app_control.AppController's app-matching -- specifically the safety
     fix for a real collision found while building this: plain
     difflib.SequenceMatcher.ratio() scored "vscode" HIGHER against
     "Discord" (0.615) than against "Visual Studio Code" (0.5) -- i.e. the
     naive version of this feature would have confidently launched the
     WRONG app. _score_app_match()'s substring-first scoring fixes it;
     this suite is what caught the bug and pins the fix.
"""

import json
from unittest.mock import patch, MagicMock

import pytest

from extractor import resolve_open_target


# ─── resolve_open_target(): pure decision logic ────────────────────────────

class TestResolveOpenTargetCascade:
    def test_app_match_wins_when_app_exists(self):
        result = resolve_open_target("open steam", app_exists_fn=lambda n: n == "steam")
        assert result == {"intent": "LAUNCH_APP", "app_name": "steam"}

    def test_falls_through_to_file_when_no_app_matches(self, monkeypatch):
        # BETA 0.3.7: this used to hardcode "C:\\Users\\Default\\Desktop",
        # which is only the Linux-sandbox fallback (get_sandbox_roots()
        # falls back to that literal when %USERPROFILE% is unset). On a
        # real Windows box with a OneDrive-redirected Desktop, a live
        # pytest run caught this failing with the REAL resolved path --
        # the code was right, this assertion was wrong. Mock the
        # resolver directly so the test is correct on the platform it's
        # actually meant to protect, not just wherever it was written.
        import extractor
        monkeypatch.setattr(extractor, "_resolve_real_desktop_path",
                             lambda: "C:\\Users\\Default\\Desktop")
        with patch("extractor.os.path.exists", return_value=True):
            result = resolve_open_target("open my resume", app_exists_fn=lambda n: False)
        assert result == {"intent": "OPEN_ITEM", "path": "C:\\Users\\Default\\Desktop\\my resume"}

    def test_none_when_neither_app_nor_file_exists(self, monkeypatch):
        # BETA 0.3.7: os.path.exists was already mocked False here, but
        # extractor.file_index is a real module-level singleton -- its
        # find_best_match() genuinely scans the actual disk. A live
        # Windows pytest run caught this test matching a real, unrelated
        # file several folders deep under the reporter's real D:\ drive,
        # because nothing here stopped FileIndex from seeing their real
        # filesystem. Force it empty so this test verifies the cascade's
        # true "nothing matched anywhere" behavior, not "whatever happens
        # to exist on this specific machine."
        import extractor
        monkeypatch.setattr(extractor.file_index, "get_entries", lambda: [])
        with patch("extractor.os.path.exists", return_value=False):
            result = resolve_open_target("open totally made up thing", app_exists_fn=lambda n: False)
        assert result is None

    def test_app_check_skipped_gracefully_when_no_fn_provided(self):
        # app_exists_fn=None (e.g. app_controller unavailable) must not
        # raise -- just skip straight to the file/folder check.
        with patch("extractor.os.path.exists", return_value=True):
            result = resolve_open_target("open my resume", app_exists_fn=None)
        assert result is not None
        assert result["intent"] == "OPEN_ITEM"

    def test_explicit_single_quote_convention_skips_the_cascade(self):
        # 'AppName' is the existing explicit-app-name convention -- the
        # user already told us exactly what they mean, don't second-guess
        # it even if app_exists_fn would say no.
        result = resolve_open_target("open 'Definitely An App'", app_exists_fn=lambda n: False)
        assert result is None  # cascade doesn't run at all; caller's own
                                 # LAUNCH_APP extract_slots() handles it

    def test_explicit_double_quote_convention_skips_the_cascade(self):
        result = resolve_open_target('open "some_file.txt"', app_exists_fn=lambda n: True)
        assert result is None  # cascade doesn't run; OPEN_ITEM's own
                                 # extract_slots() handles the literal

    def test_app_takes_priority_over_a_same_named_file(self):
        # If BOTH an app and a file/folder with the same name exist, the
        # app wins -- matches the original bug report ("asked to open
        # apps... it tried to open folder" -- the fix should bias toward
        # apps for ambiguous bare names, not the reverse).
        with patch("extractor.os.path.exists", return_value=True):
            result = resolve_open_target("open notes", app_exists_fn=lambda n: True)
        assert result["intent"] == "LAUNCH_APP"


# ─── AppController's app-matching: the vscode/Discord collision fix ───────

FAKE_APPS = [
    {"Name": "Steam", "AppID": "steam.appid"},
    {"Name": "Discord", "AppID": "discord.appid"},
    {"Name": "Visual Studio Code", "AppID": "vscode.appid"},
    {"Name": "Calculator", "AppID": "calc.appid"},
    {"Name": "Google Chrome", "AppID": "chrome.appid"},
    {"Name": "OBS Studio", "AppID": "obs.appid"},
]


@pytest.fixture
def controller():
    import app_control
    ctrl = app_control.AppController()
    ctrl.invalidate_app_cache()

    def fake_run(*a, **kw):
        m = MagicMock()
        m.stdout = json.dumps(FAKE_APPS)
        return m

    with patch("subprocess.run", side_effect=fake_run):
        yield ctrl
    ctrl.invalidate_app_cache()


class TestAppMatchingSafety:
    def test_exact_and_common_abbreviations_resolve_correctly(self, controller):
        assert controller.app_exists("steam")
        assert controller.app_exists("discord")
        assert controller.app_exists("chrome")   # substring of "Google Chrome"
        assert controller.app_exists("calc")     # substring of "Calculator"
        assert controller.app_exists("obs")      # substring of "OBS Studio"
        assert controller.app_exists("code")     # substring of "Visual Studio Code"

    def test_vscode_does_not_collide_with_discord(self, controller):
        # THE bug this suite exists to catch: plain difflib ratio matching
        # scored "vscode" higher against "Discord" (0.615) than against
        # "Visual Studio Code" (0.5) -- a wrong-app launch, not a harmless
        # miss. Correct behavior: no collision with Discord specifically.
        match = controller._find_installed_app("vscode")
        assert match is not None and match["Name"] != "Discord"

    def test_vscode_actually_resolves_to_visual_studio_code(self, controller):
        # BETA 0.3.9: found live against REAL Get-StartApps output --
        # "VsCode" (the natural way most people actually type this) scored
        # only 0.38 against the real "Visual Studio Code" entry, nowhere
        # near _APP_MATCH_THRESHOLD (0.72), because "vscode" isn't a
        # contiguous substring of "visualstudiocode" (the "vs" comes from
        # two separate words' initials). The OLD version of this test
        # tolerated that silent miss ("match is None OR...") -- but a real
        # user hit exactly this: "open VsCode" fell through the whole
        # cascade to a bad file-path guess instead of launching the app.
        # Fixed via a new leading-initials-plus-trailing-words scoring
        # tier in _score_app_match; this pins the real-world capitalization
        # that was actually typed, not just a lowercase synthetic case.
        match = controller._find_installed_app("VsCode")
        assert match is not None
        assert match["Name"] == "Visual Studio Code"

    def test_word_does_not_collide_with_discord(self, controller):
        # Same collision family, confirmed separately: "word" also scored
        # higher against "Discord" than anything relevant under plain
        # ratio matching.
        match = controller._find_installed_app("word")
        assert match is None or match["Name"] != "Discord"

    def test_unrelated_query_matches_nothing(self, controller):
        assert not controller.app_exists("photoshop")
        assert not controller.app_exists("gibberish123")

    def test_no_installed_apps_data_fails_open_to_no_match(self):
        import app_control
        ctrl = app_control.AppController()
        ctrl.invalidate_app_cache()
        with patch("subprocess.run", side_effect=Exception("powershell unreachable")):
            assert ctrl.app_exists("steam") is False
        ctrl.invalidate_app_cache()
