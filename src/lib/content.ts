import { promises as fs } from "node:fs";
import path from "node:path";
import yaml from "js-yaml";
import { z } from "zod";

const CONTENT_ROOT = path.join(process.cwd(), "content");

const dateString = z.preprocess(
  (value) => {
    if (value instanceof Date) {
      return value.toISOString().slice(0, 10);
    }
    return value;
  },
  z.string().regex(/^\d{4}-\d{2}-\d{2}$/)
);

const imageSchema = z.object({
  id: z.string(),
  title: z.string(),
  date: dateString,
  capture_mode: z.enum(["deep_sky", "solar_system"]),
  composition_type: z.enum(["single", "mosaic"]),
  location_id: z.string(),
  description: z.string().optional(),
  targets: z.array(z.string()).min(1),
  equipment: z.object({
    scope_id: z.string(),
    mount_id: z.string(),
    camera_id: z.string(),
    filter_id: z.string().optional()
  }),
  capture: z
    .object({
      focal_length_mm: z.number().positive().optional(),
      pixel_scale_arcsec_per_px: z.number().positive().optional(),
      gain: z.number().optional(),
      offset: z.number().optional(),
      notes: z.string().optional()
    })
    .optional(),
  acquisitions: z
    .array(
      z.object({
        session_id: z.string().optional(),
        date: dateString,
        frames: z.number().int().positive(),
        exposure_s: z.number().positive(),
        filter_id: z.string().optional(),
        notes: z.string().optional()
      })
    )
    .min(1),
  framing: z
    .object({
      center_ra_deg: z.number(),
      center_dec_deg: z.number(),
      rotation_deg: z.number(),
      fov_width_deg: z.number().positive(),
      fov_height_deg: z.number().positive()
    })
    .optional(),
  assets: z.object({
    version: z.number().int().min(1)
  }),
  skychart: z
    .object({
      version: z.number().int().min(1),
      caption: z.string().optional()
    })
    .optional(),
  seo: z
    .object({
      alt: z.string().optional(),
      keywords: z.array(z.string()).optional()
    })
    .optional()
});

const objectSchema = z.object({
  id: z.string(),
  slug: z.string(),
  title: z.string(),
  domain: z.enum(["deep_sky", "solar_system"]),
  object_type: z.string(),
  catalogs: z.record(z.string(), z.string()).optional(),
  constellation: z.string().optional(),
  ra_deg: z.number().optional(),
  dec_deg: z.number().optional(),
  magnitude: z.number().optional(),
  angular_size_arcmin: z.string().optional(),
  description: z.string(),
  aliases: z.array(z.string()).optional()
});

const equipmentSchema = z.object({
  id: z.string(),
  slug: z.string(),
  kind: z.enum(["scope", "mount", "camera", "filter"]),
  brand: z.string(),
  model: z.string(),
  summary: z.string(),
  specs: z.record(z.string(), z.union([z.string(), z.number(), z.boolean()])).optional()
});

const locationSchema = z.object({
  id: z.string(),
  slug: z.string(),
  name: z.string(),
  lat: z.number(),
  lon: z.number(),
  bortle: z.number().int().min(1).max(9).optional(),
  timezone: z.string().optional(),
  description: z.string().optional()
});

export type ImageEntry = z.infer<typeof imageSchema>;
export type ObjectEntry = z.infer<typeof objectSchema>;
export type EquipmentEntry = z.infer<typeof equipmentSchema>;
export type LocationEntry = z.infer<typeof locationSchema>;

type SiteData = {
  images: ImageEntry[];
  objects: ObjectEntry[];
  equipment: EquipmentEntry[];
  locations: LocationEntry[];
};

let cache: Promise<SiteData> | null = null;

async function readYamlDirectory<T>(directory: string, schema: z.ZodType<T>): Promise<T[]> {
  const absoluteDir = path.join(CONTENT_ROOT, directory);
  const entries = await fs.readdir(absoluteDir, { withFileTypes: true });
  const yamlFiles = entries
    .filter((entry) => entry.isFile() && (entry.name.endsWith(".yml") || entry.name.endsWith(".yaml")))
    .map((entry) => entry.name)
    .sort();

  const records: T[] = [];

  for (const fileName of yamlFiles) {
    const fullPath = path.join(absoluteDir, fileName);
    const raw = await fs.readFile(fullPath, "utf-8");
    const parsed = yaml.load(raw);
    const result = schema.safeParse(parsed);
    if (!result.success) {
      throw new Error(`Invalid content in ${directory}/${fileName}: ${result.error.message}`);
    }
    records.push(result.data);
  }

  return records;
}

function assertUniqueId(records: Array<{ id: string }>, label: string): void {
  const ids = new Set<string>();

  for (const record of records) {
    if (ids.has(record.id)) {
      throw new Error(`Duplicate ${label} id: ${record.id}`);
    }
    ids.add(record.id);
  }
}

function assertUniqueIdAndSlug(records: Array<{ id: string; slug: string }>, label: string): void {
  const ids = new Set<string>();
  const slugs = new Set<string>();

  for (const record of records) {
    if (ids.has(record.id)) {
      throw new Error(`Duplicate ${label} id: ${record.id}`);
    }
    ids.add(record.id);

    if (slugs.has(record.slug)) {
      throw new Error(`Duplicate ${label} slug: ${record.slug}`);
    }
    slugs.add(record.slug);
  }
}

