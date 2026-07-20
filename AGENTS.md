# Agent Notes

## Repository boundaries

- Keep image, object, equipment, and location metadata in their respective YAML directories under `content/`.
- Do not commit astrophotography originals, derivatives, sky charts, object images, secrets, or `.env` files.
- Small website UI assets under `public/` are allowed.
- Do not run `scripts/generate_derivatives.py` unless the user explicitly requests an R2-writing operation.
- Do not add workflow steps that commit generated files or metadata back to the repository.

## Content invariants

- Use stable IDs for references; never reference records by display name.
- IDs must be unique within each content category. Object, equipment, and location slugs must be unique within their category.
- Do not casually rename IDs or slugs. Image IDs affect image routes and R2 keys; object slugs affect object routes; other IDs and slugs remain stable content identifiers.
- Image IDs follow `img_YYYYMMDD_name`, and the encoded date must equal top-level `date`.
- If one or more acquisitions exist, top-level `date` must equal the latest acquisition date.
- Deep-sky images require at least one acquisition, and every acquisition requires `frames` and `exposure_s`; solar-system images may omit acquisitions.
- An image `capture_mode` must match every referenced object `domain`.
- Equipment references must match their field: `scope`, `mount`, `camera`, or `filter`. Acquisition filters must reference `kind: filter`.
- Preserve the homepage featured image ID `img_20250919_andromeda` unless `src/pages/index.astro` is updated with it.

## Schema changes

- Keep fields and shared semantic rules in JSON Schemas under `schemas/` and Zod schemas in `src/lib/content.ts` synchronized. JSON Schemas remain stricter and authoritative for complete metadata validation.
- Update `scripts/validate_content.py` when a change introduces a new cross-record or semantic invariant.
- Add or update tests in `tests/test_validate_content.py` for validator behavior changes.
- Update README content and examples when workflows, required fields, commands, or configuration change.

## Asset invariants

Image storage paths are deterministic:

- original: `originals/{image.id}/{image.id}_v{assets.version}.jpg`
- web: `web/{image.id}/{image.id}_v{assets.version}.webp`
- thumbnail: `thumbs/{image.id}/{image.id}_v{assets.version}.webp`
- sky chart: `charts/{image.id}/{image.id}_v{skychart.version}.webp`
- object image: `objects/{object.id}.webp`

- Never overwrite a versioned image asset. Increment `assets.version`, then upload the new original under the new key.
- Increment `skychart.version` independently when the chart changes.
- The derivative generator creates only web images and thumbnails. Sky charts and object images remain external/manual assets.

## Workflow safety

- Pull-request jobs must remain secrets-free and must not deploy or mutate R2.
- Restrict cloud credentials to the production deploy job and never print secret values.
- Build the site before any R2 writes, and deploy only the artifact produced by the successful build job.
- Keep production deployments serialized; do not cancel a job during R2 or Pages writes.
- Preserve `contents: read` as the default GitHub token permission unless a concrete step requires more.
- Do not introduce `pull_request_target` for workflows that execute repository code.

## Dependency updates

- Keep `package-lock.json` synchronized with `package.json` and use `npm ci` for reproducible installs.
- Change direct Python dependencies in `requirements-dev.in`, then regenerate the hashed `requirements-dev.txt` with the documented uv and Python versions; do not edit the generated lock manually.
- Keep GitHub Actions pinned to full commit SHAs with the release version in an inline comment.
- Pin Wrangler independently through the action's `wranglerVersion` input.

## Required checks

Run all checks before merging:

```bash
python -B -m unittest discover -s tests -p "test_*.py" -v
python -B scripts/validate_content.py
npm run check
npm run build
```

Report any check that could not be run. Do not run R2-writing scripts as part of local verification unless explicitly requested.
