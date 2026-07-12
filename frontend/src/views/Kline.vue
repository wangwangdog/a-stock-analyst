<template>
  <div class="kline-split">
    <!-- 左侧：共享 Sidebar 组件 -->
    <Sidebar @select-stock="switchStock" />

    <!-- 右侧：K线内容 -->
    <div class="right-kline">
    <van-nav-bar
      left-arrow
      @click-left="onClickLeft"
    >
      <template #title>
        <van-button size="small" plain type="primary" class="stock-header-btn" @click="goToChanlun" :title="'点击切换缠论K线 ' + (route.params.symbol || props.symbol)">
          {{ showChanlun ? '📈 返回K线' : ((route.params.symbol || props.symbol) + '  ' + stockName) }}
        </van-button>
      </template>
      <template #right>
        <van-icon name="more-o" @click="showMenu" />
      </template>
    </van-nav-bar>

    <!-- K线内容（默认显示） -->
    <!-- 加载遮罩 -->
    <van-overlay :show="pageLoading" z-index="10">
      <div class="loading-overlay">
        <van-loading type="spinner" color="#1989fa" size="48" />
        <div style="margin-top:12px;color:#1989fa;font-size:14px;">数据加载中...</div>
      </div>
    </van-overlay>
    <template v-if="!showChanlun">
    <!-- 基本信息栏 -->
    <div class="price-bar" v-if="priceData">
      <div class="price-main">
        <span class="price-num">{{ priceData.close.toFixed(2) }}</span>
        <span class="price-change" :style="{ color: changeColor }">
          {{ priceData.pct >= 0 ? '+' : '' }}{{ priceData.pct?.toFixed(2) }}%
        </span>
      </div>
      <div class="price-meta">
        <span>高 {{ priceData.high.toFixed(2) }}</span>
        <span>低 {{ priceData.low.toFixed(2) }}</span>
        <span>开 {{ priceData.open.toFixed(2) }}</span>
                <span v-if="rangeInfo.show" style="color:#ee0a24;font-weight:600">
          框选({{ rangeInfo.days }}日): {{ rangeInfo.startPrice?.toFixed(2) }} → {{ rangeInfo.endPrice?.toFixed(2) }}  
          <span :style="{color: rangeInfo.change >= 0 ? '#ff4757' : '#07c160'}">
            {{ rangeInfo.change >= 0 ? '+' : '' }}{{ rangeInfo.change?.toFixed(2) }}
            ({{ rangeInfo.pct >= 0 ? '+' : '' }}{{ rangeInfo.pct?.toFixed(2) }}%)
          </span>
        </span>
      </div>
    </div>

    <!-- 周期选择 -->
    <div class="period-bar">
      <van-button
        v-for="p in periods" :key="p.key"
        :type="period === p.key ? 'primary' : 'default'"
        size="small" plain
        @click="switchPeriod(p.key)"
      >{{ p.label }}</van-button>
    </div>

    <!-- 主K线图 -->
    <div class="main-chart-wrap">
      <div class="chart-container" ref="chartRef">
        <div class="chart-watermark">{{ stockName || symbol }}</div>
        <div class="range-label" v-show="rangeInfo.show" :style="rangeLabelStyle">
          <span :style="{color: rangeInfo.change >= 0 ? '#ff4757' : '#07c160', fontWeight: 600}">
            {{ rangeInfo.change >= 0 ? '+' : '' }}{{ rangeInfo.pct?.toFixed(2) }}%
          </span>
          <span style="font-size:11px;color:#999;margin-left:4px">
            {{ rangeInfo.days }}日
          </span>
          <div style="font-size:10px;color:#666;margin-top:1px">
            {{ rangeInfo.startPrice?.toFixed(2) }} → {{ rangeInfo.endPrice?.toFixed(2) }}
          </div>
        </div>
        <!-- MACD 悬浮提示 -->
        <div ref="macdTooltipRef" class="macd-tooltip" style="display:none">
          <div class="macd-tooltip-title">MACD</div>
          <div class="macd-tooltip-row"><span class="macd-dot dif"></span>DIF: <span class="macd-val dif-val"></span></div>
          <div class="macd-tooltip-row"><span class="macd-dot dea"></span>DEA: <span class="macd-val dea-val"></span></div>
          <div class="macd-tooltip-row"><span class="macd-bar-icon"></span>MACD: <span class="macd-val macd-val-bar"></span></div>
        </div>
      </div>
    </div>

    <!-- 技术指标选择 + 基本面 + MA设置 -->
    <div class="indicator-bar">
      <van-tag
        v-for="ind in indicators"
        :key="ind.key"
        :type="ind.active ? 'primary' : 'default'"
        plain round
        style="margin: 2px 4px"
        @click="toggleIndicator(ind)"
      >{{ ind.label }}</van-tag>
      <van-tag plain round :type="showFundamentals ? 'primary' : 'default'" style="margin: 2px 4px" @click="toggleFundamentals">📋 基本面</van-tag>
      <van-tag plain round :type="rangeMode ? 'danger' : 'default'" style="margin: 2px 4px" @click="toggleRangeMode">📏 框选</van-tag>
      <span class="ma-setting">
        <span class="ma-label">MA:</span>
        <input class="ma-input" v-model="maParamStr" placeholder="5,10,20,60" @change="updateMaParams" />
      </span>
    </div>

    <!-- 股票代码+名称 -->
    <div class="stock-info-line" @click="goToChanlun" style="cursor:pointer" :title="'点击查看 ' + symbol + ' 缠论图表'">
      {{ symbol }}  {{ stockName || '' }} <span style="font-size:11px;opacity:0.5">🔗缠论 v10</span>
    </div>

    <!-- 基本面信息（内联 - Tushare 分析） -->
    <div class="fund-section" v-if="showFundamentals">
      <div v-if="fundLoading" class="fund-loading">🔍 正在加载 tushare 数据分析...</div>
      <div v-else-if="fundError" class="fund-error">❌ {{ fundError }}</div>
      <div v-else class="fund-content-detailed">
        
        <!-- 公司信息 -->
        <div v-if="tushareCompany" class="fund-block">
          <div class="fund-block-title">🏢 公司概况</div>
          <div class="company-grid">
            <div class="company-item" v-if="tushareCompany.name">
              <span class="comp-label">名称</span>
              <span class="comp-val">{{ tushareCompany.name }}</span>
            </div>
            <div class="company-item" v-if="tushareCompany.industry">
              <span class="comp-label">行业</span>
              <span class="comp-val">{{ tushareCompany.industry }}</span>
            </div>
            <div class="company-item" v-if="tushareCompany.area">
              <span class="comp-label">地区</span>
              <span class="comp-val">{{ tushareCompany.area }}</span>
            </div>
            <div class="company-item" v-if="tushareCompany.list_date">
              <span class="comp-label">上市日期</span>
              <span class="comp-val">{{ tushareCompany.list_date }}</span>
            </div>
            <div class="company-item" v-if="tushareCompany.market">
              <span class="comp-label">板块</span>
              <span class="comp-val">{{ tushareCompany.market }}</span>
            </div>
            <div class="company-item company-desc" v-if="tushareCompany.main_business" :title="tushareCompany.main_business">
              <span class="comp-label">主营业务</span>
              <span class="comp-val">{{ tushareCompany.main_business }}</span>
            </div>
          </div>
        </div>

        <!-- 行情趋势分析 -->
        <div v-if="tusharePrice" class="fund-block">
          <div class="fund-block-title">📈 近期趋势分析（近20日）</div>
          <div class="pa-summary">
            <div class="pa-stat">
              <span class="pa-label">最新收盘</span>
              <span class="pa-val">{{ tusharePrice.close?.toFixed(2) }}</span>
            </div>
            <div class="pa-stat">
              <span class="pa-label">20日涨幅</span>
              <span class="pa-val" :style="{color: tusharePrice.period_return_20d >= 0 ? '#ee0a24' : '#07c160'}">{{ tusharePrice.period_return_20d >= 0 ? '+' : '' }}{{ tusharePrice.period_return_20d }}%</span>
            </div>
            <div class="pa-stat">
              <span class="pa-label">趋势判断</span>
              <span class="pa-val" style="font-size:12px">{{ tusharePrice.trend }}</span>
            </div>
            <div class="pa-stat">
              <span class="pa-label">20日波动率</span>
              <span class="pa-val">{{ tusharePrice.volatility_20d }}%</span>
            </div>
            <div class="pa-stat">
              <span class="pa-label">20日最高</span>
              <span class="pa-val">{{ tusharePrice.high_20d }}</span>
            </div>
            <div class="pa-stat">
              <span class="pa-label">20日最低</span>
              <span class="pa-val">{{ tusharePrice.low_20d }}</span>
            </div>
            <div class="pa-stat">
              <span class="pa-label">量比(最新/均值)</span>
              <span class="pa-val" :style="{color: tusharePrice.volume_ratio > 1.5 ? '#ee0a24' : '#333'}">{{ tusharePrice.volume_ratio }}x</span>
            </div>
            <div class="pa-stat" v-if="tusharePrice.ma5">
              <span class="pa-label">MA5 / MA10 / MA20</span>
              <span class="pa-val" style="font-size:12px">{{ tusharePrice.ma5 }} / {{ tusharePrice.ma10 }} / {{ tusharePrice.ma20 }}</span>
            </div>
          </div>
        </div>

        <!-- 财报说明 -->
        <div class="fund-block">
          <div class="fund-block-title">📊 财报数据</div>
          <div class="upgrade-tip">
            <van-icon name="info-o" style="margin-right:6px" />
            当前 Tushare Token 积分不足，无法获取财报、资金流数据。<br>
            如需查看完整财报和资金流向分析，请升级 Tushare Pro 积分：
            <a href="https://tushare.pro" target="_blank" style="color:#1989fa">tushare.pro</a>
          </div>
        </div>

        <!-- 资金流说明 -->
        <div class="fund-block">
          <div class="fund-block-title">💰 资金流向</div>
          <div class="upgrade-tip">
            <van-icon name="info-o" style="margin-right:6px" />
            资金流向数据需要更高 Tushare 积分权限。
          </div>
        </div>

      </div>
    </div>

    <!-- 子图区域：买入额, 资金流入 -->
    <div class="sub-charts-area">
      <!-- 大单买入数 子图（仅日线显示） -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">大单买入数</div>
        <div class="sub-chart-canvas" ref="bigbuyChartRef" id="bigbuy-chart"></div>
      </div>
      <!-- 有大买单 子图 -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">有大买单</div>
        <div class="sub-chart-canvas" ref="ratioChartRef" id="ratio-chart"></div>
      </div>
      <!-- 资金流入 子图 -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">资金流入</div>
        <div class="sub-chart-canvas" ref="fundFlowChartRef" id="fundflow-chart"></div>
      </div>
      <!-- CR 指标 子图 -->
      <div class="sub-chart-item" v-show="crData.length">
        <div class="sub-chart-label">CR <span class="cr-value" v-if="lastCr !== null">{{ lastCr }}</span></div>
        <div class="sub-chart-canvas" ref="crChartRef" id="cr-chart"></div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <van-button icon="records-o" size="small" plain :loading="quickLoading" @click="doQuickAnalysis" :style="quickBtnStyle">快速分析</van-button>
      <van-button icon="search" size="small" plain :loading="deepLoading" @click="doDeepAnalysis" :style="deepBtnStyle">深度分析</van-button>
      <template v-if="isFav">
        <van-button icon="star" size="small" plain @click="removeFavorite" style="color: #ee0a24; border-color: #ee0a24">已自选</van-button>
      </template>
      <template v-else>
        <van-button icon="star-o" size="small" plain @click="addFavorite">加自选</van-button>
      </template>
      <van-button icon="gem-o" size="small" plain :disabled="!hasStrategyPicks" :style="strategyBtnStyle" @click="checkStrategySignals">策略</van-button>
    </div>

    <!-- AI 分析结果区域 -->
    <div class="ai-result" v-if="aiResult.text">
      <div class="ai-result-header">
        <span class="ai-result-title">{{ aiResult.title }}</span>
        <van-icon name="cross" @click="aiResult.text = ''" style="font-size:18px;padding:4px" />
      </div>
      <div class="ai-result-body" v-html="aiResult.text"></div>
    </div>

    <!-- 数据源状态 -->
    <div class="source-status" v-if="dataSource">
      <span>数据源: {{ dataSource }}</span>
      <span v-if="validationFailed > 0" style="color: #ee0a24; margin-left: 8px">
        ⚠ {{ validationFailed }}天数据不一致
      </span>
    </div>
    </template>

    <!-- 缠论 iframe（点击按钮后显示） -->
    <template v-if="showChanlun">
      <iframe :src="chanlunUrl" frameborder="0" style="width:100%;height:calc(100vh - 46px);border:none;"></iframe>
    </template>

  </div>
