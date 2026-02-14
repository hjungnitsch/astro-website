#!/usr/bin/env python3
"""Generate missing web and thumbnail derivatives for changed image YAML files."""

from __future__ import annotations

import argparse
import io
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

import boto3
import yaml
from botocore.exceptions import ClientError
from PIL import Image


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate missing web/thumb images in S3-compatible object storage."
    )
    parser.add_argument("--bucket", default="astro-images", help="Bucket name")
    parser.add_argument("--content-dir", default="content/images", help="Image YAML directory")
    parser.add_argument("--changed-from", help="Git revision to diff from")
    parser.add_argument("--changed-to", help="Git revision to diff to")
    parser.add_argument("--all", action="store_true", help="Process all image YAML files")
    parser.add_argument("--thumb-size", type=int, default=600, help="Thumbnail long edge in px")
    parser.add_argument("--web-size", type=int, default=2800, help="Web image long edge in px")
    return parser.parse_args()


def get_s3_client() -> Any:
    url = os.environ.get("S3_URL")
    access_key = os.environ.get("S3_ACCESS_KEY")
    secret_key = os.environ.get("S3_SECRET_KEY")

    if not url or not access_key or not secret_key:
        raise SystemExit("Missing S3 credentials: S3_URL, S3_ACCESS_KEY, S3_SECRET_KEY")

    return boto3.client(
        "s3",
        endpoint_url=url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def list_all_image_yaml(content_dir: Path) -> list[Path]:
    return sorted(
        file_path
        for file_path in content_dir.iterdir()
        if file_path.is_file() and file_path.suffix.lower() in {".yml", ".yaml"}
    )


def list_changed_image_yaml(content_dir: Path, changed_from: str, changed_to: str) -> list[Path]:
    if changed_from == "0000000000000000000000000000000000000000":
        return list_all_image_yaml(content_dir)

    cmd = ["git", "diff", "--name-only", changed_from, changed_to]
    proc = subprocess.run(cmd, check=True, capture_output=True, text=True)
    changed_files = [line.strip() for line in proc.stdout.splitlines() if line.strip()]

    result: list[Path] = []
    for changed in changed_files:
        if not changed.startswith("content/images/"):
            continue
        path = Path(changed)
        if path.suffix.lower() not in {".yml", ".yaml"}:
            continue
        if path.exists():
            result.append(path)
    return sorted(result)


def load_yaml(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as file:
        data = yaml.safe_load(file)
    if not isinstance(data, dict):
        raise ValueError(f"Invalid YAML object: {path}")
    return data


def derive_keys(image_id: str, version: int) -> dict[str, str]:
    file_base = f"{image_id}_v{version}"
    return {
        "original": f"originals/{image_id}/{file_base}.jpg",
        "web": f"web/{image_id}/{file_base}.webp",
        "thumb": f"thumbs/{image_id}/{file_base}.webp",
    }


def object_exists(client: Any, bucket: str, key: str) -> bool:
    try:
        client.head_object(Bucket=bucket, Key=key)
        return True
    except ClientError as exc:
        code = exc.response.get("Error", {}).get("Code")
        if code in {"404", "NoSuchKey", "NotFound"}:
            return False
        raise


def fetch_original(client: Any, bucket: str, key: str) -> bytes:
    try:
        response = client.get_object(Bucket=bucket, Key=key)
    except ClientError as exc:
        raise RuntimeError(f"Missing source image {key}") from exc
    return response["Body"].read()


def resize_to_long_edge(image_data: bytes, long_edge: int, quality: int) -> bytes:
    with Image.open(io.BytesIO(image_data)) as source:
        image = source.convert("RGB")
        width, height = image.size
        if max(width, height) > long_edge:
            if width >= height:
                new_width = long_edge
                new_height = round(height * (long_edge / width))
            else:
                new_height = long_edge
                new_width = round(width * (long_edge / height))
            image = image.resize((new_width, new_height), Image.Resampling.LANCZOS)

        output = io.BytesIO()
        image.save(output, format="WEBP", quality=quality, method=6)
        return output.getvalue()


def upload_object(client: Any, bucket: str, key: str, body: bytes) -> None:
    client.put_object(
        Bucket=bucket,
        Key=key,
        Body=body,
        ContentType="image/webp",
        CacheControl="public, max-age=31536000, immutable",
    )


def ensure_derivatives(client: Any, bucket: str, image_yaml: Path, thumb_size: int, web_size: int) -> None:
    data = load_yaml(image_yaml)

    image_id = data.get("id")
    assets = data.get("assets", {})
    version = assets.get("version")

    if not isinstance(image_id, str) or not image_id:
        raise RuntimeError(f"Missing image id in {image_yaml}")
    if not isinstance(version, int) or version < 1:
        raise RuntimeError(f"Missing assets.version in {image_yaml}")

    keys = derive_keys(image_id, version)
    missing_web = not object_exists(client, bucket, keys["web"])
    missing_thumb = not object_exists(client, bucket, keys["thumb"])

    if not missing_web and not missing_thumb:
        print(f"SKIP {image_yaml}: derivatives already exist")
        return

    print(f"PROCESS {image_yaml}")
    original_data = fetch_original(client, bucket, keys["original"])

    if missing_web:
        web_image = resize_to_long_edge(original_data, web_size, quality=82)
        upload_object(client, bucket, keys["web"], web_image)
        print(f"  uploaded {keys['web']}")

    if missing_thumb:
        thumb_image = resize_to_long_edge(original_data, thumb_size, quality=74)
        upload_object(client, bucket, keys["thumb"], thumb_image)
        print(f"  uploaded {keys['thumb']}")


def main() -> int:
    args = parse_args()
    content_dir = Path(args.content_dir)
    if not content_dir.exists():
        print(f"No content directory found at {content_dir}")
        return 0

    if args.all:
        targets = list_all_image_yaml(content_dir)
    elif args.changed_from and args.changed_to:
        targets = list_changed_image_yaml(content_dir, args.changed_from, args.changed_to)
    else:
        print("No change range provided. Use --all or --changed-from/--changed-to")
        return 0

    if not targets:
        print("No changed image YAML files to process")
        return 0

    client = get_s3_client()
    for image_yaml in targets:
        ensure_derivatives(client, args.bucket, image_yaml, args.thumb_size, args.web_size)

    return 0


if __name__ == "__main__":
    sys.exit(main())
