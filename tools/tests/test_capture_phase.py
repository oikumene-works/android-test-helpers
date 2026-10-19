"""End-to-end CLI checks using only an isolated local fake ADB executable."""

import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
SCRIPT = HERE.parent / "capture_phase.py"


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="fdroid-capture-test-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.output = self.root / "evidence with spaces"
        self.output.mkdir()
        self.adb = self.root / "fake adb"
        shutil.copyfile(HERE / "fake_adb.py", self.adb)
        self.adb.chmod(0o700)
        self.jar = self.root / "no idle.jar"
        self.jar.write_bytes(b"simulated helper; never sent to a device")
        self.apk = self.root / "preserving helper.apk"
        self.apk.write_bytes(b"simulated preserving helper")

    def run_capture(self, scenario="success", notes=True, extra=()):
        env = os.environ.copy()
        env.update(CAPTURE_TEST_ROOT=str(self.root), CAPTURE_TEST_SCENARIO=scenario,
                   ADB_SERVER_SOCKET="tcp:old-server:1", ANDROID_SERIAL="old-device",
                   ANDROID_ADB_SERVER_ADDRESS="old-server", ANDROID_ADB_SERVER_PORT="1")
        command = [sys.executable, "-B", str(SCRIPT), "--adb", str(self.adb),
                   "--server-host", "127.0.0.1", "--server-port", "42117",
                   "--serial", "test-device-1", "--package", "org.example.test",
                   "--phase", "TC01-after-save", "--output", str(self.output),
                   "--timeout", "1"]
        if notes:
            command.extend(["--app-language-note", "English on screen (simulated)",
                            "--input-note", "ADB key events; intended text: Test note"])
        command.extend(extra)
        result = subprocess.run(command, capture_output=True, text=True, env=env, timeout=15)
        captures = sorted(self.output.iterdir())
        data = json.loads((captures[-1] / "metadata.json").read_text()) if captures else None
        return result, captures[-1] if captures else None, data

    def assert_partial(self, scenario, section, field, status="failed"):
        result, directory, data = self.run_capture(scenario)
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(data["status"], "partial")
        self.assertEqual(data[section][field]["status"], status)
        self.assertTrue((directory / "metadata.json").is_file())
        return directory, data

    def test_complete_capture_contains_artifacts_context_and_command_times(self):
        result, directory, data = self.run_capture()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["status"], "complete")
        self.assertEqual(data["captures"]["screenshot"]["dimensions"], [1, 1])
        self.assertEqual(data["captures"]["ui_tree"]["node_count"], 1)
        self.assertIn("Override size: 480x640", data["metadata"]["display_size"]["value"])
        self.assertNotIn("unrelated line", data["metadata"]["input_state"]["value"])
        self.assertEqual(data["metadata"]["automatic_time"]["value"], "0")
        self.assertEqual(data["cleanup"]["status"], "ok")
        self.assertEqual(list((self.root / "remote").iterdir()), [])
        self.assertEqual(directory.stat().st_mode & 0o777, 0o700)
        for record in data["commands"].values():
            self.assertEqual(record["status"], "ok")
            self.assertLessEqual(record["started_at_utc"], record["finished_at_utc"])
            self.assertTrue((directory / record["stdout"]).is_file())
            self.assertTrue((directory / record["stderr"]).is_file())

    def test_repeated_phase_preserves_every_previous_byte(self):
        _, previous, _ = self.run_capture()
        original = {p.name: hashlib.sha256(p.read_bytes()).hexdigest() for p in previous.iterdir()}
        result, current, _ = self.run_capture()
        self.assertEqual(result.returncode, 0)
        self.assertNotEqual(previous, current)
        self.assertEqual(original, {p.name: hashlib.sha256(p.read_bytes()).hexdigest()
                                    for p in previous.iterdir()})

    def test_failed_screenshot_keeps_partial_bytes_and_stderr(self):
        directory, data = self.assert_partial("screenshot_error", "captures", "screenshot")
        self.assertEqual((directory / "screenshot.png").read_bytes(), b"partial")
        self.assertIn("permission denied", (directory / "screenshot.stderr.txt").read_text())
        self.assertEqual(data["captures"]["ui_tree"]["status"], "ok")

    def test_truncated_png_is_not_success(self):
        self.assert_partial("truncated_png", "captures", "screenshot")

    def test_bad_png_crc_is_not_success(self):
        self.assert_partial("bad_png_crc", "captures", "screenshot")

    def test_malformed_xml_is_not_success(self):
        self.assert_partial("bad_xml", "captures", "ui_tree")

    def test_empty_hierarchy_is_not_success(self):
        self.assert_partial("empty_xml", "captures", "ui_tree")

    def test_ui_command_error_preserves_screenshot_and_cleans_owned_directory(self):
        _, data = self.assert_partial("ui_error", "captures", "ui_tree")
        self.assertEqual(data["cleanup"]["status"], "ok")
        self.assertEqual(data["captures"]["screenshot"]["status"], "ok")

    def test_ui_timeout_preserves_output_but_cannot_claim_remote_completion(self):
        directory, data = self.assert_partial("ui_timeout", "captures", "ui_tree")
        self.assertIn("timeout", data["commands"]["ui_dump"]["error"])
        self.assertIn("uiautomator started", (directory / "ui_dump.txt").read_text())
        self.assertEqual(data["cleanup"]["status"], "unverified")

    def test_fallback_is_opt_in_and_not_staged_when_stock_succeeds(self):
        for scenario, extra in (("ui_error", ()), ("success", ("--ui-fallback-jar", str(self.jar)))):
            with self.subTest(scenario=scenario):
                _, _, data = self.run_capture(scenario, extra=extra)
                self.assertNotIn("ui_fallback_push", data["commands"])
                self.assertEqual(len(data["ui_dump"]["attempts"]), 1)

    def test_fallback_recovers_failed_or_empty_stock_and_preserves_its_evidence(self):
        for scenario in ("ui_error", "bad_xml", "empty_xml"):
            with self.subTest(scenario=scenario):
                result, directory, data = self.run_capture(scenario, extra=("--ui-fallback-jar", str(self.jar)))
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(data["ui_dump"]["selected_method"], "no_idle")
                self.assertEqual([x["status"] for x in data["ui_dump"]["attempts"]], ["failed", "ok"])
                self.assertEqual(data["captures"]["ui_tree"]["command"], "ui_fallback_tree")
                self.assertIn("fresh fallback", (directory / data["captures"]["ui_tree"]["file"]).read_text())
                self.assertTrue((directory / "ui_dump.txt").is_file())
                if scenario != "ui_error":
                    self.assertTrue((directory / "ui_tree.xml").is_file())
                self.assertEqual(data["ui_dump"]["fallback_jar_sha256"], hashlib.sha256(self.jar.read_bytes()).hexdigest())
                self.assertEqual(data["cleanup"]["status"], "ok")
                self.assertEqual(list((self.root / "remote").iterdir()), [])

    def test_stock_timeout_does_not_launch_fallback(self):
        result, _, data = self.run_capture("ui_timeout", extra=("--ui-fallback-jar", str(self.jar)))
        self.assertEqual(result.returncode, 1)
        self.assertNotIn("ui_fallback_push", data["commands"])
        self.assertIn("unknown", data["ui_dump"]["fallback_skipped"])

    def test_fallback_failure_is_bounded_and_never_false_success(self):
        for scenario in ("fallback_empty_xml", "fallback_missing_xml", "fallback_push_error", "fallback_timeout"):
            with self.subTest(scenario=scenario):
                result, _, data = self.run_capture(scenario, extra=("--ui-fallback-jar", str(self.jar)))
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(data["captures"]["ui_tree"]["status"], "failed")
                self.assertIsNone(data["ui_dump"]["selected_method"])
                self.assertEqual(len(data["ui_dump"]["attempts"]), 2)
                self.assertEqual(data["cleanup"]["status"], "unverified" if scenario == "fallback_timeout" else "ok")

    def test_fallback_interrupt_keeps_cleanup_uncertain(self):
        result, _, data = self.run_capture("fallback_interrupt", extra=("--ui-fallback-jar", str(self.jar)))
        self.assertEqual(result.returncode, 130)
        self.assertEqual(data["cleanup"]["status"], "unverified")

    def test_invalid_fallback_path_does_not_touch_device(self):
        result, _, data = self.run_capture(extra=("--ui-fallback-jar", "relative.jar"))
        self.assertEqual(result.returncode, 2)
        self.assertIsNone(data)
        self.assertFalse((self.root / "calls.jsonl").exists())

    def preserve(self, scenario="success", extra=()):
        return self.run_capture(scenario, extra=("--ui-preserve-apk", str(self.apk), *extra))

    def calls(self):
        return [json.loads(line) for line in (self.root / "calls.jsonl").read_text().splitlines()]

    def test_preserving_capture_bypasses_stock_checks_apk_and_cleans_only_own_helper(self):
        result, directory, data = self.preserve()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual(data["ui_dump"]["selected_method"], "preserve_services")
        self.assertEqual(data["ui_dump"]["preserve_apk_sha256"], hashlib.sha256(self.apk.read_bytes()).hexdigest())
        self.assertEqual(data["captures"]["ui_tree"]["file"], "ui_preserve_tree.xml")
        self.assertEqual(data["cleanup"]["status"], "ok")
        self.assertIn("fresh preserve", (directory / "ui_preserve_tree.xml").read_text())
        self.assertFalse((self.root / "preserve/fdroid-capture-lock").exists())
        self.assertEqual(list((self.root / "preserve/files").iterdir()), [])
        for command in self.calls():
            self.assertNotIn("uiautomator", command)
            self.assertNotIn("app_process", command)
            self.assertNotIn("install", command)
            if "force-stop" in command: self.assertEqual(command[-1], "qa.capture.preserve")

    def test_preserve_preconditions_fail_without_instrumenting_or_stopping_anything(self):
        for scenario in ("preserve_other_user", "preserve_missing_helper", "preserve_wrong_apk", "preserve_lock_busy"):
            with self.subTest(scenario=scenario):
                result, _, data = self.preserve(scenario)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertNotIn("ui_preserve_dump", data["commands"])
                self.assertNotIn("ui_preserve_stop", data["commands"])
                self.assertEqual(data["cleanup"]["status"], "not_needed")
        self.assertEqual((self.root / "preserve/fdroid-capture-lock/other-owner.txt").read_text(), "keep")

    def test_preserve_checks_instrumentation_result_and_fresh_tree_identity(self):
        for scenario in ("preserve_instrument_error", "preserve_stale_tree", "preserve_wrong_flags",
                         "preserve_wrong_package", "preserve_empty_tree", "preserve_missing_tree"):
            with self.subTest(scenario=scenario):
                result, _, data = self.preserve(scenario)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(data["captures"]["ui_tree"]["status"], "failed")
                self.assertIsNone(data["ui_dump"]["selected_method"])
                self.assertEqual(data["cleanup"]["status"], "ok")
                self.assertNotIn("ui_dump", data["commands"])

    def test_preserve_timeout_stops_writer_and_verifies_cleanup_without_falling_back(self):
        result, _, data = self.preserve("preserve_timeout")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertIn("timeout", data["commands"]["ui_preserve_dump"]["error"])
        self.assertEqual(data["cleanup"]["status"], "ok")
        self.assertFalse((self.root / "preserve/running").exists())
        self.assertNotIn("ui_dump", data["commands"])

    def test_preserve_interruption_cleans_owned_writer_before_returning_130(self):
        result, _, data = self.preserve("preserve_interrupt")
        self.assertEqual(result.returncode, 130, result.stderr)
        self.assertEqual(data["cleanup"]["status"], "ok")
        self.assertFalse((self.root / "preserve/fdroid-capture-lock").exists())

    def test_preserve_uncertain_lock_is_retained_without_force_stop(self):
        for scenario, code in (("preserve_lock_timeout", 1), ("preserve_lock_interrupt", 130)):
            with self.subTest(scenario=scenario):
                lock = self.root / "preserve/fdroid-capture-lock"
                if lock.exists(): lock.rmdir()
                result, _, data = self.preserve(scenario)
                self.assertEqual(result.returncode, code, result.stderr)
                self.assertEqual(data["cleanup"]["status"], "unverified")
                self.assertNotIn("ui_preserve_stop", data["commands"])
                self.assertTrue(lock.is_dir())

    def test_preserve_uncertain_stop_keeps_lock_and_file_for_manual_recovery(self):
        for scenario in ("preserve_stop_error", "preserve_still_running", "preserve_pid_error"):
            with self.subTest(scenario=scenario):
                lock = self.root / "preserve/fdroid-capture-lock"
                if lock.exists(): lock.rmdir()
                result, _, data = self.preserve(scenario)
                self.assertEqual(result.returncode, 1, result.stderr)
                self.assertEqual(data["captures"]["ui_tree"]["status"], "ok")
                self.assertEqual(data["cleanup"]["status"], "unverified")
                self.assertNotIn("ui_preserve_remove", data["commands"])
                self.assertNotIn("ui_preserve_unlock", data["commands"])
                self.assertTrue(lock.is_dir())

    def test_preserve_file_removal_failure_is_partial(self):
        result, _, data = self.preserve("preserve_cleanup_error")
        self.assertEqual(result.returncode, 1, result.stderr)
        self.assertEqual(data["cleanup"]["status"], "unverified")
        self.assertEqual(data["captures"]["ui_tree"]["status"], "ok")

    def test_preserve_invalid_path_target_or_combined_modes_never_touch_device(self):
        for extra in (("--ui-preserve-apk", "relative.apk"),
                      ("--package", "qa.capture.preserve"),
                      ("--ui-fallback-jar", str(self.jar))):
            with self.subTest(extra=extra):
                result, _, data = self.preserve(extra=extra)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(data)
                self.assertFalse((self.root / "calls.jsonl").exists())

    def test_missing_metadata_is_distinct_from_command_failure(self):
        self.assert_partial("missing_metadata", "metadata", "font_scale", status="missing")

    def test_empty_locale_uses_active_configuration_and_keeps_primary_evidence(self):
        result, directory, data = self.run_capture("locale_fallback")
        self.assertEqual(result.returncode, 0, result.stderr)
        locale = data["metadata"]["system_locale"]
        self.assertEqual(locale["value"], "en-rUS")
        self.assertEqual(locale["value_format"], "android_locale_resource_qualifiers")
        self.assertEqual(locale["primary_probe"]["status"], "missing")
        self.assertEqual((directory / "system_locale.txt").read_text(), "\n")
        self.assertIn("config: en-rUS", (directory / "system_locale_configuration.txt").read_text())

    def test_explicit_locale_avoids_unneeded_fallback(self):
        result, _, data = self.run_capture()
        self.assertEqual(result.returncode, 0)
        self.assertEqual(data["metadata"]["system_locale"]["value"], "en-US")
        self.assertNotIn("system_locale_configuration", data["commands"])

    def test_locale_fallback_preserves_multiple_locales_and_script_qualifiers(self):
        result, _, data = self.run_capture("locale_fallback_multilingual")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(data["metadata"]["system_locale"]["value"], "fi-rFI,b+sr+Latn+RS")

    def test_unknown_locale_configuration_is_not_guessed_from_factory_defaults(self):
        _, data = self.assert_partial("locale_fallback_unknown", "metadata", "system_locale", status="missing")
        self.assertIsNone(data["metadata"]["system_locale"]["value"])
        self.assertIn("not recognized", data["metadata"]["system_locale"]["error"])

    def test_failed_locale_fallback_is_distinct_from_missing_value(self):
        self.assert_partial("locale_fallback_error", "metadata", "system_locale")

    def test_failed_property_read_is_preserved_after_successful_fallback(self):
        result, _, data = self.run_capture("locale_fallback_property_error")
        self.assertEqual(result.returncode, 0)
        self.assertEqual(data["metadata"]["system_locale"]["primary_probe"]["status"], "failed")

    def test_default_time_format_remains_partial_with_useful_cli_summary(self):
        result, _, data = self.run_capture("default_time_format")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["metadata"]["time_format"]["status"], "missing")
        self.assertIn("metadata.time_format=missing", result.stdout)

    def test_missing_window_focus_is_not_hidden(self):
        self.assert_partial("window_focus_missing", "metadata", "window_focus", status="missing")

    def test_unsupported_app_locale_probe_is_explicit(self):
        self.assert_partial("locale_unsupported", "metadata", "app_locales")

    def test_uninstalled_package_does_not_claim_complete_context(self):
        self.assert_partial("package_missing", "metadata", "package_path", status="missing")

    def test_missing_provided_context_is_not_inferred(self):
        result, _, data = self.run_capture(notes=False)
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["provided_context"]["app_language"]["status"], "missing")
        self.assertEqual(data["provided_context"]["input_method_and_input"]["status"], "missing")

    def test_cleanup_failure_is_not_hidden_by_valid_artifacts(self):
        result, _, data = self.run_capture("cleanup_error")
        self.assertEqual(result.returncode, 1)
        self.assertEqual(data["cleanup"]["status"], "unverified")
        self.assertTrue(all(v["status"] == "ok" for v in data["captures"].values()))

    def test_offline_device_stops_before_captures(self):
        result, _, data = self.run_capture("offline")
        self.assertEqual(result.returncode, 2)
        self.assertEqual(data["status"], "failed")
        self.assertEqual(list(data["commands"]), ["device_state"])
        self.assertEqual(data["captures"]["screenshot"]["status"], "not_captured")

    def test_interrupt_records_checkpoint(self):
        result, _, data = self.run_capture("interrupt")
        self.assertEqual(result.returncode, 130, result.stderr)
        self.assertIn("interrupted", data["errors"])
        self.assertEqual(data["commands"]["device_state"]["status"], "failed")

    def test_invalid_phase_package_and_timeout_do_not_touch_device_or_output(self):
        for extra in (("--phase", "../old"), ("--package", "org.example;reboot"),
                      ("--timeout", "nan"), ("--timeout", "0")):
            with self.subTest(extra=extra):
                result, _, data = self.run_capture(extra=extra)
                self.assertEqual(result.returncode, 2)
                self.assertIsNone(data)
                self.assertFalse((self.root / "calls.jsonl").exists())

    def test_device_and_server_are_required_each_invocation(self):
        result = subprocess.run([sys.executable, "-B", str(SCRIPT), "--adb", str(self.adb),
                                 "--output", str(self.output), "--package", "org.example.test",
                                 "--phase", "TC01"], capture_output=True, text=True)
        self.assertEqual(result.returncode, 2)
        for flag in ("--serial", "--server-host", "--server-port"):
            self.assertIn(flag, result.stderr)
        self.assertEqual(list(self.output.iterdir()), [])


if __name__ == "__main__":
    unittest.main()