</div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { showToast, showDialog, closeToast } from 'vant'
import { getKline, getBigBuy, getBigBuySummary, getBigDealSummary } from '../utils/api.js'
import Sidebar from '../components/Sidebar.vue'

const props = defineProps({ symbol: { type: String, default: '000001' } })
const route = useRoute()
const router = useRouter()

const chartRef = ref(null)
const macdTooltipRef = ref(null)

const bigbuyChartRef = ref(null)
const ratioChartRef = ref(null)
const fundFlowChartRef = ref(null)

const period = ref('daily')

// 缠论 iframe 模式
const showChanlun = ref(false)
const chanlunUrl = computed(() => '/tv/?code=' + (route.params.symbol || props.symbol))
const pageLoading = ref(false)
function onClickLeft() {
  if (showChanlun.value) {
    showChanlun.value = false
  } else {
    router.back()
  }
}

const periods = [
  { key: 'daily', label: '日K' },
  { key: 'weekly', label: '周K' },
  { key: 'monthly', label: '月K' },
  { key: '60min', label: '60分' },
  { key: '30min', label: '30分' },
  { key: '15min', label: '15分' },
]

// 选中股票与路由同步
const activeStock = ref(route.params.symbol || props.symbol)

watch(() => route.params.symbol, (newSym) => {
  if (newSym) activeStock.value = newSym
})

function goToChanlun() {
  showChanlun.value = !showChanlun.value
}

function switchStock(symbol) {
  const sym = route.params.symbol || props.symbol
  if (symbol === sym) return
  window.location.hash = '#/kline/' + symbol
}

// 基本面内联显示（Tushare 分析）
const showFundamentals = ref(false)
const fundLoading = ref(false)
const fundData = ref({})
const fundError = ref('')
const tushareCompany = ref(null)
const tusharePrice = ref(null)

// CR 指标
const crData = ref([])
const crChartRef = ref(null)
const lastCr = ref(null)
// MA 自定义参数
const maParamStr = ref(localStorage.getItem('kl_ma_params') || '5,10,20,60')
let maPeriods = maParamStr.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n) && n > 0)
// 框选涨幅
const rangeInfo = ref({ show: false, startPrice: null, endPrice: null, change: null, pct: null, active: false, days: 0 })
const rangeLabelStyle = ref({})
const rangeMode = ref(false)
let rangeClickCount = 0
let rangeStartTime = null
let rangeStartPriceVal = null
let rangeLineSeries = null
let rangePreviewLine = null

function toggleRangeMode() {
  rangeMode.value = !rangeMode.value
  if (rangeMode.value) {
    showToast('📏 框选模式：点击K线选择起点，再点击选择终点')
    rangeClickCount = 0
    rangeInfo.value = { show: false, startPrice: null, endPrice: null, change: null, pct: null, active: false, days: 0 }
    if (mainChart) {
      mainChart.applyOptions({ handleScroll: false, handleScale: false })
    }
  } else {
    if (mainChart) {
      mainChart.applyOptions({ handleScroll: { vertTouchDrag: true, horzTouchDrag: true, mouseWheel: true }, handleScale: { axisPressedMouse: true, mouseWheel: true, pinch: true } })
    }
    clearRangeOverlay()
    rangeInfo.value = { show: false, startPrice: null, endPrice: null, change: null, pct: null, active: false, days: 0 }
    rangeClickCount = 0
  }
}
async function updateMaParams() {
  const parts = maParamStr.value.split(',').map(s => parseInt(s.trim())).filter(n => !isNaN(n) && n > 0)
  if (!parts.length) {
    showToast('MA 参数格式错误，请用逗号分隔，如 5,10,20,60')
    return
  }

  maPeriods = parts
  maParamStr.value = parts.join(',')
  localStorage.setItem('kl_ma_params', maParamStr.value)

  // 重新加载K线数据（后端会用新的 MA 参数重新计算）
  loadData()
}

function clearRangeOverlay() {
  if (rangeLineSeries) {
    rangeLineSeries.setData([])
  }
  if (rangePreviewLine) {
    rangePreviewLine.setData([])
  }
}

async function toggleFundamentals() {
  showFundamentals.value = !showFundamentals.value
  if (!showFundamentals.value) return
  // 已有数据不重复加载
  if (tushareCompany.value || tusharePrice.value || Object.keys(fundData.value).length > 0) return
  
  fundLoading.value = true
  fundError.value = ''
  try {
    const sym = route.params.symbol || props.symbol
    const resp = await fetch('/api/v1/tushare-fundamentals/' + sym)
    const result = await resp.json()
    if (result && result.status === 'ok' && result.data) {
      const d = result.data
      if (d.company_info && !d.company_info.error) {
        tushareCompany.value = d.company_info
      }
      if (d.price_analysis && !d.price_analysis.error) {
        tusharePrice.value = d.price_analysis
      }
      if (!tushareCompany.value && !tusharePrice.value) {
        fundError.value = '暂无 tushare 数据'
      }
    } else {
      fundError.value = result?.message || '获取 tushare 数据失败'
    }
  } catch (e) {
    fundError.value = '获取 tushare 数据失败: ' + (e.message || '')
  } finally {
    fundLoading.value = false
  }
}

