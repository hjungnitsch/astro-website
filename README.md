# AstroCaptures

AstroCaptures is a static Astro website for publishing astrophotography images with linked celestial-object pages, equipment details, capture metadata, and downloadable originals.

Production website: [astrocaptures.de](https://astrocaptures.de)

## Architecture

| Concern | Implementation |
| --- | --- |
| Website | Astro static site generation |
| Metadata | YAML files under `content/` |
| Per-file validation | JSON Schema through `scripts/validate_content.py` |
| Build-time loading | Zod schemas and reference checks in `src/lib/content.ts` |
| Website hosting | Cloudflare Pages |
| Image storage | Cloudflare R2, publicly served from `img.astrocaptures.de` |
| Image processing | Python, Pillow, and the R2 S3-compatible API |
| Automation | GitHub Actions |

The build does not contain astrophotography binaries. It generates deterministic public URLs from YAML metadata, while originals and derivatives remain in R2.

## Requirements

- Node.js 22.12 or newer
- npm 9.6.5 or newer
- Python 3.12 recommended to match CI
- Git
- Suitable R2 or Cloudflare access when uploading originals, charts, object images, or generated derivatives

## Local setup

Run commands from the repository root:

```bash
npm ci

python3 -m venv .venv
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

Start the development server:

```bash
npm run dev
```

Images use `https://img.astrocaptures.de` by default, so local development does not require local image files or R2 credentials.

The custom YAML loader caches content in the Astro process. Restart the development server if a YAML change is not reflected.

## Quality checks

Run the full local quality gate before merging:

```bash
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B scripts/validate_content.py
npm run check
npm run build
```

The commands cover different concerns:

| Command | Purpose |
| --- | --- |
| `python -B -m unittest discover -s tests -p "test_*.py" -v` | Tests the content validator and its error handling |
| `python -B scripts/validate_content.py` | Validates schemas, IDs, references, equipment kinds, domains, and date invariants |
| `npm run check` | Runs Astro and TypeScript diagnostics |
| `npm run build` | Generates all static routes and catches build-time content failures |

Preview the generated `dist/` directory after a successful build:

```bash
npm run preview
```

## Content model

| Directory | Purpose |
| --- | --- |
| `content/images/` | Published image metadata and capture details |
| `content/objects/` | Celestial objects referenced by images |
| `content/equipment/` | Scopes, mounts, cameras, and filters |
| `content/locations/` | Capture locations |
| `schemas/` | Strict JSON Schemas for each content type |

References always use stable `id` values, never display names. IDs must be unique within each content category; object, equipment, and location slugs must also be unique within their category.

Image IDs determine image routes and R2 paths. Object IDs determine references and object-image keys, while object slugs determine object routes. Equipment and location IDs are reference targets; their slugs remain stable metadata even though they are not currently used for routes. Renaming any ID or slug is a migration, not a cosmetic edit.

### Image invariants

- Image IDs follow `img_YYYYMMDD_name`.
- The date encoded in the image ID equals the top-level `date`.
- When one or more `acquisitions` are present, top-level `date` equals the latest acquisition date.
- Deep-sky images require at least one acquisition, and every acquisition requires `frames` and `exposure_s`.
- Solar-system images may omit acquisitions when historical capture data is unavailable.
- `capture_mode` must match the `domain` of every referenced object.
- `scope_id`, `mount_id`, `camera_id`, and `filter_id` must reference matching equipment kinds.
- Acquisition `filter_id` values must reference equipment with `kind: filter`.
- Lucky-imaging acquisitions may use `stacked_percent` to document the retained percentage of video frames.

The homepage currently requires the featured image ID `img_20250919_andromeda` in `src/pages/index.astro`. Do not remove or rename it without updating the page.

### Schema changes

Content is described in two places:

- JSON Schemas in `schemas/`, used by the Python validator and currently authoritative for the complete field constraints.
- Zod schemas in `src/lib/content.ts`, used while Astro loads content and checks the build-time field shape.

The JSON Schemas are intentionally stricter in areas such as unknown properties, patterns, lengths, and numeric ranges. A successful Astro build alone therefore does not replace the Python validator. When changing fields or shared semantic rules, keep both schema layers aligned, update global validator rules where applicable, and update tests and documentation.

## Image storage

Storage keys are derived from stable image IDs and version numbers:

| Asset | R2 key |
| --- | --- |
| Original | `originals/{image.id}/{image.id}_v{assets.version}.jpg` |
| Web image | `web/{image.id}/{image.id}_v{assets.version}.webp` |
| Thumbnail | `thumbs/{image.id}/{image.id}_v{assets.version}.webp` |
| Sky chart | `charts/{image.id}/{image.id}_v{skychart.version}.webp` |
| Object image | `objects/{object.id}.webp` |

Do not commit originals, generated derivatives, sky charts, or object images to Git. Small website UI assets such as icons and logos under `public/` are allowed.

### Publishing a new image

1. Add any missing object, equipment, and location records first.
2. Choose a stable image ID whose date matches the final capture date.
3. Set `assets.version` to `1` and upload the source JPEG to the exact original key.
4. Add the image YAML with valid references and capture metadata.
5. Upload an optional sky chart to its deterministic chart key.
6. Run all local quality checks.
7. Open a pull request. PR CI validates and builds without accessing R2 or Cloudflare secrets.
8. After merge to `main`, the production workflow creates any missing derivatives and deploys the previously built site artifact.

The workflow checks all image YAML files, but the generator uploads only derivatives whose expected keys do not already exist.

### Reprocessing an image

Never replace an image at an existing versioned key.

1. Increment `assets.version`.
2. Upload the replacement source JPEG under the new original key.
3. Increment `skychart.version` only when the sky chart also changes, then upload the new chart.
4. Run validation and build checks before merging.

Keep old versioned image assets in R2 so older deployments and rollbacks continue to work.

### Local derivative generation

This command reads from and writes to the configured R2 bucket:

```bash
python scripts/generate_derivatives.py --bucket astro-images --all
```

Required environment variables:

- `S3_URL`
- `S3_ACCESS_KEY`
- `S3_SECRET_KEY`

The default long edges are 2800 px for web images and 600 px for thumbnails. `--all` means all image YAML files are inspected; existing derivative keys are still skipped. There is no force-overwrite mode.

Sky charts and object images are not created by this script. They must be generated and uploaded separately.

## Configuration

| Name | Scope | Required | Purpose |
| --- | --- | --- | --- |
| `PUBLIC_IMAGE_BASE_URL` | Astro build environment | No | Overrides the default `https://img.astrocaptures.de` asset base URL |
| `S3_URL` | GitHub variable or local environment | For derivative generation | R2 S3-compatible endpoint |
| `S3_ACCESS_KEY` | GitHub secret or local environment | For derivative generation | R2 access key |
| `S3_SECRET_KEY` | GitHub secret or local environment | For derivative generation | R2 secret key |
| `CLOUDFLARE_API_TOKEN` | GitHub secret | For deployment | Deploys to Cloudflare Pages |
| `CLOUDFLARE_ACCOUNT_ID` | GitHub secret | For deployment | Selects the Cloudflare account |

Production secrets may be repository-level or attached to the `production` GitHub Environment. Environment secrets are preferred because the deploy job is already bound to that environment.

The following external settings are not stored in this repository:

- Cloudflare Pages project and production branch configuration
- Custom domains and DNS
- R2 public-domain and CORS configuration
- Token scopes and rotation
- R2 lifecycle rules for obsolete asset versions

## Continuous integration and deployment

The workflow is defined in `.github/workflows/build-and-deploy-website.yaml`.

For pull requests targeting `main`, the secrets-free `Build and validate` job runs:

1. Validator unit tests.
2. Repository content validation.
3. Astro and TypeScript checks.
4. Static site build.

For pushes to `main`, the same build job additionally uploads `dist/` as a commit-specific artifact. The separate production job then:

1. Downloads and verifies that exact artifact.
2. Checks all image records and generates missing R2 derivatives.
3. Deploys the artifact to the Cloudflare Pages project `astrofotos` on branch `main`.

Production deployments are serialized and are never canceled while external writes are running. The deploy job uses the GitHub Environment `production`; PR jobs do not reference cloud secrets or perform external writes.

Configure `Build and validate` as a required status check for the `main` branch.

### Rollback

Use one of these approaches:

1. Roll back to a previous deployment in the Cloudflare Pages dashboard.
2. Revert the problematic Git commit and push the revert to `main`.

Previous image versions remain usable only while all R2 objects referenced by the old deployment still exist. The automation does not delete old R2 objects, but manual deletion or lifecycle rules can break an old deployment. Object images use unversioned keys and are not restored by a Pages rollback.

## Troubleshooting

### `Missing dependency: jsonschema`

Activate the virtual environment and install the Python requirements:

```bash
. .venv/bin/activate
python -m pip install -r requirements-dev.txt
```

### Astro reports an unsupported Node.js version

Use Node.js 22.12 or newer, keep `package-lock.json`, and reinstall dependencies with `npm ci`.

### `Missing source image`

Verify that the original JPEG exists at the deterministic `originals/` key for the current `assets.version` and that the configured credentials can read it. The script currently reports any R2 `get_object` client error as a missing source image, including some permission failures.

### Derivative generation prints `SKIP`

Both expected derivative keys already exist. To reprocess an image, increment `assets.version` and upload a new original instead of overwriting an existing key.

### A sky chart or object image is missing

These asset types are managed manually and are not checked or generated by `generate_derivatives.py`. Verify the exact R2 key and public accessibility.

### Content validation passes locally but the page looks stale

Restart `npm run dev`. The custom content loader caches YAML records for the lifetime of the Astro process.
