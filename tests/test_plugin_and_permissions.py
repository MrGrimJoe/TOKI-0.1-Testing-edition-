"""
test_plugin_and_permissions.py -- pins plugin loading only.

The dangerous-command confirmation flow this file used to test directly
(TestPluginAndPermissionGates.test_dangerous_command_permission_gate /
test_cancel_pending_permission, against the older self._pending_permission /
confirm_pending_permission() API) was superseded in BETA 0.3.38 by
checkpoint 3's self._pending_confirmation / _dispatch_or_confirm() design
(single choke point across every dispatch call site, "" as a valid confirm
word so a bare Enter or an avatar click both work with zero special-cased
UI methods). That flow now has its own, more thorough coverage in
tests/test_wcl_slot_filling_integration.py::TestCautionDestructiveConfirmationFlow
(12 tests) -- not duplicated here.
"""
import pytest
from plugin_manager import PluginManager


class TestPluginLoading:
    def test_plugin_loading_and_registration(self):
        pm = PluginManager()
        pm.load_all()
        assert "example_plugin" in pm.loaded
        assert "PLUGIN_HELLO" in pm.intents
        assert "PLUGIN_HELLO" in pm.phrasings
        assert "hello from plugin" in pm.phrasings["PLUGIN_HELLO"]
