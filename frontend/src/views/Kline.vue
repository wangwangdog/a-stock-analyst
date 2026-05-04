<template>
  <div class="kline-page">
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

    <!-- 股票代码+名称 -->
    <div class="stock-info-line">{{ symbol }}  {{ stockName || '' }}</div>

    <!-- 子图区域：MACD, 大单买入, 大单比例 -->
    <div class="sub-charts-area">
      <!-- MACD 子图 -->
      <div class="sub-chart-item">
        <div class="sub-chart-label">MACD</div>
        <div class="sub-chart-canvas" ref="macdChartRef" id="macd-chart"></div>
      </div>

      <!-- 大单买入量 子图（仅日线显示） -->
      <div class="sub-chart-item" v-show="showBigBuy">
        <div class="sub-chart-label">大单买入</div>
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

const indicators = ref([
  { key: 'ma', label: 'MA', active: true },
  { key: 'macd', label: 'MACD', active: false },

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
    },
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

  // 柱顶标注大笔买数（仅在有数据的位置显示）
  const nonZero = bbData.filter(d => d.value > 0)
  if (nonZero.length && typeof bigbuyHistogram.setMarkers === 'function') {
    const markers = nonZero.map((d, i) => ({
      time: d.time,
      position: 'aboveBar',
      color: '#1890ff',
      shape: 'arrowUp',
      text: String(bbMap[klineData.value[bbData.indexOf(d)].date.slice(0, 10)]?.count || ''),
    }))
    bigbuyHistogram.setMarkers(markers)
  }
}

// ====== 大单比例子图（仅日线 - 与大单买入同构） ======
function renderRatioChart(lw, times) {
  if (!ratioChartRef.value || !bigbuyData.value.length || !klineData.value.length) return
  const { createChart, ColorType, HistogramSeries } = lw

  // 完全复制大单买入的图表配置
  ratioChart = createChart(ratioChartRef.value, {
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
      visible: true,
    },
    timeScale: {
      borderColor: '#e0e0e0',
      timeVisible: true,
      secondsVisible: false,
    },
    width: chartRef.value?.clientWidth || 360,
    height: 120,
  })

  // 完全复制大单买入的 series 配置
  ratioHistogram = ratioChart.addSeries(HistogramSeries, {
    color: 'rgba(255, 165, 0, 0.7)',
    priceFormat: { type: 'volume', precision: 0 },
    lastValueVisible: false,
  })

  // 大单数据映射：date -> data
  const bbMap = {}
  bigbuyData.value.forEach(d => { bbMap[d.date.slice(0, 10)] = d })

  // 与大单买入完全相同的日期构建方式，仅修改 value 计算
  const ratioData = klineData.value.map((d, i) => {
    const date = d.date.slice(0, 10)
    const match = bbMap[date]
    const klineAmount = d.amount || 0
    const rawRatio = (match && klineAmount > 0) ? (match.amount / klineAmount) : 0
    return {
      time: times[i],
      rawRatio,
    }
  })

  // 归一化
  const maxRatio = Math.max(0.001, ...ratioData.map(r => r.rawRatio))

  const chartData = ratioData.map(r => ({
    time: r.time,
    value: r.rawRatio / maxRatio,
    color: r.rawRatio > 0 ? 'rgba(255, 165, 0, 0.7)' : 'rgba(255, 165, 0, 0.05)',
  }))

  if (chartData.length) ratioHistogram.setData(chartData)

  // 柱顶标注（与大单买入相同的 markers 写法）
  const nonZero = chartData.filter(d => d.value > 0)
  if (nonZero.length && typeof ratioHistogram.setMarkers === 'function') {
    const markers = nonZero.map(d => ({
      time: d.time,
      position: 'aboveBar',
      color: '#ff8c00',
      shape: 'arrowUp',
      text: String(((bbMap[String(d.time)]?.amount || 0) / (klineData.value.find(k => k.date.slice(0,10) === d.time)?.amount || 1) * 100).toFixed(1) + '%'),
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
