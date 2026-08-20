import type { MetadataRoute } from "next";

const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";

export default function manifest(): MetadataRoute.Manifest {
  const appRoot = `${basePath}/`;

  return {
    id: appRoot,
    name: "Witscraft",
    short_name: "Witscraft",
    description: "Player-led, AI-authored interactive fiction",
    start_url: appRoot,
    scope: appRoot,
    display: "standalone",
    background_color: "#f4efe4",
    theme_color: "#22201b",
    lang: "zh-CN",
    icons: [
      {
        src: `${basePath}/web-app-manifest-192x192.png`,
        sizes: "192x192",
        type: "image/png",
        purpose: "any"
      },
      {
        src: `${basePath}/web-app-manifest-512x512.png`,
        sizes: "512x512",
        type: "image/png",
        purpose: "any"
      }
    ]
  };
}
