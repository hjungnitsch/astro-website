# Agent Notes

## Repository conventions

- Keep image metadata in YAML under `content/images`.
- Keep object, equipment, and location records in their respective `content/*` folders.
- Do not commit image binaries to Git.
- Use stable IDs (`id`) for references; do not reference by display name.

## Image key strategy

Image storage paths are deterministic and derived from YAML values:

- original: `originals/{image.id}/v{assets.version}.jpg`
- web: `web/{image.id}/v{assets.version}.webp`
- thumb: `thumbs/{image.id}/v{assets.version}.webp`
- skychart: `charts/{image.id}/v{skychart.version}.webp`

When an image is reprocessed, increment `assets.version` (and `skychart.version` if needed).

## Validation and automation

- Run `python3 scripts/validate_content.py` before merging.
- GitHub Actions generates missing derivatives for changed image YAMLs.
- Do not write workflow steps that commit metadata back to the repository.
