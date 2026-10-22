#!/usr/bin/env python3
"""Run the installed SeedVR2 image preset, retaining PNG masters and audit records.

Uses only Python's standard library. No final wallpaper export is performed:
the original SaveImage PNG bytes are copied into a fresh project output folder.
An interrupted/ambiguous submission is never retried automatically; consult the
saved prompt IDs and history before deciding whether to submit it again.
"""

import argparse
import copy
from datetime import datetime, timezone
import hashlib
import json
import math
import os
from pathlib import Path
import re
import shlex
import shutil
import signal
import struct
import subprocess
import time
from urllib.parse import quote
from urllib.request import Request, urlopen
import uuid
import zlib


PROJECT_OUTPUT = Path(__file__).resolve().parents[1] / "output"
DEFAULT_INSTALL = Path("/home/bernardv/Work/seedvr2")
API = "http://127.0.0.1:8188"
EDITABLE = {"1": "image", "2": "scale_by", "11": "filename_prefix"}
# Every fixed input, including graph edges, must match the supplied 3B preset.
EXPECTED = {
    "1": ("LoadImage", {}),
    "2": ("ImageScaleBy", {"image": ["1", 0], "upscale_method": "lanczos"}),
    "3": ("UNETLoader", {"unet_name": "seedvr2_3b_fp16.safetensors",
                         "weight_dtype": "default"}),
    "4": ("VAELoader", {"vae_name": "seedvr2_ema_vae_fp16.safetensors"}),
    "5": ("SeedVR2Preprocess", {"resized_images": ["2", 0]}),
    "6": ("VAEEncodeTiled", {"pixels": ["5", 0], "vae": ["4", 0],
                             "tile_size": 512, "overlap": 64,
                             "temporal_size": 64, "temporal_overlap": 8}),
    "7": ("SeedVR2Conditioning", {"model": ["3", 0], "vae_conditioning": ["6", 0]}),
    "8": ("KSampler", {"model": ["3", 0], "seed": 17, "steps": 1,
                        "cfg": 1.0, "sampler_name": "euler", "scheduler": "simple",
                        "positive": ["7", 0], "negative": ["7", 1],
                        "latent_image": ["6", 0], "denoise": 1.0}),
    "9": ("VAEDecodeTiled", {"samples": ["8", 0], "vae": ["4", 0],
                             "tile_size": 512, "overlap": 64,
                             "temporal_size": 64, "temporal_overlap": 8}),
    "10": ("SeedVR2PostProcessing", {"images": ["9", 0],
                                     "original_resized_images": ["2", 0],
                                     "color_correction_method": "none"}),
    "11": ("SaveImage", {"images": ["10", 0]}),
}


def validate_workflow(workflow):
    if not isinstance(workflow, dict) or workflow.keys() != EXPECTED.keys():
        raise ValueError("Expected exactly the installed image workflow's nodes 1–11")
    for node_id, (class_type, expected_inputs) in EXPECTED.items():
        node = workflow[node_id]
        if not isinstance(node, dict) or node.get("class_type") != class_type:
            raise ValueError(f"Unexpected class for node {node_id}: expected {class_type}")
        inputs = copy.deepcopy(node.get("inputs", {}))
        if not isinstance(inputs, dict):
            raise ValueError(f"Invalid inputs for node {node_id}")
        if node_id in EDITABLE:
            key = EDITABLE[node_id]
            if key not in inputs:
                raise ValueError(f"Missing node {node_id} input {key}")
            del inputs[key]
        if inputs != expected_inputs:
            raise ValueError(f"Node {node_id} differs from the expected 3B FP16 preset")


