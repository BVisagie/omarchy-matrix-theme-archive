# Background overhaul plan

Approved direction dated 2026-10-22, based on repository commit `01b09c3` and
visual review of the collection. The implemented default cycle contains four
cinematic backgrounds mastered with SeedVR2 at 4K and 6K. **Hotel Corridor is the
first wallpaper.** Both code-rain designs remain optional native 4K/8K extras,
outside `backgrounds/` so theme application does not select them.

The final user selection supersedes the original plan to keep After Hours' export
unchanged: its successful composition is retained, and its original 1672×941 PNG
was recovered from Git and mastered through the same SeedVR2 3B FP16 workflow.
Earlier Real-ESRGAN exports remain in separate comparison folders. See
[current provenance](background-provenance.json), [generation prompts](background-prompts.json),
and the [comparison record](seedvr2-comparison.json).

The chosen direction remains **cinematic 1999 Matrix: restrained green, believable
spaces, and film texture**. The original art briefs below record the reasoning
behind each composition; the final packaging and mastering decisions above take
precedence over earlier filename, cycle, and preservation instructions.

## Collection direction

Ordinary places inside the simulation after everyone has left: late-1990s materials, institutional repetition, practical lighting, olive shadows, and small phosphor accents. Preserve six distinct roles: signature code, minimal monochrome, city exterior, corporate interior, hotel, and back office.

Use the theme's `#080C09` black and `#3CBF5C` accent as references. Photographic scenes need varied, believable material colors; reserve the strongest greens for screens and selected light sources. Retain shadow detail and subtle texture. Keep highlights localized and give windows room to sit comfortably over the artwork.

## Decisions and production briefs

| Background | Decision | Why |
| --- | --- | --- |
| `1-falling-code.jpg` | Refine | Good restraint and identity; thin streams have weak visual hierarchy at desktop scale. |
| `2-mono-rain.jpg` | Redesign the composition | It currently repeats Falling Code's layout exactly, with a different palette. |
| `3-green-street.jpg` | Refine substantially | Strong camera angle and atmosphere; broad lime reflections, conspicuous rain, and the baked frame need work. |
| `4-the-office.jpg` | Rebuild first | Bright desks, numerous active screens, pink fluorescent edges, and crowded props compete for attention. |
| `5-hotel-corridor.jpg` | Rebuild | Good perspective, but repeated exit markers, bright sconces, exterior neon, and the distressed frame weaken the setting. |
| `6-after-hours.jpg` | Keep unchanged | Convincing materials, controlled lighting, quiet wall planes, and the partly concealed CRT already work well behind the desktop. |

**Falling Code.** Extend the existing procedural renderer. Make the foreground streams more legible, vary their clustering, introduce interrupted trails and real spatial gaps, and keep pale heads sparse. Preserve the dark working area. The renderer already has three size layers, bloom, scanlines, and center dimming; improve their visual hierarchy rather than adding another global effect. Its current quiet-center function dims glyphs without reducing their occupancy, so intentional gaps need placement changes.

**Mono Rain.** Create a separate deterministic composition: fewer, somewhat larger silver-phosphor streams, asymmetric placement, broad black space, and faint distant traces. This should be the collection's quietest choice. Give it its own reproducible preset and retain neutral grayscale. Avoid simply desaturating the revised green wallpaper.

**Green Street.** Preserve the oblique camera angle, abandoned intersection, payphones, and receding street lamps. Use the original as an image-edit reference. Remove the rounded black frame; reduce the yellow cast and broad pavement highlights. Concentrate light around one entrance or payphone, darken some windows, and show rain chiefly where light catches it. Improve wet asphalt and architectural detail without flattening the scene into uniform darkness. If an edit cannot resolve the source's soft detail, create a new rendition that retains this framing and setting.

**The Office.** Recompose around one credible, off-center workstation in an empty cubicle floor. Include a beige CRT, telephone, and sparse paperwork. Leave most monitors and some ceiling fixtures dark. Use partitions and shadow to create a calmer central field. Keep fluorescent light subdued and consistent with the palette. Check keyboards, cables, furniture, and repeated ceiling geometry closely; reduce novelty props and incidental branding.

**Hotel Corridor.** Retain the rainy end window and the sense of depth. Emphasize faded wallpaper, dark timber doors, brass sconces, and worn carpet, making this setting distinct from After Hours' institutional corridor. Use fewer illuminated lamps and uneven pools of light. Add a slight asymmetry, such as a service cart, while keeping the composition legible. Remove the decorative frame, pink neon, and implausibly repeated exit markers.

**After Hours.** Preserve the shipped file, exposure, framing, and restrained CRT glow. Some texture is soft at full resolution, but the complete composition earns the exception. Use it to judge the new scenes' lighting, texture, and desktop usability.

## Execution sequence

1. **Establish the pilot pair.** Produce two Office concepts and two Falling Code treatments. Compare them with the originals and After Hours, both unobstructed and under representative theme windows. Select the lighting and rain intensity before extending the collection.
2. **Extend the direction.** Refine Green Street and develop Hotel Corridor and Mono Rain. Create two candidates for each where useful, then refine the strongest. Keep candidate images and source masters outside `backgrounds/` so they do not enter the installed cycle.
3. **Finish the selected five.** Use image generation/editing for cinematic artwork and the existing code renderer for rain. Retain generation instructions, reference inputs, actual source dimensions, and processing details. Preserve source masters, inspect them before upscaling, and export the final six-image collection at 3840×2160, including unchanged After Hours.
4. **Integrate.** Keep the six filenames and cycle order. Update `README.md` with the new briefs, source provenance, and exact rain reproduction commands. Refresh screenshots if they depict changed artwork; the existing After Hours desktop preview can remain if it still accurately represents the release.

## Acceptance and validation

- Compare original and candidate at the same scale. A replacement must visibly improve composition, light, or detail while retaining the intended setting.
- Inspect cinematic sources and final exports at 100% for malformed geometry, smeared materials, repeated props, sharpening halos, banding, and compression damage. Upscaling must not be the only improvement.
- Review each image behind opaque editor and terminal windows and with the top bar and menus visible. Check 100% and 150% desktop scaling. Keep bright hotspots from dominating the exposed desktop, and preserve readable shadow detail.
- Use edge-to-edge artwork without decorative borders. Check 16:10 and ultrawide crops for resilience; additional aspect-ratio exports are optional future work, not part of this six-file release.
- Export RGB/sRGB 3840×2160 JPEGs. Use quality 95 without chroma subsampling as the initial export setting, then inspect actual output and size. The rain is native-resolution; document any upscaling of cinematic sources honestly. The current README records 1280×720 sources for Street, Office, and Hotel, and 1672×941 for After Hours.
- Preserve seeded reproducibility, unclipped glyphs, grayscale output, and JPEG/portrait export behavior when modifying `scripts/render_rain.py`. Add focused regression coverage for any new preset or placement behavior, then run `python -m unittest discover -s tests -v`.
- Verify that the shipped background cycle still contains exactly the six intended images and that After Hours is unchanged. Existing image tests check RGB and 4K dimensions; visual acceptance remains a separate review.

Expected implementation touches: five files in `backgrounds/`, `scripts/render_rain.py`, focused renderer tests if needed, and `README.md`. The theme palette, shell styling, terminal configuration, and lock artwork remain outside this background overhaul.