// 格式化辅助函数
function formatEndDate(d) {
  if (!d) return '-'
  const s = String(d)
  return s.slice(0, 4) + '-' + s.slice(4, 6)
}

function formatMoneyCompact(val) {
  if (val == null || isNaN(val)) return '-'
  const abs = Math.abs(val)
  if (abs >= 1e12) return (val / 1e12).toFixed(2) + '万亿'
  if (abs >= 1e8) return (val / 1e8).toFixed(2) + '亿'
  if (abs >= 1e4) return (val / 1e4).toFixed(2) + '万'
  return val.toFixed(2)
}

function moneyCls(val) {
  if (val == null) return ''
  return val >= 0 ? 'num-pos' : 'num-neg'
}

function fmtPct(val) {
  if (val == null || isNaN(val)) return '-'
  return (val * 100).toFixed(2) + '%'
}

function trendCls(val, threshold, invert) {
  if (val == null) return ''
  const pct = val * 100
  if (invert) {
    return pct <= threshold ? 'num-pos' : 'num-neg'
  }
  return pct >= threshold ? 'num-pos' : 'num-neg'
}

const indicators = ref([
  { key: 'ma', label: 'MA', active: true },
  { key: 'bollinger', label: '布林', active: false },
  { key: 'kdj', label: 'KDJ', active: false },
])

const klineData = ref([])
const indData = ref({})
const priceData = ref(null)
const stockName = ref('')
const dataSource = ref('')
const validationFailed = ref(0)
const bigbuyData = ref([])
const bigDealNetData = ref([])  // 有大买单数据（big_deal_summary）
const fundFlowData = ref([])   // 资金流入数据（fund_flow）

// AI 分析结果
const aiResult = ref({ title: '', text: '', visible: false })
const quickLoading = ref(false)
const deepLoading = ref(false)
const hasQuickCache = ref(false)
const hasDeepCache = ref(false)
const cachedQuickResult = ref(null)
const cachedDeepResult = ref(null)

const RED = 'border-color:#ff9999;color:#cc3333;background:#ffebeb'
const quickBtnStyle = computed(() => hasQuickCache.value ? RED : '')
const deepBtnStyle = computed(() => hasDeepCache.value ? RED : '')
const hasStrategyPicks = ref(false)
const strategyBtnStyle = computed(() => hasStrategyPicks.value ? 'color:#ee0a24;border-color:#ee0a24;background:#ffebeb' : '')

async function checkAnalysisCache() {
  const sym = (route.params.symbol || props.symbol)
  const u = localStorage.getItem('username')
  if (!u) { console.log('❌ 无用户名, 跳过缓存检查'); return }
  try {
    console.log('🔍 检查缓存:', u, sym, 'quick')
    const qResp = await fetch('/api/auth/cache/check', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username: u, symbol: sym, analysis_type: 'quick'})
    })
    const q = await qResp.json()
    console.log('  快速结果:', JSON.stringify(q))

    console.log('🔍 检查缓存:', u, sym, 'deep')
    const dResp = await fetch('/api/auth/cache/check', {
      method: 'POST', headers: {'Content-Type':'application/json'},
      body: JSON.stringify({username: u, symbol: sym, analysis_type: 'deep'})
    })
    const d = await dResp.json()
    console.log('  深度结果:', JSON.stringify(d))

    hasQuickCache.value = q.cached === true
    hasDeepCache.value = d.cached === true
    if (q.cached) cachedQuickResult.value = q.result
    if (d.cached) cachedDeepResult.value = d.result
    console.log('  按钮状态:', hasQuickCache.value ? '🔴快速' : '⚪快速', hasDeepCache.value ? '🔴深度' : '⚪深度', sym)
  } catch (e) { console.log('❌ 缓存检查失败:', e) }
}

async function doQuickAnalysis() {
  const sym = route.params.symbol || props.symbol
  
  // 有缓存直接显示
  if (hasQuickCache.value && cachedQuickResult.value) {
    const data = cachedQuickResult.value
    if (data && data.success !== false) {
      let signalText = ''
      if (data.signal === 'buy') signalText = '🟢 关注/可介入'
      else if (data.signal === 'watch') signalText = '🟡 观望'
      else if (data.signal === 'pass') signalText = '🔴 不宜介入'
      else signalText = '⚪ ' + (data.signal || '未知')
      const moneyIcon = { '有主力介入迹象': '🟢', '无明显主力迹象': '🟡', '主力出货': '🔴' }[data.main_force_judgment] || '⚪'
      const bottomIcon = { '已见底': '🟢', '底部区域': '🟡', '需观察': '🟡', '仍在下跌中': '🔴' }[data.bottom_pattern] || '⚪'
      aiResult.value = {
        title: '⚡ 快速研判结果(缓存)',
        text: `<div class="ai-quick-result"><div class="ai-signal ${data.signal}"><strong>${signalText}</strong></div><div class="ai-detail">${moneyIcon} 主力资金: ${data.main_force_judgment || '未知'}</div><div class="ai-detail">${bottomIcon} 底部形态: ${data.bottom_pattern || '未知'}</div><div class="ai-reason">💡 ${data.reasoning || ''}</div></div>`
      }
    } else {
      aiResult.value = { title: '❌ 缓存无效', text: '缓存数据格式错误' }
    }
    return
  }
  
  quickLoading.value = true
  aiResult.value = { title: '⚡ 快速分析中...', text: '正在获取数据并研判，请稍候...' }
  try {
    const resp = await fetch('/api/ai/quick', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stock_code: sym,
        stock_name: stockName.value,
        llm_provider: 'deepseek'
      })
    })
    const data = await resp.json()
    if (data.success) {
      // 保存缓存
      try {
        const u = getU()
        const cacheBody = JSON.stringify({username: u, symbol: sym, analysis_type: 'quick', result_json: JSON.stringify(data)})
        fetch('/api/auth/cache/save', { method: 'POST', headers: {'Content-Type':'application/json'}, body: cacheBody })
        hasQuickCache.value = true
        cachedQuickResult.value = data
      } catch {}
      let signalText = ''
      if (data.signal === 'buy') signalText = '🟢 关注/可介入'
      else if (data.signal === 'watch') signalText = '🟡 观望'
      else if (data.signal === 'pass') signalText = '🔴 不宜介入'
      else signalText = '⚪ ' + data.signal

      const moneyColors = {
        '有主力介入迹象': '🟢',
        '无明显主力迹象': '🟡',
        '主力出货': '🔴'
      }
      const moneyIcon = moneyColors[data.main_force_judgment] || '⚪'

      const bottomColors = {
        '已见底': '🟢',
        '底部区域': '🟡',
        '需观察': '🟡',
        '仍在下跌中': '🔴'
      }
      const bottomIcon = bottomColors[data.bottom_pattern] || '⚪'

      aiResult.value = {
        title: '⚡ 快速研判结果',
        text: `
          <div class="ai-quick-result">
            <div class="ai-signal ${data.signal}"><strong>${signalText}</strong></div>
            <div class="ai-detail">${moneyIcon} 主力资金: ${data.main_force_judgment || '未知'}</div>
            <div class="ai-detail">${bottomIcon} 底部形态: ${data.bottom_pattern || '未知'}</div>
            <div class="ai-reason">💡 ${data.reasoning || ''}</div>
          </div>
        `
      }
    } else {
      aiResult.value = { title: '❌ 分析失败', text: data.error || '未知错误' }
    }
  } catch (e) {
    aiResult.value = { title: '❌ 分析失败', text: e.message }
  } finally {
    quickLoading.value = false
  }
}

