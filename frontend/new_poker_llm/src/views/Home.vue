<template>
  <div class="home-container">
    <div class="header-section">
      <div class="title-area">
        <h1 class="main-title">
          <span class="poker-icon">♠</span>
          Poker LLM 实时对局
          <span class="poker-icon">♥</span>
        </h1>
        <p class="subtitle">连接 FastAPI 后端，实时观察状态并提交行动</p>
      </div>
      <div class="features">
        <div class="feature-item">
          <el-icon class="feature-icon"><Connection /></el-icon>
          <span>实时 WebSocket</span>
        </div>
        <div class="feature-item">
          <el-icon class="feature-icon"><Monitor /></el-icon>
          <span>桌面状态</span>
        </div>
        <div class="feature-item">
          <el-icon class="feature-icon"><EditPen /></el-icon>
          <span>提交行动</span>
        </div>
        <div class="feature-item">
          <el-icon class="feature-icon"><List /></el-icon>
          <span>事件日志</span>
        </div>
      </div>
    </div>

    <div class="content-grid">
      <div class="card">
        <div class="card-header">
          <el-icon class="card-icon"><Plus /></el-icon>
          <h2>开始对局</h2>
        </div>

        <el-form :model="startForm" label-width="110px">
          <el-form-item label="Hero 名称">
            <el-input v-model="startForm.human_name" />
          </el-form-item>
          <el-form-item label="视图模式">
            <el-select v-model="startForm.view" style="width: 100%">
              <el-option label="debug（展示更多信息）" value="debug" />
              <el-option label="user（更接近玩家视角）" value="user" />
            </el-select>
          </el-form-item>
        </el-form>

        <div class="actions">
          <el-button type="primary" size="large" :loading="starting" @click="onStart">
            <el-icon><VideoPlay /></el-icon>
            开始并进入
          </el-button>
        </div>

        <el-alert v-if="started" type="success" :closable="false" show-icon class="mt">
          <template #title>
            <div class="success-title">
              <span>已开始对局</span>
            </div>
          </template>
          <div class="kv">
            <div class="kv-row">
              <div class="kv-key">hero_token</div>
              <div class="kv-val mono">{{ store.heroToken }}</div>
            </div>
          </div>
        </el-alert>
      </div>

      <div class="card">
        <div class="card-header">
          <el-icon class="card-icon"><Link /></el-icon>
          <h2>后端连接</h2>
        </div>

        <div class="card-subtitle">后端地址</div>
        <div class="row">
          <el-input v-model="store.apiBase" />
          <el-button @click="pingHealth">
            <el-icon><Check /></el-icon>
            检查
          </el-button>
        </div>
      </div>
    </div>

    <footer class="footer">
      <p>参考回放页面的三栏布局与卡片风格，提供实时对局联通</p>
    </footer>
  </div>
</template>

<script setup>
import { reactive, ref } from 'vue'
import { useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { useLiveGameStore } from '@/stores/liveGame'

const router = useRouter()
const store = useLiveGameStore()

const starting = ref(false)
const started = ref(false)

const startForm = reactive({
  human_name: 'You',
  view: 'debug',
})

async function onStart() {
  starting.value = true
  try {
    const data = await store.startGame(startForm)
    started.value = true
    router.push({ name: 'Play', query: { token: data.hero_token } })
  } catch (e) {
    ElMessage.error(e.message || '开始失败')
  } finally {
    starting.value = false
  }
}

async function pingHealth() {
  try {
    const res = await fetch(`${store.apiBase}/health`)
    if (!res.ok) throw new Error()
    ElMessage.success('后端可用')
  } catch (e) {
    ElMessage.error('后端不可用或地址错误')
  }
}
</script>

<style scoped>
.home-container {
  padding: 2rem 1.5rem;
  max-width: 1200px;
  margin: 0 auto;
}

.header-section {
  text-align: center;
  margin-bottom: 2rem;
}

.title-area {
  margin-bottom: 1.5rem;
}

.main-title {
  font-size: 2.3rem;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  -webkit-background-clip: text;
  -webkit-text-fill-color: transparent;
  display: inline-flex;
  align-items: center;
  gap: 0.75rem;
}

.poker-icon {
  -webkit-text-fill-color: initial;
  color: #667eea;
  font-size: 2.2rem;
}

.subtitle {
  margin-top: 0.75rem;
  color: var(--text-secondary);
}

.features {
  display: flex;
  justify-content: center;
  gap: 2rem;
  flex-wrap: wrap;
}

.feature-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
  padding: 0.75rem 1rem;
  background: white;
  border-radius: 1rem;
  box-shadow: var(--shadow-sm);
  color: var(--text-secondary);
}

.feature-icon {
  color: var(--primary-color);
  font-size: 1.25rem;
}

.content-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 1rem;
}

.card {
  background: white;
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: var(--shadow-md);
}

.card-header {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  margin-bottom: 1rem;
}

.card-icon {
  font-size: 1.25rem;
  color: var(--primary-color);
}

.actions {
  margin-top: 1rem;
  display: flex;
  justify-content: flex-start;
}

.row {
  display: flex;
  align-items: center;
  gap: 0.75rem;
  width: 100%;
}

.sep {
  color: var(--text-tertiary);
}

.mt {
  margin-top: 1rem;
}

.card-subtitle {
  font-weight: 600;
  margin-bottom: 0.5rem;
  color: var(--text-primary);
}

.success-title {
  display: flex;
  align-items: center;
  gap: 0.75rem;
}

.kv {
  margin-top: 0.75rem;
}

.kv-row {
  display: grid;
  grid-template-columns: 90px 1fr;
  gap: 0.75rem;
  align-items: start;
}

.kv-key {
  color: var(--text-secondary);
}

.kv-val {
  word-break: break-all;
}

.mono {
  font-family: var(--font-family-mono);
}

.footer {
  margin-top: 2rem;
  text-align: center;
  color: var(--text-tertiary);
}

@media (max-width: 900px) {
  .content-grid {
    grid-template-columns: 1fr;
  }
}
</style>
