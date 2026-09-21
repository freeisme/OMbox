<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useRoute, useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { api } from "../api/client";
import { firstVisiblePath, loadMeta, login, session } from "../session";

const route = useRoute();
const router = useRouter();
const form = reactive({ username: "", password: "" });
const submitting = ref(false);
const errorMessage = ref("");
const version = computed(() => session.meta?.version || __APP_VERSION__);
/** 登录页显示系统设置里的名称与提示语；接口不可用时回落到产品默认名。 */
const appName = ref("OMbox 运维（O&M）盒子");
const loginNotice = ref("");

async function loadBranding(): Promise<void> {
  try {
    const payload = await api<{ settings?: { app_name?: string; login_notice?: string } }>(
      "/api/auth/bootstrap-status",
    );
    if (payload.settings?.app_name) appName.value = payload.settings.app_name;
    loginNotice.value = payload.settings?.login_notice?.trim() || "";
  } catch {
    // 保持默认名称，不阻塞登录
  }
}

async function submit(): Promise<void> {
  if (!form.username.trim() || !form.password) {
    errorMessage.value = "请输入账号和密码。";
    return;
  }
  submitting.value = true;
  errorMessage.value = "";
  try {
    await login(form.username.trim(), form.password);
    await loadMeta();
    ElMessage.success("登录成功。");
    const redirect = typeof route.query.redirect === "string" ? route.query.redirect : "";
    await router.replace(redirect || firstVisiblePath());
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "登录失败。";
  } finally {
    submitting.value = false;
  }
}

void loadMeta();
void loadBranding();
</script>

<template>
  <div class="oa-login">
    <el-card class="oa-login-card">
      <template #header>
        <div class="oa-flex-between">
          <strong>{{ appName }}</strong>
          <el-tag size="small" effect="plain" type="info">v{{ version }}</el-tag>
        </div>
      </template>
      <p v-if="loginNotice" class="oa-hint oa-mb-3">{{ loginNotice }}</p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="账号">
          <el-input v-model="form.username" autocomplete="username" placeholder="请输入账号" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input
            v-model="form.password"
            type="password"
            show-password
            autocomplete="current-password"
            placeholder="请输入密码"
            @keyup.enter="submit"
          />
        </el-form-item>
        <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
        <el-button
          type="primary"
          class="oa-full-width oa-mt-3"
          :loading="submitting"
          @click="submit"
        >
          登录
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>
