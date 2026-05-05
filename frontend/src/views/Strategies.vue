<template>
  <div class="strategies-page">
    <van-nav-bar title="Sequoia-X 量化选股" left-arrow @click-left="$router.back()">
      <template #right>
        <van-button size="small" plain type="primary" :loading="syncing" @click="doSync">
          {{ syncing ? '同步中...' : '📥 每日同步' }}
        </van-button>
        <van-icon name="replay" @click="loadAll" style="padding:4px;margin-left:4px" />
      </template>
    </van-nav-bar>

    <!-- 状态条 -->
    <div class="status-bar">
      <div class="status-left">
        <van-tag :type="status.db_exists ? 'success' : 'warning'" size="medium">
          {{ status.db_exists ? '✅ 数据引擎就绪' : '⚠ 未初始化' }}
        </van-tag>
        <span class="status-meta" v-if="status.stock_count > 0">
          {{ status.stock_count }} 只股票
          <template v-if="status.latest_date"> · 最新 {{ status.latest_date }}</template>
        </span>
      </div>
      <div class="status-right">
        <span class="picks-badge" v-if="status.picks_today > 0">
          {{ status.picks_today }} 只选股
        </span>
      </div>
    </div>

    <!-- 策略网格 -->
    <div class="strategy-grid">
      <van-grid :column-num="2" :border="false" :gutter="8">
        <van-grid-item
          v-for="s in strategyList"
          :key="s.key"
          class="sc-card"
          :class="{ active: selectedKey === s.key, 'has-picks': strategyPicks[s.key]?.length }"
          @click="selectStrategy(s.key)"
        >
          <div class="sc-badge" v-if="strategyPicks[s.key]?.length">
            {{ strategyPicks[s.key].length }}
          </div>
          <div class="sc-name">{{ s.name }}</div>
          <div class="sc-desc">{{ s.desc }}</div>
        </van-grid-item>
      </van-grid>
    </div>

    <!-- 选中策略的选股列表 -->
    <div class="picks-section" v-if="selectedKey && strategyPicks[selectedKey]?.length">
      <van-cell-group :title="`${strategyLabel(selectedKey)} — 选股结果`">
        <van-cell
          v-for="sym in strategyPicks[selectedKey]"
          :key="sym"
          is-link
          @click="$router.push('/kline/' + sym)"
        >
          <template #title>
            <van-tag plain>{{ sym }}</van-tag>
          </template>
          <template #value>
            <van-icon name="arrow" />
          </template>
        </van-cell>
      </van-cell-group>
    </div>
    <div class="empty-hint" v-else-if="selectedKey">
      <van-empty description="该策略暂无选股结果" />
    </div>

    <!-- 历史记录 -->
    <div class="history-section" v-if="!selectedKey && history.length">
      <van-cell-group title="📋 最近选股记录">
        <van-cell
          v-for="h in history.slice(0, 5)"
          :key="h.id || h.date + h.strategy"
          :title="h.strategy"
          :label="h.date + ' · ' + h.symbol"
          is-link
          @click="$router.push('/kline/' + h.symbol)"
        >
          <template #icon>
            <van-tag plain style="margin-right:8px">{{ h.symbol }}</van-tag>
          </template>
        </van-cell>
      </van-cell-group>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, computed } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast, showDialog } from 'vant'

const router = useRouter()
const status = ref({})
const strategyList = ref([])
const strategyPicks = ref({})
const history = ref([])
const selectedKey = ref(null)
const syncing = ref(false)

const STRATEGY_LABELS = {
  ma_volume: '均线放量',
  turtle_trade: '海龟交易',
  high_tight_flag: '高窄旗形',
  limit_up_shakeout: '涨停洗盘',
  uptrend_limit_down: '跌停反包',
  rps_breakout: 'RPS突破',
}

function strategyLabel(key) { return STRATEGY_LABELS[key] || key }

async function loadStatus() {
  try {
    const r = await fetch('/api/v1/strategy/status')
    status.value = await r.json()
  } catch { status.value = {} }
}

async function loadStrategies() {
  try {
    const r = await fetch('/api/v1/strategy/list')
    const data = await r.json()
    strategyList.value = data.strategies || []
  } catch { strategyList.value = [] }
}

async function loadPicks() {
  try {
    const r = await fetch('/api/v1/strategy/picks?today_only=true')
    const data = await r.json()
    strategyPicks.value = data.picks || {}
  } catch { strategyPicks.value = {} }
}

async function loadHistory() {
  try {
    const r = await fetch('/api/v1/strategy/history?days=7')
    const data = await r.json()
    history.value = data.records || []
  } catch { history.value = [] }
}

async function loadAll() {
  await Promise.all([loadStatus(), loadStrategies(), loadPicks(), loadHistory()])
}

function selectStrategy(key) {
  selectedKey.value = selectedKey.value === key ? null : key
}

async function doSync() {
  syncing.value = true
  const toast = showLoadingToast({ message: '🔄 同步数据 + 执行策略...', duration: 0 })
  try {
    const r = await fetch('/api/v1/strategy/sync', { method: 'POST' })
    const data = await r.json()
    closeToast()
    if (data.status === 'ok') {
      const msg = `✅ 写入 ${data.sync_count} 条数据\n已选 ${data.total_picks} 只股票`
      showDialog({ title: '同步完成', message: msg })
    } else {
      showToast({ message: `同步失败: ${data.error}`, type: 'fail' })
    }
  } catch {
    closeToast()
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    syncing.value = false
    loadAll()
  }
}

onMounted(() => loadAll())
</script>

<style scoped>
.status-bar {
  padding: 8px 12px;
  display: flex;
  align-items: center;
  justify-content: space-between;
  background: #fff;
  border-bottom: 1px solid #eee;
  font-size: 12px;
}
.status-left { display: flex; align-items: center; gap: 8px; flex-wrap: wrap; }
.status-meta { color: #999; }
.picks-badge {
  background: #e74c3c; color: #fff; padding: 2px 10px;
  border-radius: 10px; font-size: 11px; font-weight: 600;
}

.strategy-grid { padding: 8px; }
.sc-card {
  background: #fff; border-radius: 8px; padding: 12px;
  position: relative; cursor: pointer;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  transition: all 0.2s;
  min-height: 80px;
}
.sc-card:active { transform: scale(0.96); }
.sc-card.active { border: 2px solid #1989fa; background: #f0f8ff; }
.sc-card.has-picks { border: 1px solid #4fc3f7; }

.sc-badge {
  position: absolute; top: 4px; right: 8px;
  background: #e74c3c; color: #fff; font-size: 11px;
  font-weight: 700; padding: 1px 8px; border-radius: 10px;
  min-width: 20px; text-align: center;
}
.sc-name { font-size: 15px; font-weight: 600; margin-bottom: 4px; color: #333; }
.sc-desc { font-size: 11px; color: #999; line-height: 1.4; }

.picks-section { margin-top: 8px; }
.empty-hint { margin-top: 16px; }
.history-section { margin-top: 8px; margin-bottom: 16px; }
</style>
