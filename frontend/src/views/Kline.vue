<template>
  <div class="kline-page">
    <van-nav-bar
      :title="stockName || symbol"
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
      <div class="chart-container" ref="chartRef"></div>
    </div>

    <!-- 技术指标选择 -->
    <div class="indicator-bar">
      <van-tag
        v-for="ind in indicators"
        :key="ind.key"
        :type="ind.active ? 'primary' : 'default'"
        plain round
        style="margin: 2px 4px"
        @click="toggleIndicator(ind)"
      >{{ ind.label }}</van-tag>
    </div>

    <!-- 子图区域：MACD, RSI, 大单买入量 -->
    <div class="sub-charts-area">
      <!-- MACD 子图 -->
      <div class="sub-chart-item">
        <div class="sub-chart-label">MACD</div>
        <div class="sub-chart-canvas" ref="macdChartRef" id="macd-chart"></div>
      </div>
      <!-- RSI 子图 -->
      <div class="sub-chart-item">
        <div class="sub-chart-label">RSI</div>
        <div class="sub-chart-canvas" ref="rsiChartRef" id="rsi-chart"></div>
      </div>
      <!-- 大单买入量 子图（仅日线显示） -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">大单买入</div>
        <div class="sub-chart-canvas" ref="bigbuyChartRef" id="bigbuy-chart"></div>
      </div>
    </div>

    <!-- 操作按钮 -->
    <div class="action-bar">
      <van-button icon="info-o" size="small" plain @click="$router.push('/fund/' + symbol)">基本面</van-button>
      <template v-if="isFav">
        <van-button icon="star" size="small" plain disabled class="fav-disabled">已自选</van-button>
      </template>
      <template v-else>
        <van-button icon="star-o" size="small" plain @click="addFavorite">加自选</van-button>
      </template>
    </div>

    <!-- 数据源状态 -->
    <div class="source-status" v-if="dataSource">
      <span>数据源: {{ dataSource }}</span>
      <span v-if="validationFailed > 0" style="color: #ee0a24; margin-left: 8px">
        ⚠ {{ validationFailed }}天数据不一致
      </span>
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
const rsiChartRef = ref(null)
const bigbuyChartRef = ref(null)

const period = ref('daily')
const periods = [
  { key: 'daily', label: '日K' },
  { key: 'weekly', label: '周K' },
  { key: 'monthly', label: '月K' },
  { key: '60min', label: '60分' },
  { key: '30min', label: '30分' },
  { key: '15min', label: '15分' },
]

const indicators = ref([
  { key: 'ma', label: 'MA', active: true },
  { key: 'macd', label: 'MACD', active: false },
  { key: 'rsi', label: 'RSI', active: false },
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

// 自选股
const favorites = ref(JSON.parse(localStorage.getItem('stock_favorites') || '[]'))
const isFav = computed(() => {
  const sym = route.params.symbol || props.symbol
  return favorites.value.includes(sym)
})

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
let rsiChart = null
let bigbuyChart = null

let macdHistogram = null
let macdLine = null
let signalLine = null
let rsiLine = null
let bigbuyHistogram = null

// lw模块缓存
let lwModuleCache = null

watch(() => route.params.symbol, (newSym) => {
  if (newSym) loadData()
})

onMounted(() => {
  loadData()
})

function addFavorite() {
  const sym = route.params.symbol || props.symbol
  if (favorites.value.includes(sym)) {
    showToast('已在自选中')
    return
  }
  favorites.value.push(sym)
  localStorage.setItem('stock_favorites', JSON.stringify(favorites.value))
  showToast('已添加自选')
}

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
    stockName.value = data.symbol

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

    // 主K线图
    renderMainChart(lw)
    // MACD子图
    renderMacdChart(lw)
    // RSI子图
    renderRsiChart(lw)
    // 大单买入量子图
    if (showBigBuy.value) {
      renderBigbuyChart(lw)
    }

    // crosshair 联动
    setupCrosshairSync()
    // 初始对齐时间轴
    setTimeout(syncTimeScales, 100)
  })
}

function destroyAllCharts() {
  if (mainChart) { mainChart.remove(); mainChart = null }
  if (macdChart) { macdChart.remove(); macdChart = null }
  if (rsiChart) { rsiChart.remove(); rsiChart = null }
  if (bigbuyChart) { bigbuyChart.remove(); bigbuyChart = null }
  candleSeries = null
  volSeries = null
  maLines = []
  macdHistogram = null
  macdLine = null
  signalLine = null
  rsiLine = null
  bigbuyHistogram = null
}

