"""SeedVR2 batch contract tests: temporary files, mocked HTTP and service calls."""

from contextlib import ExitStack, redirect_stdout
import copy
import io
import json
from pathlib import Path
import struct
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
from urllib.error import URLError
import zlib

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import upscale_seedvr2 as runner


def installed_workflow():
    # Independent fixture of the supplied workflow; never read the real install.
    nodes = [
        ("LoadImage", {"image": "watch_macro_shot.png"}),
        ("ImageScaleBy", {"image": ["1", 0], "upscale_method": "lanczos", "scale_by": 2.0}),
        ("UNETLoader", {"unet_name": "seedvr2_3b_fp16.safetensors", "weight_dtype": "default"}),
        ("VAELoader", {"vae_name": "seedvr2_ema_vae_fp16.safetensors"}),
        ("SeedVR2Preprocess", {"resized_images": ["2", 0]}),
        ("VAEEncodeTiled", {"pixels": ["5", 0], "vae": ["4", 0], "tile_size": 512,
                             "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}),
        ("SeedVR2Conditioning", {"model": ["3", 0], "vae_conditioning": ["6", 0]}),
        ("KSampler", {"model": ["3", 0], "seed": 17, "steps": 1, "cfg": 1.0,
                        "sampler_name": "euler", "scheduler": "simple", "positive": ["7", 0],
                        "negative": ["7", 1], "latent_image": ["6", 0], "denoise": 1.0}),
        ("VAEDecodeTiled", {"samples": ["8", 0], "vae": ["4", 0], "tile_size": 512,
                             "overlap": 64, "temporal_size": 64, "temporal_overlap": 8}),
        ("SeedVR2PostProcessing", {"images": ["9", 0], "original_resized_images": ["2", 0],
                                    "color_correction_method": "none"}),
        ("SaveImage", {"images": ["10", 0], "filename_prefix": "SeedVR2/images/upscaled"}),
    ]
    return {str(index): {"class_type": cls, "inputs": inputs}
            for index, (cls, inputs) in enumerate(nodes, 1)}


def png(width=2, height=3):
    def chunk(kind, data):
        return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
    return (b"\x89PNG\r\n\x1a\n"
            + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0))
            + chunk(b"IDAT", zlib.compress((b"\0" + b"\x20\x80\x30" * width) * height))
            + chunk(b"IEND", b""))


