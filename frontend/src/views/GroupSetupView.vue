<script setup lang="ts">
import { computed, reactive, ref } from "vue";
import { useRouter } from "vue-router";
import { ElMessage } from "element-plus";
import { completeGroupSetup } from "../api/company";
import { firstVisiblePath, loadMeta, refreshSession, session } from "../session";

const router = useRouter();
const form = reactive({
  groupName: "",
  companyName: "",
  moduleDatacenterEnabled: true,
  moduleInspectionEnabled: true,
});
const submitting = ref(false);
const errorMessage = ref("");
const version = computed(() => session.meta?.version || __APP_VERSION__);

async function submit(): Promise<void> {
  if (!form.groupName.trim() || !form.companyName.trim()) {
    errorMessage.value = "请填写集团名称与公司名称。";
    return;
  }
  submitting.value = true;
  errorMessage.value = "";
  try {
    await completeGroupSetup({
      groupName: form.groupName.trim(),
      companyName: form.companyName.trim(),
      moduleDatacenterEnabled: form.moduleDatacenterEnabled,
      moduleInspectionEnabled: form.moduleInspectionEnabled,
    });
    await refreshSession();
    await loadMeta();
    ElMessage.success("集团/公司初始化完成。");
    await router.replace(firstVisiblePath());
  } catch (error) {
    errorMessage.value = error instanceof Error ? error.message : "初始化失败。";
  } finally {
    submitting.value = false;
  }
}

void loadMeta();
</script>

<template>
  <div class="oa-login">
    <el-card class="oa-login-card oa-setup-card">
      <template #header>
        <div class="oa-flex-between">
          <span class="oa-login-brand">
            <strong>{{ session.appName || "OMbox 运维（O&M）盒子" }}</strong>
          </span>
          <el-tag size="small" effect="plain" type="info">v{{ version }}</el-tag>
        </div>
      </template>
      <p class="oa-hint oa-mb-3">
        首次使用需要完成集团与公司初始化：一个集团下可管理多个公司，每个公司独立管理自己的组织、资产与物资。
      </p>
      <el-form label-position="top" @submit.prevent="submit">
        <el-form-item label="集团名称" required>
          <el-input v-model="form.groupName" placeholder="例如：示例集团" />
        </el-form-item>
        <el-form-item label="初始公司名称" required>
          <el-input v-model="form.companyName" placeholder="例如：示例公司" />
        </el-form-item>
        <el-form-item label="机房管理">
          <el-switch v-model="form.moduleDatacenterEnabled" active-text="开启" inactive-text="关闭" />
        </el-form-item>
        <el-form-item label="巡检管理">
          <el-switch v-model="form.moduleInspectionEnabled" active-text="开启" inactive-text="关闭" />
        </el-form-item>
        <el-alert v-if="errorMessage" :title="errorMessage" type="error" :closable="false" show-icon />
        <el-button type="primary" class="oa-full-width oa-mt-3" :loading="submitting" @click="submit">
          完成初始化
        </el-button>
      </el-form>
    </el-card>
  </div>
</template>
