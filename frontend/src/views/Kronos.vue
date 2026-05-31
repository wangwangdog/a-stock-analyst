<template>
  <div class="kronos-page">
    <van-nav-bar title="Kronos AI 预测" fixed placeholder />
    
    <!-- 参数配置区 -->
    <van-cell-group title="预测参数" class="param-group">
      <van-field
        v-model="lookback"
        label="历史窗口"
        type="number"
        placeholder="200"
        :rules="[{ pattern: /^[1-9][0-9]*$/, message: '请输入有效数字' }]"
      />
      <van-field
        v-model="predLen"
        label="预测长度"
        type="number"
        placeholder="20"
        :rules="[{ pattern: /^[1-9][0-9]*$/, message: '请输入有效数字' }]"
      />
      <van-field
        v-model="temperature"
        label="温度 (T)"
        type="number"
        placeholder="1.0"
        min="0.1"
        max="2.0"
        step="0.1"
      />
      <van-field
        v-model="sampleCount"
        label="采样数"
        type="number"
        placeholder="1"
        min="1"
        max="10"
        hint=">1 时计算置信度区间"
      />
      <van-cell title="模型">
        <template #right-icon>
          <van-select-group v-model="modelSelect" shape="square" @change="onModelChange">
            <van-option value="kronos-mini" name="kronos-mini">Mini (4.1M)</van-option>
            <van-option value="kronos-small" name="kronos-small" checked>Small (24.7M)</van-option>
            <van-option value="kronos-base" name="kronos-base">Base (102.3M)</van-option>
          </van-select-group>
        </template>
      </van-cell>
      <van-cell center>
        <template #title>
          <van-button type="primary" block round @click="runPrediction" :loading="loading">
            {{ loading ? '预测中...' : '立即预测' }}
          </van-button>
        </template>
      </van-cell>
    </van-cell-group>

    <!-- 提示信息 -->
    <van-cell-group v-if="!hasPredicted" title="使用说明">
      <van-field label="提示" is-link>
        <template #left-icon>
          <van-icon name="info-o" />
        </template>
        <div style="font-size: 12px; color: #666; line-height: 1.6;">
          <p>1. Kronos 是首个开源金融 K 线基础模型（27.7k stars）</p>
          <p>2. 基于 Transformer 架构，在 45+ 全球交易所数据上预训练</p>
          <p>3. 预测结果仅供参考，不构成投资建议</p>
          <p>4. 历史窗口建议 200-512，预测长度建议 10-50</p>
        </div>
      </van-field>
    </van-cell-group>

    <!-- 图表区 -->
    <div v-if="hasPredicted" class="chart-section">
      <van-cell-group title="K 线预测图">
        <div ref="chartContainer" class="chart-container"></div>
        <van-button plain type="primary" size="small" @click="zoomOut" style="margin-top: 10px;">
          重置缩放
        </van-button>
      </van-cell-group>
    </div>

    <!-- 预测结果表格 -->
    <div v-if="predictionData && predictionData.length > 0">
      <van-cell-group title="预测结果（前 20 个交易日）">
        <van-table :data="predictionData.slice(0, 20)" style="font-size: 12px;">
          <van-table-column field="date" title="日期" width="80" />
          <van-table-column field="open" title="开" width="60" />
          <van-table-column field="high" title="高" width="60" />
          <van-table-column field="low" title="低" width="60" />
          <van-table-column field="close" title="收" width="60" />
          <van-table-column field="pct" title="涨跌幅%" width="70" />
        </van-table>
      </van-cell-group>
    </div>

    <!-- 统计信息 -->
    <div v-if="hasPredicted && stats">
      <van-cell-group title="统计信息">
        <van-row>
          <van-col span="12">
            <van-cell title="预测起点" :value="stats.startPrice.toFixed(2)" />
          </van-col>
          <van-col span="12">
            <van-cell title="预测终点" :value="stats.endPrice.toFixed(2)" />
          </van-col>
          <van-col span="12">
            <van-cell title="预测涨幅" :value="`${stats.changePct.toFixed(2)}%`">
              <template #label>
                <van-tag :type="stats.changePct > 0 ? 'success' : 'danger'">
                  {{ stats.changePct > 0 ? '↑' : '↓' }}
                </van-tag>
              </template>
            </van-cell>
          </van-col>
          <van-col span="12">
            <van-cell title="最高价" :value="stats.highPrice.toFixed(2)" />
          </van-col>
          <van-col span="12">
            <van-cell title="最低价" :value="stats.lowPrice.toFixed(2)" />
          </van-col>
          <van-col span="12">
            <van-cell title="模型" :value="modelInfo" />
          </van-col>
        </van-row>
      </van-cell-group>
    </div>

    <!-- 底部占位 -->
    <div style="height: 60px;"></div>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick } from 'vue'
