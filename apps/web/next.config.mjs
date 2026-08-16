/** @type {import('next').NextConfig} */
const basePath = process.env.NEXT_PUBLIC_BASE_PATH ?? "";
const configuredDevOrigins = (process.env.NEXT_ALLOWED_DEV_ORIGINS ?? "")
  .split(",")
  .map((origin) => origin.trim())
  .filter(Boolean);

const nextConfig = {
  allowedDevOrigins: ["127.0.0.1", "localhost", ...configuredDevOrigins],
  basePath,
  poweredByHeader: false,
  productionBrowserSourceMaps: false,
  reactStrictMode: true
};

export default nextConfig;