async function doDeepAnalysis() {
  const sym = route.params.symbol || props.symbol
  
  // 有缓存直接显示
  if (hasDeepCache.value && cachedDeepResult.value) {
    _showDeepResultCached(cachedDeepResult.value)
    return
  }
  
  deepLoading.value = true
  
  let progressHtml = '<div class="stream-start">🧠 深度分析启动，等待各Agent完成...</div>'
  let finalized = false
  
  try {
    const resp = await fetch('/api/ai/analyze/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stock_code: sym,
        llm_provider: 'deepseek',
        max_debate_rounds: 1
      })
    })
    
    const reader = resp.body.getReader()
    const decoder = new TextDecoder()
    let buffer = ''

    while (true) {
      const { done, value } = await reader.read()
      if (done) break
      
      buffer += decoder.decode(value, { stream: true })
      const lines = buffer.split('\n')
      buffer = lines.pop() || ''
      
      for (const line of lines) {
        if (!line.startsWith('data: ')) continue
        try {
          const payload = JSON.parse(line.slice(6))
          
          if (payload.done) {
            finalized = true
            // 保存缓存
            try {
              const u = getU()
              const cacheBody = JSON.stringify({username: u, symbol: sym, analysis_type: 'deep', result_json: JSON.stringify(payload.result)})
              fetch('/api/auth/cache/save', { method: 'POST', headers: {'Content-Type':'application/json'}, body: cacheBody })
              hasDeepCache.value = true
              cachedDeepResult.value = payload.result
            } catch {}
            
            if (payload.result) {
              const fa = payload.result.full_analysis || {}
              
              // 三栏分析
              const col1 = '<div class="analysis-col" style="background:#e3f2fd"><div class="col-title">📈 基本面分析师</div><div class="col-content">' + _escHtml(fa.fundamentals_report || fa.market_report || '暂无数据') + '</div></div>'
              const col2 = '<div class="analysis-col" style="background:#e8f5e9"><div class="col-title">📗 多头研究员</div><div class="col-content">' + _escHtml(fa.bull_analysis || '暂无数据') + '</div></div>'
              const col3 = '<div class="analysis-col" style="background:#ffebee"><div class="col-title">📕 空头研究员</div><div class="col-content">' + _escHtml(fa.bear_analysis || '暂无数据') + '</div></div>'
              
              // 最终结论
              const fd = fa.final_decision || {}
              const signalLabels = { 'buy': '🟢 买入', 'sell': '🔴 卖出', 'hold': '🟡 持有' }
              const sl = signalLabels[fd.signal_type] || '⚪ ' + (fd.signal_type || '未知')
              
              progressHtml = `
                <div class="three-col-analysis">
                  <div class="three-col-row">${col1}${col2}${col3}</div>
                  <div class="final-conclusion">
                    <div class="conclusion-title">📋 最终研判结论</div>
                    <div class="ai-signal ${fd.signal_type}"><strong>${sl}</strong> | 置信度: ${Math.round((fd.confidence || 0) * 100)}%</div>
                    <div class="ai-reason">💡 ${fd.reasoning || ''}</div>
                    ${fd.risk_level ? '<div class="ai-detail" style="margin-top:6px">⚠️ 风险评级: ' + fd.risk_level + '</div>' : ''}
                  </div>
                </div>`
            } else {
              progressHtml = '<div class="stream-error">❌ ' + (payload.error || '未知错误') + '</div>'
            }
          } else if (payload.agent) {
            const emojis = { '市场分析师': '📊', '社交媒体分析师': '💬', '新闻分析师': '📰', '基本面分析师': '📈', '看涨研究员': '📗', '看跌研究员': '📕', '研究经理': '📋', '交易员': '💼', '激进风控': '🔥', '保守风控': '🛡️', '中性风控': '⚖️', '风控经理': '🎯' }
            const emoji = emojis[payload.agent] || '🤖'
            progressHtml += '<div class="stream-agent-card"><div class="stream-agent-header">' + emoji + ' ' + payload.agent + ' <span class="stream-time">⏱ ' + (payload.time || '') + '</span></div></div>'
          }
          
          aiResult.value = {
            title: finalized ? '🧠 深度研判结果' : '🧠 深度分析进行中...',
            text: progressHtml
          }
        } catch {}
      }
    }
    
    if (!finalized) {
      progressHtml += '<div class="stream-error">❌ 连接中断</div>'
      aiResult.value = { title: '❌ 连接中断', text: progressHtml }
    }
  } catch (e) {
    aiResult.value = { title: '❌ 分析失败', text: e.message }
  } finally {
    deepLoading.value = false
  }
}

function _showDeepResultCached(d) {
  if (!d || !d.full_analysis) {
    aiResult.value = { title: '❌ 缓存无效', text: '缓存数据不完整' }
    return
  }
  const fa = d.full_analysis || {}
  const col1 = '<div class="analysis-col" style="background:#e3f2fd"><div class="col-title">📈 基本面分析师</div><div class="col-content">' + _escHtml(fa.fundamentals_report || fa.market_report || '暂无数据') + '</div></div>'
  const col2 = '<div class="analysis-col" style="background:#e8f5e9"><div class="col-title">📗 多头研究员</div><div class="col-content">' + _escHtml(fa.bull_analysis || '暂无数据') + '</div></div>'
  const col3 = '<div class="analysis-col" style="background:#ffebee"><div class="col-title">📕 空头研究员</div><div class="col-content">' + _escHtml(fa.bear_analysis || '暂无数据') + '</div></div>'
  const fd = fa.final_decision || {}
  const signalLabels = { 'buy': '🟢 买入', 'sell': '🔴 卖出', 'hold': '🟡 持有' }
  const sl = signalLabels[fd.signal_type] || '⚪ ' + (fd.signal_type || '未知')
  aiResult.value = {
    title: '🧠 深度研判结果(缓存)',
    text: `<div class="three-col-analysis"><div class="three-col-row">${col1}${col2}${col3}</div><div class="final-conclusion"><div class="conclusion-title">📋 最终研判结论</div><div class="ai-signal ${fd.signal_type}"><strong>${sl}</strong> | 置信度: ${Math.round((fd.confidence || 0) * 100)}%</div><div class="ai-reason">💡 ${fd.reasoning || ''}</div>${fd.risk_level ? '<div class="ai-detail" style="margin-top:6px">⚠️ 风险评级: ' + fd.risk_level + '</div>' : ''}</div></div>`
  }
}

function _escHtml(s) {
  if (!s) return ''
  var r = s.split('&').join('&amp;').split('<').join('&lt;').split('>').join('&gt;')
  return r.split(String.fromCharCode(10)).join('<br>')
}

// 自选股 (后端 API)
const favorites = ref([])
const isFav = ref(false)

function getU() { return localStorage.getItem('username') || '' }

async function loadFavorites() {
  const u = getU()
  if (!u) return
  try {
    const resp = await fetch('/api/v1/favorites?username=' + encodeURIComponent(u))
    const list = await resp.json()
    favorites.value = list.map(f => f.symbol)
    const sym = route.params.symbol || props.symbol
    isFav.value = favorites.value.includes(sym)
  } catch { }
}

async function addFavorite() {
  const sym = route.params.symbol || props.symbol
  const u = getU()
  if (!u) return
  try {
    await fetch('/api/v1/favorites', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: u, symbol: sym, name: stockName.value })
    })
    isFav.value = true
    showToast('已添加自选')
    loadFavorites()
  } catch {
    showToast('操作失败')
  }
}

async function removeFavorite() {
  const sym = route.params.symbol || props.symbol
  const u = getU()
  if (!u) return
  try {
    await fetch('/api/v1/favorites/' + encodeURIComponent(sym) + '?username=' + encodeURIComponent(u), { method: 'DELETE' })
    isFav.value = false
    showToast('已取消自选')
    loadFavorites()
  } catch {
    showToast('操作失败')
  }
}

const showBigBuy = computed(() => period.value === 'daily')

const changeColor = computed(() => {
  if (!priceData.value) return '#666'
  return priceData.value.pct >= 0 ? '#ee0a24' : '#07c160'
})

// 检查个股是否在策略数据库中
async function checkStrategyPick() {
  const sym = route.params.symbol || props.symbol
  if (!sym) return
  try {
    const r = await fetch('/api/v1/strategy/check/' + sym)
    const data = await r.json()
    hasStrategyPicks.value = data.has_picks === true
  } catch {
    hasStrategyPicks.value = false
  }
}

// Sequoia-X 策略信号查询
async function checkStrategySignals() {
  const sym = route.params.symbol || props.symbol
  if (!sym) return
  try {
    const r = await fetch('/api/v1/strategy/signals/' + sym)
    const data = await r.json()
    if (!data.has_signals) {
      showToast('暂无策略信号')
      return
    }
    showDialog({
      title: '📊 策略信号',
      message: data.signals,
      showCancelButton: false,
    })
  } catch {
    showToast('策略信号查询失败')
  }
}

// 图表实例
let mainChart = null
let candleSeries = null
let volSeries = null
let maLines = []

// 子图实例
let bigbuyChart = null
let ratioChart = null
let crChart = null

let bigbuyHistogram = null
let ratioHistogram = null

// lw模块缓存
let lwModuleCache = null

watch(() => route.params.symbol, (newSym) => {
  if (newSym) {
    aiResult.value = { title: '', text: '' }
    loadData()
    checkAnalysisCache()
    checkStrategyPick()
  }
})

onMounted(() => {
  // 🔴 ALL data loading deferred: 先渲染框架，再异步加载数据
  nextTick(() => {
    setTimeout(() => {
      loadData()
      loadFavorites()
      checkAnalysisCache()
      checkStrategyPick()
    }, 50)
  })
})

// 从缠论返回时，DOM 重建后重新渲染图表
watch(showChanlun, (val) => {
  if (!val) {
    nextTick(() => {
      renderAllCharts()
    })
  }
})

