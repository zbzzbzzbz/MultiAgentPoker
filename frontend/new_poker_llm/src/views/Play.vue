<template>
  <div class="play-container">
    <div class="control-panel">
      <div class="panel-header">
        <h2>控制面板</h2>
        <el-button :icon="ArrowLeft" circle size="small" @click="backToHome" title="返回首页" />
      </div>

      <div class="kv">
        <div class="kv-row">
          <div class="kv-key">token</div>
          <div class="kv-val mono">{{ store.heroToken || '（旁观者）' }}</div>
        </div>
        <div class="kv-row">
          <div class="kv-key">后端</div>
          <div class="kv-val mono">{{ store.apiBase }}</div>
        </div>
      </div>

      <div class="connection-section">
        <div class="progress-info">
          <span>连接状态</span>
          <el-tag size="small" :type="store.connected ? 'success' : store.connecting ? 'warning' : 'info'">
            {{ store.connected ? '已连接' : store.connecting ? '连接中' : '未连接' }}
          </el-tag>
        </div>
        <div class="row">
          <el-button :disabled="store.connecting" type="primary" plain @click="connect">
            <el-icon><Connection /></el-icon>
            连接
          </el-button>
          <el-button :disabled="!store.connected" type="danger" plain @click="store.disconnectWs()">
            <el-icon><Close /></el-icon>
            断开
          </el-button>
          <el-button :disabled="!store.connected" @click="store.requestSnapshot()">
            <el-icon><Refresh /></el-icon>
            刷新
          </el-button>
        </div>
        <el-alert v-if="store.lastError" type="error" :closable="false" show-icon class="mt">
          {{ store.lastError }}
        </el-alert>
      </div>

      <div class="action-section">
        <div class="nav-title">你的行动</div>

        <el-alert v-if="!store.actionRequest" type="info" :closable="false" show-icon>
          等待后端发起 ACTION_REQUEST
        </el-alert>

        <template v-else>
          <div class="req-meta">
            <div class="req-row">
              <span class="label">阶段</span>
              <el-tag size="small" type="success">{{ formatStage(store.actionRequest.stage) }}</el-tag>
            </div>
            <div class="req-row">
              <span class="label">当前下注</span>
              <span class="value">{{ store.actionRequest.current_bet }}</span>
            </div>
            <div class="req-row">
              <span class="label">需跟注</span>
              <span class="value">{{ store.actionRequest.call_amount }}</span>
            </div>
            <div class="req-row">
              <span class="label">最小加注</span>
              <span class="value">{{ store.actionRequest.min_raise }}</span>
            </div>
          </div>

          <div class="raise-row">
            <el-input-number v-model="raiseAmount" :min="minRaise" :max="maxRaise" :disabled="!canRaise" />
            <el-button :disabled="!canRaise" type="warning" @click="submitRaise">
              加注
            </el-button>
          </div>

          <div class="action-buttons">
            <el-button :disabled="!canFold" type="danger" plain @click="submitSimple('fold')">弃牌</el-button>
            <el-button :disabled="!canCheck" type="info" plain @click="submitSimple('check')">过牌</el-button>
            <el-button :disabled="!canCall" type="success" plain @click="submitSimple('call')">跟注</el-button>
            <el-button :disabled="!canAllIn" type="danger" @click="submitSimple('all-in')">全押</el-button>
          </div>
        </template>
      </div>
    </div>

    <div class="game-area">
      <div class="game-info-bar">
        <div class="info-group">
          <div class="info-item">
            <span class="label">手牌:</span>
            <el-tag size="small" type="primary">#{{ table.handNumber }}</el-tag>
          </div>
          <div class="info-item">
            <span class="label">阶段:</span>
            <el-tag size="small" type="success">{{ formatStage(table.stage) }}</el-tag>
          </div>
        </div>
        <div class="info-group">
          <div class="info-item">
            <span class="label">底池:</span>
            <span class="pot-value">{{ table.pot }}</span>
          </div>
          <div class="info-item">
            <span class="label">当前下注:</span>
            <span class="pot-value">{{ table.currentBet }}</span>
          </div>
        </div>
      </div>

      <div class="poker-table">
        <div class="community-area">
          <div class="area-title">公共牌</div>
          <div class="cards-row">
            <transition-group name="card">
              <div
                v-for="(card, index) in table.communityCards"
                :key="card"
                class="table-card"
                :class="{ red: isRedCard(card) }"
                :style="{ animationDelay: `${index * 0.15}s` }"
              >
                {{ card }}
              </div>
            </transition-group>
            <div v-if="table.communityCards.length === 0" class="no-cards">暂无</div>
          </div>
        </div>

        <div class="players-area">
          <div
            v-for="player in table.players"
            :key="player.name"
            class="player-seat"
            :class="getSeatClasses(player)"
          >
            <div v-if="isHero(player.name)" class="hero-indicator">
              <el-icon><User /></el-icon>
            </div>

            <div class="player-header">
              <div class="player-name">{{ player.name }}</div>
              <div class="player-chips">💰 {{ player.chips }}</div>
            </div>

            <div class="player-cards" v-if="Array.isArray(player.hand) && player.hand.length">
              <div
                v-for="(card, cardIndex) in player.hand"
                :key="`${player.name}-${cardIndex}`"
                class="player-card"
                :class="{ red: isRedCard(card) }"
              >
                {{ card }}
              </div>
            </div>

            <div class="player-status">
              <el-tag v-if="player.folded" size="small" type="danger">已弃牌</el-tag>
              <el-tag v-else-if="player.all_in" size="small" type="warning">全押</el-tag>
              <div v-else-if="player.bet_in_round > 0" class="bet-amount">已下注: {{ player.bet_in_round }}</div>
            </div>
          </div>
        </div>

        <div class="action-display" v-if="lastAction">
          <div class="action-header">
            <div class="action-player">{{ lastAction.payload.player_name }}</div>
            <el-tag :type="getActionTagType(lastAction.payload.action)">
              {{ formatAction(lastAction.payload.action) }}
              <span v-if="lastAction.payload.amount > 0">: {{ lastAction.payload.amount }}</span>
            </el-tag>
          </div>
        </div>
      </div>
    </div>

    <div class="details-panel">
      <div class="panel-tabs">
        <el-radio-group v-model="activeTab" size="small">
          <el-radio-button label="events">
            <el-icon><List /></el-icon>
            事件
          </el-radio-button>
          <el-radio-button label="raw">
            <el-icon><Document /></el-icon>
            详情
          </el-radio-button>
        </el-radio-group>
      </div>

      <div class="panel-content">
        <div v-show="activeTab === 'events'" class="tab-content">
          <div class="events">
            <div v-if="store.eventLog.length === 0" class="empty">暂无事件</div>
            <div v-for="evt in store.eventLog" :key="`${evt.seq}-${evt.type}-${evt.ts}`" class="event-item">
              <div class="event-head">
                <el-tag size="small" :type="tagType(evt.type)">{{ evt.type }}</el-tag>
                <span class="event-meta">#{{ evt.seq }}</span>
              </div>
              <div class="event-body mono">{{ formatPayload(evt.payload) }}</div>
            </div>
          </div>
        </div>

        <div v-show="activeTab === 'raw'" class="tab-content">
          <div class="raw-section">
            <div class="raw-title">STATE_SNAPSHOT.payload</div>
            <pre class="mono pre">{{ prettyJson(store.snapshot) }}</pre>
          </div>
          <div class="raw-section">
            <div class="raw-title">ACTION_REQUEST.payload</div>
            <pre class="mono pre">{{ prettyJson(store.actionRequest) }}</pre>
          </div>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { ElMessage } from 'element-plus'
