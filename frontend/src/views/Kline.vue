<template>
  <div class="kline-split">
    <!-- 左侧：大笔买入排名 -->
    <div class="left-sidebar">
      <div class="sidebar-header">📊 大笔买入排名</div>
      <div class="sidebar-list">
        <div
          v-for="(item, idx) in bigBuyRank"
          :key="item.symbol"
          class="sidebar-item"
          :class="{ active: activeStock === item.symbol }"
          @click="switchStock(item.symbol)"
        >
          <span class="rank-num">{{ idx + 1 }}</span>
          <span class="rank-name">{{ item.name || item.symbol }}</span>
          <span class="rank-code">{{ item.symbol }}</span>
          <span class="rank-days">{{ item.days }}天</span>
        </div>
        <div v-if="!bigBuyRank.length" class="sidebar-empty">暂无数据</div>
      </div>
    </div>

    <!-- 右侧：K线内容 -->
    <div class="right-kline">
    <van-nav-bar
      :title="(route.params.symbol || props.symbol) + '  ' + stockName"
      left-arrow
      @click-left="$router.back()"
    >
      <template #right>
        <van-icon name="more-o" @click="showMenu" />
      </template>
    </van-nav-bar>

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
      </div>
    </div>

    <!-- 技术指标选择 + 基本面 -->
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
    </div>

    <!-- 股票代码+名称 -->
    <div class="stock-info-line">{{ symbol }}  {{ stockName || '' }}</div>

    <!-- 基本面信息（内联） -->
    <div class="fund-section" v-if="showFundamentals">
      <div v-if="fundLoading" class="fund-loading">加载中...</div>
      <div v-else-if="fundError" class="fund-error">{{ fundError }}</div>
      <div v-else class="fund-content">
        <div v-for="(v, k) in fundData" :key="k" class="fund-row">
          <span class="fund-label">{{ k }}:</span>
          <span class="fund-value">{{ v }}</span>
        </div>
      </div>
    </div>

    <!-- 子图区域：MACD, 大单买入, 大单比例 -->
    <div class="sub-charts-area">
      <!-- MACD 子图 -->
      <div class="sub-chart-item">
        <div class="sub-chart-label">MACD</div>
        <div class="sub-chart-canvas" ref="macdChartRef" id="macd-chart"></div>
      </div>

      <!-- 大单买入总额 子图（仅日线显示） -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">大单买入总额</div>
        <div class="sub-chart-canvas" ref="bigbuyChartRef" id="bigbuy-chart"></div>
      </div>
      <!-- 大单比例 子图（仅日线显示） -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">大单比例</div>
        <div class="sub-chart-canvas" ref="ratioChartRef" id="ratio-chart"></div>
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
  </div>
</div>
</template>

<script setup>
import { ref, computed, onMounted, nextTick, watch } from 'vue'
import { useRoute } from 'vue-router'
import { showToast } from 'vant'
import { getKline, getBigBuy } from '../utils/api.js'

const props = defineProps({ symbol: { type: String, default: '000001' } })
const route = useRoute()

const chartRef = ref(null)
const macdChartRef = ref(null)

const bigbuyChartRef = ref(null)
const ratioChartRef = ref(null)

const period = ref('daily')
const periods = [
  { key: 'daily', label: '日K' },
  { key: 'weekly', label: '周K' },
  { key: 'monthly', label: '月K' },
  { key: '60min', label: '60分' },
  { key: '30min', label: '30分' },
  { key: '15min', label: '15分' },
]

// 左侧大单排名
const bigBuyRank = ref([])
// 左侧选中股票与路由同步
const activeStock = ref(route.params.symbol || props.symbol)

// 监听路由变化同步高亮
watch(() => route.params.symbol, (newSym) => {
  if (newSym) activeStock.value = newSym
})

async function loadBigBuyRank() {
  try {
    const resp = await fetch('/api/v1/bigbuy-rank')
    bigBuyRank.value = await resp.json()
  } catch {}
}

function switchStock(symbol) {
  const sym = route.params.symbol || props.symbol
  if (symbol === sym) return
  window.location.hash = '#/kline/' + symbol
}

// 基本面内联显示
const showFundamentals = ref(false)
const fundLoading = ref(false)
const fundData = ref({})
const fundError = ref('')

