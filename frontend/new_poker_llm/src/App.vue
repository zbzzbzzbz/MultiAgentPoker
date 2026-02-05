<script setup>
import { RouterView } from 'vue-router'
import { ElConfigProvider } from 'element-plus'
</script>

<template>
  <el-config-provider>
    <div class="app-container">
      <RouterView />
    </div>
  </el-config-provider>
</template>

<style>
.app-container {
  min-height: 100vh;
  overflow-x: hidden;
}

.el-message {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}

.el-notification {
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.15) !important;
}

.el-dialog {
  border-radius: 1rem !important;
  overflow: hidden;
}

.el-dialog__header {
  padding: 1.5rem !important;
  border-bottom: 1px solid #f0f0f0;
}

.el-dialog__body {
  padding: 1.5rem !important;
}

.el-tag {
  border-radius: 0.375rem !important;
  font-weight: 500;
}
</style>

