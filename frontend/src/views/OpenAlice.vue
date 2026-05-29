<template>
  <div class="openalice-container">
    <div class="header">
      <h2>🤖 OpenAlice AI 分析平台</h2>
      <div class="status-badge" :class="{ 'online': isOnline, 'offline': !isOnline }">
        {{ isOnline ? '● 在线' : '○ 离线' }}
      </div>
    </div>

    <!-- 控制区 -->
    <div class="control-panel">
      <div class="input-group">
        <input
          v-model="stockCode"
          type="text"
          placeholder="输入股票代码 (如：600519)"
          maxlength="10"
          @keyup.enter="runAnalysis"
        />
        <input
          v-model="stockName"
          type="text"
          placeholder="股票名称 (可选)"
          maxlength="20"
        />
      </div>
      
      <div class="action-buttons">
        <button 
          @click="runAnalysis" 
          :disabled="isLoading"
          class="btn-primary"
        >
          {{ isLoading ? '🚀 分析中...' : '🚀 深度分析' }}
        </button>
        <button 
          @click="runHealthcheck" 
          :disabled="!hasHoldings"
          class="btn-warning"
        >
          ⚠️ 持仓检查
        </button>
        <button 
          @click="fetchMarketSummary" 
          class="btn-info"
        >
          📰 市场摘要
        </button>
      </div>
    </div>

    <!-- 持仓输入区（可选） -->
    <div v-if="showHoldings" class="holdings-section">
      <h4>持仓输入（用于健康检查）</h4>
      <div class="holdings-input">
        <textarea
          v-model="holdingsText"
          placeholder="格式：600519,100,12.50\n000858,500,18.00\n(code,quantity,cost)"
          rows="4"
        ></textarea>
        <button @click="parseHoldings">解析持仓</button>
      </div>
    </div>

    <!-- 分析结果区 -->
    <div class="result-section">
      <div v-if="isLoading" class="loading-content">
        <div class="spinner"></div>
        <p>🤖 OpenAlice 正在深度分析中...</p>
        <p class="hint">首次分析可能需要 10-30 秒（AI 思考时间）</p>
      </div>

      <div v-else-if="error" class="error-content">
        <div class="alert alert-danger">❌ {{ error }}</div>
        <button @click="clearError" class="btn-secondary">重试</button>
      </div>

      <div v-else-if="result" class="analysis-result">
        <!-- 核心结论 -->
        <div class="card conclusion-card">
          <h3>📊 核心结论</h3>
          <div class="signal-badge" :class="recommendationClass">
            {{ result.data?.recommendation || 'HOLD' }}
          </div>
          <div class="confidence">
            置信度：{{ result.data?.confidence || '-' }}/100
          </div>
          <p class="reasoning">{{ result.data?.reasoning || result.data?.summary || '' }}</p>
        </div>

        <!-- 详细分析 -->
        <div class="card detail-card">
          <h3>📖 详细分析</h3>
          <div class="tabs">
            <button 
              v-for="tab in tabs" 
              :key="tab.key"
              :class="{ active: currentTab === tab.key }"
              @click="currentTab = tab.key"
            >
              {{ tab.label }}
            </button>
          </div>
          
          <div class="tab-content">
            <div v-html="formatMarkdown(currentTabContent)" class="markdown-body"></div>
          </div>
        </div>

        <!-- 风险因素 -->
        <div v-if="result.data?.analysis?.risk_factors && result.data.analysis.risk_factors.length > 0" 
             class="card risk-card">
          <h3>⚠️ 风险因素</h3>
          <ul>
            <li v-for="(risk, idx) in result.data.analysis.risk_factors" :key="idx">
              {{ risk }}
            </li>
          </ul>
        </div>

        <!-- 价格目标 -->
        <div v-if="result.data?.price_target" class="card target-card">
          <h3>🎯 价格目标</h3>
          <div class="targets">
            <div class="target support">
              <span>支撑位</span>
              <strong>{{ result.data.price_target.support || '-' }}</strong>
            </div>
            <div class="target resistance">
              <span>阻力位</span>
              <strong>{{ result.data.price_target.resistance || '-' }}</strong>
            </div>
          </div>
        </div>
      </div>

      <div v-else class="empty-state">
        <p>👈 输入股票代码，点击「深度分析」开始</p>
        <p class="hint">支持 A 股全部品种：主板、创业板、科创板、北交所</p>
      </div>
    </div>

    <!-- OpenAlice 原始界面（可选 iframe） -->
    <div v-if="showIframe" class="iframe-section">
      <h4>OpenAlice 原始界面（实验性）</h4>
      <iframe
        :src="openaliceUrl"
        class="openalice-iframe"
        sandbox="allow-scripts allow-same-origin"
      ></iframe>
    </div>
  </div>
</template>

<script setup>
import { ref, computed } from 'vue'

// 状态
const stockCode = ref('')
const stockName = ref('')
const isLoading = ref(false)
const error = ref('')
const result = ref(null)
const isOnline = ref(false)
const showHoldings = ref(false)
const holdingsText = ref('')
const holdings = ref([])
const hasHoldings = computed(() => holdings.value.length > 0)
const showIframe = ref(false)
const openaliceUrl = ref('http://localhost:47331')