def png_dimensions(path):
    """Check the PNG signature, IHDR/CRC and IEND; return header dimensions."""
    with path.open("rb") as stream:
        header = stream.read(33)
        if len(header) != 33:
            raise ValueError(f"Truncated PNG: {path}")
        stream.seek(-12, 2)
        end = stream.read(12)
    if (len(header) != 33 or header[:16] != b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR"
            or zlib.crc32(header[12:29]) != struct.unpack(">I", header[29:33])[0]
            or end != b"\x00\x00\x00\x00IEND\xaeB`\x82"):
        raise ValueError(f"Invalid PNG header or end marker: {path}")
    width, height, depth, color, compression, filtering, interlace = struct.unpack(
        ">IIBBBBB", header[16:29])
    depths = {0: (1, 2, 4, 8, 16), 2: (8, 16), 3: (1, 2, 4, 8),
              4: (8, 16), 6: (8, 16)}
    if (not width or not height or depth not in depths.get(color, ())
            or compression != 0 or filtering != 0 or interlace not in (0, 1)):
        raise ValueError(f"Invalid PNG dimensions or format: {path}")
    return width, height


def sha256(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def copy_new(source, destination):
    with source.open("rb") as src, destination.open("xb") as dst:
        shutil.copyfileobj(src, dst)


def json_bytes(value):
    return (json.dumps(value, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def save_json(path, value):
    # Only called inside the exclusively created run directory.
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(json_bytes(value))
    temporary.replace(path)


def request(path, body=None, timeout=30):
    req = Request(API + path, data=body,
                  headers={"Content-Type": "application/json"} if body else {})
    with urlopen(req, timeout=timeout) as response:
        return response.read()


def wait_for_output(prompt_id, record_dir, deadline, poll_interval):
    while True:
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise TimeoutError(f"Timed out waiting for prompt {prompt_id}")
        raw = request("/history/" + quote(prompt_id, safe=""), timeout=min(30, remaining))
        (record_dir / "history.json").write_bytes(raw)
        history = json.loads(raw)
        entry = history.get(prompt_id)
        if entry is not None:
            status = entry.get("status", {})
            messages = status.get("messages", [])
            failed = any(message[0] in ("execution_error", "execution_interrupted")
                         for message in messages if isinstance(message, list) and message)
            if status.get("status_str") == "error" or failed:
                raise RuntimeError(f"SeedVR2 failed for {prompt_id}; see {record_dir / 'history.json'}")
            if status.get("completed") is True:
                if status.get("status_str") != "success":
                    raise RuntimeError(f"Prompt {prompt_id} did not report success")
                images = entry.get("outputs", {}).get("11", {}).get("images", [])
                if not isinstance(images, list) or len(images) != 1:
                    raise RuntimeError(f"Expected one PNG from SaveImage node 11 for {prompt_id}")
                return images[0]
        time.sleep(min(poll_interval, max(0, deadline - time.monotonic())))


def output_path(image, output_root, run_output):
    if (not isinstance(image, dict) or image.get("type") != "output"
            or not isinstance(image.get("filename"), str)
            or not isinstance(image.get("subfolder"), str)):
        raise ValueError("Invalid SaveImage output metadata")
    name = image["filename"]
    if Path(name).name != name or Path(name).suffix.lower() != ".png":
        raise ValueError("Expected a PNG filename in SaveImage output")
    path = (output_root / image["subfolder"] / name).resolve(strict=True)
    if (not path.is_relative_to(output_root) or not path.is_relative_to(run_output)
            or not path.is_file()):
        raise ValueError(f"SaveImage output escapes this run's output directory: {path}")
    return path


def run_batch(sources, *, seedvr2_dir=DEFAULT_INSTALL, scale=2, workdir=None,
              timeout=1800, poll_interval=2.5):
    if scale not in (2, 4) or not sources:
        raise ValueError("Supply PNG sources and scale 2 or 4")
    if not all(math.isfinite(value) and value > 0 for value in (timeout, poll_interval)):
        raise ValueError("Timeout and poll interval must be finite and positive")
    install = Path(seedvr2_dir).expanduser().resolve(strict=True)
    launcher = install / "scripts/seedvr2"
    server_command = (install / "scripts/run-server").read_text()
    if "--disable-async-offload" not in shlex.split(server_command, comments=True):
        raise ValueError("scripts/run-server must retain --disable-async-offload")
    if not launcher.is_file():
        raise FileNotFoundError(launcher)
    template = install / "workflows/api/image.json"
    template_bytes = template.read_bytes()
    workflow = json.loads(template_bytes)
    validate_workflow(workflow)
    input_root = (install / "data/input").resolve(strict=True)
    output_root = (install / "data/output").resolve(strict=True)

    prepared = []
    stems = set()
    for source in sources:
        source = Path(source).expanduser().resolve(strict=True)
        if source.suffix.lower() != ".png":
            raise ValueError(f"Only PNG sources are supported: {source}")
        stem = re.sub(r"[^A-Za-z0-9_-]", "-", source.stem)
        if not stem or stem in stems:
            raise ValueError(f"Source stems must be distinct after sanitizing: {source}")
        stems.add(stem)
        prepared.append((source, stem, png_dimensions(source), sha256(source)))

    run_id = "seedvr2-" + datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ-") + uuid.uuid4().hex[:12]
    workdir = Path(workdir).expanduser().resolve() if workdir else PROJECT_OUTPUT.resolve() / run_id
    if workdir.parent != PROJECT_OUTPUT.resolve() or not re.fullmatch(r"seedvr2-[A-Za-z0-9_-]+", workdir.name):
        raise ValueError(f"--workdir must be a new seedvr2-* directory directly under {PROJECT_OUTPUT}")
    run_id = workdir.name
    run_output = output_root / "SeedVR2/matrix" / run_id
    if run_output.exists() or run_output.is_symlink():
        raise FileExistsError(f"SeedVR2 output for this run already exists: {run_output}")
    if not run_output.resolve().is_relative_to(output_root):
        raise ValueError("SeedVR2/matrix must remain inside data/output")
    workdir.mkdir(parents=True, exist_ok=False)
    (workdir / "masters").mkdir()
    (workdir / "jobs").mkdir()
    (workdir / "workflow.template.json").write_bytes(template_bytes)
    manifest_path = workdir / "manifest.json"
    manifest = {"run_id": run_id, "seedvr2_dir": str(install), "scale": scale,
                "status": "preparing", "service_stopped": False, "jobs": []}
    save_json(manifest_path, manifest)
    print(f"Run records: {workdir}", flush=True)

    # Stage all inputs before starting the service. Never open an original for writing.
    for source, stem, dimensions, digest in prepared:
        job_dir = workdir / "jobs" / stem
        job_dir.mkdir()
        input_copy = input_root / f"matrix-{run_id}-{stem}.png"
        copy_new(source, input_copy)
        if sha256(input_copy) != digest:
            raise RuntimeError(f"Source changed while copying: {source}")
        prompt = copy.deepcopy(workflow)
        prompt["1"]["inputs"]["image"] = input_copy.name
        prompt["2"]["inputs"]["scale_by"] = scale
        prompt["11"]["inputs"]["filename_prefix"] = f"SeedVR2/matrix/{run_id}/{stem}"
        (job_dir / "prompt.json").write_bytes(json_bytes({"prompt": prompt}))
        manifest["jobs"].append({"source": str(source), "source_sha256": digest,
                                 "input_copy": str(input_copy), "input_dimensions": dimensions,
                                 "stem": stem, "status": "prepared",
                                 "prompt_file": str(job_dir / "prompt.json")})
        save_json(manifest_path, manifest)

    failure = None
    startup_attempted = False
    try:
        manifest["status"] = "starting"
        save_json(manifest_path, manifest)
        # The launcher can start systemd then fail readiness; always attempt stop.
        startup_attempted = True
        subprocess.run([str(launcher), "start"], check=True, timeout=300)
        for job in manifest["jobs"]:
            job_dir = workdir / "jobs" / job["stem"]
            manifest["status"] = "running"
            job["status"] = "submission_unknown"
            save_json(manifest_path, manifest)
            deadline = time.monotonic() + timeout
            raw = request("/prompt", Path(job["prompt_file"]).read_bytes(), timeout=min(30, timeout))
            accepted = json.loads(raw)
            prompt_id = accepted.get("prompt_id")
            if not isinstance(prompt_id, str) or not prompt_id:
                (job_dir / "accepted.json").write_bytes(raw)
                raise RuntimeError(f"Prompt rejected: {accepted}")
            # Persist acceptance before any other response validation or polling.
            print(f"Accepted {job['stem']}: {prompt_id}", flush=True)
            with (workdir / "prompt-ids.jsonl").open("ab") as log:
                log.write((json.dumps({"stem": job["stem"], "prompt_id": prompt_id}) + "\n").encode())
                log.flush()
                os.fsync(log.fileno())
            job.update(prompt_id=prompt_id, status="accepted")
            (job_dir / "accepted.json").write_bytes(raw)
            save_json(manifest_path, manifest)
            if accepted.get("node_errors"):
                raise RuntimeError(f"Accepted prompt {prompt_id} reported node errors; inspect accepted.json")
            image = wait_for_output(prompt_id, job_dir, deadline, poll_interval)
            output = output_path(image, output_root, run_output.resolve())
            dimensions = png_dimensions(output)
            expected_size = tuple(size * scale for size in job["input_dimensions"])
            if dimensions != expected_size:
                raise ValueError(f"Unexpected output dimensions {dimensions}; expected {expected_size}")
            master = workdir / "masters" / f"{job['stem']}-x{scale}.png"
            copy_new(output, master)
            job.update(status="success", output_path=str(output), master_path=str(master),
                       output_dimensions=dimensions, output_sha256=sha256(master))
            save_json(manifest_path, manifest)
            print(f"Output: {output}\nMaster: {master} ({dimensions[0]}x{dimensions[1]})", flush=True)
        manifest["status"] = "success"
    except BaseException as error:
        failure = error
        manifest.update(status="interrupted" if isinstance(error, KeyboardInterrupt) else "failed",
                        error=f"{type(error).__name__}: {error}")
        raise
    finally:
        # Cleanup must precede fallible record writes, and preserve the original error.
        propagating = failure is not None
        try:
            if startup_attempted:
                subprocess.run([str(launcher), "stop"], check=True, timeout=120)
                manifest["service_stopped"] = True
        except BaseException as stop_error:
            manifest.update(status="failed", stop_error=f"{type(stop_error).__name__}: {stop_error}")
            if failure is None:
                failure = stop_error
            else:
                failure.add_note(f"SeedVR2 stop also failed: {stop_error}")
        try:
            save_json(manifest_path, manifest)
        except BaseException as record_error:
            if failure is None:
                failure = record_error
            else:
                failure.add_note(f"Saving final manifest also failed: {record_error}")
        if failure is not None and not propagating:
            raise failure
    return manifest_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("sources", nargs="+", type=Path, help="Preserved source PNGs")
    parser.add_argument("--seedvr2-dir", type=Path, default=DEFAULT_INSTALL)
    parser.add_argument("--scale", type=int, choices=(2, 4), default=2)
    parser.add_argument("--workdir", type=Path, help="New output/seedvr2-* directory (default: unique timestamp/ID)")
    parser.add_argument("--timeout", type=float, default=1800, help="Deadline in seconds per job (default: 1800)")
    args = parser.parse_args()

    def terminate(signum, frame):
        raise KeyboardInterrupt(f"Received signal {signum}")

    previous = signal.signal(signal.SIGTERM, terminate)
    try:
        manifest = run_batch(args.sources, seedvr2_dir=args.seedvr2_dir, scale=args.scale,
                             workdir=args.workdir, timeout=args.timeout)
        print(f"Manifest: {manifest}", flush=True)
    finally:
        signal.signal(signal.SIGTERM, previous)


if __name__ == "__main__":
    main()