import { ArrowLeft } from '@element-plus/icons-vue'
import { useLiveGameStore } from '@/stores/liveGame'

const router = useRouter()
const route = useRoute()
const store = useLiveGameStore()

const activeTab = ref('events')
const raiseAmount = ref(0)

const table = computed(() => store.tableInfo)

const heroName = computed(() => store.actionRequest?.hero || '')
const minRaise = computed(() => store.actionRequest?.min_raise || 0)
const maxRaise = computed(() => store.actionRequest?.chips || 0)

const legal = computed(() => store.actionRequest?.legal_actions || {})
const canFold = computed(() => Boolean(store.actionRequest))
const canCheck = computed(() => Boolean(legal.value.check))
const canCall = computed(() => Boolean(legal.value.call))
const canRaise = computed(() => Boolean(legal.value.raise) && maxRaise.value > 0)
const canAllIn = computed(() => Boolean(legal.value.all_in) && maxRaise.value > 0)

const lastAction = computed(() => store.eventLog.find(e => e.type === 'ACTION_TAKEN') || null)

function backToHome() {
  store.disconnectWs()
  router.push({ name: 'Home' })
}

function connect() {
  store.connectGameWs({ token: store.heroToken }).catch(e => {
    ElMessage.error(e.message || '连接失败')
  })
}

function isHero(name) {
  return heroName.value && name === heroName.value
}