// ====== 主K线图 ======
function renderMainChart(lw) {
  const { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries } = lw

  mainChart = createChart(chartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#fff' },
      textColor: '#333',
    },
    grid: {
      vertLines: { color: '#f0f0f0' },
      horzLines: { color: '#f0f0f0' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e0e0e0',
    },
    timeScale: {
      borderColor: '#e0e0e0',
      timeVisible: true,
      secondsVisible: false,
    },
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

  const isIntraday = ['15min', '30min', '60min'].includes(period.value)
  const candles = klineData.value.map(d => ({
    time: makeTime(d),
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

  const volumes = klineData.value.map(d => ({
    time: makeTime(d),
    value: d.volume || 0,
    color: d.close >= d.open ? 'rgba(238,10,36,0.3)' : 'rgba(7,193,96,0.3)',
  }))
  volSeries.setData(volumes)

  // 均线（默认显示）
  renderMainIndicators(lw)
}

// ====== MACD 子图 ======
function renderMacdChart(lw) {
  if (!macdChartRef.value) return
  const { createChart, ColorType, HistogramSeries, LineSeries } = lw

  macdChart = createChart(macdChartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#fff' },
      textColor: '#666',
    },
    grid: {
      vertLines: { color: '#f5f5f5' },
      horzLines: { color: '#f5f5f5' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e0e0e0',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: '#e0e0e0',
      timeVisible: true,
      secondsVisible: false,
      visible: false, // 隐藏时间轴
    },
    width: chartRef.value?.clientWidth || 360,
    height: 120,
  })

  const macdInd = indData.value?.macd
  if (!macdInd) return

  const isIntraday = ['15min', '30min', '60min'].includes(period.value)
  const times = klineData.value.map(d => makeTime(d))

  // MACD 柱状图
  macdHistogram = macdChart.addSeries(HistogramSeries, {
    priceFormat: { type: 'price' },
  })
  const histData = macdInd.HISTOGRAM?.map((v, i) => ({
    time: times[i],
    value: v,
    color: v >= 0 ? 'rgba(238,10,36,0.5)' : 'rgba(7,193,96,0.5)',
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (histData.length) macdHistogram.setData(histData)

  // MACD 线
  macdLine = macdChart.addSeries(LineSeries, {
    color: '#1890ff',
    lineWidth: 1,
    lastValueVisible: false,
    priceFormat: { type: 'price' },
  })
  const macdLineData = macdInd.MACD?.map((v, i) => ({
    time: times[i],
    value: v,
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (macdLineData.length) macdLine.setData(macdLineData)

  // SIGNAL 线
  signalLine = macdChart.addSeries(LineSeries, {
    color: '#fa8c16',
    lineWidth: 1,
    lastValueVisible: false,
    priceFormat: { type: 'price' },
  })
  const signalData = macdInd.SIGNAL?.map((v, i) => ({
    time: times[i],
    value: v,
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (signalData.length) signalLine.setData(signalData)
}

// ====== RSI 子图 ======
function renderRsiChart(lw) {
  if (!rsiChartRef.value) return
  const { createChart, ColorType, LineSeries } = lw

  rsiChart = createChart(rsiChartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#fff' },
      textColor: '#666',
    },
    grid: {
      vertLines: { color: '#f5f5f5' },
      horzLines: { color: '#f5f5f5' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e0e0e0',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: '#e0e0e0',
      timeVisible: true,
      secondsVisible: false,
      visible: false,
    },
    width: chartRef.value?.clientWidth || 360,
    height: 120,
  })

  const rsiInd = indData.value?.rsi
  if (!rsiInd) return

  const times = klineData.value.map(d => makeTime(d))

  // 70 上界参考线
  const upperLine = rsiChart.addSeries(LineSeries, {
    color: 'rgba(238,10,36,0.3)',
    lineWidth: 1,
    lastValueVisible: false,
    priceFormat: { type: 'price' },
  })
  upperLine.setData(times.map(t => ({ time: t, value: 70 })))

  // 30 下界参考线
  const lowerLine = rsiChart.addSeries(LineSeries, {
    color: 'rgba(7,193,96,0.3)',
    lineWidth: 1,
    lastValueVisible: false,
    priceFormat: { type: 'price' },
  })
  lowerLine.setData(times.map(t => ({ time: t, value: 30 })))

  // RSI 线
  rsiLine = rsiChart.addSeries(LineSeries, {
    color: '#a05dff',
    lineWidth: 2,
    lastValueVisible: false,
    priceFormat: { type: 'price' },
  })
  const rsiData = rsiInd.RSI?.map((v, i) => ({
    time: times[i],
    value: v,
  })).filter(d => d.value !== null && !isNaN(d.value)) || []
  if (rsiData.length) rsiLine.setData(rsiData)
}

// ====== 大单买入量子图（仅日线） ======
function renderBigbuyChart(lw) {
  if (!bigbuyChartRef.value || !bigbuyData.value.length) return
  const { createChart, ColorType, HistogramSeries } = lw

  bigbuyChart = createChart(bigbuyChartRef.value, {
    layout: {
      background: { type: ColorType.Solid, color: '#fff' },
      textColor: '#666',
    },
    grid: {
      vertLines: { color: '#f5f5f5' },
      horzLines: { color: '#f5f5f5' },
    },
    crosshair: { mode: 0 },
    rightPriceScale: {
      borderColor: '#e0e0e0',
      scaleMargins: { top: 0.1, bottom: 0.1 },
    },
    timeScale: {
      borderColor: '#e0e0e0',
      timeVisible: true,
      secondsVisible: false,
      visible: false,
    },
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

  const bbData = klineData.value.map(d => {
    const date = d.date.slice(0, 10)
    const match = bbMap[date]
    return {
      time: date,
      value: match ? (match.amount || 0) : 0,
      color: match ? 'rgba(24,144,255,0.7)' : 'rgba(24,144,255,0.05)',
    }
  })

  if (bbData.length) bigbuyHistogram.setData(bbData)

  // 柱顶标注大笔买数（仅在有数据的位置显示）
  const nonZero = bbData.filter(d => d.value > 0)
  if (nonZero.length && typeof bigbuyHistogram.setMarkers === 'function') {
    const markers = nonZero.map(d => ({
      time: d.time,
      position: 'aboveBar',
      color: '#1890ff',
      shape: 'arrowUp',
      text: String(bbMap[d.time]?.count || ''),
    }))
    bigbuyHistogram.setMarkers(markers)
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
        lineStyle: 2,
      })
      line.setData(klineData.value.map((d, i) => ({
        time: makeTime(d),
        value: boll.BOLL_UP[i],
      })).filter(d => d.value))
      maLines.push(line)

      const line2 = mainChart.addSeries(LineSeries, {
        color: '#fa8c16',
        lineWidth: 1,
        lineStyle: 2,
      })
      line2.setData(klineData.value.map((d, i) => ({
        time: makeTime(d),
        value: boll.BOLL_DN[i],
      })).filter(d => d.value))
      maLines.push(line2)
    }
  }
}

// ====== crosshair 联动 ======
function setupCrosshairSync() {
  const allCharts = [mainChart, macdChart, rsiChart]
  if (bigbuyChart) allCharts.push(bigbuyChart)

  // 用 setVisibleLogicalRange 同步时间轴
  allCharts.forEach((sourceChart, sourceIdx) => {
    if (!sourceChart) return
    let syncing = false

    sourceChart.subscribeCrosshairMove((param) => {
      if (syncing || !param.time) return
      syncing = true

      try {
        // 当鼠标离开图表区域时 param.point 为 null
        if (param.point) {
          // 将主图的时间轴范围同步到子图
          const logicalRange = sourceChart.timeScale().getVisibleLogicalRange()

          allCharts.forEach((targetChart, targetIdx) => {
            if (targetIdx === sourceIdx || !targetChart) return
            if (logicalRange) {
              targetChart.timeScale().setVisibleLogicalRange(logicalRange)
            }
          })
        }
      } catch (e) {
        // ignore
      }

      // requestAnimationFrame 防止递归
      requestAnimationFrame(() => { syncing = false })
    })
  })
}

// 初始对齐所有图表时间轴（主图 -> 子图）
function syncTimeScales() {
  if (!mainChart) return
  const range = mainChart.timeScale().getVisibleLogicalRange()
  if (!range) return
  const charts = [macdChart, rsiChart, bigbuyChart].filter(Boolean)
  charts.forEach(c => {
    try { c.timeScale().setVisibleLogicalRange(range) } catch(e) {}
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
.kline-page {
  background: #fff;
  min-height: 100vh;
  padding-bottom: 70px;
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
  width: 100%;
  height: 360px;
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
</style>
