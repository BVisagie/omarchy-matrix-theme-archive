"""Still export contracts; no GPU, SeedVR2 install, or full-size JPEG exports."""

import argparse
import ast
from contextlib import redirect_stdout
import hashlib
import importlib.machinery
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
import zlib


ROOT = Path(__file__).resolve().parents[1]
loader = importlib.machinery.SourceFileLoader("export_stills", str(ROOT / "scripts/export_stills"))
spec = importlib.util.spec_from_loader(loader.name, loader)
exporter = importlib.util.module_from_spec(spec)
loader.exec_module(exporter)

SCENES = ("3-green-street", "4-the-office", "5-hotel-corridor", "6-after-hours")
FILENAMES = ("0-hotel-corridor.jpg", "3-green-street.jpg", "4-the-office.jpg", "6-after-hours.jpg")


def tiny_png():
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress(b"\0\x20\x80\x30"))
            + chunk(b"IEND", b""))


class StillExportTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.runs = [self.root / "run-three", self.root / "run-after-hours"]
        for directory, stems in zip(self.runs, (SCENES[:3], SCENES[3:])):
            (directory / "masters").mkdir(parents=True)
            jobs = []
            for stem in stems:
                master = directory / "masters" / f"{stem}-x4.png"
                master.write_bytes(tiny_png())
                jobs.append({"stem": stem, "status": "success", "master_path": str(master),
                             "output_dimensions": [6688, 3764],
                             "output_sha256": hashlib.sha256(master.read_bytes()).hexdigest()})
            (directory / "manifest.json").write_text(json.dumps({
                "status": "success", "scale": 4, "jobs": jobs,
            }))
        self.protected = {}
        for directory in ("backgrounds", "extras/backgrounds-6k"):
            for filename in (*FILENAMES, "user-wallpaper.jpg"):
                path = self.root / directory / filename
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(b"existing " + filename.encode())
                self.protected[path] = path.read_bytes()
        self.commands = []

    def edit_manifest(self, change, index=-1):
        path = self.runs[index] / "manifest.json"
        manifest = json.loads(path.read_text())
        change(manifest)
        path.write_text(json.dumps(manifest))

    def magick(self, command, **kwargs):
        self.assertEqual(command[0], "magick")
        self.assertTrue(kwargs["check"])
        self.commands.append(command)
        if command[-1] == "info:":
            self.assertIn("-regard-warnings", command)
            return subprocess.CompletedProcess(command, 0, stdout="PNG 6688 3764")
        # Existing installed images must survive until every conversion finishes.
        self.assert_protected()
        Path(command[-1]).write_bytes(b"new JPEG")
        return subprocess.CompletedProcess(command, 0)

    def assert_protected(self):
        for path, contents in self.protected.items():
            self.assertEqual(path.read_bytes(), contents, str(path))

    def assert_rejected(self, error, message, runs=None):
        before = set(self.root.rglob("*"))
        with patch.object(exporter.subprocess, "run", side_effect=self.magick), \
                patch.object(exporter.tempfile, "TemporaryDirectory") as staging:
            with self.assertRaisesRegex(error, message):
                exporter.export(self.runs if runs is None else runs, self.root)
            staging.assert_not_called()
        self.assertEqual(set(self.root.rglob("*")), before)
        self.assertTrue(all(command[-1] == "info:" for command in self.commands))
        self.assert_protected()

    def test_missing_manifest_and_missing_scene_rejected_before_writes(self):
        self.assert_rejected(FileNotFoundError, "manifest.json", [self.runs[0], self.root / "missing"])
        self.assert_rejected(ValueError, "Missing scenes: 6-after-hours", self.runs[:1])

    def test_failed_or_incomplete_run_and_job_rejected_before_writes(self):
        original = (self.runs[-1] / "manifest.json").read_text()
        for level in ("run", "job"):
            for status in ("failed", "running", "prepared", None):
                with self.subTest(level=level, status=status):
                    (self.runs[-1] / "manifest.json").write_text(original)
                    self.edit_manifest(lambda m: (m if level == "run" else m["jobs"][0]).update(status=status))
                    self.assert_rejected(ValueError, "did not succeed")

    def test_duplicate_scene_within_and_across_runs_rejected_before_writes(self):
        self.assert_rejected(ValueError, "Duplicate scene", [*self.runs, self.runs[0]])
        self.edit_manifest(lambda m: m["jobs"].append(dict(m["jobs"][0])))
        self.assert_rejected(ValueError, "Duplicate scene: 6-after-hours")

    def test_malformed_manifest_and_unexpected_scene_rejected_before_writes(self):
        path = self.runs[-1] / "manifest.json"
        original = path.read_text()
        for malformed in ("{", "[]", '{"status":"success","scale":4,"jobs":{}}'):
            with self.subTest(manifest=malformed):
                path.write_text(malformed)
                self.assert_rejected(ValueError, ".+")
        path.write_text(original)
        self.edit_manifest(lambda m: m["jobs"][0].update(stem="1-falling-code"))
        self.assert_rejected(ValueError, "Unexpected scene")

    def test_bad_master_metadata_rejected_before_writes(self):
        path = self.runs[-1] / "manifest.json"
        original = path.read_text()
        for fields, message in (({"output_dimensions": [3344, 1882]}, "6688x3764"),
                                ({"output_sha256": "oops"}, "Invalid output_sha256"),
                                ({"master_path": None}, "Missing master_path")):
            with self.subTest(fields=fields):
                path.write_text(original)
                self.edit_manifest(lambda m: m["jobs"][0].update(fields))
                self.assert_rejected(ValueError, message)

    def test_last_master_hash_mismatch_rejected_before_writes(self):
        self.edit_manifest(lambda m: m["jobs"][0].update(output_sha256="0" * 64))
        self.assert_rejected(ValueError, "SHA-256 mismatch")

    def test_missing_or_non_png_master_rejected_before_writes(self):
        master = self.runs[-1] / "masters/6-after-hours-x4.png"
        master.unlink()
        self.assert_rejected(FileNotFoundError, "6-after-hours-x4.png")
        master.write_bytes(b"not a PNG")
        self.assert_rejected(ValueError, "not a PNG")

    def test_decoded_dimensions_are_checked_independently(self):
        with patch.object(self, "magick", return_value=subprocess.CompletedProcess([], 0, stdout="PNG 3344 1882")):
            self.assert_rejected(ValueError, "valid 6688x3764 PNG")

    @unittest.skipUnless(shutil.which("magick"), "ImageMagick is unavailable")
    def test_real_decoder_rejects_tiny_and_corrupt_png_without_exporting(self):
        # Small fixtures exercise actual decoding without allocating/exporting 4K images.
        for contents, error in ((tiny_png(), ValueError),
                                (b"\x89PNG\r\n\x1a\ntruncated", subprocess.CalledProcessError)):
            with self.subTest(contents=contents):
                master = self.runs[0] / "masters/5-hotel-corridor-x4.png"
                master.write_bytes(contents)
                self.edit_manifest(lambda m: m["jobs"][2].update(
                    output_sha256=hashlib.sha256(contents).hexdigest()), index=0)
                with patch.object(exporter.tempfile, "TemporaryDirectory") as staging:
                    with self.assertRaises(error):
                        exporter.export(self.runs, self.root)
                    staging.assert_not_called()
                self.assert_protected()

    def test_exact_exports_hotel_mapping_relative_master_and_unknown_file_preservation(self):
        self.edit_manifest(lambda m: m["jobs"][0].update(master_path="masters/6-after-hours-x4.png"))
        with patch.object(exporter.subprocess, "run", side_effect=self.magick), redirect_stdout(io.StringIO()):
            exporter.export(list(reversed(self.runs)), self.root)
        self.assertEqual(len(self.commands), 12)
        self.assertTrue(all(command[-1] == "info:" for command in self.commands[:4]))
        for offset, (dimensions, directory) in enumerate((
                ("3840x2160", "backgrounds"), ("6144x3456", "extras/backgrounds-6k"))):
            for number, filename in enumerate(FILENAMES):
                command = self.commands[4 + offset * 4 + number]
                stem = "5-hotel-corridor" if filename.startswith("0-") else Path(filename).stem
                self.assertEqual(Path(command[1]).name, f"{stem}-x4.png")
                self.assertEqual(command[2:-1], [
                    "-filter", "Lanczos", "-resize", f"{dimensions}^", "-gravity", "center",
                    "-extent", dimensions, "-colorspace", "sRGB", "-strip",
                    "-sampling-factor", "4:4:4", "-quality", "95",
                    "-define", "jpeg:optimize-coding=true",
                ])
                self.assertEqual(Path(command[-1]).name, filename)
                self.assertEqual((self.root / directory / filename).read_bytes(), b"new JPEG")
            self.assertFalse((self.root / directory / "5-hotel-corridor.jpg").exists())
            unknown = self.root / directory / "user-wallpaper.jpg"
            self.assertEqual(unknown.read_bytes(), self.protected[unknown])
        self.assertFalse(list(self.root.glob(".export-stills-*")))

    def test_last_conversion_failure_leaves_installed_set_intact(self):
        def fail_last(command, **kwargs):
            result = self.magick(command, **kwargs)
            if len(self.commands) == 12:
                raise subprocess.CalledProcessError(1, command)
            return result
        with patch.object(exporter.subprocess, "run", side_effect=fail_last):
            with self.assertRaises(subprocess.CalledProcessError):
                exporter.export(self.runs, self.root)
        self.assert_protected()
        self.assertFalse(list(self.root.glob(".export-stills-*")))

    def test_realesrgan_legacy_runner_only_writes_optional_destinations(self):
        scripts = self.root / "scripts"
        scripts.mkdir()
        legacy = scripts / "export_stills_realesrgan"
        shutil.copy2(ROOT / "scripts/export_stills_realesrgan", legacy)
        for stem in SCENES[:3]:
            source = self.root / "extras/background-sources" / f"{stem}.png"
            source.parent.mkdir(parents=True, exist_ok=True)
            source.write_bytes(tiny_png())
        binary = self.root / "mock-upscaler"
        binary.write_text("#!/bin/sh\nexit 0\n")
        binary.chmod(0o755)
        models = self.root / "models"
        models.mkdir()
        for suffix in ("bin", "param"):
            (models / f"realesrgan-x4plus.{suffix}").touch()
        magick = scripts / "magick"
        magick.write_text(f"#!{sys.executable}\nfrom pathlib import Path\nimport sys\n"
                          "Path(sys.argv[-1]).write_bytes(b'mocked JPEG')\n")
        magick.chmod(0o755)
        subprocess.run(["bash", str(legacy), str(binary), str(models)], check=True,
                       capture_output=True, text=True,
                       env={**os.environ, "PATH": str(scripts) + os.pathsep + os.environ["PATH"]})
        self.assert_protected()
        for directory in ("extras/backgrounds-realesrgan-4k", "extras/backgrounds-realesrgan-6k"):
            self.assertEqual({path.name for path in (self.root / directory).glob("*.jpg")},
                             {f"{stem}.jpg" for stem in SCENES[:3]})

    def test_rain_cli_defaults_to_optional_directory_without_rendering(self):
        # Execute only CLI wiring, avoiding imports of Cairo/Pango/Pillow.
        path = ROOT / "scripts/render_rain.py"
        tree = ast.parse(path.read_text())
        main = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == "main")
        render = Mock()
        namespace = {"__file__": str(path), "__doc__": "Test CLI", "argparse": argparse,
                     "Path": Path, "FONT": "unused", "PALETTES": {"matrix": {}, "mono": {}},
                     "PROFILES": {}, "render": render}
        exec(compile(ast.Module(body=[main], type_ignores=[]), str(path), "exec"), namespace)
        with patch.object(sys, "argv", [str(path)]), patch.object(Path, "mkdir") as mkdir, \
                redirect_stdout(io.StringIO()):
            namespace["main"]()
        mkdir.assert_called_once_with(parents=True, exist_ok=True)
        self.assertEqual([call.args[0] for call in render.call_args_list], [
            ROOT / "extras/backgrounds-code-4k/1-falling-code.jpg",
            ROOT / "extras/backgrounds-code-4k/2-mono-rain.jpg",
        ])


if __name__ == "__main__":
    unittest.main()
