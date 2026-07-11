/// <reference types="vite/client" />

interface ImportMetaEnv {
  readonly VITE_OAUTH_ENABLED?: "true" | "false";
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