async function toggleFundamentals() {
  showFundamentals.value = !showFundamentals.value
  if (!showFundamentals.value) return
  if (Object.keys(fundData.value).length > 0) return  // 已有数据不重复加载
  
  fundLoading.value = true
  fundError.value = ''
  try {
    const resp = await fetch('/api/v1/fundamentals/' + (route.params.symbol || props.symbol))
    const data = await resp.json()
    if (data && data.data) {
      fundData.value = data.data
    } else if (data && data.message) {
      fundData.value = { '信息': data.message }
    } else {
      fundData.value = data
    }
  } catch (e) {
    fundError.value = '获取基本面失败'
  } finally {
    fundLoading.value = false
  }
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

// 图表实例
let mainChart = null
let candleSeries = null
let volSeries = null
let maLines = []

// 子图实例
let macdChart = null
let bigbuyChart = null
let ratioChart = null

let macdHistogram = null
let macdLine = null
let signalLine = null
let bigbuyHistogram = null
let ratioHistogram = null

// lw模块缓存
let lwModuleCache = null

watch(() => route.params.symbol, (newSym) => {
  if (newSym) {
    aiResult.value = { title: '', text: '' }
    loadData()
    checkAnalysisCache()
  }
})

onMounted(() => {
  loadData()
  loadFavorites()
  loadBigBuyRank()
  checkAnalysisCache()
})

async function loadData() {
  showToast({ message: '加载中...', type: 'loading', duration: 0 })
  try {
    const res = await getKline(route.params.symbol || props.symbol, {
      period: period.value,
      start_date: getStartDate(period.value),
      end_date: getEndDate(),
      indicators: true,
    })
    const data = res.data
    klineData.value = data.data || []
    indData.value = data.indicators || {}
    dataSource.value = data.source
    stockName.value = data.name || ''

    // 统计校验失败
    if (data.validation) {
      validationFailed.value = data.validation.filter(v => !v.passed).length
    }

    // 最新价格
    if (data.data && data.data.length > 0) {
      const last = data.data[data.data.length - 1]
      const prev = data.data.length > 1 ? data.data[data.data.length - 2] : last
      priceData.value = {
        ...last,
        pct: prev.close ? ((last.close - prev.close) / prev.close * 100) : 0
      }
    }

    // 加载大单数据（仅日线）
    if (showBigBuy.value) {
      try {
        const bbRes = await getBigBuy(route.params.symbol || props.symbol, 60)
        bigbuyData.value = bbRes.data.data || []
      } catch (e) {
        bigbuyData.value = []
      }
    } else {
      bigbuyData.value = []
    }

    await nextTick()
    renderAllCharts()
    showToast.clear()
  } catch (e) {
    console.error('❌ loadData 失败:', e, e.message)
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
  if (period === 'daily') startY = y - 1
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
    const lw = LW.default || LW
    lwModuleCache = lw

    // 销毁旧图表
    destroyAllCharts()

    // 计算统一的时间数据
    const times = klineData.value.map(d => makeTime(d))

    // 主K线图
    renderMainChart(lw, times)
    // MACD子图
    renderMacdChart(lw, times)
    // 大单买入量子图
    if (showBigBuy.value) {
      renderBigbuyChart(lw, times)
    }
    // 大单比例子图
    if (showBigBuy.value) {
      renderRatioChart(lw, times)
    }

    // 初始对齐时间轴
    setupTimeScaleSync()
  })
}

function destroyAllCharts() {
  if (mainChart) { mainChart.remove(); mainChart = null }
  if (macdChart) { macdChart.remove(); macdChart = null }
  if (bigbuyChart) { bigbuyChart.remove(); bigbuyChart = null }
  if (ratioChart) { ratioChart.remove(); ratioChart = null }
  candleSeries = null
  volSeries = null
  maLines = []
  macdHistogram = null
  macdLine = null
  signalLine = null
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
    downColor: '#07c160',
    borderUpColor: '#ee0a24',
    borderDownColor: '#07c160',
    wickUpColor: '#ee0a24',
    wickDownColor: '#07c160',
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
    color: d.close >= d.open ? 'rgba(238,10,36,0.3)' : 'rgba(7,193,96,0.3)',
  }))
  volSeries.setData(volumes)

  // 均线（默认显示）
  renderMainIndicators(lw)
}