async function loadData() {
  pageLoading.value = true
  try {
    const res = await getKline(route.params.symbol || props.symbol, {
      period: period.value,
      start_date: getStartDate(period.value),
      end_date: getEndDate(),
      indicators: true,
      ma_periods: maParamStr.value,
    })
    const data = res.data
    // 数据清洗：去重 + 绝对值修正 high/low
    let raw = data.data || []
    const seen = new Map()
    for (const d of raw) {
      // 绝对值修正：high = max(open, close, 原始high, 原始low)
      // low = min(open, close, 原始high, 原始low)
      // 原始数据源存在 H/L 倒挂，简单 swap 不够（swap 后 low 可能还在 body 内）
      const vals = [d.open, d.close, d.high, d.low]
      d.high = Math.max(...vals)
      d.low = Math.min(...vals)
      // 按 date 去重（保留最后一个）
      seen.set(d.date, d)
    }
    klineData.value = Array.from(seen.values())
    indData.value = data.indicators || {}
    dataSource.value = data.source
    stockName.value = data.name || ''

    // 统计校验失败
    if (data.validation) {
      validationFailed.value = data.validation.filter(v => !v.passed).length
    }

    // 最新价格
    if (klineData.value.length > 0) {
      const last = klineData.value[klineData.value.length - 1]
      const prev = klineData.value.length > 1 ? klineData.value[klineData.value.length - 2] : last
      priceData.value = {
        ...last,
        pct: prev.close ? ((last.close - prev.close) / prev.close * 100) : 0
      }
    }

    // 加载大单买入数（仅日线）— subchart: 大单买入数（hzeveryday）
    if (showBigBuy.value) {
      try {
        const bbRes = await getBigBuySummary(route.params.symbol || props.symbol, 60)
        bigbuyData.value = bbRes.data.data || []
      } catch (e) {
        bigbuyData.value = []
      }
    } else {
      bigbuyData.value = []
    }

    // 加载有大买单数据（仅日线）— subchart: 有大买单（big_deal_summary）
    if (showBigBuy.value) {
      try {
        const ddRes = await getBigDealSummary(route.params.symbol || props.symbol, 60)
        bigDealNetData.value = ddRes.data.data || []
      } catch (e) {
        bigDealNetData.value = []
      }
    } else {
      bigDealNetData.value = []
    }

    // 加载资金流入数据（仅日线）— subchart: 资金流入（fund_flow）
    if (showBigBuy.value) {
      try {
        const ffRes = await getBigBuy(route.params.symbol || props.symbol, 60)
        fundFlowData.value = ffRes.data.data || []
      } catch (e) {
        fundFlowData.value = []
      }
    } else {
      fundFlowData.value = []
    }

    // 加载 CR 指标数据（仅日线）
    if (period.value === 'daily') {
      try {
        const crRes = await fetch(`/api/v1/cr-indicator/${route.params.symbol || props.symbol}?limit=1000`)
        const crJson = await crRes.json()
        crData.value = (crJson.data || []).reverse()
        lastCr.value = crData.value.length ? crData.value[crData.value.length - 1].cr : null
      } catch (e) {
        crData.value = []
        lastCr.value = null
      }
    } else {
      crData.value = []
      lastCr.value = null
    }

    await nextTick()
    renderAllCharts()
    pageLoading.value = false
  } catch (e) {
    console.error('❌ loadData 失败:', e, e.message)
    pageLoading.value = false
    showToast({ message: '数据加载失败', type: 'fail' })
  }
}

function switchPeriod(p) {
  period.value = p
  loadData()
}

function getStartDate(period) {
  const now = new Date()
  const y = now.getFullYear()
  const m = String(now.getMonth() + 1).padStart(2, '0')
  const d = String(now.getDate()).padStart(2, '0')
  
  if (['15min', '30min', '60min'].includes(period)) {
    const start = new Date(now)
    start.setDate(start.getDate() - 30)
    return `${start.getFullYear()}-${String(start.getMonth() + 1).padStart(2, '0')}-${String(start.getDate()).padStart(2, '0')}`
  }
  
  let startY = y
  if (period === 'daily') {
    // 加载全量数据（与TV一致），2020年覆盖所有A股IPO
    return '2020-01-01'
  }
  else if (period === 'weekly') startY = y - 3
  else startY = y - 5
  return `${startY}-01-01`
}

function getEndDate() {
  const now = new Date()
  return `${now.getFullYear()}-${String(now.getMonth()+1).padStart(2,'0')}-${String(now.getDate()).padStart(2,'0')}`
}

function makeTime(d) {
  const isIntraday = ['15min', '30min', '60min'].includes(period.value)
  if (isIntraday) {
    const dt = new Date(d.date.replace(' ', 'T') + '+08:00')
    return Math.floor(dt.getTime() / 1000)
  }
  return d.date.slice(0, 10)
}

function makeTimeFromStr(dateStr) {
  if (dateStr.length === 10) return dateStr // already YYYY-MM-DD
  const dt = new Date(dateStr.replace(' ', 'T') + '+08:00')
  return Math.floor(dt.getTime() / 1000)
}

function renderAllCharts() {
  if (!chartRef.value || !klineData.value.length) return

  import('lightweight-charts').then(LW => {
    try {
      const lw = LW.default || LW
      lwModuleCache = lw

      // 销毁旧图表
      destroyAllCharts()

      // 计算统一的时间数据
      const times = klineData.value.map(d => makeTime(d))

      // 主K线图
      renderMainChart(lw, times)
      // 大单买入数子图
      if (showBigBuy.value) {
        renderBigbuyChart(lw, times)
      }
      // 有大买单子图
      if (showBigBuy.value) {
        renderRatioChart(lw, times)
      }
      // 资金流入子图
      if (showBigBuy.value) {
        renderFundFlowChart(lw, times)
      }
      // CR 子图
      if (crData.value.length) {
        renderCrChart(lw, times)
      }

      // 初始对齐时间轴
      setupTimeScaleSync()
    } catch(e) {
      console.error('🐛 renderAllCharts error:', e.message, e.stack?.substring(0,500))
    }
  })
}

function destroyAllCharts() {
  if (mainChart) { mainChart.remove(); mainChart = null }
  if (bigbuyChart) { bigbuyChart.remove(); bigbuyChart = null }
  if (ratioChart) { ratioChart.remove(); ratioChart = null }
  if (crChart) { crChart.remove(); crChart = null }
  candleSeries = null
  volSeries = null
  maLines = []
  bigbuyHistogram = null
  ratioHistogram = null
}

