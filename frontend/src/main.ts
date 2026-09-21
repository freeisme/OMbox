import { createApp } from "vue";
// 组件由 unplugin-vue-components 按需引入；命令式 API（ElMessage / ElMessageBox）
// 在各页面显式 import，样式统一在这里登记一次。
import "element-plus/theme-chalk/dark/css-vars.css";
import "element-plus/es/components/message/style/css";
import "element-plus/es/components/message-box/style/css";
import { ElMessage } from "element-plus";
import "./styles/tokens.css";
import "./styles/app.css";
import App from "./App.vue";
import { setUnauthorizedHandler } from "./api/client";
import { router } from "./router";
import { expireSession, session } from "./session";
import { applyThemeColor, currentThemeColor } from "./theme";

const theme = window.localStorage.getItem("oa-theme") === "dark" ? "dark" : "light";
document.documentElement.dataset.theme = theme;
applyThemeColor(currentThemeColor(), { persist: false });

// 会话过期（例如服务端重启、会话被吊销）时立即回到登录页，并记住原地址。
let redirectingToLogin = false;
setUnauthorizedHandler(() => {
  if (!session.user || redirectingToLogin) return;
  expireSession();
  redirectingToLogin = true;
  const current = router.currentRoute.value;
  ElMessage.warning("登录状态已过期，请重新登录。");
  void router
    .replace({
      path: "/login",
      query: current.path === "/login" ? {} : { redirect: current.fullPath },
    })
    .finally(() => {
      redirectingToLogin = false;
    });
});

createApp(App).use(router).mount("#app");