// ====== MACD 子图 ======
function renderMacdChart(lw, times) {
  if (!macdChartRef.value) return
  const { createChart, ColorType, HistogramSeries, LineSeries } = lw

  macdChart = createChart(macdChartRef.value, {
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
    width: chartRef.value?.clientWidth || 360,
    height: 120,
  })

  const macdInd = indData.value?.macd
  if (!macdInd) return

  // MACD 柱状图（从后端 MACD 字段取）
  macdHistogram = macdChart.addSeries(HistogramSeries, {
    priceFormat: { type: 'price' },
  })
  const histData = macdInd.MACD?.map((v, i) => ({
    time: times[i],
    value: v,
    color: v >= 0 ? 'rgba(238,10,36,0.5)' : 'rgba(7,193,96,0.5)',
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (histData.length) macdHistogram.setData(histData)

  // DIF 线（快线，蓝色）
  macdLine = macdChart.addSeries(LineSeries, {
    color: '#1890ff',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: { type: 'price' },
  })
  const difData = macdInd.DIF?.map((v, i) => ({
    time: times[i],
    value: v,
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (difData.length) macdLine.setData(difData)

  // DEA 线（慢线，橙色）
  signalLine = macdChart.addSeries(LineSeries, {
    color: '#fa8c16',
    lineWidth: 1,
    lastValueVisible: false,
    priceLineVisible: false,
    priceFormat: { type: 'price' },
  })
  const deaData = macdInd.DEA?.map((v, i) => ({
    time: times[i],
    value: v,
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (deaData.length) signalLine.setData(deaData)
}



// ====== 大单买入量子图（仅日线） ======
function renderBigbuyChart(lw, times) {
  if (!bigbuyChartRef.value || !bigbuyData.value.length) return
  const { createChart, ColorType, HistogramSeries } = lw

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
    width: chartRef.value?.clientWidth || 360,
    height: 120,
  })

  bigbuyHistogram = bigbuyChart.addSeries(HistogramSeries, {
    color: '#1890ff',
    priceFormat: { type: 'volume', precision: 0 },
    lastValueVisible: false,
  })

  // 构建完整的日期序列，与 K 线时间轴对齐
  // 用 klineData 的所有日期为基础，大单数据有则填、无则 0
  const bbMap = {}
  bigbuyData.value.forEach(d => { bbMap[d.date.slice(0, 10)] = d })

  const bbData = klineData.value.map((d, i) => {
    const date = d.date.slice(0, 10)
    const match = bbMap[date]
    return {
      time: times[i],
      value: match ? (match.amount || 0) : 0,
      color: match ? 'rgba(24,144,255,0.7)' : 'rgba(24,144,255,0.05)',
    }
  })

  if (bbData.length) bigbuyHistogram.setData(bbData)

  // 柱顶标注大笔买数
  try {
    const markers = []
    klineData.value.forEach((kd, i) => {
      const date = kd.date.slice(0, 10)
      const match = bbMap[date]
      if (match && match.count > 0) {
        markers.push({
          time: times[i],
          position: 'aboveBar',
          color: '#e74c3c',
          shape: 'arrowUp',
          text: String(match.count),
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

// ====== 大单比例子图（仅日线 - 与大单买入同构） ======
function renderRatioChart(lw, times) {
  if (!ratioChartRef.value || !bigbuyData.value.length || !klineData.value.length) return
  const { createChart, ColorType, HistogramSeries } = lw

  // 完全复制大单买入的图表配置
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
      visible: true,
    },
    timeScale: {
      borderColor: '#e8e0c8',
      timeVisible: true,
      secondsVisible: false,
    },
    handleScroll: false,
    handleScale: false,
    width: chartRef.value?.clientWidth || 360,
    height: 120,
  })

  // 完全复制大单买入的 series 配置，只换颜色（橙色）
  ratioHistogram = ratioChart.addSeries(HistogramSeries, {
    color: 'rgba(255, 165, 0, 0.7)',
    priceFormat: { type: 'price', precision: 1, suffix: '%' },
    lastValueVisible: false,
  })

  // 大单数据映射
  const bbMap = {}
  bigbuyData.value.forEach(d => { bbMap[d.date.slice(0, 10)] = d })

  // 与大单买入相同的结构，数据改为：合计金额/当日成交额，归一化
  let maxRatio = 0
  const rawData = klineData.value.map((d, i) => {
    const date = d.date.slice(0, 10)
    const match = bbMap[date]
    const klineAmount = d.amount || 0
    const ratio = (match && klineAmount > 0) ? (match.amount / klineAmount) : 0
    if (ratio > maxRatio) maxRatio = ratio
    return { time: times[i], ratio, count: match?.count || 0 }
  })
  if (maxRatio === 0) maxRatio = 1

  const chartData = rawData.map(r => ({
    time: r.time,
    value: (r.ratio / maxRatio) * 100,
    color: r.ratio > 0 ? 'rgba(255, 165, 0, 0.7)' : 'rgba(255, 165, 0, 0.05)',
  }))

  if (chartData.length) ratioHistogram.setData(chartData)

  // 柱顶标注百分比
  const nonZero = rawData.filter(r => r.ratio > 0)
  if (nonZero.length && typeof ratioHistogram.setMarkers === 'function') {
    const markers = nonZero.map(r => ({
      time: r.time,
      position: 'aboveBar',
      color: '#ff8c00',
      shape: 'arrowUp',
      text: (r.ratio * 100).toFixed(1) + '%',
    }))
    ratioHistogram.setMarkers(markers)
  }
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
    const periods = [5, 10, 20, 60]
    const colors = ['#f7931a', '#1890ff', '#52c41a', '#722ed1']
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

  // ═══ 画出最近7日最低到最高点的连线(斜线) ═══
  if (klineData.value.length >= 3) {
    const last7 = klineData.value.slice(-7)
    let highest = -Infinity
    let lowest = Infinity
    let highTime = null
    let lowTime = null
    last7.forEach(d => {
      const h = d.high || d.最高 || 0
      const l = d.low || d.最低 || 0
      const t = makeTime(d)
      if (h > highest) { highest = h; highTime = t }
      if (l < lowest) { lowest = l; lowTime = t }
    })
    
    if (highTime && lowTime && highest > -Infinity && lowest < Infinity && highTime !== lowTime) {
      // 确保时间按先后顺序
      const t1 = highTime < lowTime ? highTime : lowTime
      const v1 = highTime < lowTime ? highest : lowest
      const t2 = highTime > lowTime ? highTime : lowTime
      const v2 = highTime > lowTime ? highest : lowest

      const diagLine = mainChart.addSeries(LineSeries, {
        color: '#000000',
        lineWidth: 2,
        lineStyle: 0,  // 实线
        lastValueVisible: true,
        priceLineVisible: false,
        crosshairMarkerVisible: true,
      })
      diagLine.setData([
        { time: t1, value: v1 },
        { time: t2, value: v2 },
      ])
      maLines.push(diagLine)
    }
  }
}

// ====== 时间轴联动 ======
function setupTimeScaleSync() {
  const allCharts = [mainChart, macdChart]
  if (bigbuyChart) allCharts.push(bigbuyChart)
  if (ratioChart) allCharts.push(ratioChart)

  // 获取所有 chart 的完整时间范围（以主图为准）
  const times = klineData.value.map(d => makeTime(d))
  const timeFrom = times[0]
  const timeTo = times[times.length - 1]

  // 使用绝对时间值 setVisibleRange 强制对齐
  allCharts.forEach(c => {
    if (!c) return
    try {
      c.timeScale().setVisibleRange({ from: timeFrom, to: timeTo })
    } catch(e) {}
  })

  // 订阅可见范围变化，联动所有子图
  allCharts.forEach((sourceChart, sourceIdx) => {
    if (!sourceChart) return
    let syncing = false

    sourceChart.timeScale().subscribeVisibleLogicalRangeChange((range) => {
      if (syncing || !range) return
      syncing = true

      try {
        allCharts.forEach((targetChart, targetIdx) => {
          if (targetIdx === sourceIdx || !targetChart) return
          targetChart.timeScale().setVisibleLogicalRange(range)
        })
      } catch (e) {
        // ignore
      }

      requestAnimationFrame(() => { syncing = false })
    })

  })
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
}
.left-sidebar {
  width: 180px;
  min-width: 180px;
  background: #f5f7fa;
  border-right: 1px solid #e0e0e0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  padding: 12px 10px;
  font-weight: 700;
  font-size: 14px;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  position: sticky;
  top: 0;
  z-index: 1;
}
.sidebar-list {
  flex: 1;
  overflow-y: auto;
}
.sidebar-item {
  display: flex;
  align-items: center;
  padding: 8px 10px;
  border-bottom: 1px solid #eee;
  cursor: pointer;
  transition: background 0.15s;
  gap: 4px;
}
.sidebar-item:hover { background: #e8f0fe; }
.sidebar-item.active { background: #d0e3ff; }
.rank-num {
  width: 20px;
  font-size: 11px;
  color: #999;
  text-align: right;
  margin-right: 4px;
}
.rank-name {
  flex: 1;
  font-size: 13px;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.rank-code {
  font-size: 11px;
  color: #999;
}
.rank-days {
  font-size: 11px;
  color: #e74c3c;
  font-weight: 600;
}
.sidebar-empty {
  padding: 20px;
  text-align: center;
  color: #999;
  font-size: 13px;
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
</style>