function submitSimple(action) {
  store.submitAction({ action }).catch(e => {
    ElMessage.error(e.message || '提交失败')
  })
}

function submitRaise() {
  store.submitAction({ action: 'raise', amount: raiseAmount.value }).catch(e => {
    ElMessage.error(e.message || '提交失败')
  })
}

function formatStage(stage) {
  const stageMap = {
    preflop: '前翻牌',
    flop: '翻牌',
    turn: '转牌',
    river: '河牌',
    showdown: '摊牌',
  }
  return stageMap[stage] || stage || '—'
}

function formatAction(action) {
  const actionMap = {
    fold: '弃牌',
    check: '过牌',
    call: '跟注',
    raise: '加注',
    'all-in': '全押',
  }
  return actionMap[action] || action || '—'
}

function getActionTagType(action) {
  const typeMap = {
    fold: 'danger',
    check: 'info',
    call: 'success',
    raise: 'warning',
    'all-in': 'danger',
  }
  return typeMap[action] || 'info'
}

function isRedCard(card) {
  if (!card) return false
  return card.includes('♥') || card.includes('♦') || card.includes('红桃') || card.includes('方块')
}

function getSeatClasses(player) {
  return {
    hero: isHero(player.name),
    folded: player.folded,
    'all-in': player.all_in,
  }
}

function tagType(type) {
  if (type === 'ERROR') return 'danger'
  if (type === 'ACTION_REQUEST') return 'warning'
  if (type === 'ACTION_TAKEN') return 'success'
  if (type === 'STATE_SNAPSHOT') return 'info'
  if (type === 'GAME_END') return 'primary'
  return 'info'
}

function formatPayload(payload) {
  if (!payload) return ''
  const keys = Object.keys(payload)
  if (keys.length === 0) return '{}'
  const compact = {}
  for (const k of keys) {
    if (k === 'players') continue
    if (k === 'community_cards') compact[k] = payload[k]
    else compact[k] = payload[k]
  }
  return JSON.stringify(compact)
}

function prettyJson(obj) {
  try {
    return JSON.stringify(obj || {}, null, 2)
  } catch (e) {
    return String(obj)
  }
}

watch(
  () => store.actionRequest,
  (req) => {
    if (!req) return
    raiseAmount.value = Math.max(req.min_raise || 0, 0)
  },
  { immediate: true }
)

onMounted(() => {
  const token = route.query.token !== undefined ? String(route.query.token) : ''
  store.heroToken = token
  connect()
})
</script>

<style scoped>
.play-container {
  display: grid;
  grid-template-columns: 320px 1fr 420px;
  gap: 1rem;
  padding: 1rem;
  height: 100vh;
  background: #f0f2f5;
}

.control-panel,
.details-panel {
  background: white;
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow-y: auto;
}

.panel-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.panel-header h2 {
  margin: 0;
  font-size: 1.2rem;
  color: #333;
}

.kv {
  border-top: 1px solid #f0f0f0;
  padding-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.5rem;
}