class SeedVR2Tests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.root = Path(self.stack.enter_context(tempfile.TemporaryDirectory()))
        self.install = self.root / "seedvr2"
        self.project = self.root / "project"
        self.output = self.project / "output"
        for directory in ("scripts", "workflows/api", "data/input", "data/output"):
            (self.install / directory).mkdir(parents=True)
        self.template = self.install / "workflows/api/image.json"
        self.workflow = installed_workflow()
        self.workflow["8"]["_meta"] = {"title": "Keep this metadata, too"}
        self.template.write_text(json.dumps(self.workflow))
        self.server = self.install / "scripts/run-server"
        self.server.write_text('#!/bin/sh\nexec python main.py \\\n  --disable-async-offload\n')
        (self.install / "scripts/seedvr2").write_text("Never execute this fixture")
        self.sources = []
        for stem in ("3-green-street", "4-the-office", "5-hotel-corridor"):
            path = self.project / "extras/background-sources" / f"{stem}.png"
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(png())
            self.sources.append(path)
        self.protected = {}
        for path in (*self.sources, self.template, self.server,
                     self.project / "backgrounds/3-green-street.jpg",
                     self.project / "extras/backgrounds-6k/3-green-street.jpg",
                     self.output / "realesrgan/old.png",
                     self.install / "data/input/previous.png",
                     self.install / "data/output/SeedVR2/images/previous.png"):
            path.parent.mkdir(parents=True, exist_ok=True)
            if not path.exists():
                path.write_bytes(b"existing result: do not overwrite")
            self.protected[path] = path.read_bytes()
        self.workdir = self.output / "seedvr2-test"
        self.stdout = self.stack.enter_context(redirect_stdout(io.StringIO()))
        self.stack.enter_context(patch.object(runner, "PROJECT_OUTPUT", self.output))
        self.service = self.stack.enter_context(patch.object(runner.subprocess, "run"))
        self.http = self.stack.enter_context(patch.object(runner, "urlopen", side_effect=self.respond))
        self.sleep = self.stack.enter_context(patch.object(runner.time, "sleep"))
        self.events = []
        self.prompts = {}
        self.history_hook = None

    def run_batch(self, sources=None, **kwargs):
        return runner.run_batch(self.sources if sources is None else sources,
                                seedvr2_dir=self.install, scale=4,
                                workdir=self.workdir, **kwargs)

    def respond(self, request, timeout):
        self.assertGreater(timeout, 0)
        self.assertLessEqual(timeout, 30)
        path = request.full_url.removeprefix(runner.API)
        self.events.append((request.get_method(), path))
        if path == "/prompt":
            self.assertEqual(request.get_method(), "POST")
            # The previous job must already be preserved before another submission.
            self.assertEqual(len(list((self.workdir / "masters").glob("*.png"))), len(self.prompts))
            prompt_id = f"prompt-{len(self.prompts) + 1}"
            self.prompts[prompt_id] = json.loads(request.data)["prompt"]
            stem = Path(self.prompts[prompt_id]["11"]["inputs"]["filename_prefix"]).name
            self.assertEqual(request.data, (self.workdir / "jobs" / stem / "prompt.json").read_bytes())
            result = {"prompt_id": prompt_id, "node_errors": {}}
        else:
            self.assertEqual(request.get_method(), "GET")
            self.assertTrue(path.startswith("/history/"))
            prompt_id = path.removeprefix("/history/")
            ids = [json.loads(line)["prompt_id"] for line in
                   (self.workdir / "prompt-ids.jsonl").read_text().splitlines()]
            self.assertIn(prompt_id, ids, "Acceptance must be durable before polling")
            if self.history_hook:
                result = self.history_hook(prompt_id)
            else:
                result = self.success_history(prompt_id)
        return io.BytesIO(json.dumps(result).encode())

    def success_history(self, prompt_id, *, dimensions=(8, 12)):
        prefix = Path(self.prompts[prompt_id]["11"]["inputs"]["filename_prefix"])
        destination = self.install / "data/output" / prefix.parent / (prefix.name + "_00001_.png")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_bytes(png(*dimensions))
        return {prompt_id: {"status": {"status_str": "success", "completed": True},
                            "outputs": {"11": {"images": [{"filename": destination.name,
                                                           "subfolder": str(prefix.parent),
                                                           "type": "output"}]}}}}

    def assert_service_calls(self):
        self.assertEqual([call.args[0] for call in self.service.call_args_list],
                         [[str(self.install / "scripts/seedvr2"), action] for action in ("start", "stop")])

    def manifest(self):
        return json.loads((self.workdir / "manifest.json").read_text())

    def test_three_jobs_preserve_inputs_and_only_change_three_workflow_values(self):
        record = self.run_batch()
        self.assertEqual(record, self.workdir / "manifest.json")
        self.assert_service_calls()
        self.assertEqual([method for method, _ in self.events], ["POST", "GET"] * 3)
        manifest = self.manifest()
        self.assertEqual(manifest["status"], "success")
        self.assertTrue(manifest["service_stopped"])
        self.assertEqual((self.workdir / "workflow.template.json").read_bytes(), self.protected[self.template])
        for job, submitted in zip(manifest["jobs"], self.prompts.values()):
            original = copy.deepcopy(submitted)
            for node, key in (("1", "image"), ("2", "scale_by"), ("11", "filename_prefix")):
                self.assertNotEqual(submitted[node]["inputs"][key], self.workflow[node]["inputs"][key])
                original[node]["inputs"][key] = self.workflow[node]["inputs"][key]
            self.assertEqual(original, self.workflow)
            self.assertEqual(submitted["2"]["inputs"]["scale_by"], 4)
            self.assertEqual(submitted["11"]["inputs"]["filename_prefix"],
                             f"SeedVR2/matrix/seedvr2-test/{job['stem']}")
            self.assertEqual(Path(job["input_copy"]).read_bytes(), Path(job["source"]).read_bytes())
            self.assertEqual(job["source_sha256"], runner.sha256(Path(job["source"])))
            self.assertEqual(Path(job["master_path"]).read_bytes(), Path(job["output_path"]).read_bytes())
            self.assertEqual(job["output_dimensions"], [8, 12])
            self.assertIn(job["output_path"], self.stdout.getvalue())
            history = json.loads((self.workdir / "jobs" / job["stem"] / "history.json").read_bytes())
            self.assertTrue(history[job["prompt_id"]]["status"]["completed"])
        for path, before in self.protected.items():
            self.assertEqual(path.read_bytes(), before, str(path))
        # An existing run cannot accidentally be submitted again.
        with self.assertRaises(FileExistsError):
            self.run_batch()
        self.assert_service_calls()

    def test_rejects_configuration_drift_before_service_start(self):
        for node, key, value in (("3", "unet_name", "wrong-model.safetensors"),
                                 ("4", "vae_name", "wrong-vae.safetensors"),
                                 ("8", "seed", 42), ("6", "tile_size", 1024),
                                 ("9", "samples", ["6", 0])):
            with self.subTest(node=node, key=key):
                workflow = copy.deepcopy(self.workflow)
                workflow[node]["inputs"][key] = value
                self.template.write_text(json.dumps(workflow))
                with self.assertRaises(ValueError):
                    self.run_batch()
        workflow = copy.deepcopy(self.workflow)
        workflow["11"]["class_type"] = "PreviewImage"
        self.template.write_text(json.dumps(workflow))
        with self.assertRaises(ValueError):
            self.run_batch()
        self.service.assert_not_called()
        self.http.assert_not_called()

    def test_offload_flag_cannot_be_missing_or_only_commented(self):
        for script in ("exec python main.py\n", "# --disable-async-offload\nexec python main.py\n"):
            self.server.write_text(script)
            with self.assertRaisesRegex(ValueError, "disable-async-offload"):
                self.run_batch()
        self.service.assert_not_called()

    def test_rejects_duplicate_stems_invalid_png_and_protected_workdir(self):
        with self.assertRaisesRegex(ValueError, "distinct"):
            self.run_batch([self.sources[0], self.sources[0]])
        self.sources[0].write_bytes(b"not a png")
        with self.assertRaisesRegex(ValueError, "PNG"):
            self.run_batch()
        self.sources[0].write_bytes(png())
        self.workdir = self.project / "backgrounds/seedvr2-test"
        with self.assertRaisesRegex(ValueError, "workdir"):
            self.run_batch()
        self.service.assert_not_called()

    def test_existing_input_is_never_overwritten(self):
        collision = self.install / "data/input/matrix-seedvr2-test-3-green-street.png"
        collision.write_bytes(b"keep this input")
        with self.assertRaises(FileExistsError):
            self.run_batch()
        self.assertEqual(collision.read_bytes(), b"keep this input")
        self.service.assert_not_called()

    def test_startup_failure_still_stops_service(self):
        self.service.side_effect = [subprocess.TimeoutExpired("seedvr2 start", 300), None]
        with self.assertRaises(subprocess.TimeoutExpired):
            self.run_batch()
        self.assert_service_calls()
        self.http.assert_not_called()
        self.assertTrue(self.manifest()["service_stopped"])

    def test_ambiguous_submission_is_not_retried(self):
        self.http.side_effect = URLError("connection lost after submission")
        with self.assertRaises(URLError):
            self.run_batch()
        self.assert_service_calls()
        self.assertEqual(self.http.call_count, 1)
        self.assertEqual(self.manifest()["jobs"][0]["status"], "submission_unknown")

    def test_execution_error_with_completed_false_stops_without_waiting(self):
        self.history_hook = lambda pid: {pid: {"status": {"status_str": "error", "completed": False,
                                              "messages": [["execution_error", {"message": "OOM"}]]}}}
        with self.assertRaisesRegex(RuntimeError, "SeedVR2 failed"):
            self.run_batch()
        self.assert_service_calls()
        self.sleep.assert_not_called()
        self.assertEqual(len(self.prompts), 1)
        self.assertEqual(self.manifest()["jobs"][0]["prompt_id"], "prompt-1")

    def test_empty_history_has_bounded_deadline_and_sleep(self):
        self.history_hook = lambda pid: {}
        with patch.object(runner.time, "monotonic", side_effect=[0, 0, 0.75, 1.1]):
            with self.assertRaises(TimeoutError):
                self.run_batch(timeout=1)
        self.sleep.assert_called_once_with(0.25)
        self.assert_service_calls()
        self.assertEqual(len(self.prompts), 1)

    def test_keyboard_interrupt_stops_before_propagating(self):
        def interrupt(pid):
            raise KeyboardInterrupt()
        self.history_hook = interrupt
        with self.assertRaises(KeyboardInterrupt):
            self.run_batch()
        self.assert_service_calls()
        self.assertEqual(self.manifest()["status"], "interrupted")
        self.assertTrue(self.manifest()["service_stopped"])

    def test_missing_node11_output_is_failure(self):
        self.history_hook = lambda pid: {pid: {"status": {"status_str": "success", "completed": True},
                                              "outputs": {"9": {"images": ["wrong node"]}}}}
        with self.assertRaisesRegex(RuntimeError, "node 11"):
            self.run_batch()
        self.assert_service_calls()

    def test_output_dimension_mismatch_stops(self):
        self.history_hook = lambda pid: self.success_history(pid, dimensions=(4, 6))
        with self.assertRaisesRegex(ValueError, "dimensions"):
            self.run_batch()
        self.assert_service_calls()
        self.assertFalse(list((self.workdir / "masters").glob("*.png")))

    def test_output_resolution_rejects_traversal_symlinks_missing_files_and_wrong_type(self):
        output_root = self.install / "data/output"
        run_output = output_root / "SeedVR2/matrix/run"
        run_output.mkdir(parents=True)
        outside = self.root / "outside.png"
        outside.write_bytes(png())
        (run_output / "link.png").symlink_to(outside)
        candidates = [
            {"filename": "outside.png", "subfolder": "../../..", "type": "output"},
            {"filename": "link.png", "subfolder": "SeedVR2/matrix/run", "type": "output"},
            {"filename": "missing.png", "subfolder": "SeedVR2/matrix/run", "type": "output"},
            {"filename": "previous.png", "subfolder": "SeedVR2/images", "type": "output"},
            {"filename": "link.png", "subfolder": "SeedVR2/matrix/run", "type": "temp"},
        ]
        for image in candidates:
            with self.subTest(image=image), self.assertRaises((ValueError, FileNotFoundError)):
                runner.output_path(image, output_root, run_output)

    def test_accepted_id_is_recorded_even_when_response_has_node_errors(self):
        self.http.side_effect = lambda *args, **kwargs: io.BytesIO(
            b'{"prompt_id":"accepted-but-bad","node_errors":{"11":"bad"}}')
        with self.assertRaisesRegex(RuntimeError, "node errors"):
            self.run_batch()
        self.assertEqual(self.http.call_count, 1)
        self.assertIn("accepted-but-bad", (self.workdir / "prompt-ids.jsonl").read_text())
        self.assert_service_calls()

    def test_manifest_write_failure_cannot_prevent_shutdown(self):
        real_save = runner.save_json
        def fail_after_start(path, manifest):
            if self.service.call_count:
                raise OSError("disk full")
            real_save(path, manifest)
        with patch.object(runner, "save_json", side_effect=fail_after_start):
            with self.assertRaisesRegex(OSError, "disk full"):
                self.run_batch()
        self.assert_service_calls()

    def test_stop_failure_is_reported_without_masking_execution_error(self):
        original = URLError("network broke")
        self.http.side_effect = original
        self.service.side_effect = [None, subprocess.CalledProcessError(1, "seedvr2 stop")]
        with self.assertRaises(URLError) as caught:
            self.run_batch()
        self.assertIs(caught.exception, original)
        self.assertIn("stop also failed", " ".join(original.__notes__))
        self.assertFalse(self.manifest()["service_stopped"])
        self.assertIn("stop_error", self.manifest())

    def test_stop_failure_after_success_is_not_silenced(self):
        self.service.side_effect = [None, subprocess.CalledProcessError(1, "seedvr2 stop")]
        with self.assertRaises(subprocess.CalledProcessError):
            self.run_batch()
        self.assertEqual(self.manifest()["status"], "failed")


if __name__ == "__main__":
    unittest.main()
