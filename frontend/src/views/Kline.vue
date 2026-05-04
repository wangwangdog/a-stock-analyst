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

    <!-- K线图 -->
    <div class="chart-container" ref="chartRef"></div>

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

    <!-- 操作按钮 -->
    <div class="action-bar">
      <van-button icon="info-o" size="small" plain @click="$router.push('/fund/' + symbol)">基本面</van-button>
      <van-button icon="star-o" size="small" plain @click="addFavorite">加自选</van-button>
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
import { getKline } from '../utils/api.js'

const props = defineProps({ symbol: { type: String, default: '000001' } })
const route = useRoute()

const chartRef = ref(null)
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

const changeColor = computed(() => {
  if (!priceData.value) return '#666'
  return priceData.value.pct >= 0 ? '#ee0a24' : '#07c160'
})

let chart = null
let candleSeries = null
let volSeries = null
let maLines = []

watch(() => route.params.symbol, (newSym) => {
  if (newSym) loadData()
})

onMounted(() => loadData())

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

    await nextTick()
    renderChart()
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
  
  // 分钟级只取最近30天
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

function renderChart() {
  if (!chartRef.value || !klineData.value.length) return

  // 导入 lightweight-charts
  import('lightweight-charts').then(LW => {
    const lw = LW.default || LW
    const { createChart, ColorType, CandlestickSeries, HistogramSeries, LineSeries } = lw

    if (chart) chart.remove()
    chart = createChart(chartRef.value, {
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
    candleSeries = chart.addSeries(CandlestickSeries, {
      upColor: '#ee0a24',
      downColor: '#07c160',
      borderUpColor: '#ee0a24',
      borderDownColor: '#07c160',
      wickUpColor: '#ee0a24',
      wickDownColor: '#07c160',
    })

    const isIntraday = ['15min', '30min', '60min'].includes(period.value)
    const candles = klineData.value.map(d => {
      let time
      if (isIntraday) {
        // 分钟级：将 "2026-04-20 09:45:00" 转为 UNIX 秒级时间戳 (UTC)
        const dt = new Date(d.date.replace(' ', 'T') + '+08:00')
        time = Math.floor(dt.getTime() / 1000)
      } else {
        time = d.date.slice(0, 10) // "2026-04-20"
      }
      return { time, open: d.open, high: d.high, low: d.low, close: d.close }
    })
    candleSeries.setData(candles)

    // 成交量
    volSeries = chart.addSeries(HistogramSeries, {
      priceFormat: { type: 'volume' },
      priceScaleId: 'volume',
    })
    chart.priceScale('volume').applyOptions({
      scaleMargins: { top: 0.8, bottom: 0 },
    })

    const volumes = klineData.value.map(d => {
      let time
      if (isIntraday) {
        const dt = new Date(d.date.replace(' ', 'T') + '+08:00')
        time = Math.floor(dt.getTime() / 1000)
      } else {
        time = d.date.slice(0, 10)
      }
      return {
        time,
        value: d.volume || 0,
        color: d.close >= d.open ? 'rgba(238,10,36,0.3)' : 'rgba(7,193,96,0.3)',
      }
    })
    volSeries.setData(volumes)

    // 均线
    renderIndicators(lw)
  })
}

function renderIndicators(lwModule) {
  if (!chart || !indData.value) return

  // 清除旧均线
  maLines.forEach(l => chart.removeSeries(l))
  maLines = []

  const lw = lwModule
  const { LineSeries } = lw
  const active = indicators.value.filter(i => i.active)
  const ind = indData.value

  const isIntraday = ['15min', '30min', '60min'].includes(period.value)

  if (active.find(i => i.key === 'ma') && ind.ma) {
    const periods = [5, 10, 20, 60]
    const colors = ['#f7931a', '#1890ff', '#52c41a', '#722ed1']
    periods.forEach((p, idx) => {
      const key = `MA${p}`
      if (ind.ma[key] && ind.ma[key].length) {
        const line = chart.addSeries(LineSeries, {
          color: colors[idx],
          lineWidth: 1,
          lastValueVisible: false,
          priceFormat: { type: 'price' },
        })
        const data = klineData.value.map((d, i) => {
          let time
          if (isIntraday) {
            const dt = new Date(d.date.replace(' ', 'T') + '+08:00')
            time = Math.floor(dt.getTime() / 1000)
          } else {
            time = d.date.slice(0, 10)
          }
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
    const makeTime = (d) => {
      if (isIntraday) {
        const dt = new Date(d.date.replace(' ', 'T') + '+08:00')
        return Math.floor(dt.getTime() / 1000)
      }
      return d.date.slice(0, 10)
    }
    if (boll.BOLL_UP && boll.BOLL_UP.length) {
      const line = chart.addSeries(LineSeries, {
        color: '#fa8c16',
        lineWidth: 1,
        lineStyle: 2,
      })
      line.setData(klineData.value.map((d, i) => ({
        time: makeTime(d),
        value: boll.BOLL_UP[i],
      })).filter(d => d.value))
      maLines.push(line)

      const line2 = chart.addSeries(LineSeries, {
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

function toggleIndicator(ind) {
  ind.active = !ind.active
  renderIndicators()
}

function addFavorite() {
  showToast('已添加自选')
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
.chart-container {
  width: 100%;
  height: 360px;
}
.indicator-bar {
  padding: 8px 12px;
  background: #fff;
  border-top: 1px solid #f0f0f0;
  display: flex;
  flex-wrap: wrap;
}
.action-bar {
  display: flex;
  gap: 12px;
  padding: 12px 16px;
}
.source-status {
  padding: 6px 16px;
  font-size: 11px;
  color: #999;
  text-align: center;
}
</style>
