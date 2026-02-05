import { defineStore } from 'pinia'
import { computed, ref } from 'vue'

function getDefaultApiBase() {
  return (import.meta.env && import.meta.env.VITE_API_BASE) || 'http://localhost:8000'
}

function httpUrlToWsUrl(httpUrl) {
  if (httpUrl.startsWith('https://')) return `wss://${httpUrl.slice('https://'.length)}`
  if (httpUrl.startsWith('http://')) return `ws://${httpUrl.slice('http://'.length)}`
  return httpUrl
}

export const useLiveGameStore = defineStore('liveGame', () => {
  const apiBase = ref(getDefaultApiBase())

  const heroToken = ref('')

  const connected = ref(false)
  const connecting = ref(false)
  const heroAuthed = computed(() => Boolean(heroToken.value))

  const ws = ref(null)
  const lastError = ref('')

  const snapshot = ref(null)
  const status = ref('created')
  const actionRequest = ref(null)
  const eventLog = ref([])

  function resetRuntimeState() {
    snapshot.value = null
    actionRequest.value = null
    eventLog.value = []
    lastError.value = ''
  }

  async function startGame(payload = {}) {
    const res = await fetch(`${apiBase.value}/start`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(payload || {}),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || `开始失败(${res.status})`)
    }
    const data = await res.json()
    heroToken.value = data.hero_token || ''
    status.value = data.status || 'created'
    return data
  }

  function pushEvent(evt) {
    eventLog.value.unshift(evt)
    if (eventLog.value.length > 200) eventLog.value.length = 200
  }

  function applyServerMessage(msg) {
    if (!msg || typeof msg !== 'object') return

    const type = msg.type
    const payload = msg.payload || {}
    if (type === 'STATE_SNAPSHOT') {
      snapshot.value = payload
    } else if (type === 'ACTION_REQUEST') {
      actionRequest.value = payload
    } else if (type === 'ERROR') {
      lastError.value = payload.error || '未知错误'
    } else if (type === 'STARTED') {
      status.value = 'running'
    } else if (type === 'GAME_END') {
      status.value = 'finished'
    }

    pushEvent({
      ts: msg.ts,
      seq: msg.seq,
      type,
      payload,
    })
  }

  async function connectGameWs({ token } = {}) {
    if (connecting.value) return

    if (token !== undefined) heroToken.value = token

    disconnectWs()
    resetRuntimeState()

    connecting.value = true
    lastError.value = ''

    const baseWs = httpUrlToWsUrl(apiBase.value)
    const url = new URL(`${baseWs}/ws`)
    if (heroToken.value) url.searchParams.set('token', heroToken.value)

    const socket = new WebSocket(url.toString())
    ws.value = socket

    socket.onopen = () => {
      connected.value = true
      connecting.value = false
    }

    socket.onmessage = (evt) => {
      try {
        const data = JSON.parse(evt.data)
        applyServerMessage(data)
      } catch (e) {
        lastError.value = '解析消息失败'
      }
    }

    socket.onerror = () => {
      lastError.value = 'WebSocket 错误'
    }

    socket.onclose = () => {
      connected.value = false
      connecting.value = false
    }
  }

  function disconnectWs() {
    if (ws.value) {
      try {
        ws.value.close()
      } catch (e) {
      }
    }
    ws.value = null
    connected.value = false
    connecting.value = false
  }

  function requestSnapshot() {
    if (!ws.value || !connected.value) return
    ws.value.send(JSON.stringify({ type: 'REQUEST_SNAPSHOT', payload: {} }))
  }

  async function submitAction(actionPayload) {
    if (ws.value && connected.value && heroToken.value) {
      ws.value.send(JSON.stringify({ type: 'USER_ACTION', payload: actionPayload }))
      return
    }

    if (!heroToken.value) throw new Error('token 不能为空')

    const res = await fetch(`${apiBase.value}/actions?token=${encodeURIComponent(heroToken.value)}`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(actionPayload),
    })
    if (!res.ok) {
      const data = await res.json().catch(() => ({}))
      throw new Error(data.detail || `提交动作失败(${res.status})`)
    }
  }

  const tableInfo = computed(() => {
    const s = snapshot.value || {}
    return {
      handNumber: s.hand_number || 1,
      stage: s.stage || '',
      pot: s.pot || 0,
      currentBet: s.current_bet || 0,
      communityCards: s.community_cards || [],
      players: s.players || [],
      dealerPosition: s.dealer_position,
    }
  })

  return {
    apiBase,
    heroToken,
    connected,
    connecting,
    heroAuthed,
    lastError,
    snapshot,
    tableInfo,
    status,
    actionRequest,
    eventLog,
    startGame,
    connectGameWs,
    disconnectWs,
    requestSnapshot,
    submitAction,
  }
})