.kv-row {
  display: grid;
  grid-template-columns: 70px 1fr;
  gap: 0.75rem;
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

.connection-section {
  border-top: 1px solid #f0f0f0;
  padding-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.progress-info {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 0.9rem;
  color: #666;
}

.row {
  display: flex;
  gap: 0.5rem;
  flex-wrap: wrap;
}

.mt {
  margin-top: 0.75rem;
}

.action-section {
  border-top: 1px solid #f0f0f0;
  padding-top: 1rem;
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.nav-title {
  font-weight: 600;
  color: #333;
}

.req-meta {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem 1rem;
  background: #f8f9fa;
  border-radius: 0.75rem;
  padding: 0.75rem;
}

.req-row {
  display: flex;
  justify-content: space-between;
  gap: 0.75rem;
  align-items: center;
}

.label {
  color: var(--text-secondary);
}

.value {
  font-weight: 600;
  color: var(--text-primary);
}

.raise-row {
  display: flex;
  gap: 0.5rem;
  align-items: center;
}

.action-buttons {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 0.5rem;
}

.game-area {
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow: hidden;
}

.game-info-bar {
  background: white;
  border-radius: 1rem;
  padding: 1rem 1.5rem;
  display: flex;
  justify-content: space-between;
  align-items: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
}

.info-group {
  display: flex;
  gap: 1.5rem;
}

.info-item {
  display: flex;
  align-items: center;
  gap: 0.5rem;
}

.pot-value {
  font-weight: 600;
  color: #667eea;
  font-size: 1.1rem;
}

.poker-table {
  flex: 1;
  background: radial-gradient(circle at center, #2d5a27 0%, #1a3d18 100%);
  border-radius: 1.5rem;
  padding: 1.5rem;
  box-shadow: 0 8px 24px rgba(0, 0, 0, 0.2);
  display: flex;
  flex-direction: column;
  gap: 1.5rem;
  position: relative;
  overflow: hidden;
}

.community-area {
  background: rgba(255, 255, 255, 0.1);
  border-radius: 1rem;
  padding: 1rem;
  text-align: center;
}

.area-title {
  color: rgba(255, 255, 255, 0.9);
  font-weight: 600;
  margin-bottom: 0.75rem;
}

.cards-row {
  display: flex;
  justify-content: center;
  gap: 0.75rem;
  min-height: 60px;
  align-items: center;
}

.table-card {
  width: 55px;
  height: 75px;
  background: white;
  border-radius: 0.5rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 1.25rem;
  font-weight: 600;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.2);
  animation: dealCard 0.4s ease-out both;
}

.table-card.red {
  color: #e03131;
}

.no-cards {
  color: rgba(255, 255, 255, 0.6);
}

.players-area {
  display: grid;
  grid-template-columns: repeat(auto-fit, minmax(160px, 1fr));
  gap: 1rem;
  flex: 1;
  align-content: start;
}

.player-seat {
  background: rgba(255, 255, 255, 0.12);
  border: 1px solid rgba(255, 255, 255, 0.18);
  border-radius: 1rem;
  padding: 1rem;
  position: relative;
  backdrop-filter: blur(10px);
}

.player-seat.hero {
  border-color: rgba(102, 126, 234, 0.9);
  box-shadow: 0 0 0 2px rgba(102, 126, 234, 0.25);
}

.hero-indicator {
  position: absolute;
  top: -10px;
  right: -10px;
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: rgba(102, 126, 234, 0.95);
  color: white;
  display: flex;
  align-items: center;
  justify-content: center;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.25);
}

.player-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.75rem;
}

.player-name {
  color: white;
  font-weight: 600;
}

.player-chips {
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.9rem;
}

.player-cards {
  display: flex;
  gap: 0.5rem;
  margin-bottom: 0.75rem;
}

.player-card {
  width: 42px;
  height: 58px;
  background: white;
  border-radius: 0.4rem;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 1rem;
}

.player-card.red {
  color: #e03131;
}

.player-status {
  display: flex;
  justify-content: center;
  min-height: 24px;
}

.bet-amount {
  color: rgba(255, 255, 255, 0.9);
  font-size: 0.85rem;
}

.action-display {
  position: absolute;
  left: 50%;
  bottom: 18px;
  transform: translateX(-50%);
  background: rgba(255, 255, 255, 0.95);
  border-radius: 1rem;
  padding: 0.75rem 1rem;
  box-shadow: 0 6px 18px rgba(0, 0, 0, 0.25);
  min-width: 320px;
}

.action-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.action-player {
  font-weight: 700;
  color: #333;
}

.details-panel {
  background: white;
  border-radius: 1rem;
  padding: 1.5rem;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  gap: 1rem;
  overflow: hidden;
}

.panel-content {
  flex: 1;
  overflow-y: auto;
}

.tab-content {
  height: 100%;
}

.events {
  display: flex;
  flex-direction: column;
  gap: 0.75rem;
}

.event-item {
  border: 1px solid #f0f0f0;
  border-radius: 0.75rem;
  padding: 0.75rem;
  background: #fff;
}

.event-head {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 0.5rem;
}

.event-meta {
  color: var(--text-tertiary);
  font-size: 0.85rem;
}

.event-body {
  color: var(--text-secondary);
  font-size: 0.85rem;
  word-break: break-word;
}

.empty {
  color: var(--text-tertiary);
  text-align: center;
  padding: 2rem 0;
}

.raw-section {
  margin-bottom: 1rem;
}

.raw-title {
  font-weight: 700;
  margin-bottom: 0.5rem;
}

.pre {
  background: #0b1020;
  color: #d0d7ff;
  border-radius: 0.75rem;
  padding: 0.75rem;
  font-size: 0.85rem;
  overflow: auto;
}

@keyframes dealCard {
  from {
    opacity: 0;
    transform: translateY(-10px) scale(0.95);
  }
  to {
    opacity: 1;
    transform: translateY(0) scale(1);
  }
}

@media (max-width: 1100px) {
  .play-container {
    grid-template-columns: 1fr;
    height: auto;
  }
}
</style>
