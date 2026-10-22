"""Regression checks for glyph clipping, exports, readability, and launcher argv."""
import json
from collections import defaultdict
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import tomllib
import unittest
from unittest.mock import patch

from PIL import Image, ImageChops

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import render_rain as rain


def luminance(color):
    values = [int(color[i:i + 2], 16) / 255 for i in (1, 3, 5)]
    linear = [v / 12.92 if v <= 0.04045 else ((v + 0.055) / 1.055) ** 2.4 for v in values]
    return sum(v * w for v, w in zip(linear, (0.2126, 0.7152, 0.0722)))


def contrast(a, b):
    lo, hi = sorted((luminance(a), luminance(b)))
    return (hi + 0.05) / (lo + 0.05)


class ThemeTests(unittest.TestCase):
    def test_shipped_wallpapers_are_valid_4k_images(self):
        supported = {".jpg", ".jpeg", ".png", ".gif", ".bmp", ".webp"}
        wallpapers = sorted(path for path in (ROOT / "backgrounds").iterdir()
                            if path.suffix.lower() in supported)
        self.assertEqual({path.name for path in wallpapers}, {
            "0-hotel-corridor.jpg", "3-green-street.jpg",
            "4-the-office.jpg", "6-after-hours.jpg",
        })
        # Omarchy sorts shipped images and selects the first unmatched entry.
        # Keep code rain outside this directory, including after a rebuild.
        self.assertEqual(wallpapers[0].name, "0-hotel-corridor.jpg")
        for path in wallpapers:
            with self.subTest(wallpaper=path.name), Image.open(path) as image:
                self.assertEqual(image.size, (3840, 2160))
                self.assertEqual(image.mode, "RGB")
                image.verify()

    def test_higher_resolution_companions_are_valid(self):
        for directory, size, names in (
            ("backgrounds-code-4k", (3840, 2160), {"1-falling-code.jpg", "2-mono-rain.jpg"}),
            ("backgrounds-8k", (7680, 4320), {"1-falling-code.jpg", "2-mono-rain.jpg"}),
            ("backgrounds-6k", (6144, 3456), {
                "0-hotel-corridor.jpg", "3-green-street.jpg", "4-the-office.jpg", "6-after-hours.jpg",
            }),
        ):
            paths = list((ROOT / "extras" / directory).glob("*.jpg"))
            self.assertEqual({path.name for path in paths}, names)
            for path in paths:
                with self.subTest(wallpaper=path), Image.open(path) as image:
                    self.assertEqual(image.size, size)
                    self.assertEqual(image.mode, "RGB")
                    image.verify()

    @unittest.skipUnless(shutil.which("glslangValidator"), "glslangValidator is not installed")
    def test_phosphor_shader_compiles(self):
        with tempfile.TemporaryDirectory() as directory:
            shader = Path(directory) / "phosphor.frag"
            shader.write_text(
                "#version 330 core\nuniform vec3 iResolution;\nuniform sampler2D iChannel0;\nout vec4 color;\n"
                + (ROOT / "extras/phosphor.glsl").read_text()
                + "\nvoid main() { mainImage(color, gl_FragCoord.xy); }\n")
            result = subprocess.run(["glslangValidator", "-S", "frag", str(shader)],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_glyph_ink_fits_without_touching_cell_edges(self):
        for cell, padding in ((8, 2), (16, 2), (22, 2), (28, 2), (32, 2),
                              (44, 2), (62, 2), (64, 2), (82, 2), (128, 4), (164, 4)):
            for ch, surface in rain.cache_glyphs(cell, padding=padding).items():
                surface.flush()
                data, stride = bytes(surface.get_data()), surface.get_stride()
                pixels = [data[y * stride:y * stride + cell] for y in range(cell)]
                with self.subTest(cell=cell, glyph=ch):
                    self.assertTrue(any(any(row) for row in pixels), "empty glyph")
                    self.assertFalse(any(pixels[0]) or any(pixels[-1]), "vertical clipping")
                    self.assertFalse(any(row[0] or row[-1] for row in pixels), "horizontal clipping")

    def test_exports_are_repeatable_and_seed_changes_composition(self):
        with tempfile.TemporaryDirectory() as directory:
            paths = [Path(directory) / f"{i}.png" for i in range(3)]
            for palette in rain.PALETTES:
                with self.subTest(palette=palette):
                    for path, seed in zip(paths, (1999, 1999, 2000)):
                        rain.render(path, width=320, height=180, seed=seed, cell=16,
                                    palette_name=palette)
                    self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())
                    self.assertNotEqual(paths[0].read_bytes(), paths[2].read_bytes())
                    with Image.open(paths[0]) as image:
                        self.assertEqual(image.size, (320, 180))

    def test_rain_profiles_keep_composition_at_native_8k(self):
        for profile in rain.PROFILES:
            for width, height in ((3840, 2160), (2160, 3840)):
                with self.subTest(profile=profile, size=(width, height)):
                    scene = rain.plan_scene(width=width, height=height, profile_name=profile)
                    large = rain.plan_scene(width=width * 2, height=height * 2, profile_name=profile)
                    self.assertTrue(scene.glyphs)
                    self.assertEqual(scene.glyphs, large.glyphs)
                    self.assertEqual(large.scale, scene.scale * 2)
                    explicit = rain.plan_scene(width=width * 2, height=height * 2,
                                               profile_name=profile, cell=64)
                    self.assertEqual(large, explicit)

    def test_mono_has_independent_sparser_larger_placement(self):
        green = rain.plan_scene(profile_name="falling-code")
        mono = rain.plan_scene(profile_name="mono-rain")
        geometry = lambda scene: {(g.x, g.y, g.cell) for g in scene.glyphs}
        self.assertNotEqual(geometry(green), geometry(mono))
        self.assertLess(len(mono.glyphs), len(green.glyphs) / 2)
        self.assertGreater(min(g.cell for g in mono.glyphs), min(g.cell for g in green.glyphs))

    def test_explicit_pixel_cell_keeps_ink_size_independent_of_canvas_scale(self):
        with tempfile.TemporaryDirectory() as directory:
            images = []
            for scale in (1, 2):
                # Feed the rasterizer the same physical glyph at two reference
                # scales, avoiding full 4K/8K buffers for this ink-size check.
                mark = rain.Glyph(16 / scale, 16 / scale, 14 / scale,
                                  "8", "body", 1, 0, (1, 0), 0)
                scene = rain.Scene(64 / scale, 64 / scale, scale, (mark,))
                path = Path(directory) / f"{scale}.png"
                with patch.object(rain, "plan_scene", return_value=scene):
                    rain.render(path, width=64, height=64, cell=16,
                                palette_name="mono", bloom=0, scanlines=0)
                images.append(path.read_bytes())
            self.assertEqual(*images)

    def test_working_area_removes_occupancy_and_trails_have_internal_gaps(self):
        for profile in rain.PROFILES:
            with self.subTest(profile=profile):
                scene = rain.plan_scene(profile_name=profile)
                full = rain.plan_scene(profile_name=profile, quiet=0)
                core = lambda g: rain.quiet_field((g.x + g.cell / 2) / scene.width,
                                                   (g.y + g.cell / 2) / scene.height, profile) > 0.65
                self.assertTrue(any(core(g) for g in full.glyphs))
                self.assertFalse(any(core(g) for g in scene.glyphs))
                self.assertLess(len(scene.glyphs), len(full.glyphs))
                # quiet=0 isolates actual interrupted trails from the clearing.
                streams = defaultdict(list)
                for glyph in full.glyphs:
                    streams[glyph.stream].append(glyph.step)
                self.assertTrue(any(b - a >= 3 for steps in streams.values()
                                    for a, b in zip(steps, steps[1:])))

    def test_cli_mono_alone_matches_paired_export_across_processes(self):
        with tempfile.TemporaryDirectory() as directory:
            paired, single = Path(directory) / "paired", Path(directory) / "single"
            command = [sys.executable, str(ROOT / "scripts/render_rain.py"),
                       "--width", "320", "--height", "180", "--format", "png"]
            for output, palette in ((paired, "both"), (single, "mono")):
                subprocess.run([*command, str(output), "--palette", palette],
                               capture_output=True, text=True, check=True)
            self.assertEqual((paired / "2-mono-rain.png").read_bytes(),
                             (single / "2-mono-rain.png").read_bytes())

    def test_portrait_jpeg_and_mono_export(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "portrait.jpg"
            rain.render(path, width=180, height=320, palette_name="mono", cell=16)
            with Image.open(path) as image:
                self.assertEqual(image.format, "JPEG")
                self.assertEqual(image.size, (180, 320))
                r, g, b = image.convert("RGB").split()
                self.assertIsNone(ImageChops.difference(r, g).getbbox())
                self.assertIsNone(ImageChops.difference(g, b).getbbox())

    def test_text_contrast_and_ansi_aliases(self):
        colors = tomllib.loads((ROOT / "colors.toml").read_text())
        for bg in ("background", "lighter_background"):
            for key in ("foreground", "muted", "red", "magenta"):
                self.assertGreaterEqual(contrast(colors[key], colors[bg]), 4.5, (key, bg))
        self.assertGreaterEqual(contrast(colors["selection_foreground"], colors["selection_background"]), 4.5)
        roles = ["background", "red", "green", "yellow", "blue", "magenta", "cyan", "foreground",
                 "muted", "bright_red", "bright_green", "bright_yellow", "bright_blue", "bright_magenta",
                 "bright_cyan", "bright_foreground"]
        for i, role in enumerate(roles):
            self.assertEqual(colors[f"color{i}"], colors[role])

    def test_shell_sections_are_valid_and_colors_stay_in_palette(self):
        colors = tomllib.loads((ROOT / "colors.toml").read_text())
        for path in ROOT.glob("shell.*.toml"):
            values = tomllib.loads(path.read_text())
            self.assertFalse(any(isinstance(value, dict) for value in values.values()), path.name)
            for key, value in values.items():
                if isinstance(value, str) and value.startswith("#"):
                    self.assertIn(value, colors.values(), (path.name, key))
        lock = tomllib.loads((ROOT / "shell.lock.toml").read_text())
        self.assertGreaterEqual(contrast(lock["placeholder"], lock["background"]), 4.5)

    def test_launcher_preserves_command_arguments_and_scopes_prompt(self):
        with tempfile.TemporaryDirectory(prefix="matrix test ") as directory:
            root = Path(directory)
            for terminal in ("ghostty", "foot"):
                stub = root / terminal
                stub.write_text(f"#!{sys.executable}\nimport os,sys,json\nprint(json.dumps([sys.argv[1:],os.environ.get('STARSHIP_CONFIG')]))\n")
                stub.chmod(0o755)
                command = ["printf", "%s", "hello space", "$(do-not-execute)"]
                env = dict(os.environ, PATH=f"{root}:{os.environ['PATH']}")
                result = subprocess.run([sys.executable, str(ROOT / "scripts/matrix-terminal"),
                                         "--terminal", terminal, "--", *command],
                                        env=env, capture_output=True, text=True, check=True)
                argv, prompt = json.loads(result.stdout)
                self.assertEqual(argv[-len(command):], command)
                self.assertEqual(prompt, str(ROOT / "extras/starship.toml"))

    def test_invalid_cli_values_fail_before_export(self):
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "not-created"
            for options in (("--density", "nan"), ("--quiet", "inf"), ("--bloom", "-1"),
                            ("--scanlines", "1.1"), ("--width", "63"), ("--height", "16385"),
                            ("--cell", "7"), ("--cell", "129"),
                            ("--width", "8000", "--height", "6000"), ("--profile", "unknown")):
                with self.subTest(options=options):
                    result = subprocess.run([sys.executable, str(ROOT / "scripts/render_rain.py"),
                                             str(output), *options], capture_output=True)
                    self.assertEqual(result.returncode, 2)
                    self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
