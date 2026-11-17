import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import vue from "@vitejs/plugin-vue";
import AutoImport from "unplugin-auto-import/vite";
import Components from "unplugin-vue-components/vite";
import { ElementPlusResolver } from "unplugin-vue-components/resolvers";
import { defineConfig } from "vite";

const versionPath = fileURLToPath(new URL("../VERSION", import.meta.url));
const appVersion = readFileSync(versionPath, "utf8").trim();

// 构建到 web/app/，由 server.py 在 / 与前端路由上回落这个入口；
// base 用 /app/ 保证深层路由（如 /settings）刷新时静态资源仍然可解析。
export default defineConfig({
  base: "/app/",
  plugins: [
    vue(),
    // Element Plus 按需引入：只打包页面真正用到的组件与其样式
    // （首屏 JS 由 1.3 MB 降到约 270 KB）。
    // 这里刻意不生成组件类型声明：Element Plus 的表格/树等组件把作用域插槽的
    // row 标成 DefaultRow，会把现有 90 多处模板调用判成类型错误，属于噪音。
    AutoImport({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
    Components({
      resolvers: [ElementPlusResolver()],
      dts: false,
    }),
  ],
  define: {
    __APP_VERSION__: JSON.stringify(appVersion),
    __APP_BUILD_TIME__: JSON.stringify(new Date().toISOString()),
  },
  // 开发模式：把 /api 转发到本地后端（默认 python server.py 监听 8000），
  // 否则 dev server 会把接口请求当成静态资源返回 404，登录与列表都加载不出来。
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: {
      "/api": {
        target: process.env.OA_DEV_API ?? "http://127.0.0.1:8000",
        changeOrigin: true,
      },
    },
  },
  build: {
    outDir: "../web/app",
    emptyOutDir: true,
    target: "es2020",
    sourcemap: false,
    chunkSizeWarningLimit: 600,
  },
});
