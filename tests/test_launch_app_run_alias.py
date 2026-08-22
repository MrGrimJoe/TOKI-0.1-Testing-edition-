"""
test_launch_app_run_alias.py -- BETA 0.3.62: "run <app>" (e.g. "run vscode")
previously didn't route to LAUNCH_APP at all -- neither ACTION_OPEN nor
ACTION_START_PROGRAM in graph_source_data/tier_a_components.py had a bare
"run" alias, despite STATUS.md notes elsewhere claiming "run" should alias
to LAUNCH_APP. Fixed by adding "run" to ACTION_START_PROGRAM. Exercises the
real LayeredGraphRouter (component router first, TF-IDF fallback) against
the actual checked-in toki_graph_db, matching test_graph_router.py's own
skip-if-graph-missing convention.
"""

import pytest

kuzu = pytest.importorskip("kuzu")

from pathlib import Path

if not (Path(__file__).resolve().parent.parent / "toki_graph_db").exists():
    pytest.skip("toki_graph_db not present -- run migrate_to_kuzu.py first", allow_module_level=True)

from graph_router import GraphRouter, DB_PATH
from component_router_kuzu import KuzuComponentRouter
from orchestrator import LayeredGraphRouter


@pytest.fixture(scope="module")
def router():
    cr = KuzuComponentRouter(str(DB_PATH))
    tf = GraphRouter()
    r = LayeredGraphRouter(cr, tf)
    yield r
    cr.close()
    tf.close()


class TestRunAliasRoutesToLaunchApp:
    @pytest.mark.parametrize("text", [
        "run vscode",
        "run chrome",
        "run notepad",
    ])
    def test_run_app_routes_to_launch_app(self, router, text):
        result = router.classify_or_ask(text)
        assert result.get("intent") == "LAUNCH_APP", (
            f"{text!r} -> {result}; bare 'run <app>' should resolve to "
            f"LAUNCH_APP the same way 'open <app>'/'launch <app>' already do"
        )

    def test_run_alias_does_not_break_existing_start_up_phrasing(self, router):
        # "start up" is ACTION_START_PROGRAM's other bare-ish alias --
        # confirm adding "run" alongside it didn't disturb it.
        result = router.classify_or_ask("start up chrome")
        assert result.get("intent") == "LAUNCH_APP"

    def test_run_alias_does_not_break_make_file_start_phrasing(self, router):
        # ACTION_START_PROGRAM deliberately excludes bare "start" because it
        # collides with MAKE_FILE's "start a new file" -- confirm the new
        # "run" alias (a different word) didn't reopen that or a similar
        # collision on this exact phrasing.
        result = router.classify_or_ask("start a new file")
        assert result.get("intent") == "MAKE_FILE"


class TestRunAliasKnownRemainingGap:
    def test_run_macro_not_yet_reachable_documents_the_collision_risk(self, router):
        # NOT a claim this is fixed -- the opposite. RUN_MACRO has zero
        # taxonomy coverage in this codebase today (no component map entry,
        # no tier_a_phrasings), so it was never reachable via either router
        # before this change either way. Adding bare "run" to LAUNCH_APP
        # means a phrase like this now confidently (wrongly) resolves to
        # LAUNCH_APP instead of falling through to an honest ASK. Pinned
        # here so whoever eventually gives RUN_MACRO real training data
        # sees this test fail and knows to add a forbidden-macro guard to
        # LAUNCH_APP at the same time (see the comment on
        # ACTION_START_PROGRAM in graph_source_data/tier_a_components.py).
        result = router.classify_or_ask("run my morning macro")
        assert result.get("intent") == "LAUNCH_APP"
