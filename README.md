# Matrix

An Omarchy 4 (Quattro) theme for the 1999 film.

Phosphor green on void black, with olive shadows. The accent is CRT green
(`#3CBF5C`), with brighter highlights reserved for the code-rain wallpapers.

![Live desktop — Hotel Corridor wallpaper with rain, Neovim, and btop](preview.png)

Live Omarchy 4.0.6 desktop, captured at **3840×2160** and **150% display scaling**.
The SeedVR2-mastered **Hotel Corridor** default sits behind terminal rain,
Neovim with the optional phosphor shader, and themed btop. The demo windows are
arranged for this screenshot; terminal rain is not started by the theme.

## Install

Omarchy 4:

```sh
omarchy theme install https://github.com/BVisagie/omarchy-matrix-theme
```

Or *Install > Style > Theme* in the Omarchy menu (`Super + Space`) and paste that URL.

Backgrounds cycle with `Super + Ctrl + Space`.

The base theme contains colors, shell styling, and static backgrounds. The
[optional operator terminal](#operator-terminal) is launched separately.

Compatibility: targets **Omarchy 4 / Quickshell**, checked against the installed
**4.0.3-1** templates and desktop. Omarchy 3's Waybar/Mako setup is not
covered by these overrides. The published theme is **Matrix**; older lock-screen
examples use the local development name **Matrix Operator**.

## Palette

| Role | Hex | In the film |
| --- | --- | --- |
| Background | `#080C09` | The simulation's black, with a green lift |
| Accent | `#3CBF5C` | CRT phosphor, not the rain's white-hot head |
| Foreground | `#8BC98C` | Terminal text, the body of the stream |
| Muted | `#678D6A` | Readable comments and secondary text |
| Selection | `#23482A` | Highlighted code |
| Red | `#D15D57` | The pill, the alarm, ACCESS DENIED |
| Yellow | `#B8BA48` | Sickly fluorescent |
| Cyan | `#4BB56A` | Prompt, still in-world |

Syntax highlighting stays inside that world: phosphor greens, a brick
red, a little teal for directories and the prompt. No magenta nightclub.

Comments, normal red, and muted syntax each exceed 4.5:1 contrast against both
the main background and lifted panel background. Decorative rain remains dimmer.

## Operator terminal

From this repository, or after `cd ~/.config/omarchy/themes/matrix` for an
installed copy:

```sh
./scripts/matrix-terminal
./scripts/matrix-terminal --terminal foot
./scripts/matrix-terminal --font-size 12
./scripts/matrix-terminal --phosphor
```

Requires Python 3.11+, Ghostty or Foot, and JetBrainsMono Nerd Font. The default
is Ghostty. The launcher reads `colors.toml` directly, so it can preview the
palette before the desktop theme is applied. It keeps your normal terminal
configuration and overrides appearance for this session: 11pt type, additional
padding, an opaque background, and a steady block cursor. Ghostty also gets a
little extra line spacing and runs in a separate instance.

The companion Starship prompt shows directory, Git state, slow command duration,
and failed exit codes. SSH hosts and root sessions stay identifiable. Omarchy's
usual shell startup initializes Starship; custom shells need their own Starship
initialization. `STARSHIP_CONFIG` is scoped to the launched process and its
children. No shell startup files, default terminal, or keybindings are edited.

`--phosphor` enables a small static glow in Ghostty. It adds no animation loop,
flicker, warping, or cursor trails. Foot uses the clean profile. Close the preview
window and open your normal terminal to return to your existing setup.

Run a specific command with arguments after `--`, or request the greeting by hand:

```sh
./scripts/matrix-terminal -- btop
./scripts/matrix-greeting
```

Alacritty and Kitty still receive the base palette through Omarchy. This first
iteration's optional launcher supports Ghostty and Foot.

The launcher uses the documented [Ghostty configuration options](https://ghostty.org/docs/config/reference)
and [Starship prompt configuration](https://starship.rs/config/).

## Shell

The `shell.*.toml` files style the bar, controls, launcher, menus, notifications,
popups, tooltips, and lock input. Panels are opaque near-black; selected rows have
a readable green fill; keyboard focus gets a distinct 2px green border. User
font scaling remains inherited. Omarchy shares the bar's red active token among
recording, updates, and other attention states.

Omarchy replaces entire sections when applying these files, so overridden
sections include their supported defaults explicitly. Global user shell overrides
can still take precedence. No shell plugins or Hyprland behavior are installed.

## Backgrounds

**Hotel Corridor is the default wallpaper.** The bundled cycle contains four
cinematic scenes, all mastered with **SeedVR2** at **3840×2160**, with matching
[6K companions](extras/backgrounds-6k) at **6144×3456**:

1. **Hotel Corridor** — faded wallpaper, timber doors, brass sconces, and rain beyond the end window (`0-hotel-corridor.jpg`)
2. **Green Street** — the empty intersection and wet-road reflections (`3-green-street.jpg`)
3. **The Office** — one active CRT beside a dark cubicle aisle (`4-the-office.jpg`)
4. **After Hours** — the back-office corridor, tired fluorescents, and a partly concealed CRT (`6-after-hours.jpg`)

Omarchy sorts the files in `backgrounds/`; Hotel comes first on a fresh selection.
Reapplying an already active theme can advance to the next image, and personal
backgrounds can take precedence. Both code-rain wallpapers live outside the
bundled cycle, so the theme does not select them during normal application.

The four cinematic sources are **1672×941** PNGs preserved in
[extras/background-sources](extras/background-sources). After Hours retains its
original composition, recovered from the repository's generation record. All
four use the same installed SeedVR2 **3B FP16** workflow at **4×**, producing
**6688×3764** PNG masters. Lanczos downsampling and a minimal central crop produce
sRGB JPEGs at quality 95 with 4:4:4 chroma. These are **AI-upscaled artworks**;
larger pixel dimensions do not imply native 4K or 6K source detail.

[Generation prompts](docs/background-prompts.json) and
[current source/export provenance](docs/background-provenance.json) record the
sources, processing, and hashes. Earlier [Real-ESRGAN 4K exports](extras/backgrounds-realesrgan-4k)
and [6K exports](extras/backgrounds-realesrgan-6k) remain available for comparison.
The [comparison record](docs/seedvr2-comparison.json) retains the original review
and records the final SeedVR2 selection. Working files remain in ignored `output/`.

### Optional code rain

**Falling Code** uses irregular green clusters, larger foreground streams,
interrupted trails, and a quiet working area. **Mono Rain** has an independent,
sparse silver composition with asymmetric streams. Their [native 4K files](extras/backgrounds-code-4k)
and [native 8K companions](extras/backgrounds-8k) (**7680×4320**) remain optional.
The renderer draws glyphs directly at each size; they do not need photographic
reconstruction. Their seed is `1999`, and the monochrome image stays grayscale.

To opt into either image, select it manually or copy it into your personal
`~/.config/omarchy/backgrounds/matrix/` directory. This is an explicit addition to
the cycle; it is not part of the theme's default installation.

### Rebuild the cinematic exports

Use the existing local SeedVR2 installation and its tested
`workflows/api/image.json`. The runner changes only the input filename, scale
factor, and output prefix. It retains seed `17`, the tiled VAE settings, and
`--disable-async-offload`; copies inputs under unique names; records prompts and
history; and stops the service after the batch. It does not install or update
anything.

```sh
python scripts/upscale_seedvr2.py --scale 4 \
  extras/background-sources/3-green-street.png \
  extras/background-sources/4-the-office.png \
  extras/background-sources/5-hotel-corridor.png \
  extras/background-sources/6-after-hours.png

# Use the run directory printed above. Requires ImageMagick.
./scripts/export_stills output/seedvr2-YOUR-RUN-ID
```

The installation defaults to `/home/bernardv/Work/seedvr2`; override it with
`--seedvr2-dir`. The runner prints full PNG output paths under its `data/output/`
directory and retains master copies in a unique `output/seedvr2-*` directory.
The exporter accepts one or more successful run directories containing all four
scenes. It maps the original Hotel source stem `5-hotel-corridor` to the shipped
`0-hotel-corridor`, and writes the 4K cycle and 6K companions. No reconstruction
runs during this export step.

To rebuild the selected files from the two retained local batches:

```sh
./scripts/export_stills \
  output/seedvr2-matrix-comparison-20261022-r1 \
  output/seedvr2-after-hours-20261022-r1
```

The earlier Real-ESRGAN recipe is retained as `scripts/export_stills_realesrgan`.
It accepts the NCNN/Vulkan executable and model directory and writes only the
separate Real-ESRGAN comparison folders.

### Rebuild the optional rain

On Arch, the renderer uses `python-cairo`, `python-gobject`, `python-pillow`,
`pango`, and `noto-fonts-cjk`. Pillow exports JPEGs at quality 95 with chroma
subsampling disabled.

```sh
# Defaults to extras/backgrounds-code-4k; never reintroduces rain into the cycle.
python scripts/render_rain.py

python scripts/render_rain.py extras/backgrounds-8k --width 7680 --height 4320
python scripts/render_rain.py /tmp/matrix-ultrawide --width 3440 --height 1440
python scripts/render_rain.py /tmp/matrix-portrait --width 2160 --height 3840
python scripts/render_rain.py /tmp/matrix-clean --scanlines 0 --bloom 0 --format png
```

`--profile auto` selects a distinct placement profile for each palette.
`--density`, `--quiet`, `--seed`, and `--palette` allow further tuning. Glyph size
scales automatically; `--cell` overrides the base cell in output pixels.
Repeated runs with identical options and rendering libraries are deterministic;
font or library versions can affect pixels.

## Lock screen

This theme styles the lock input with readable placeholder text, green focus,
and a red error state. It does not replace the lock design or authentication.

The earlier preview used a separately installed custom design named `my-rain`
from Lock Screen Explorer. That design is **not bundled** and the name is not a
stock dependency. A portable animated lock companion is planned separately;
installing this theme alone provides the lock colors, not animated rain.

## What it themes

Omarchy generates the rest from `colors.toml` when the theme is applied:

- Omarchy shell (bar, menus, notifications, OSD, lock chrome)
- Alacritty, Foot, Ghostty, Kitty
- Neovim (Aether), Helix, VS Code, Obsidian
- btop, Chromium
- Hyprland active border
- Keyboard RGB (`3CBF5C`)
- Icons: `Yaru-olive-dark`

## Validation

```sh
python -m unittest discover -s tests -v
./scripts/matrix-terminal --check
./scripts/matrix-terminal --terminal foot --check
./scripts/matrix-terminal --phosphor --check
```

The GitHub Actions workflow checks unclipped glyphs, seeded exports, independent
rain profiles, consistent native 4K/8K placement, JPEG/portrait output, the exact
four-scene cinematic cycle, Hotel-first ordering, optional rain and 4K/6K/8K
dimensions, palette contrast and aliases, shell colors,
argument handling, invalid renderer input, and GLSL compilation.
The shader test requires `glslangValidator` and skips locally if it is absent;
CI installs it. Terminal `--check` commands validate configs without opening a window.

Local validation uses Omarchy 4.0.3-1, Ghostty 1.3.1, Foot 1.28.0, and Starship
1.26.0. Repository staging was exercised in an isolated directory, including the
generated terminal configs and shell overrides. Desktop review covers the menu,
lock preview, terminal profiles, and Ghostty glow on an AMD Radeon RX 7900 XTX.
Rendering on other GPUs and display scales may differ.

## License

MIT. The cinematic stills are original generations. The rain is original
code. The unlock mark is the Omarchy geometry recolored to phosphor green.