// ====== 主K线图 ======
function renderMainChart(lw, times) {
    const { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries } = lw

  mainChart = createChart(chartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#FFFEF5' },
      textColor: '#333',
    },
    grid: {
      vertLines: { color: '#f5f0e0' },
      horzLines: { color: '#f5f0e0' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e8e0c8',
    },
    timeScale: {
      borderColor: '#e8e0c8',
      timeVisible: true,
      secondsVisible: false,
    },
    handleScroll: { vertTouchDrag: true, horzTouchDrag: true, mouseWheel: true },
    handleScale: { axisPressedMouse: true, mouseWheel: true, pinch: true },
    width: chartRef.value.clientWidth,
    height: 360,
  })

  // K线
  candleSeries = mainChart.addSeries(CandlestickSeries, {
    upColor: '#ee0a24',
    downColor: '#16a34a',
    borderUpColor: '#ee0a24',
    borderDownColor: '#16a34a',
    wickUpColor: '#ee0a24',
    wickDownColor: '#16a34a',
  })

  const candles = klineData.value.map((d, i) => ({
    time: times[i],
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close,
  }))
  candleSeries.setData(candles)

  // 成交量
  volSeries = mainChart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume' },
    priceScaleId: 'volume',
  })
  mainChart.priceScale('volume').applyOptions({
    scaleMargins: { top: 0.8, bottom: 0 },
  })

  const volumes = klineData.value.map((d, i) => ({
    time: times[i],
    value: d.volume || 0,
    color: d.close >= d.open ? 'rgba(238,10,36,0.3)' : 'rgba(22,163,74,0.3)',
  }))
  volSeries.setData(volumes)

  // ═══ 预创建框选用 LineSeries（避免动态 addSeries 重建 canvas）═══
  rangeLineSeries = mainChart.addSeries(LineSeries, {
    color: '#ee0a24',
    lineWidth: 2,
    lineStyle: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  })
  rangeLineSeries.setData([])  // 空数据，不显示

  rangePreviewLine = mainChart.addSeries(LineSeries, {
    color: 'rgba(238,10,36,0.25)',
    lineWidth: 2,
    lineStyle: 2,
    lastValueVisible: false,
    priceLineVisible: false,
    crosshairMarkerVisible: false,
  })
  rangePreviewLine.setData([])  // 空数据，不显示

  // 均线（默认显示）
  renderMainIndicators(lw)

  // ═══ K线框选：两次点击计算涨幅 ═══
  //
  // 注意：不依赖 lightweight-charts subscribeClick（canvas重建会丢失）
  // 直接监听容器 div 的点击事件 + coordinateToTime

  function findBarData(t) {
    let norm
    if (typeof t === 'string') norm = t
    else if (typeof t === 'number') norm = t
    else if (t && typeof t === 'object' && t.year !== undefined) {
      norm = `${t.year}-${String(t.month).padStart(2,'0')}-${String(t.day).padStart(2,'0')}`
    } else {
      norm = String(t)
    }
    const idx = times.indexOf(norm)
    if (idx >= 0 && idx < klineData.value.length) {
      const d = klineData.value[idx]
      return { time: norm, close: d.close, low: d.low, high: d.high, idx }
    }
    return null
  }

  // 直接用容器 div 的点击事件（不依赖 lightweight-charts canvas）
  const chartContainer = chartRef.value
  if (chartContainer) {
    chartContainer.addEventListener('click', (e) => {
      // 找到 chart 内的 canvas
      const canvas = chartContainer.querySelector('canvas')
      if (!canvas) {
        console.log('[容器click] 无canvas')
        return
      }
      const rect = canvas.getBoundingClientRect()
      const x = e.clientX - rect.left
      const y = e.clientY - rect.top

      console.log('[容器click] x:', x.toFixed(0), 'y:', y.toFixed(0), 'rangeMode:', rangeMode.value, 'rangeClickCount:', rangeClickCount)

      if (!rangeMode.value) return

      // 用 lightweight-charts API 将坐标转时间
      const t = mainChart.timeScale().coordinateToTime(x)
      if (!t) {
        console.log('[容器click] coordinateToTime 返回空', {x: x.toFixed(0)})
        showToast('⚠️ 请点击K线区域')
        return
      }

      console.log('[容器click] coordinateToTime:', t, '(type:', typeof t, ')')

      const td = findBarData(t)
      if (!td) {
        console.log('[容器click] findBarData 未匹配:', t)
        showToast('⚠️ 未匹配到K线数据:' + String(t))
        return
      }

      console.log('[容器click 匹配成功]', td.time, 'close:', td.close)

      // 已有框选结果 → 保留，不做任何清除，提示用户关闭框选重新开始
      if (rangeInfo.value.show) {
        showToast('ℹ️ 已有框选结果，关闭📏框选模式再重新选择')
        return
      }

      if (rangeClickCount === 0) {
        // ===== 第一次点击 =====
        rangeStartTime = td.time
        rangeStartPriceVal = td.close
        rangeInfo.value = { show: false, startPrice: td.close, endPrice: null, change: null, pct: null, active: true, days: 0 }
        rangeClickCount = 1
        showToast(`✅ 起点: ${td.time} 收盘价 ${td.close.toFixed(2)} → 请点击终点K线`)

        clearRangeOverlay()
        rangeLineSeries.setData([
          { time: td.time, value: td.low },
          { time: td.time, value: td.high },
        ])
        rangePreviewLine.setData([
          { time: td.time, value: td.close },
          { time: td.time, value: td.close },
        ])
        console.log('[容器click] 起点标记完成')
      } else {
        // ===== 第二次点击 =====
        const start = rangeStartPriceVal
        const end = td.close
        const change = end - start
        const pct = start ? (change / start * 100) : 0
        const startIdx = times.indexOf(rangeStartTime)
        const daysCount = td.idx >= 0 && startIdx >= 0
          ? Math.abs(td.idx - startIdx) + 1
          : 0

        rangeInfo.value = { show: true, startPrice: start, endPrice: end, change, pct, active: true, days: daysCount }

        rangePreviewLine.setData([])
        rangeLineSeries.setData([
          { time: rangeStartTime, value: start },
          { time: td.time, value: end },
        ])
        rangeLineSeries.applyOptions({ lineStyle: 0, color: '#ff4757', lineWidth: 2 })

        // 在终点位置定位标签
        requestAnimationFrame(() => {
          try {
            const endX = mainChart.timeScale().timeToCoordinate(td.time)
            const endY = candleSeries.priceToCoordinate(end)
            if (endX !== null && endY !== null) {
              rangeLabelStyle.value = {
                left: Math.min(endX + 8, (chartRef.value?.clientWidth || 600) - 140) + 'px',
                top: Math.max(endY - 38, 0) + 'px',
              }
            }
          } catch (e) {
            console.log('[容器click] label定位失败:', e)
          }
        })
        rangeClickCount = 0
        console.log('[容器click] 涨幅计算完成')
      }
    })
    console.log('[容器click] 已注册点击监听（替代subscribeClick）')
  }
}



// ====== 大单买入数子图（仅日线） ======
// ====== 大单买入数子图（仅日线） ======
function renderBigbuyChart(lw, times) {
  if (!bigbuyChartRef.value) return
  const { createChart, ColorType, HistogramSeries } = lw
  
  // 使用子图自身宽度，fallback到主K线图宽度
  const subWidth = bigbuyChartRef.value.clientWidth || chartRef.value?.clientWidth || 360

  bigbuyChart = createChart(bigbuyChartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#FFFEF5' },
      textColor: '#666',
    },
    grid: {
      vertLines: { color: '#f5f0e0' },
      horzLines: { color: '#f5f0e0' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e8e0c8',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: '#e8e0c8',
      timeVisible: true,
      secondsVisible: false,
    },
    handleScroll: false,
    handleScale: false,
    width: subWidth,
    height: 120,
  })

  bigbuyHistogram = bigbuyChart.addSeries(HistogramSeries, {
    color: '#1890ff',
    priceFormat: { type: 'volume', precision: 0 },
    lastValueVisible: false,
  })

  // 构建完整的日期序列，与 K 线时间轴对齐
  const bbMap = {}
  bigbuyData.value.forEach(d => { bbMap[d.date.slice(0, 10)] = d })

  const bbData = klineData.value.map((d, i) => {
    const date = d.date.slice(0, 10)
    const match = bbMap[date]
    const val = match ? ((match.amount || 0) / 10000) : 0
    return {
      time: times[i],
      value: val,
      color: match ? 'rgba(235,82,54,0.7)' : 'rgba(235,82,54,0.05)',
    }
  })

  if (bbData.length) bigbuyHistogram.setData(bbData)
  else bigbuyHistogram.setData([{ time: times[0] || '', value: 0 }])

  // 柱顶标注买入额
  try {
    const markers = []
    klineData.value.forEach((kd, i) => {
      const date = kd.date.slice(0, 10)
      const match = bbMap[date]
      if (match && match.amount > 0) {
        const amtWan = (match.amount / 10000).toFixed(0)
        markers.push({
          time: times[i],
          position: 'aboveBar',
          color: '#e74c3c',
          shape: 'arrowUp',
          text: amtWan + 'w',
        })
      }
    })
    if (markers.length && typeof bigbuyHistogram.setMarkers === 'function') {
      bigbuyHistogram.setMarkers(markers)
    }
  } catch (e) {
    console.warn('标记失败:', e)
  }
}

// ====== 大单净额子图（±柱状图，0轴） ======
function renderRatioChart(lw, times) {
  if (!ratioChartRef.value) return
  const { createChart, ColorType, HistogramSeries } = lw
  
  const subWidth = ratioChartRef.value.clientWidth || chartRef.value?.clientWidth || 360

  ratioChart = createChart(ratioChartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#FFFEF5' },
      textColor: '#666',
    },
    grid: {
      vertLines: { color: '#f5f0e0' },
      horzLines: { color: '#f5f0e0' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e8e0c8',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: '#e8e0c8',
      timeVisible: true,
      secondsVisible: false,
    },
    handleScroll: false,
    handleScale: false,
    width: subWidth,
    height: 120,
  })

  ratioHistogram = ratioChart.addSeries(HistogramSeries, {
    priceFormat: { type: 'volume', precision: 0 },
    lastValueVisible: false,
  })

  // 零轴基线
  try {
    ratioHistogram.createPriceLine({
      price: 0,
      color: '#999',
      lineWidth: 1,
      lineStyle: 2,
      axisLabelVisible: false,
    })
  } catch(e) {}

  if (!bigDealNetData.value.length) {
    ratioHistogram.setData([{ time: times[0] || '', value: 0 }])
    return
  }

  const ndMap = {}
  bigDealNetData.value.forEach(d => { ndMap[d.date.slice(0, 10)] = d.amount })

  const chartData = klineData.value.map((d, i) => {
    const date = d.date.slice(0, 10)
    const val = ndMap[date] !== undefined ? ndMap[date] : 0
    return {
      time: times[i],
      value: val,
      color: val >= 0 ? 'rgba(238,10,36,0.75)' : 'rgba(7,193,96,0.75)',
    }
  })

  ratioHistogram.setData(chartData)

  // 柱顶标注
  try {
    const markers = []
    klineData.value.forEach((d, i) => {
      const date = d.date.slice(0, 10)
      const val = ndMap[date]
      if (val !== undefined && val !== 0) {
        markers.push({
          time: times[i],
          position: val >= 0 ? 'aboveBar' : 'belowBar',
          color: val >= 0 ? '#ee0a24' : '#07c160',
          shape: val >= 0 ? 'arrowUp' : 'arrowDown',
          text: (val / 10000).toFixed(0) + '万',
        })
      }
    })
    if (markers.length && typeof ratioHistogram.setMarkers === 'function') {
      ratioHistogram.setMarkers(markers)
    }
  } catch (e) {}
}