import { createChart, CandlestickSeries, CrosshairMode } from 'lightweight-charts'

// 当前股票代码（从 URL 或全局状态获取）
const currentSymbol = ref('000001') // 默认平安银行

// 参数
const lookback = ref('200')
const predLen = ref('20')
const temperature = ref('1.0')
const sampleCount = ref('1')
const modelSelect = ref('kronos-small')
const loading = ref(false)
const hasPredicted = ref(false)

// 数据
const historicalData = ref([])
const predictionData = ref([])
const stats = ref(null)
const modelInfo = ref('')

// 图表
let chart = null
let candleSeries = null
let predSeries = null

// 模型描述
const modelDesc = {
  'kronos-mini': '轻量级 (4.1M 参数，2048 上下文)',
  'kronos-small': '推荐 (24.7M 参数，512 上下文)',
  'kronos-base': '高精度 (102.3M 参数，512 上下文)'
}

const onModelChange = (val) => {
  modelInfo.value = modelDesc[val]
}

const runPrediction = async () => {
  if (!lookback.value || !predLen.value) {
    alert('请填写完整参数')
    return
  }

  loading.value = true
  
  try {
    const resp = await fetch('/api/v1/kronos/predict', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        symbol: currentSymbol.value,
        lookback: parseInt(lookback.value),
        pred_len: parseInt(predLen.value),
        model: modelSelect.value,
        T: parseFloat(temperature.value),
        top_p: 0.9,
        sample_count: parseInt(sampleCount.value)
      })
    })

    const data = await resp.json()
    
    if (data.code === 0) {
      historicalData.value = data.historical
      predictionData.value = data.prediction
      
      // 计算统计信息
      if (predictionData.value.length > 0 && historicalData.value.length > 0) {
        const startPrice = historicalData.value[historicalData.value.length - 1]?.close || 0
        const endPrice = predictionData.value[predictionData.value.length - 1]?.close || 0
        const changePct = ((endPrice - startPrice) / startPrice) * 100
        
        const closes = predictionData.value.map(d => d.close)
        stats.value = {
          startPrice,
          endPrice,
          changePct,
          highPrice: Math.max(...closes),
          lowPrice: Math.min(...closes)
        }
      }
      
      modelInfo.value = modelDesc[modelSelect.value]
      hasPredicted.value = true
      
      // 绘制图表
      await nextTick()
      drawChart()
      
      alert('预测完成')
    } else {
      throw new Error(data.message || '预测失败')
    }
  } catch (err) {
    alert(err.message || '网络错误')
  } finally {
    loading.value = false
  }
}

