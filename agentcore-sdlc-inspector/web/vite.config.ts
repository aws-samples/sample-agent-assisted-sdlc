// Copyright Amazon.com, Inc. or its affiliates. All Rights Reserved.
// SPDX-License-Identifier: Apache-2.0

import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig({
  plugins: [react()],
  server: {
    port: parseInt(process.env.INSPECTOR_WEB_PORT || "5173", 10),
    proxy: {
      "/api": {
        target: `http://localhost:${process.env.INSPECTOR_API_PORT || "8787"}`,
        changeOrigin: true,
      },
    },
  },
});