function assertReferences(data: SiteData): void {
  const objectIds = new Set(data.objects.map((entry) => entry.id));
  const equipmentIds = new Set(data.equipment.map((entry) => entry.id));
  const locationIds = new Set(data.locations.map((entry) => entry.id));

  for (const image of data.images) {
    if (!locationIds.has(image.location_id)) {
      throw new Error(`Image ${image.id} references unknown location_id: ${image.location_id}`);
    }

    for (const targetId of image.targets) {
      if (!objectIds.has(targetId)) {
        throw new Error(`Image ${image.id} references unknown target: ${targetId}`);
      }
    }

    const equipmentRefs = [
      image.equipment.scope_id,
      image.equipment.mount_id,
      image.equipment.camera_id,
      image.equipment.filter_id
    ].filter(Boolean) as string[];

    for (const equipmentId of equipmentRefs) {
      if (!equipmentIds.has(equipmentId)) {
        throw new Error(`Image ${image.id} references unknown equipment: ${equipmentId}`);
      }
    }
  }
}

async function loadSiteData(): Promise<SiteData> {
  const [images, objects, equipment, locations] = await Promise.all([
    readYamlDirectory("images", imageSchema),
    readYamlDirectory("objects", objectSchema),
    readYamlDirectory("equipment", equipmentSchema),
    readYamlDirectory("locations", locationSchema)
  ]);

  const sortedImages = images.sort((a, b) => b.date.localeCompare(a.date));
  const sortedObjects = objects.sort((a, b) => a.title.localeCompare(b.title));
  const sortedEquipment = equipment.sort((a, b) => a.kind.localeCompare(b.kind) || a.model.localeCompare(b.model));
  const sortedLocations = locations.sort((a, b) => a.name.localeCompare(b.name));

  const data: SiteData = {
    images: sortedImages,
    objects: sortedObjects,
    equipment: sortedEquipment,
    locations: sortedLocations
  };

  assertUniqueId(data.images, "image");
  assertUniqueIdAndSlug(data.objects, "object");
  assertUniqueIdAndSlug(data.equipment, "equipment");
  assertUniqueIdAndSlug(data.locations, "location");
  assertReferences(data);

  return data;
}

export async function getSiteData(): Promise<SiteData> {
  if (!cache) {
    cache = loadSiteData();
  }
  return cache;
}

export async function getAllImages(): Promise<ImageEntry[]> {
  const { images } = await getSiteData();
  return images;
}

export async function getAllObjects(): Promise<ObjectEntry[]> {
  const { objects } = await getSiteData();
  return objects;
}

export async function getImageById(id: string): Promise<ImageEntry | undefined> {
  const images = await getAllImages();
  return images.find((image) => image.id === id);
}

export async function getObjectBySlug(slug: string): Promise<ObjectEntry | undefined> {
  const objects = await getAllObjects();
  return objects.find((entry) => entry.slug === slug);
}

export async function getImagesForObject(objectId: string): Promise<ImageEntry[]> {
  const images = await getAllImages();
  return images.filter((image) => image.targets.includes(objectId));
}

export function getImageAssetKey(image: ImageEntry, kind: "original" | "web" | "thumb"): string {
  const version = image.assets.version;
  if (kind === "original") {
    return `originals/${image.id}/v${version}.jpg`;
  }
  if (kind === "web") {
    return `web/${image.id}/v${version}.webp`;
  }
  return `thumbs/${image.id}/v${version}.webp`;
}

export function getImageAssetUrl(image: ImageEntry, kind: "original" | "web" | "thumb"): string {
  const baseUrl = (import.meta.env.PUBLIC_IMAGE_BASE_URL ?? "https://img.astrocaptures.de").replace(/\/+$/, "");
  return `${baseUrl}/${getImageAssetKey(image, kind)}`;
}

export function getSkychartUrl(image: ImageEntry): string | null {
  if (!image.skychart) {
    return null;
  }
  const baseUrl = (import.meta.env.PUBLIC_IMAGE_BASE_URL ?? "https://img.astrocaptures.de").replace(/\/+$/, "");
  return `${baseUrl}/charts/${image.id}/v${image.skychart.version}.webp`;
}

export function formatDate(date: string): string {
  return new Intl.DateTimeFormat("en", {
    year: "numeric",
    month: "short",
    day: "numeric"
  }).format(new Date(`${date}T00:00:00Z`));
}

export function formatIntegrationSeconds(totalSeconds: number): string {
  const hours = Math.floor(totalSeconds / 3600);
  const minutes = Math.floor((totalSeconds % 3600) / 60);
  const seconds = Math.round(totalSeconds % 60);

  if (hours > 0) {
    return `${hours}h ${minutes}m`;
  }
  if (minutes > 0) {
    return `${minutes}m ${seconds}s`;
  }
  return `${seconds}s`;
}

export function acquisitionIntegration(acquisition: ImageEntry["acquisitions"][number]): number {
  return acquisition.frames * acquisition.exposure_s;
}

export function imageTotalIntegration(image: ImageEntry): number {
  return image.acquisitions.reduce((total, acquisition) => total + acquisitionIntegration(acquisition), 0);
}
