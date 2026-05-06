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

    <!-- 模式切换 Tab -->
    <van-tabs v-model:active="mode" sticky>
      <van-tab title="📊 策略选股">
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

        <!-- 多策略按钮区 + 初筛 -->
        <div class="multi-strat-actions">
          <van-button
            icon="filter-o"
            size="small"
            plain
            type="primary"
            :loading="loadingMulti2"
            @click="doMultiPicks(2, 2)"
            style="margin: 4px"
          >🎯 满足2个策略条件</van-button>
          <van-button
            icon="filter-o"
            size="small"
            plain
            type="danger"
            :loading="loadingMulti3"
            @click="doMultiPicks(3)"
            style="margin: 4px"
          >🔥 满足3+策略条件</van-button>
        </div>
        <div class="multi-strat-actions">
          <van-button
            icon="search"
            size="small"
            plain
            type="warning"
            :loading="loadingChushai"
            @click="doChushai"
            style="margin: 4px"
          >🔍 初筛</van-button>
        </div>

        <!-- 初筛结果展示 -->
        <div class="picks-section" v-if="chushaiResults.length">
          <van-cell-group :title="`🔍 初筛 — 20日涨幅排名第101-500 (共${chushaiTotal}只)`">
            <template #title>
              <span>🔍 初筛 — 20日涨幅排名 (第101-500位)</span>
              <span style="font-size:12px;color:#999;margin-left:8px">共 {{ chushaiTotal }} 只</span>
            </template>
            <van-cell
              v-for="item in chushaiResults"
              :key="item.symbol"
              is-link
              @click="$router.push('/kline/' + item.symbol)"
            >
              <template #title>
                <van-tag plain>{{ item.symbol }}</van-tag>
                <van-tag
                  :type="item.return_20d >= 0 ? 'danger' : 'success'"
                  style="margin-left:6px"
                >#{{ item.rank }}</van-tag>
              </template>
              <template #label>
                <span style="color:#999;font-size:11px">
                  最新 {{ item.latest_close?.toFixed(2) }} ({{ item.latest_date }})
                  20日前 {{ item.close_20d?.toFixed(2) }} ({{ item.date_20d }})
                </span>
              </template>
              <template #value>
                <span :style="{color: item.return_20d >= 0 ? '#ee0a24' : '#07c160', fontWeight: 700}">
                  {{ item.return_20d >= 0 ? '+' : '' }}{{ item.return_20d?.toFixed(2) }}%
                </span>
              </template>
            </van-cell>
          </van-cell-group>
        </div>

        <!-- 多策略结果展示 -->
        <div class="picks-section" v-if="multiResults.length && multiMode">
          <van-cell-group :title="multiTitle">
            <van-cell
              v-for="item in multiResults"
              :key="item.symbol"
              is-link
              @click="$router.push('/kline/' + item.symbol)"
            >
              <template #title>
                <van-tag plain>{{ item.symbol }}</van-tag>
                <van-tag
                  :type="item.count >= 3 ? 'danger' : 'primary'"
                  style="margin-left:6px"
                >{{ item.count }}策略</van-tag>
              </template>
              <template #label>
                <span style="font-size:11px;color:#999">{{ item.strategy_names.join(' · ') }}</span>
              </template>
              <template #value>
                <van-icon name="arrow" />
              </template>
            </van-cell>
          </van-cell-group>
        </div>

        <!-- 选中策略的选股列表 -->
        <div class="picks-section" v-if="!multiMode && selectedKey && strategyPicks[selectedKey]?.length">
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
        <div class="empty-hint" v-else-if="!multiMode && selectedKey">
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
      </van-tab>

      <van-tab title="🔍 条件筛选">
        <van-form @submit="doScreen">
          <van-cell-group title="筛选条件">
            <van-field
              v-model="filters.industry"
              name="industry"
              label="行业"
              placeholder="如：银行、医药"
              clearable
            />
            <van-field
              v-model="filters.market_cap_min"
              name="market_cap_min"
              label="最小总市值(亿)"
              type="number"
              placeholder="如：100"
              clearable
            />
            <van-field
              v-model="filters.market_cap_max"
              name="market_cap_max"
              label="最大总市值(亿)"
              type="number"
              placeholder="如：10000"
              clearable
            />
          </van-cell-group>

          <div style="padding: 16px">
            <van-button round block type="primary" native-type="submit" :loading="screening">
              {{ screening ? '筛选中...' : '开始筛选' }}
            </van-button>
          </div>
        </van-form>

        <!-- 筛选结果 -->
        <div v-if="screenResults.length" class="result-area">
          <van-cell-group :title="`筛选结果 (${screenTotal}只)`">
            <van-cell
              v-for="s in screenResults"
              :key="s.symbol"
              is-link
              @click="$router.push('/kline/' + s.symbol)"
            >
              <template #title>
                <span>{{ s.name }}</span>
                <van-tag plain style="margin-left: 8px">{{ s.symbol }}</van-tag>
              </template>
              <template #label>
                <span v-if="s.price" :style="{color: s.pct_change >= 0 ? '#ee0a24' : '#07c160'}">
                  {{ s.price?.toFixed(2) }}
                  {{ s.pct_change >= 0 ? '+' : '' }}{{ s.pct_change?.toFixed(2) }}%
                </span>
                <span v-if="s.industry" style="margin-left: 8px; color: #999">{{ s.industry }}</span>
              </template>
              <template #value>
                <span style="font-size:12px;color:#999">{{ formatMkt(s.market_cap) }}</span>
              </template>
            </van-cell>
          </van-cell-group>
        </div>
        <van-empty v-if="screenSearched && !screening && !screenResults.length" description="无匹配结果，试试放宽条件" />
      </van-tab>
    </van-tabs>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast, showLoadingToast, closeToast, showDialog } from 'vant'