// ====== CR 指标子图 ======

// ====== 资金流入子图 ======
function renderFundFlowChart(lw, times) {
  if (!fundFlowChartRef.value || !fundFlowData.value.length) return
  const { createChart, ColorType, HistogramSeries } = lw
  const width = fundFlowChartRef.value.clientWidth || fundFlowChartRef.value.parentElement?.clientWidth || 400
  let ffc = createChart(fundFlowChartRef.value, {
    width, height: 120, layout: { background: { type: ColorType.Solid, color: '#FFFEF5' } },
    grid: { vertLines: { visible: false }, horzLines: { visible: false } },
    timeScale: { visible: true, borderVisible: false, fixLeftEdge: true, fixRightEdge: true },
    rightPriceScale: { visible: true, borderVisible: false, scaleMargins: { top: 0.15, bottom: 0.15 } },
    crosshair: { vertLine: { visible: false }, horzLine: { visible: false } },
    handleScroll: false, handleScale: false,
  })
  const series = ffc.addSeries(HistogramSeries, {
    color: '#1989fa', priceFormat: { type: 'volume', precision: 0 }, priceLineVisible: false,
    lastValueVisible: false,
  })
  const ffMap = {}
  fundFlowData.value.forEach(d => { ffMap[d.date.slice(0, 10)] = d.amount || d.qty || 0 })
  const chartData = klineData.value.map((d, i) => {
    const val = ffMap[d.date.slice(0, 10)] || 0
    return { time: times[i], value: val, color: val >= 0 ? 'rgba(238,10,36,0.75)' : 'rgba(7,193,96,0.75)' }
  })
  series.setData(chartData)
  ffc.timeScale().fitContent()
}

// ====== CR 指标子图（与MACD一样映射到K线times，支持setVisibleLogicalRange同步） ======
function renderCrChart(lw, times) {
  if (!crChartRef.value || !crData.value.length) return
  const { createChart, ColorType, LineSeries } = lw

  const width = crChartRef.value.clientWidth || crChartRef.value.parentElement?.clientWidth || 400

  crChart = createChart(crChartRef.value, {
    width,
    height: 130,
    layout: {
      background: { type: ColorType.Solid, color: '#FFFEF5' },
      textColor: '#333',
    },
    rightPriceScale: {
      visible: true,
      borderColor: '#e8e0c8',
      scaleMargins: { top: 0.08, bottom: 0.08 },
    },
    timeScale: {
      visible: true,
      borderColor: '#e8e0c8',
      timeVisible: true,
      secondsVisible: false,
    },
    grid: {
      vertLines: { color: '#f5f0e0' },
      horzLines: { color: '#f5f0e0' },
    },
    crosshair: { mode: 0 },
    handleScroll: false,
    handleScale: false,
  })

  const crLine = crChart.addSeries(LineSeries, {
    color: '#eb2f96',
    lineWidth: 2,
    lastValueVisible: true,
    priceLineVisible: true,
    priceLineColor: '#eb2f96',
    priceFormat: { type: 'price', precision: 1, minMove: 0.1 },
  })
  const ma1Line = crChart.addSeries(LineSeries, { color: '#fadb14', lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false })
  const ma2Line = crChart.addSeries(LineSeries, { color: '#52c41a', lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false })
  const ma3Line = crChart.addSeries(LineSeries, { color: '#1890ff', lineWidth: 1.5, lastValueVisible: false, priceLineVisible: false })
  
  // 与MACD一样：将CR数据映射到K线 times 位置
  // 按日期匹配，确保与主图时间轴对齐
  const crByDate = {}
  crData.value.forEach(d => { crByDate[d.date] = d })

  const crValues = []
  const ma1Values = []
  const ma2Values = []
  const ma3Values = []

  klineData.value.forEach((kd, i) => {
    const date = kd.date ? kd.date.slice(0, 10) : ''
    if (!date) return
    const d = crByDate[date]
    if (!d) return
    crValues.push({ time: times[i], value: d.cr })
    if (d.ma1 != null) ma1Values.push({ time: times[i], value: d.ma1 })
    if (d.ma2 != null) ma2Values.push({ time: times[i], value: d.ma2 })
    if (d.ma3 != null) ma3Values.push({ time: times[i], value: d.ma3 })
  })

  if (crValues.length) crLine.setData(crValues)
  if (ma1Values.length) ma1Line.setData(ma1Values)
  if (ma2Values.length) ma2Line.setData(ma2Values)
  if (ma3Values.length) ma3Line.setData(ma3Values)
}

// ====== 均线渲染 ======
function renderMainIndicators(lw) {
  if (!mainChart || !indData.value) return

  // 清除旧均线
  maLines.forEach(l => mainChart.removeSeries(l))
  maLines = []

  const { LineSeries } = lw
  const active = indicators.value.filter(i => i.active)
  const ind = indData.value

  if (active.find(i => i.key === 'ma') && ind.ma) {
    const periods = maPeriods
    const colors = ['#f7931a', '#1890ff', '#52c41a', '#722ed1', '#eb2f96', '#13c2c2', '#fa541c', '#2f54eb']
    periods.forEach((p, idx) => {
      const key = `MA${p}`
      if (ind.ma[key] && ind.ma[key].length) {
        const line = mainChart.addSeries(LineSeries, {
          color: colors[idx],
          lineWidth: 1,
          lastValueVisible: false,
          priceLineVisible: false,
          priceFormat: { type: 'price' },
        })
        const data = klineData.value.map((d, i) => {
          let time = makeTime(d)
          return { time, value: ind.ma[key][i] }
        }).filter(d => d.value !== null && !isNaN(d.value))
        line.setData(data)
        maLines.push(line)
      }
    })
  }

  // 布林带
  if (active.find(i => i.key === 'bollinger') && ind.bollinger) {
    const boll = ind.bollinger
    if (boll.BOLL_UP && boll.BOLL_UP.length) {
      const line = mainChart.addSeries(LineSeries, {
        color: '#fa8c16',
        lineWidth: 1,
        lineStyle: 0,
      })
      line.setData(klineData.value.map((d, i) => ({
        time: makeTime(d),
        value: boll.BOLL_UP[i],
      })).filter(d => d.value))
      maLines.push(line)

      const line2 = mainChart.addSeries(LineSeries, {
        color: '#fa8c16',
        lineWidth: 1,
        lineStyle: 0,
      })
      line2.setData(klineData.value.map((d, i) => ({
        time: makeTime(d),
        value: boll.BOLL_DN[i],
      })).filter(d => d.value))
      maLines.push(line2)
    }
  }


}

// ====== 时间轴联动 ======
function setupTimeScaleSync() {
  // 主K线图 + 所有子图（CR同样映射到times，与MACD一样用索引同步）
  const allSameCountCharts = [mainChart]
  if (bigbuyChart) allSameCountCharts.push(bigbuyChart)
  if (ratioChart) allSameCountCharts.push(ratioChart)
  if (crChart) allSameCountCharts.push(crChart)

  // 主图 fitContent 显示全部数据（与chanlun-pro TradingView默认一致）
  setTimeout(() => {
    if (!mainChart) return
    allSameCountCharts.forEach(c => {
      if (!c) return
      try {
        c.timeScale().fitContent()
      } catch(e) {}
    })
  }, 100)

  // 订阅主图变化，联动所有子图（包括CR，都已映射到times，用索引同步）
  if (mainChart) {
    allSameCountCharts.forEach((sourceChart, sourceIdx) => {
      if (!sourceChart) return
      let syncing = false

      sourceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
        if (syncing || !range) return
        syncing = true
        try {
          allSameCountCharts.forEach((targetChart, targetIdx) => {
            if (targetIdx === sourceIdx || !targetChart) return
            targetChart.timeScale().setVisibleLogicalRange(range)
          })
        } catch(e) {}
        requestAnimationFrame(() => { syncing = false })
      })
    })
  }
}

function toggleIndicator(ind) {
  ind.active = !ind.active
  if (lwModuleCache && mainChart) {
    renderMainIndicators(lwModuleCache)
  }
}

function showMenu() {
  showToast({ message: '代码: ' + (route.params.symbol || props.symbol), icon: 'info-o' })
}
</script>

