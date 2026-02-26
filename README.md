# AstroCaptures

AstroCaptures is a static Astro website for publishing astrophotography images with linked object pages, equipment details, and downloadable originals.

## Stack

- Astro (static site generation)
- YAML content files in `content/`
- Cloudflare Pages deployment
- Cloudflare R2 image storage (`img.astrocaptures.de`)
- Python scripts for metadata validation and derivative generation

## Content model

- `content/images/*.yml`
- `content/objects/*.yml`
- `content/equipment/*.yml`
- `content/locations/*.yml`

Image capture detail conventions:

- Deep-sky images include detailed `acquisitions` with `frames` and `exposure_s`.
- Solar-system images can omit detailed `acquisitions` when historical capture stats are unavailable.
- For lucky imaging, `acquisitions` can include `stacked_percent` to document the best X% of video frames used for stacking.

Example (deep sky with capture stats):

```yaml
id: img_20251226_orion_widefield
capture_mode: deep_sky
acquisitions:
  - date: 2025-12-26
    frames: 275
    exposure_s: 45
```

Example (solar system without capture stats):

```yaml
id: img_20260118_jupiter_europa
capture_mode: solar_system
# acquisitions omitted when stats are unavailable
```

Example (solar system lucky imaging):

```yaml
id: img_20260118_jupiter_europa
capture_mode: solar_system
acquisitions:
  - date: 2026-01-18
    frames: 12000
    exposure_s: 0.008
    stacked_percent: 20
```

Image asset keys are derived from `image.id` and `assets.version`:

- `originals/{id}/{id}_v{version}.jpg`
- `web/{id}/{id}_v{version}.webp`
- `thumbs/{id}/{id}_v{version}.webp`
- optional skychart: `charts/{id}/{id}_v{skychart.version}.webp`

## Local development

```bash
npm install
python3 -m pip install -r requirements-dev.txt
python3 scripts/validate_content.py
npm run dev
```

## Build

```bash
npm run build
```

## Thumbnail/web derivative generation

The workflow script only processes changed image YAML files on push:

```bash
python3 scripts/generate_derivatives.py --bucket astro-images --all
```

Required environment variables:

- `S3_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`

## Deploy

Deployment runs via GitHub Actions (`.github/workflows/build-and-deploy-website.yaml`) and publishes `dist/` to Cloudflare Pages.