// Tabs
const tabs = [
  { key: 'fundamental', label: '基本面' },
  { key: 'technical', label: '技术面' },
  { key: 'capital', label: '资金面' },
  { key: 'summary', label: '摘要' }
]
const currentTab = ref('fundamental')

const currentTabContent = computed(() => {
  const analysis = result.value?.data?.analysis || {}
  const map = {
    fundamental: analysis.fundamental || analysis.fundamentals_report || '暂无数据',
    technical: analysis.technical || analysis.technicals || '暂无数据',
    capital: analysis.capital_flow || analysis.capital || '暂无数据',
    summary: analysis.summary || result.value?.data?.reasoning || '暂无数据'
  }
  return map[currentTab.value] || '暂无数据'
})

const recommendationClass = computed(() => {
  const rec = result.value?.data?.recommendation || 'HOLD'
  if (rec === 'BUY') return 'signal-buy'
  if (rec === 'SELL') return 'signal-sell'
  return 'signal-hold'
})

// 检查服务状态
const checkStatus = async () => {
  try {
    const res = await fetch('/api/openalice/status')
    const data = await res.json()
    isOnline.value = data.success
    if (!data.success && data.message) {
      error.value = data.message
    }
  } catch (e) {
    isOnline.value = false
  }
}

// 深度分析
const runAnalysis = async () => {
  if (!stockCode.value || !/^[0-9]{6}$/.test(stockCode.value)) {
    error.value = '请输入有效的 6 位股票代码'
    return
  }

  isLoading.value = true
  error.value = ''
  result.value = null

  try {
    const res = await fetch('/api/openalice/analyze', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        stock_code: stockCode.value,
        stock_name: stockName.value,
        analysis_type: 'full',
        language: 'zh'
      })
    })

    const data = await res.json()

    if (data.success) {
      result.value = data
    } else {
      error.value = data.error || data.message || '分析失败'
    }
  } catch (e) {
    error.value = `请求失败：${e.message}`
  } finally {
    isLoading.value = false
  }
}

// 持仓检查
const parseHoldings = () => {
  try {
    const lines = holdingsText.value.split('\n').filter(l => l.trim())
    holdings.value = lines.map(line => {
      const parts = line.split(/[,,]/).map(s => s.trim())
      return {
        code: parts[0],
        qty: parseInt(parts[1]) || 0,
        cost: parseFloat(parts[2]) || 0
      }
    }).filter(h => h.code)
    hasHoldings.value = holdings.value.length > 0
  } catch (e) {
    alert('持仓格式错误')
  }
}

const runHealthcheck = async () => {
  if (!hasHoldings.value) return

  isLoading.value = true
  try {
    const res = await fetch('/api/openalice/portfolio/healthcheck', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ holdings: holdings.value })
    })
    const data = await res.json()
    if (data.success) {
      alert('持仓分析：' + data.data.analysis)
    } else {
      alert('检查失败：' + data.error)
    }
  } catch (e) {
    alert('请求失败')
  } finally {
    isLoading.value = false
  }
}

// 市场摘要
const fetchMarketSummary = async () => {
  try {
    const res = await fetch('/api/openalice/market/summary')
    const data = await res.json()
    if (data.success) {
      alert('📰 市场摘要：' + data.data.summary)
    }
  } catch (e) {
    alert('获取失败')
  }
}

// 工具函数
const clearError = () => {
  error.value = ''
  result.value = null
}

const formatMarkdown = (text) => {
  // 简单 Markdown 转 HTML（实际项目中可用 marked.js）
  if (!text) return ''
  return text
    .replace(/\n/g, '<br>')
    .replace(/\*\*(.*?)\*\*/g, '<strong>$1</strong>')
    .replace(/\*(.*?)\*/g, '<em>$1</em>')
}

// 初始化
checkStatus()
</script>

<style scoped>
.openalice-container {
  max-width: 1200px;
  margin: 0 auto;
  padding: 20px;
  font-family: 'PingFang SC', 'Microsoft YaHei', sans-serif;
}

.header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 20px;
  padding-bottom: 10px;
  border-bottom: 2px solid #e0e0e0;
}

.header h2 {
  margin: 0;
  font-size: 24px;
  color: #333;
}

.status-badge {
  padding: 5px 10px;
  border-radius: 12px;
  font-size: 12px;
  background: #f0f0f0;
}

.status-badge.online {
  background: #d4edda;
  color: #155724;
}

.status-badge.offline {
  background: #f8d7da;
  color: #721c24;
}

.control-panel {
  background: #f8f9fa;
  padding: 20px;
  border-radius: 8px;
  margin-bottom: 20px;
}

.input-group {
  display: flex;
  gap: 10px;
  margin-bottom: 15px;
}

.input-group input {
  flex: 1;
  padding: 10px 15px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-size: 14px;
}

.input-group input:focus {
  outline: none;
  border-color: #007bff;
}

.action-buttons {
  display: flex;
  gap: 10px;
}