import { screenStocks } from '../utils/api.js'

const router = useRouter()

// ===== 策略模式 =====
const mode = ref(0)
const status = ref({})
const strategyList = ref([])
const strategyPicks = ref({})
const history = ref([])
const selectedKey = ref(null)
const syncing = ref(false)

// ===== 初筛（20日涨幅排名101-500）=====
const chushaiResults = ref([])
const chushaiTotal = ref(0)
const loadingChushai = ref(false)

async function doChushai() {
  loadingChushai.value = true
  multiMode.value = false
  selectedKey.value = null
  chushaiResults.value = []
  try {
    // 先刷新数据
    await fetch('/api/v1/strategy/vol20day/refresh', { method: 'POST' })
    // 拉取 101-500
    const r = await fetch('/api/v1/strategy/vol20day?min_rank=101&max_rank=500')
    const data = await r.json()
    if (data.status === 'ok') {
      chushaiResults.value = data.data || []
      chushaiTotal.value = data.total || 0
      showToast(`共 ${data.total} 只，已加载排名101-500 (${data.returned}只)`)
    } else {
      showToast({ message: '初筛失败', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    loadingChushai.value = false
  }
}

// ===== 多策略交集 =====
const multiResults = ref([])
const multiMode = ref(false)
const multiTitle = ref('')
const loadingMulti2 = ref(false)
const loadingMulti3 = ref(false)
const multi2Count = ref(0)
const multi3Count = ref(0)

async function doMultiPicks(minCount, maxCount = null) {
  multiMode.value = true
  selectedKey.value = null
  if (minCount === 2 && maxCount === 2) {
    loadingMulti2.value = true
  } else {
    loadingMulti3.value = true
  }
  const label = maxCount === 2 ? '满足2个策略' : '满足3+策略'
  multiTitle.value = `🎯 ${label} (${multiResults.value.length})`
  try {
    const params = `min_count=${minCount}${maxCount ? `&max_count=${maxCount}` : ''}`
    const r = await fetch(`/api/v1/strategy/multi-picks?${params}`)
    const data = await r.json()
    if (data.status === 'ok') {
      multiResults.value = data.data || []
      multiTitle.value = `🎯 ${label} — ${data.total}只`
      if (minCount === 2 && maxCount === 2) {
        multi2Count.value = data.total
      } else {
        multi3Count.value = data.total
      }
      showToast(`找到 ${data.total} 只`)
    } else {
      showToast({ message: '查询失败', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    loadingMulti2.value = false
    loadingMulti3.value = false
  }
}

// ===== 筛选模式 =====
const filters = ref({ industry: '', market_cap_min: '', market_cap_max: '' })
const screenResults = ref([])
const screenTotal = ref(0)
const screening = ref(false)
const screenSearched = ref(false)

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
  multiMode.value = false
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

// ===== 筛选函数 =====
async function doScreen() {
  screening.value = true
  screenSearched.value = true
  try {
    const params = {}
    if (filters.value.industry) params.industry = filters.value.industry
    if (filters.value.market_cap_min) params.market_cap_min = parseFloat(filters.value.market_cap_min)
    if (filters.value.market_cap_max) params.market_cap_max = parseFloat(filters.value.market_cap_max)
    
    const res = await screenStocks(params)
    if (res.data.status === 'ok') {
      screenResults.value = res.data.data?.slice(0, 100) || []
      screenTotal.value = res.data.total || 0
      showToast(`找到 ${screenTotal.value} 只`)
    } else {
      showToast({ message: '筛选失败', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    screening.value = false
  }
}

function formatMkt(val) {
  if (!val) return ''
  return (val / 1e8).toFixed(0) + '亿'
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

.multi-strat-actions {
  display: flex;
  flex-wrap: wrap;
  padding: 8px 12px;
  justify-content: center;
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
.result-area { margin-bottom: 16px; }
</style>
