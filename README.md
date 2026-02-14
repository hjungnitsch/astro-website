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