const drawChart = () => {
  const container = document.getElementById('chartContainer')
  if (!container || !historicalData.value.length) return

  // 销毁旧图表
  if (chart) {
    chart.remove()
  }

  // 创建新图表
  chart = createChart(container, {
    width: container.clientWidth,
    height: 400,
    layout: {
      background: { color: '#100c2a' },
      textColor: '#d1d4dc',
    },
    grid: {
      vertLines: { color: 'rgba(255, 255, 255, 0.1)' },
      horzLines: { color: 'rgba(255, 255, 255, 0.1)' },
    },
    crosshair: {
      mode: CrosshairMode.Normal,
    },
    rightPriceScale: {
      borderColor: 'rgba(197, 203, 206, 0.8)',
    },
    timeScale: {
      borderColor: 'rgba(197, 203, 206, 0.8)',
      timeVisible: true,
    },
  })

  // 历史 K 线系列（实线）
  candleSeries = chart.addCandlestickSeries({
    upColor: '#26a69a',
    downColor: '#ef5350',
    borderVisible: false,
    wickUpColor: '#26a69a',
    wickDownColor: '#ef5350',
  })

  // 预测 K 线系列（虚线/半透明）
  predSeries = chart.addCandlestickSeries({
    upColor: '#4bc0c0',
    downColor: '#f64e60',
    borderVisible: true,
    borderUpColor: '#4bc0c0',
    borderDownColor: '#f64e60',
    borderColor: '#ffffff',
    wickUpColor: '#4bc0c0',
    wickDownColor: '#f64e60',
    priceLineVisible: false,
  })

  // 准备历史数据
  const histCandles = historicalData.value.map(d => ({
    time: new Date(d.trade_date).getTime() / 1000,
    open: d.open,
    high: d.high,
    low: d.low,
    close: d.close
  }))

  // 准备预测数据（使用未来时间戳）
  const lastDate = new Date(historicalData.value[historicalData.value.length - 1]?.trade_date)
  const predCandles = predictionData.value.map((d, idx) => {
    // 模拟未来日期（交易日）
    const futureDate = new Date(lastDate)
    futureDate.setDate(lastDate.getDate() + (idx + 1) * 1.5) // 近似交易日
    
    return {
      time: futureDate.getTime() / 1000,
      open: d.open,
      high: d.high,
      low: d.low,
      close: d.close
    }
  })

  candleSeries.setData(histCandles)
  predSeries.setData(predCandles)

  // 自动缩放
  chart.timeScale().fitContent()
}

const zoomOut = () => {
  if (chart) {
    chart.timeScale().fitContent()
  }
}

// 监听窗口大小变化
let resizeObserver = null
onMounted(() => {
  onModelChange(modelSelect.value)
  
  // 尝试从 URL 获取股票代码
  const urlParams = new URLSearchParams(window.location.search)
  const symbol = urlParams.get('symbol')
  if (symbol) {
    currentSymbol.value = symbol
  }
  
  // 监听窗口大小
  resizeObserver = new ResizeObserver(() => {
    if (chart) {
      chart.resize(document.getElementById('chartContainer').clientWidth, 400)
    }
  })
  
  nextTick(() => {
    const container = document.getElementById('chartContainer')
    if (container) {
      resizeObserver.observe(container)
    }
  })
})
</script>

<style scoped>
.kronos-page {
  padding-top: 46px;
  background: #000;
  min-height: 100vh;
  color: #fff;
}

.param-group {
  margin: 16px;
}

.chart-section {
  margin: 16px;
}

.chart-container {
  width: 100%;
  height: 400px;
  border: 1px solid #333;
  border-radius: 8px;
  overflow: hidden;
}

.van-cell-group__title {
  color: #888;
  font-size: 13px;
}

.van-field__label {
  color: #888;
}

.van-field__control:disabled {
  color: #666;
}

/* 表格样式优化 */
:deep(.van-table) {
  font-size: 12px !important;
}

:deep(.van-table th) {
  background: #1a1a1a !important;
  color: #fff !important;
}

:deep(.van-table td) {
  background: #000 !important;
  color: #ddd !important;
  border-bottom: 1px solid #333 !important;
}

:deep(.van-table tr:hover td) {
  background: #1a1a1a !important;
}
</style>
