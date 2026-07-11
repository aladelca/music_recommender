const apiOrigin = requiredHttpsOrigin(process.env.PRODUCT_API_ORIGIN);
const securityHeaders = [
  {
    key: "Content-Security-Policy",
    value: "default-src 'self'; script-src 'self' https://open.spotify.com; style-src 'self' 'unsafe-inline'; frame-src https://open.spotify.com; connect-src 'self' https://open.spotify.com; img-src 'self' data: https://i.scdn.co https://image-cdn-ak.spotifycdn.com; font-src 'self'; base-uri 'self'; form-action 'self'; frame-ancestors 'none'; object-src 'none'",
  },
  { key: "Referrer-Policy", value: "strict-origin-when-cross-origin" },
  { key: "X-Content-Type-Options", value: "nosniff" },
  { key: "X-Frame-Options", value: "DENY" },
  { key: "Permissions-Policy", value: "camera=(), microphone=(), geolocation=()" },
  { key: "Strict-Transport-Security", value: "max-age=31536000; includeSubDomains" },
];

export const config = {
  buildCommand: "npm run build",
  outputDirectory: "dist",
  framework: "vite",
  rewrites: [
    { source: "/api/:path*", destination: `${apiOrigin}/:path*` },
    { source: "/:path*", destination: "/index.html" },
  ],
  headers: [
    {
      source: "/api/:path*",
      headers: [{ key: "Cache-Control", value: "private, no-store, max-age=0" }],
    },
    {
      source: "/",
      headers: securityHeaders,
    },
    {
      source: "/:path*",
      headers: securityHeaders,
    },
  ],
};

function requiredHttpsOrigin(value) {
  if (!value) throw new Error("PRODUCT_API_ORIGIN is required for Vercel deployment.");
  const parsed = new URL(value);
  if (
    parsed.protocol !== "https:"
    || parsed.username
    || parsed.password
    || parsed.pathname !== "/"
    || parsed.search
    || parsed.hash
  ) {
    throw new Error("PRODUCT_API_ORIGIN must be an HTTPS origin without a path.");
  }
  return parsed.origin;
}
