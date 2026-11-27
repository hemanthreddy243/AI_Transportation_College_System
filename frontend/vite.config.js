import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import basicSsl from "@vitejs/plugin-basic-ssl";

// `npm run dev:https` -> https://<your-PC-IP>:5173 so a driver's phone on the same Wi-Fi can share
// real GPS (phone browsers only allow location on HTTPS). Accept the certificate warning once.
export default defineConfig(({ mode }) => ({
  plugins: [react(), ...(mode === "https" ? [basicSsl()] : [])],
  server: {
    host: true, // reachable from phones on the same Wi-Fi
    proxy: { "/api": { target: "http://localhost:8000", ws: true } },
  },
}));
