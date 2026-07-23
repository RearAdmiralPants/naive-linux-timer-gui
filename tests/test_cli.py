"""Headless tests for CLI argument parsing and JSON parameter loading.

No display or Qt widgets required -- the CLI parser and the load/apply path are
pure data transforms.
"""

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))

from naive_timer.shard import ShardParams
from naive_timer.tuning import apply_json_dict, load_params_file, ParamsError
from naive_timer.app import _parse_cli

# Path to real params files in the repo root.
_REPO_ROOT = os.path.join(os.path.dirname(__file__), "..")
_DEFAULT_PARAMS = os.path.join(_REPO_ROOT, "default-params.json")
_GREEN_NEBULA = os.path.join(_REPO_ROOT, "green-nebula.json")


class ParseCliTest(unittest.TestCase):
    """_parse_cli takes an explicit argv list and returns an argparse.Namespace.

    argparse reports usage errors and --help by raising SystemExit; the error
    tests swallow its stderr/stdout so a passing run stays quiet.
    """

    def _expect_exit(self, *args: str) -> SystemExit:
        buf = io.StringIO()
        with contextlib.redirect_stderr(buf), contextlib.redirect_stdout(buf):
            with self.assertRaises(SystemExit) as cm:
                _parse_cli(list(args))
        return cm.exception

    # -- happy paths --

    def test_no_args(self) -> None:
        cli = _parse_cli([])
        self.assertIsNone(cli.json)
        self.assertFalse(cli.no_panel)

    def test_json_space(self) -> None:
        cli = _parse_cli(["--json", "params.json"])
        self.assertEqual(cli.json, "params.json")
        self.assertFalse(cli.no_panel)

    def test_json_equals(self) -> None:
        cli = _parse_cli(["--json=params.json"])
        self.assertEqual(cli.json, "params.json")

    def test_json_equals_with_path(self) -> None:
        cli = _parse_cli(["--json=./configs/green-nebula.json"])
        self.assertEqual(cli.json, "./configs/green-nebula.json")

    def test_no_panel_flag(self) -> None:
        cli = _parse_cli(["--no-panel"])
        self.assertTrue(cli.no_panel)
        self.assertIsNone(cli.json)

    def test_json_and_no_panel(self) -> None:
        cli = _parse_cli(["--json", "p.json", "--no-panel"])
        self.assertEqual(cli.json, "p.json")
        self.assertTrue(cli.no_panel)

    def test_parse_does_not_touch_sys_argv(self) -> None:
        before = list(sys.argv)
        _parse_cli(["--no-panel"])
        self.assertEqual(sys.argv, before)

    # -- error paths (argparse exits) --

    def test_json_missing_value(self) -> None:
        self._expect_exit("--json")

    def test_unknown_option(self) -> None:
        self._expect_exit("--foo")

    def test_positional_is_error(self) -> None:
        self._expect_exit("my-params.json")

    def test_help_exits_zero(self) -> None:
        exc = self._expect_exit("--help")
        self.assertEqual(exc.code, 0)


class LoadParamsFileTest(unittest.TestCase):
    """load_params_file reads a JSON file and returns a dict."""

    def test_default_params(self) -> None:
        data = load_params_file(_DEFAULT_PARAMS)
        self.assertIsInstance(data, dict)
        self.assertIn("light_x", data)
        self.assertIn("glass_color", data)

    def test_green_nebula(self) -> None:
        data = load_params_file(_GREEN_NEBULA)
        self.assertIn("gravity", data)
        self.assertEqual(data["gravity"], 0.0)

    def test_missing_file(self) -> None:
        with self.assertRaises(ParamsError) as cm:
            load_params_file("/nonexistent/path/params.json")
        self.assertIn("not found", str(cm.exception))

    def test_directory_rejected(self) -> None:
        with self.assertRaises(ParamsError) as cm:
            load_params_file(_REPO_ROOT)
        self.assertIn("not a file", str(cm.exception))

    def test_invalid_json(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            try:
                f.write("{not valid json}")
                f.flush()
                with self.assertRaises(ParamsError):
                    load_params_file(f.name)
            finally:
                os.unlink(f.name)

    def test_non_object_top_level(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            try:
                json.dump([1, 2, 3], f)
                f.flush()
                with self.assertRaises(ParamsError) as cm:
                    load_params_file(f.name)
                self.assertIn("object", str(cm.exception))
            finally:
                os.unlink(f.name)

    def test_empty_object_is_valid(self) -> None:
        with tempfile.NamedTemporaryFile(
            mode="w", suffix=".json", delete=False
        ) as f:
            try:
                json.dump({}, f)
                f.flush()
                data = load_params_file(f.name)
            finally:
                os.unlink(f.name)
        self.assertEqual(data, {})


class ApplyJsonDictTest(unittest.TestCase):
    """apply_json_dict folds a dict into ShardParams in place."""

    def test_overwrites_known_field(self) -> None:
        params = ShardParams()
        apply_json_dict(params, {"light_x": 99.0})
        self.assertEqual(params.light_x, 99.0)

    def test_tuple_fields_coerced_from_list(self) -> None:
        params = ShardParams()
        apply_json_dict(params, {"glass_color": [1.0, 0.5, 0.0]})
        self.assertEqual(params.glass_color, (1.0, 0.5, 0.0))
        self.assertIsInstance(params.glass_color, tuple)

    def test_ignores_unknown_fields(self) -> None:
        params = ShardParams()
        before = params.light_x
        apply_json_dict(params, {"__nonexistent_key__": 123})
        self.assertEqual(params.light_x, before)

    def test_partial_update(self) -> None:
        params = ShardParams()
        orig_nebula = params.nebula
        apply_json_dict(params, {"gravity": 2.0})
        self.assertEqual(params.gravity, 2.0)
        self.assertEqual(params.nebula, orig_nebula)  # unchanged

    def test_loads_real_file_and_applies(self) -> None:
        params = ShardParams()
        data = load_params_file(_GREEN_NEBULA)
        apply_json_dict(params, data)

        # green-nebula.json has distinctive values
        self.assertEqual(params.light_x, 2.87)
        self.assertEqual(params.gravity, 0.0)
        self.assertEqual(params.nebula, 1.17)
        self.assertEqual(params.glass_color, (0.2, 0.2, 0.2))

    def test_string_fields(self) -> None:
        params = ShardParams()
        apply_json_dict(params, {"font_family": "serif", "font_bold": False})
        self.assertEqual(params.font_family, "serif")
        self.assertFalse(params.font_bold)


if __name__ == "__main__":
    unittest.main()