.action-buttons button {
  padding: 10px 20px;
  border: none;
  border-radius: 4px;
  cursor: pointer;
  font-size: 14px;
  font-weight: 500;
  transition: all 0.2s;
}

.btn-primary {
  background: #007bff;
  color: white;
}

.btn-primary:hover:not(:disabled) {
  background: #0056b3;
}

.btn-primary:disabled {
  background: #6c757d;
  cursor: not-allowed;
}

.btn-warning {
  background: #ffc107;
  color: #212529;
}

.btn-warning:hover:not(:disabled) {
  background: #e0a800;
}

.btn-info {
  background: #17a2b8;
  color: white;
}

.btn-info:hover {
  background: #138496;
}

.holdings-section {
  margin-bottom: 20px;
  padding: 15px;
  background: #fff;
  border: 1px solid #ddd;
  border-radius: 8px;
}

.holdings-input {
  margin-top: 10px;
}

.holdings-input textarea {
  width: 100%;
  padding: 10px;
  border: 1px solid #ddd;
  border-radius: 4px;
  font-family: monospace;
  resize: vertical;
}

.holdings-input button {
  margin-top: 10px;
  padding: 8px 16px;
  background: #6c757d;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.result-section {
  min-height: 400px;
}

.loading-content {
  text-align: center;
  padding: 60px 20px;
  color: #666;
}

.spinner {
  width: 40px;
  height: 40px;
  border: 4px solid #f3f3f3;
  border-top: 4px solid #007bff;
  border-radius: 50%;
  animation: spin 1s linear infinite;
  margin: 0 auto 20px;
}

@keyframes spin {
  0% { transform: rotate(0deg); }
  100% { transform: rotate(360deg); }
}

.error-content {
  padding: 20px;
  text-align: center;
}

.alert {
  padding: 15px;
  border-radius: 4px;
  margin-bottom: 15px;
}

.alert-danger {
  background: #f8d7da;
  color: #721c24;
  border: 1px solid #f5c6cb;
}

.btn-secondary {
  padding: 8px 16px;
  background: #6c757d;
  color: white;
  border: none;
  border-radius: 4px;
  cursor: pointer;
}

.analysis-result {
  display: grid;
  gap: 20px;
}

.card {
  background: white;
  border: 1px solid #e0e0e0;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 4px rgba(0,0,0,0.05);
}

.card h3 {
  margin: 0 0 15px;
  font-size: 16px;
  color: #333;
  border-bottom: 1px solid #eee;
  padding-bottom: 10px;
}

.conclusion-card {
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  color: white;
}

.conclusion-card h3 {
  color: white;
  border-bottom-color: rgba(255,255,255,0.3);
}

.signal-badge {
  display: inline-block;
  padding: 8px 20px;
  border-radius: 20px;
  font-size: 18px;
  font-weight: bold;
  margin: 10px 0;
}

.signal-buy {
  background: #28a745;
  color: white;
}

.signal-sell {
  background: #dc3545;
  color: white;
}

.signal-hold {
  background: #ffc107;
  color: #212529;
}

.confidence {
  font-size: 14px;
  opacity: 0.9;
  margin-bottom: 10px;
}

.reasoning {
  font-size: 14px;
  line-height: 1.6;
  margin: 0;
}

.detail-card .tabs {
  display: flex;
  gap: 5px;
  margin-bottom: 15px;
}

.detail-card .tabs button {
  padding: 8px 16px;
  border: none;
  background: #f0f0f0;
  cursor: pointer;
  border-radius: 4px 4px 0 0;
  font-size: 13px;
}

.detail-card .tabs button.active {
  background: #007bff;
  color: white;
}

.tab-content {
  background: #f8f9fa;
  padding: 15px;
  border-radius: 0 4px 4px 4px;
  min-height: 150px;
}

.markdown-body {
  line-height: 1.6;
  font-size: 14px;
}

.risk-card {
  border-left: 4px solid #dc3545;
}

.risk-card ul {
  margin: 0;
  padding-left: 20px;
}

.risk-card li {
  margin-bottom: 8px;
  color: #721c24;
}

.target-card {
  border-left: 4px solid #17a2b8;
}

.targets {
  display: flex;
  gap: 20px;
}

.target {
  flex: 1;
  padding: 15px;
  background: #f8f9fa;
  border-radius: 8px;
  text-align: center;
}

.target span {
  display: block;
  font-size: 12px;
  color: #666;
  margin-bottom: 5px;
}

.target strong {
  display: block;
  font-size: 20px;
  color: #333;
}

.target.support strong {
  color: #28a745;
}

.target.resistance strong {
  color: #dc3545;
}

.empty-state {
  text-align: center;
  padding: 60px 20px;
  color: #999;
  background: #f8f9fa;
  border-radius: 8px;
}

.hint {
  font-size: 12px;
  color: #999;
  margin-top: 10px;
}

.iframe-section {
  margin-top: 30px;
  padding-top: 20px;
  border-top: 2px solid #e0e0e0;
}

.openalice-iframe {
  width: 100%;
  height: 600px;
  border: 1px solid #ddd;
  border-radius: 8px;
  background: #f5f5f5;
}
</style>
