#!/usr/bin/env python3
"""Deterministic digital rain at the requested resolution.

Requires Python 3.11+, Pycairo, PyGObject, Pillow and Noto Sans CJK JP.
See --help for export options; no desktop settings are changed.
"""
from __future__ import annotations

import argparse
from dataclasses import dataclass
import io
import math
from pathlib import Path
import random

import cairo
import gi
from PIL import Image, ImageChops, ImageFilter

gi.require_version("Pango", "1.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import Pango, PangoCairo

GLYPHS = "ｱｲｳｴｵｶｷｸｹｺｻｼｽｾｿﾀﾁﾂﾃﾄﾅﾆﾇﾈﾉﾊﾋﾌﾍﾎﾏﾐﾑﾒﾓﾔﾕﾖﾗﾘﾙﾚﾛﾜﾝｰ0123456789"
FONT = "Noto Sans CJK JP"
PALETTES = {
    "matrix": {"bg": "020403", "head": "D6E8D5", "body": "70C781", "trail": "409A56"},
    "mono": {"bg": "030303", "head": "DFDFDF", "body": "B5B5B5", "trail": "808080"},
}


@dataclass(frozen=True)
class Layer:
    size: float
    spacing: float
    population: float
    strength: float
    length: tuple[float, float]
    pale_heads: float


@dataclass(frozen=True)
class Profile:
    layers: tuple[Layer, ...]
    clusters: tuple[tuple[float, float, float], ...]
    ambient: float
    quiet: float


# Sizes are relative to a 32px base cell at a 2160px short edge. Separate
# placement fields and seed namespaces make silver an independent composition.
PROFILES = {
    "falling-code": Profile(
        layers=(Layer(0.5625, 1.1, 0.95, 0.23, (0.22, 0.76), 0.00),
                Layer(0.875, 1.2, 0.88, 0.52, (0.18, 0.68), 0.09),
                Layer(1.375, 1.5, 0.74, 0.82, (0.24, 0.72), 0.22),
                Layer(2.0, 1.8, 0.38, 1.02, (0.34, 0.82), 0.50)),
        clusters=((0.12, 0.070, 0.95), (0.30, 0.045, 0.72),
                  (0.72, 0.075, 0.86), (0.91, 0.042, 0.95)),
        ambient=0.14, quiet=0.62),
    "mono-rain": Profile(
        layers=(Layer(0.6875, 1.5, 0.42, 0.15, (0.18, 0.56), 0.00),
                Layer(1.3125, 1.6, 0.69, 0.46, (0.18, 0.55), 0.08),
                Layer(1.9375, 1.8, 0.70, 0.83, (0.25, 0.68), 0.25),
                Layer(2.5625, 2.0, 0.48, 0.96, (0.30, 0.65), 0.45)),
        clusters=((0.18, 0.078, 1.10), (0.76, 0.050, 0.72), (0.93, 0.025, 0.45)),
        ambient=0.045, quiet=0.78),
}
DEFAULT_PROFILES = {"matrix": "falling-code", "mono": "mono-rain"}


@dataclass(frozen=True)
class Glyph:
    x: float
    y: float
    cell: float
    character: str
    tone: str
    alpha: float
    glow: float
    stream: tuple[int, int]
    step: int


@dataclass(frozen=True)
class Scene:
    width: float
    height: float
    scale: float
    glyphs: tuple[Glyph, ...]


def hex_rgb(value: str) -> tuple[float, ...]:
    value = value.lstrip("#")
    return tuple(int(value[i:i + 2], 16) / 255 for i in (0, 2, 4))


def glyph_layouts(cell: int, font_name: str = FONT, padding: float = 2):
    """Fit actual ink, including bearings, with a shared baseline and padding."""
    ctx = cairo.Context(cairo.ImageSurface(cairo.FORMAT_A8, cell, cell))
    font = Pango.FontDescription(font_name)
    size = float(cell - 2 * padding)
    for _ in range(20):
        font.set_absolute_size(size * Pango.SCALE)
        layouts = []
        for ch in GLYPHS:
            layout = PangoCairo.create_layout(ctx)
            layout.set_font_description(font)
            layout.set_text(ch, -1)
            if layout.get_unknown_glyphs_count():
                raise ValueError(f"Font {font_name!r} cannot render {ch!r}; install Noto Sans CJK JP")
            ink, _ = layout.get_pixel_extents()
            layouts.append((ch, layout, ink))
        top = min(ink.y for _, _, ink in layouts)
        bottom = max(ink.y + ink.height for _, _, ink in layouts)
        extent = max(bottom - top, max(ink.width for _, _, ink in layouts))
        if extent <= cell - 2 * padding:
            y = (cell - (bottom - top)) / 2 - top
            return [(ch, layout, (cell - ink.width) / 2 - ink.x, y)
                    for ch, layout, ink in layouts]
        size *= (cell - 2 * padding) / extent * 0.98
    raise ValueError(f"Could not fit {font_name!r} into a {cell}px cell")


def cache_glyphs(cell: int, font_name: str = FONT, padding: float = 2) -> dict[str, cairo.ImageSurface]:
    cached = {}
    for ch, layout, x, y in glyph_layouts(cell, font_name, padding):
        surf = cairo.ImageSurface(cairo.FORMAT_A8, cell, cell)
        ctx = cairo.Context(surf)
        ctx.set_source_rgba(1, 1, 1, 1)
        ctx.move_to(x, y)
        PangoCairo.show_layout(ctx, layout)
        cached[ch] = surf
    return cached


def paint_glyph(ctx, glyph, x, y, rgb, alpha):
    ctx.set_source_rgba(*rgb, min(1, max(0, alpha)))
    ctx.mask_surface(glyph, x, y)


def quiet_field(x: float, y: float, profile_name: str) -> float:
    """A shared, curved clearing: all depths leave real room for windows."""
    if profile_name == "mono-rain":
        center = 0.48 + 0.045 * math.sin(y * 6.0 + 0.5)
        ellipses = ((center, 0.50, 0.26, 0.57), (0.64, 0.22, 0.13, 0.29))
    else:
        center = 0.47 + 0.045 * math.sin(y * 6.5 - 0.4)
        ellipses = ((center, 0.46, 0.19, 0.34), (0.57, 0.72, 0.14, 0.23))
    return max(math.exp(-(((x - cx) / rx) ** 2 + ((y - cy) / ry) ** 2))
               for cx, cy, rx, ry in ellipses)


def plan_scene(*, width=3840, height=2160, seed=1999, cell=None,
               density=0.82, profile_name="falling-code", quiet=None) -> Scene:
    """Plan in reference coordinates, independent of output pixel count.

    An explicit cell keeps the original CLI's pixel-override behavior. With no
    override, 4K and 8K have identical placements, glyphs, gaps and brightness.
    Small previews clamp the base cell to keep their glyphs readable.
    """
    profile = PROFILES[profile_name]
    quiet = profile.quiet if quiet is None else quiet
    scale = min(width, height) / 2160
    base = (cell if cell is not None else max(16, 32 * scale)) / scale
    width, height = width / scale, height / scale
    glyphs = []
    for depth, spec in enumerate(profile.layers):
        size = max(8 / scale, base * spec.size)
        pitch = size * spec.spacing
        for column in range(math.ceil(width / pitch)):
            # Explicit strings are stable across Python processes. Independent
            # streams prevent palette/brightness tweaks from moving neighbours.
            key = f"{seed}:{profile_name}:{depth}:{column}"
            geometry = random.Random(key + ":placement")
            appearance = random.Random(key + ":appearance")
            x = (column + geometry.uniform(0.08, 0.75)) * pitch
            cluster = profile.ambient + sum(
                weight * math.exp(-0.5 * ((x / width - center) / spread) ** 2)
                for center, spread, weight in profile.clusters)
            if geometry.random() >= density * spec.population * min(1, cluster):
                continue
            if profile_name == "mono-rain":
                # Silver hangs lower on the left, with a shorter answering
                # cluster high on the right and an open lower-right field.
                head_range = (0.36, 1.20) if x / width < 0.4 else (0.12, 0.72)
            else:
                head_range = (0.08, 1.30)
            head_y = geometry.uniform(*head_range) * height
            length = max(8, round(geometry.uniform(*spec.length) * height / size))
            clearance = 1 - quiet * geometry.uniform(0.72, 1.08)
            strength = spec.strength * appearance.uniform(0.72, 1.0)
            pale = appearance.random() < spec.pale_heads
            gap_end = -1
            for step in range(length):
                y = head_y - step * size
                # Broken runs, rather than a noisy checkerboard of lost letters.
                if step >= gap_end and step > 3 and geometry.random() < 0.065:
                    gap_end = step + geometry.randint(2, 6)
                character = appearance.choice(GLYPHS)
                flicker = appearance.uniform(0.65, 1.0)
                if step < gap_end or not 0 <= y <= height - size or x + size > width:
                    continue
                field = quiet_field((x + size / 2) / width, (y + size / 2) / height, profile_name)
                if field > clearance:
                    continue
                local = strength * (1 - quiet * field * 0.40)
                if step == 0:
                    tone, alpha = ("head" if pale else "body"), local
                elif step < 4:
                    tone, alpha = "body", local * (0.96 - step * 0.09)
                else:
                    tone, alpha = "trail", local * (1 - step / length) ** 0.85 * flicker
                glyphs.append(Glyph(x, y, size, character, tone, alpha,
                                    alpha * 0.40 if step < 3 else 0,
                                    (depth, column), step))
    return Scene(width, height, scale, tuple(glyphs))


def to_image(surface) -> Image.Image:
    buffer = io.BytesIO()
    surface.write_to_png(buffer)
    buffer.seek(0)
    return Image.open(buffer).convert("RGB")


def render(path: Path, *, width=3840, height=2160, seed=1999, cell=None,
           density=0.82, palette_name="matrix", profile_name="auto", quiet=None, font=FONT,
           scanlines=0.035, bloom=0.22):
    profile_name = DEFAULT_PROFILES[palette_name] if profile_name == "auto" else profile_name
    scene = plan_scene(width=width, height=height, seed=seed, cell=cell,
                       density=density, profile_name=profile_name, quiet=quiet)
    palette = PALETTES[palette_name]
    surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    glow_surface = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    ctx, glow = cairo.Context(surface), cairo.Context(glow_surface)
    ctx.set_source_rgb(*hex_rgb(palette["bg"]))
    ctx.paint()
    caches = {}
    colors = {tone: hex_rgb(value) for tone, value in palette.items()}
    glyph_scale = scene.scale if cell is None else cell / 32
    for mark in scene.glyphs:
        size = max(8, round(mark.cell * scene.scale))
        if size not in caches:
            # Padding scales too; 8K doesn't accidentally get proportionally
            # larger ink from keeping a fixed two-pixel border.
            caches[size] = cache_glyphs(size, font, min(size / 4, max(1, 2 * glyph_scale)))
        glyph = caches[size][mark.character]
        x, y = mark.x * scene.scale, mark.y * scene.scale
        paint_glyph(ctx, glyph, x, y, colors[mark.tone], mark.alpha)
        if mark.glow:
            paint_glyph(glow, glyph, x, y, colors[mark.tone], mark.glow)
    image = to_image(surface)
    surface.finish()
    if bloom:
        radius = (cell if cell is not None else 32 * scene.scale) / 12
        halo = to_image(glow_surface).filter(ImageFilter.GaussianBlur(max(0.7, radius)))
        halo = Image.blend(Image.new("RGB", image.size), halo, bloom)
        image = ImageChops.add(image, halo)
        del halo
    glow_surface.finish()
    finish = cairo.ImageSurface(cairo.FORMAT_RGB24, width, height)
    finish_ctx = cairo.Context(finish)
    finish_ctx.set_source_rgb(1, 1, 1)
    finish_ctx.paint()
    finish_ctx.set_source_rgba(0, 0, 0, scanlines)
    scan_pitch = max(1, 3 * scene.scale)
    for row in range(math.ceil(height / scan_pitch)):
        finish_ctx.rectangle(0, row * scan_pitch, width, max(0.5, scene.scale))
    finish_ctx.fill()
    gradient = cairo.RadialGradient(width / 2, height / 2, min(width, height) * 0.25,
                                    width / 2, height / 2, math.hypot(width, height) / 2)
    gradient.add_color_stop_rgba(0, 0, 0, 0, 0)
    gradient.add_color_stop_rgba(1, 0, 0, 0, 0.32)
    finish_ctx.set_source(gradient)
    finish_ctx.paint()
    image = ImageChops.multiply(image, to_image(finish))
    finish.finish()
    if path.suffix.lower() in (".jpg", ".jpeg"):
        image.save(path, quality=95, subsampling=0, optimize=True)
    else:
        image.save(path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("output", nargs="?", type=Path,
                        default=Path(__file__).resolve().parent.parent / "extras/backgrounds-code-4k")
    parser.add_argument("--width", type=int, default=3840)
    parser.add_argument("--height", type=int, default=2160)
    parser.add_argument("--seed", type=int, default=1999)
    parser.add_argument("--cell", type=int, help="override base cell in output pixels (default: scales with the short edge, 32px at 4K)")
    parser.add_argument("--density", type=float, default=0.82)
    parser.add_argument("--quiet", type=float, help="strength of curved empty working area, 0 to 1 (default: profile-specific)")
    parser.add_argument("--scanlines", type=float, default=0.035)
    parser.add_argument("--bloom", type=float, default=0.22)
    parser.add_argument("--font", default=FONT)
    parser.add_argument("--palette", choices=["both", *PALETTES], default="both")
    parser.add_argument("--profile", choices=["auto", *PROFILES], default="auto",
                        help="placement preset (auto pairs each palette with its own composition)")
    parser.add_argument("--format", choices=["jpg", "png"], default="jpg")
    args = parser.parse_args()
    if not (64 <= args.width <= 16384 and 64 <= args.height <= 16384):
        parser.error("width and height must be between 64 and 16384")
    if args.width * args.height > 40_000_000:
        parser.error("keep exports at or below 40 megapixels")
    if args.cell is not None and not 8 <= args.cell <= 128:
        parser.error("cell must be between 8 and 128")
    for key in ("density", "quiet", "scanlines", "bloom"):
        value = getattr(args, key)
        if value is not None and not 0 <= value <= 1:
            parser.error(f"{key} must be between 0 and 1")
    args.output.mkdir(parents=True, exist_ok=True)
    for name, stem in [("matrix", "1-falling-code"), ("mono", "2-mono-rain")]:
        if args.palette not in ("both", name):
            continue
        path = args.output / f"{stem}.{args.format}"
        render(path, width=args.width, height=args.height, seed=args.seed,
               cell=args.cell, density=args.density, quiet=args.quiet,
               palette_name=name, profile_name=args.profile, font=args.font,
               scanlines=args.scanlines, bloom=args.bloom)
        print(f"Wrote {path} ({args.width}×{args.height})")


if __name__ == "__main__":
    main()
