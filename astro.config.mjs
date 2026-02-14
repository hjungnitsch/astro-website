import { defineConfig } from "astro/config";
import sitemap from "@astrojs/sitemap";

export default defineConfig({
  site: "https://astrocaptures.de",
  output: "static",
  integrations: [sitemap()],
  trailingSlash: "never"
});