<style scoped>
.kline-split {
  display: flex;
  height: 100vh;
  overflow: hidden;
}
.right-kline {
  flex: 1;
  overflow-y: auto;
  background: #fff;
  padding-bottom: 70px;
  position: relative;
}
.loading-overlay {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  display: flex;
  flex-direction: column;
  align-items: center;
}
.price-bar {
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
}
.price-main {
  display: flex;
  align-items: baseline;
  gap: 12px;
}
.price-num {
  font-size: 28px;
  font-weight: 700;
}
.price-change {
  font-size: 16px;
  font-weight: 500;
}
.price-meta {
  display: flex;
  gap: 16px;
  font-size: 12px;
  color: #999;
  margin-top: 4px;
}
.period-bar {
  display: flex;
  gap: 8px;
  padding: 8px 16px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
}
.main-chart-wrap {
  width: 100%;
}
.chart-container {
  position: relative;
  width: 100%;
  height: 360px;
}
.chart-watermark {
  position: absolute;
  top: 50%;
  left: 50%;
  transform: translate(-50%, -50%);
  font-size: 48px;
  font-weight: bold;
  color: rgba(0, 0, 0, 0.05);
  pointer-events: none;
  z-index: 1;
  white-space: nowrap;
}
.range-label {
  position: absolute;
  background: rgba(255,255,245,0.95);
  border: 1px solid #e0d8c0;
  border-radius: 6px;
  padding: 4px 8px;
  z-index: 10;
  pointer-events: none;
  white-space: nowrap;
  box-shadow: 0 1px 4px rgba(0,0,0,0.12);
}
.stock-info-line {
  padding: 6px 16px;
  font-size: 13px;
  color: #999;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
}
.fund-section {
  padding: 10px 16px;
  background: #fff;
  border-bottom: 1px solid #f0f0f0;
  font-size: 13px;
}
.fund-loading, .fund-error {
  color: #999;
  text-align: center;
  padding: 8px;
}
.fund-content {
  display: flex;
  flex-wrap: wrap;
}
.fund-row {
  width: 50%;
  padding: 3px 0;
}
.fund-label {
  color: #999;
  margin-right: 4px;
}
.fund-value {
  color: #333;
  font-weight: 500;
}
.indicator-bar {
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid #f0f0f0;
  border-bottom: 1px solid #f0f0f0;
  display: flex;
  flex-wrap: wrap;
  align-items: center;
  gap: 4px;
}
.ma-setting {
  display: inline-flex;
  align-items: center;
  gap: 4px;
  margin-left: 8px;
}
.ma-label {
  font-size: 12px;
  color: #666;
  font-weight: 600;
}
.ma-input {
  width: 100px;
  height: 24px;
  border: 1px solid #ddd;
  border-radius: 12px;
  padding: 0 10px;
  font-size: 12px;
  outline: none;
  text-align: center;
}
.ma-input:focus {
  border-color: #667eea;
}
.cr-value {
  font-size: 12px;
  color: #ff6b81;
  font-weight: 700;
  margin-left: 6px;
}
.sub-charts-area {
  width: 100%;
  border-top: 1px solid #eee;
}
.sub-chart-item {
  position: relative;
  border-bottom: 1px solid #f0f0f0;
}
.sub-chart-label {
  position: absolute;
  top: 2px;
  left: 8px;
  font-size: 10px;
  color: #999;
  z-index: 10;
  pointer-events: none;
}
.sub-chart-canvas {
  width: 100%;
  height: 120px;
}
.action-bar {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
}
.btn-cached {
  border-color: #ff9999 !important;
  color: #cc3333 !important;
  background: #ffebeb !important;
}
.fav-disabled {
  opacity: 0.5;
  pointer-events: none;
}
.source-status {
  padding: 6px 16px;
  font-size: 11px;
  color: #999;
  text-align: center;
}

/* AI 分析结果区域 */
.ai-result {
  margin: 8px 16px;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  background: #fff;
  overflow: hidden;
}
.ai-result-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  padding: 10px 14px;
  background: linear-gradient(135deg, #667eea, #764ba2);
  color: #fff;
  font-size: 14px;
  font-weight: 600;
}
.ai-result-body {
  padding: 14px;
  font-size: 13px;
  line-height: 1.6;
}
.ai-signal {
  font-size: 16px;
  font-weight: 700;
  margin-bottom: 8px;
  padding: 6px 10px;
  border-radius: 6px;
  text-align: center;
}
.ai-signal.buy { background: #e8f5e9; color: #2e7d32; }
.ai-signal.watch { background: #fff8e1; color: #f57f17; }
.ai-signal.pass, .ai-signal.sell { background: #ffebee; color: #c62828; }
.ai-signal.hold { background: #e3f2fd; color: #1565c0; }
.ai-detail {
  margin: 4px 0;
  font-size: 13px;
}
.ai-reason {
  margin-top: 8px;
  padding: 8px 10px;
  background: #f5f5f5;
  border-radius: 6px;
  font-size: 13px;
  color: #555;
}

/* 流式进度显示 */
.ai-progress {
  text-align: center;
  padding: 16px 0;
}
.progress-item {
  font-size: 18px;
  margin-bottom: 8px;
}
.progress-status {
  font-size: 13px;
  color: #666;
  margin-bottom: 4px;
}
.progress-time {
  font-size: 11px;
  color: #999;
}
.progress-content {
  margin-top: 8px;
  padding: 8px 10px;
  background: #f8f8f8;
  border-radius: 6px;
  font-size: 12px;
  color: #444;
  line-height: 1.5;
  text-align: left;
  max-height: 150px;
  overflow-y: auto;
  border-left: 3px solid #667eea;
}

/* 累积流式日志样式 */
.ai-stream-log {
  max-height: 400px;
  overflow-y: auto;
}
.stream-start {
  padding: 8px;
  color: #999;
  font-size: 12px;
  text-align: center;
}
.stream-agent-card {
  margin: 6px 0;
  padding: 8px 10px;
  background: #fff;
  border: 1px solid #eee;
  border-radius: 6px;
  border-left: 3px solid #667eea;
}
.stream-agent-header {
  font-weight: 600;
  font-size: 14px;
  margin-bottom: 4px;
}
.stream-time {
  font-weight: 400;
  font-size: 11px;
  color: #999;
  margin-left: 8px;
}
.stream-agent-content {
  font-size: 12px;
  color: #444;
  line-height: 1.5;
  margin-top: 4px;
  padding: 6px 8px;
  background: #fafafa;
  border-radius: 4px;
  max-height: 120px;
  overflow-y: auto;
}
.stream-final {
  margin: 8px 0;
  padding: 12px;
  background: #f0f8ff;
  border: 1px solid #b3d8f0;
  border-radius: 8px;
}
.stream-final-header {
  font-weight: 700;
  font-size: 15px;
  margin-bottom: 8px;
  color: #1565c0;
}
.stream-error {
  padding: 8px;
  color: #c62828;
  text-align: center;
}

/* 三栏分析布局 */
.three-col-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.analysis-col {
  flex: 1;
  min-width: 200px;
  border-radius: 8px;
  padding: 10px;
  border: 1px solid #e0e0e0;
  max-height: 400px;
  overflow: hidden;
  display: flex;
  flex-direction: column;
}
.col-title {
  font-weight: 700;
  font-size: 14px;
  margin-bottom: 6px;
  padding-bottom: 4px;
  border-bottom: 1px solid rgba(0,0,0,0.1);
}
.col-content {
  font-size: 12px;
  line-height: 1.5;
  color: #333;
  overflow-y: auto;
  flex: 1;
  white-space: pre-wrap;
  word-break: break-word;
}
.col-empty {
  color: #999;
  font-size: 12px;
  text-align: center;
  padding: 20px;
}
.final-conclusion {
  margin-top: 12px;
  padding: 14px;
  background: #f0f8ff;
  border: 1px solid #b3d8f0;
  border-radius: 10px;
}
.conclusion-title {
  font-weight: 700;
  font-size: 16px;
  margin-bottom: 8px;
  color: #1565c0;
}

/* ====== Tushare 基本面详细样式 ====== */
.fund-content-detailed {
  padding: 4px 0;
}
.fund-block {
  margin-bottom: 10px;
}
.fund-block-title {
  font-size: 14px;
  font-weight: 700;
  color: #333;
  margin-bottom: 6px;
  padding: 5px 8px;
  background: #f8f9fa;
  border-left: 3px solid #667eea;
  border-radius: 0 4px 4px 0;
}
.fund-block-empty {
  text-align: center;
  color: #999;
  padding: 12px;
  font-size: 13px;
}
.num-pos { color: #ee0a24; }
.num-neg { color: #07c160; }

/* 公司信息网格 */
.company-grid {
  display: grid;
  grid-template-columns: repeat(2, 1fr);
  gap: 4px;
}
.company-item {
  background: #f8f9fa;
  border-radius: 6px;
  padding: 5px 8px;
}
.comp-label {
  display: block;
  font-size: 10px;
  color: #999;
}
.comp-val {
  display: block;
  font-size: 13px;
  font-weight: 600;
  color: #333;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.company-desc {
  grid-column: 1 / -1;
}

/* 行情趋势分析 */
.pa-summary {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 4px;
}
.pa-stat {
  background: #f8f9fa;
  border-radius: 6px;
  padding: 5px 6px;
  text-align: center;
}
.pa-label {
  display: block;
  font-size: 10px;
  color: #999;
}
.pa-val {
  display: block;
  font-size: 14px;
  font-weight: 700;
  color: #333;
}

/* 升级提示 */
.upgrade-tip {
  padding: 10px;
  background: #fffbe6;
  border: 1px solid #ffe58f;
  border-radius: 6px;
  font-size: 12px;
  color: #ad8b00;
  line-height: 1.6;
}
</style>
