<template>
  <div class="home-split">
    <!-- 左侧：大单排名 -->
    <div class="left-sidebar">
      <div class="sidebar-header">
        <span :class="['tab-btn', {active: filterDays === 'all'}]"
              @click="setFilter('all')">全量</span>
        <span :class="['tab-btn', {active: filterDays === '5'}]"
              @click="setFilter('5')">近5/1</span>
        <span :class="['tab-btn', {active: filterDays === '10'}]"
              @click="setFilter('10')">近10/1</span>
      </div>
      <div class="sidebar-list">
        <div
          v-for="(item, idx) in bigBuyRank"
          :key="item.symbol"
          class="sidebar-item"
          :class="{ active: activeStock === item.symbol }"
          @click="selectStock(item)"
        >
          <span class="rank-num">{{ idx + 1 }}</span>
          <span class="rank-name">{{ item.name || item.symbol }}</span>
          <span class="rank-code">{{ item.symbol }}</span>
          <span class="rank-days">{{ item.days }}天</span>
        </div>
        <div v-if="!bigBuyRank.length" class="sidebar-empty">暂无数据</div>
      </div>
    </div>

    <!-- 中间：消息列表 + 搜索 -->
    <div class="msg-center">
      <van-nav-bar title="AI 量化工具-DOGE" left-text="消息">
        <template #right>
          <span style="font-size:12px;color:#999;margin-right:8px" v-if="username">{{ username }}</span>
          <van-icon name="logout" @click="doLogout" style="padding:4px" />
        </template>
      </van-nav-bar>
      
      <div class="search-box">
        <van-search
          v-model="keyword"
          placeholder="搜索股票/产品/行业..."
          @search="onSearch"
          @clear="onClear"
        />
      </div>

      <!-- 搜索结果 -->
      <div v-if="searchResults.length" class="search-results">
        <van-cell-group title="搜索结果">
          <van-cell
            v-for="s in searchResults"
            :key="(s.type||'stock') + '_' + (s.code||s.name)"
            :title="s.name"
            :label="s.code || s.type"
            is-link
            @click="goSearchResult(s)"
          >
            <template #icon>
              <van-tag 
                round plain 
                :type="s.type === 'industry' ? 'warning' : s.type === 'product' ? 'success' : 'primary'"
                style="margin-right:8px"
              >{{ s.type === 'company' ? s.code : s.type }}</van-tag>
            </template>
          </van-cell>
        </van-cell-group>
      </div>

      <!-- 消息列表 -->
      <div class="message-list" v-if="!searchResults.length">
        <div class="section-title">
          <span>📰 智能消息</span>
          <span class="refresh-btn" @click="loadMessages">刷新</span>
        </div>
        
        <van-loading v-if="msgLoading" style="padding:20px;text-align:center" />
        
        <van-empty v-if="!msgLoading && !messages.length" description="暂无消息" />
        
        <div
          v-for="msg in messages"
          :key="msg.id"
          class="msg-card"
          @click="onMsgClick(msg)"
        >
          <div class="msg-header">
            <van-tag 
              :type="msg.type === 'big_deal' ? 'danger' : 'primary'" 
              size="small"
              plain
            >{{ msg.type === 'big_deal' ? '大单' : '系统' }}</van-tag>
            <span class="msg-date">{{ msg.date }}</span>
          </div>
          <div class="msg-title">{{ msg.title }}</div>
          <div class="msg-summary">{{ msg.summary }}</div>
          <div class="msg-action" v-if="msg.action === 'view_chain'">
            <van-button size="small" type="primary" plain>查看产业链 →</van-button>
          </div>
        </div>

        <!-- 快捷入口 -->
        <div class="quick-links">
          <van-grid :column-num="4" :border="false" icon-size="24">
            <van-grid-item icon="chart-trending-o" text="K线" @click="$router.push('/kline/000001')" />
            <van-grid-item icon="cluster-o" text="产业链" @click="openChainSearch" />
            <van-grid-item icon="gem-o" text="策略" @click="$router.push('/strategies')" />
            <van-grid-item icon="link-o" text="链接" @click="$router.push('/links')" />
          </van-grid>
        </div>
      </div>
    </div>

    <!-- 右侧：图谱弹层 -->
    <van-popup
      v-model:show="showChain"
      position="right"
      :style="{ width: '100%', height: '100%' }"
      closeable
      round
    >
      <div class="chain-view">
        <van-nav-bar 
          :title="chainTitle" 
          left-text="返回" 
          left-arrow 
          @click-left="showChain = false"
        />
        
        <van-loading v-if="chainLoading" style="padding:40px;text-align:center" />
        
        <div v-if="!chainLoading && chainData" class="chain-content">
          <!-- 公司信息 -->
          <van-cell-group title="公司信息">
            <van-cell :title="chainData.name" :label="chainData.code">
              <template #value>{{ chainData.fullname }}</template>
            </van-cell>
          </van-cell-group>
          
          <!-- 所属行业 -->
          <van-cell-group v-if="chainData.industries?.length" title="🏭 所属行业">
            <van-cell
              v-for="ind in chainData.industries" :key="ind.code"
              :title="ind.name"
              is-link
              @click="viewIndustry(ind.name)"
            />
          </van-cell-group>
          
          <!-- 主营产品 -->
          <van-cell-group v-if="chainData.main_products?.length" title="📦 主营产品">
            <van-cell
              v-for="(prod, i) in chainData.main_products.slice(0, 10)" :key="i"
              :title="prod.name"
              is-link
              @click="viewProduct(prod.name)"
            />
            <van-cell v-if="chainData.main_products.length > 10" 
              :title="`+${chainData.main_products.length - 10} 更多...`" />
          </van-cell-group>
          
          <!-- 上游原材料 -->
          <van-cell-group v-if="chainData.upstream?.length" title="⬆️ 上游原材料">
            <van-cell
              v-for="(up, i) in chainData.upstream.slice(0, 10)" :key="'up'+i"
              :title="up.material"
              :label="`用于生产: ${up.product}`"
            />
          </van-cell-group>
          
          <!-- 下游产品 -->
          <van-cell-group v-if="chainData.downstream?.length" title="⬇️ 下游应用">
            <van-cell
              v-for="(down, i) in chainData.downstream.slice(0, 10)" :key="'down'+i"
              :title="down.product"
              :label="`使用: ${down.uses}`"
            />
          </van-cell-group>
          
          <!-- 同行业 -->
          <van-cell-group v-if="chainData.peers?.length" title="👥 同行业公司">
            <van-cell
              v-for="p in chainData.peers.slice(0, 10)" :key="p.code"
              :title="p.name"
              :label="p.code"
              is-link
              @click="viewChain(p.code)"
            />
          </van-cell-group>
          
          <!-- 图谱可视化区域 -->
          <div v-if="chainData.graph?.nodes?.length" class="graph-section">
            <div class="section-title" style="padding:12px 16px;margin:0;background:#f7f8fa;border-top:1px solid #ebedf0">
              🗺️ 产业链图谱
            </div>
            <div ref="graphContainer" class="graph-container"></div>
          </div>
          
          <van-empty v-if="!chainData.industries?.length && !chainData.main_products?.length" 
            description="暂无产业链数据" />
        </div>
        
        <!-- 产业链搜索面板 -->
        <div v-if="chainSearchMode" class="chain-search-panel">
          <van-search
            v-model="chainSearchKey"
            placeholder="搜索公司/产品/行业..."
            @search="doChainSearch"
          />
          <div v-if="chainSearchResults.length" class="search-list">
            <van-cell
              v-for="r in chainSearchResults" :key="(r.type||'') + '_' + (r.code||r.name)"
              :title="r.name"
              :label="r.type === 'company' ? r.code : r.type"
              is-link
              @click="goSearchResult(r)"
            >
              <template #icon>
                <van-tag 
                  round plain size="small"
                  :type="r.type === 'company' ? 'primary' : r.type === 'product' ? 'success' : 'warning'"
                  style="margin-right:8px"
                >{{ r.type }}</van-tag>
              </template>
            </van-cell>
          </div>
        </div>
      </div>
    </van-popup>
  </div>
</template>

<script setup>
import { ref, onMounted, nextTick, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'

const router = useRouter()
const keyword = ref('')
const searchResults = ref([])
const loading = ref(false)
const allStocks = ref([])
const showFavorites = ref(false)
const favList = ref([])
const username = ref(localStorage.getItem('username') || '')

// 左侧大单排名
const bigBuyRank = ref([])
const activeStock = ref('')
const activeStockName = ref('')
const filterDays = ref('all')

// 消息列表
const messages = ref([])
const msgLoading = ref(false)

// 产业链图谱弹窗
const showChain = ref(false)
const chainTitle = ref('产业链图谱')
const chainData = ref(null)
const chainLoading = ref(false)
const chainSearchMode = ref(false)
const chainSearchKey = ref('')
const chainSearchResults = ref([])
const graphContainer = ref(null)

function getU() { return localStorage.getItem('username') || '' }

function selectStock(item) {
  router.push('/kline/' + item.symbol)
}

function setFilter(days) {
  filterDays.value = days
  loadBigBuyRank(days === 'all' ? '' : days)
}

async function loadBigBuyRank(days) {
  try {
    const resp = await fetch('/api/v1/bigbuy-rank' + (days ? '?days=' + days : ''))
    bigBuyRank.value = await resp.json()
  } catch {}
}

async function loadMessages() {
  msgLoading.value = true
  try {
    const resp = await fetch('/api/v1/messages?days=7')
    const data = await resp.json()
    messages.value = data.messages || []
  } catch (e) {
    messages.value = []
  } finally {
    msgLoading.value = false
  }
}

async function loadFavs() {
  const u = getU()
  if (!u) return
  try {
    const resp = await fetch('/api/v1/favorites?username=' + encodeURIComponent(u))
    favList.value = await resp.json()
  } catch {}
}

async function doLogout() {
  localStorage.removeItem('username')
  router.push('/login')
}

onMounted(async () => {
  loadFavs()
  loadBigBuyRank()
  loadMessages()
  
  try {
    const resp = await fetch('/api/v1/stocks')
    const data = await resp.json()
    if (data.status === 'ok') allStocks.value = data.data
  } catch (e) {}

  showGreeting()
})

function showGreeting() {
  const h = new Date().getHours()
  let msg = '晚上好 ☕'
  if (h < 6) msg = '还不睡？🌙'
  else if (h < 9) msg = '早上好 ☀️'
  else if (h < 12) msg = '上午好 📊'
  else if (h < 14) msg = '中午好 🥟'
  else if (h < 18) msg = '下午好 📈'
  showToast(msg)
}

function onSearch(val) {
  if (!val.trim()) return
  loading.value = true
  const q = val.trim().toLowerCase()
  
  searchResults.value = []
  
  // 本地股票搜索
  if (allStocks.value.length) {
    searchResults.value = allStocks.value.filter(s => {
      const code = (s.code || s.symbol || '').toLowerCase()
      const name = (s.name || '').toLowerCase()
      return code.includes(q) || name.includes(q)
    }).slice(0, 10).map(s => ({
      type: 'company',
      code: s.code || s.symbol,
      name: s.name,
    }))
  }
  
  // 同时搜索产业链
  fetch(`/api/v1/chain/search?q=${encodeURIComponent(q)}&limit=10`)
    .then(r => r.json())
    .then(d => {
      if (d.results?.length) {
        searchResults.value = [...searchResults.value, ...d.results]
      }
    })
    .finally(() => { loading.value = false })
}

function onClear() {
  searchResults.value = []
}

function goSearchResult(s) {
  if (s.type === 'company') {
    viewChain(s.code)
  } else if (s.type === 'product') {
    viewProduct(s.name)
  } else if (s.type === 'industry') {
    viewIndustry(s.name)
  }
}

// ===== 产业链图谱 =====

async function viewChain(code) {
  if (!code) return
  chainSearchMode.value = false
  showChain.value = true
  chainTitle.value = `${code} 产业链`
  chainLoading.value = true
  chainData.value = null
  
  try {
    const resp = await fetch(`/api/v1/chain/stock/${code}`)
    const data = await resp.json()
    chainData.value = data
    if (data.name) chainTitle.value = `${data.name}(${code}) 产业链图谱`
  } catch (e) {
    chainData.value = null
  } finally {
    chainLoading.value = false
    if (chainData.value?.graph) {
      await nextTick()
      renderGraph()
    }
  }
}

function viewIndustry(name) {
  chainSearchMode.value = false
  chainTitle.value = `行业: ${name}`
  chainLoading.value = true
  fetch(`/api/v1/chain/industry/${encodeURIComponent(name)}?limit=50`)
    .then(r => r.json())
    .then(d => {
      chainData.value = {
        name: d.industry,
        peers: d.companies || [],
        industries: [{ code: '', name: d.industry }],
      }
    })
    .finally(() => { chainLoading.value = false })
}

function viewProduct(name) {
  chainSearchMode.value = false
  chainTitle.value = `产品: ${name}`
  chainLoading.value = true
  fetch(`/api/v1/chain/product/${encodeURIComponent(name)}`)
    .then(r => r.json())
    .then(d => {
      chainData.value = {
        name: d.product,
        main_products: [{ name: d.product }],
        upstream: (d.upstream_materials || []).map(m => ({ material: m, product: d.product })),
        downstream: (d.downstream_users || []).map(u => ({ product: u, uses: d.product })),
        peers: (d.producers || []).map(p => ({ code: p.code, name: p.name, industry: '' })),
      }
    })
    .finally(() => { chainLoading.value = false })
}

function openChainSearch() {
  showChain.value = true
  chainSearchMode.value = true
  chainTitle.value = '产业链搜索'
  chainData.value = null
  chainSearchResults.value = []
  chainSearchKey.value = ''
}

function doChainSearch() {
  const q = chainSearchKey.value.trim()
  if (!q) return
  fetch(`/api/v1/chain/search?q=${encodeURIComponent(q)}&limit=20`)
    .then(r => r.json())
    .then(d => { chainSearchResults.value = d.results || [] })
}

function onMsgClick(msg) {
  if (msg.action === 'view_chain' && msg.action_target) {
    viewChain(msg.action_target)
  } else if (msg.action === 'search_chain') {
    openChainSearch()
  } else if (msg.action === 'industry_list') {
    chainTitle.value = '行业热度'
    chainLoading.value = true
    showChain.value = true
    chainSearchMode.value = false
    fetch('/api/v1/chain/industry-list')
      .then(r => r.json())
      .then(d => {
        chainData.value = {
          name: '行业分布',
          peers: (d.industries || []).map(ind => ({
            code: ind.name,
            name: `${ind.name} (${ind.company_count}家)`,
            industry: ind.name,
          }))
        }
      })
      .finally(() => { chainLoading.value = false })
  }
}

// ===== 图谱渲染 (Canvas 简易力导向) =====

function renderGraph() {
  const container = graphContainer.value
  if (!container || !chainData.value?.graph) return
  
  const { nodes, edges } = chainData.value.graph
  if (!nodes.length) return
  
  // 清理旧 canvas
  container.innerHTML = ''
  
  const W = container.clientWidth || 350
  const H = 400
  const canvas = document.createElement('canvas')
  canvas.width = W
  canvas.height = H
  canvas.style.width = W + 'px'
  canvas.style.height = H + 'px'
  container.appendChild(canvas)
  
  const ctx = canvas.getContext('2d')
  
  // 节点颜色映射
  const colors = {
    company: '#1989fa',
    industry: '#ff976a',
    product: '#07c160',
    material: '#ee0a24',
    downstream_product: '#9768d1',
  }
  
  // 初始化节点位置（圆形布局）
  const cx = W / 2
  const cy = H / 2
  const r = Math.min(W, H) * 0.35
  
  nodes.forEach((n, i) => {
    const angle = (2 * Math.PI * i) / nodes.length - Math.PI / 2
    n.x = cx + r * Math.cos(angle)
    n.y = cy + r * Math.sin(angle)
    n.vx = 0
    n.vy = 0
  })
  
  // 简易力导向 + 渲染
  function tick() {
    // 斥力
    const k = 200
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x
        const dy = nodes[i].y - nodes[j].y
        const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
        const force = k / (dist * dist)
        nodes[i].vx += (dx / dist) * force * 0.1
        nodes[i].vy += (dy / dist) * force * 0.1
        nodes[j].vx -= (dx / dist) * force * 0.1
        nodes[j].vy -= (dy / dist) * force * 0.1
      }
    }
    
    // 引力（边）
    for (const e of edges) {
      const s = nodes.find(n => n.id === e.source)
      const t = nodes.find(n => n.id === e.target)
      if (!s || !t) continue
      const dx = t.x - s.x
      const dy = t.y - s.y
      const dist = Math.max(Math.sqrt(dx * dx + dy * dy), 1)
      const force = 0.01 * dist
      s.vx += (dx / dist) * force
      s.vy += (dy / dist) * force
      t.vx -= (dx / dist) * force
      t.vy -= (dy / dist) * force
    }
    
    // 中心引力
    for (const n of nodes) {
      n.vx += (cx - n.x) * 0.001
      n.vy += (cy - n.y) * 0.001
    }
    
    // 更新 + 阻尼
    for (const n of nodes) {
      n.x += n.vx
      n.y += n.vy
      n.vx *= 0.9
      n.vy *= 0.9
      
      // 边界
      n.x = Math.max(20, Math.min(W - 20, n.x))
      n.y = Math.max(20, Math.min(H - 20, n.y))
    }
    
    // 渲染
    ctx.clearRect(0, 0, W, H)
    
    // 边
    for (const e of edges) {
      const s = nodes.find(n => n.id === e.source)
      const t = nodes.find(n => n.id === e.target)
      if (!s || !t) continue
      ctx.beginPath()
      ctx.moveTo(s.x, s.y)
      ctx.lineTo(t.x, t.y)
      ctx.strokeStyle = '#ddd'
      ctx.lineWidth = 1
      ctx.stroke()
      
      // 边标签（中间）
      if (e.label) {
        const mx = (s.x + t.x) / 2
        const my = (s.y + t.y) / 2
        ctx.fillStyle = '#999'
        ctx.font = '9px sans-serif'
        ctx.textAlign = 'center'
        ctx.fillText(e.label, mx, my - 4)
      }
    }
    
    // 节点
    for (const n of nodes) {
      const color = colors[n.type] || '#666'
      const r = n.type === 'company' ? 12 : 8
      
      ctx.beginPath()
      ctx.arc(n.x, n.y, r, 0, 2 * Math.PI)
      ctx.fillStyle = color
      ctx.fill()
      ctx.strokeStyle = '#fff'
      ctx.lineWidth = 2
      ctx.stroke()
      
      // 标签
      ctx.fillStyle = '#333'
      ctx.font = '10px sans-serif'
      ctx.textAlign = 'center'
      const label = n.label.length > 8 ? n.label.slice(0, 7) + '…' : n.label
      ctx.fillText(label, n.x, n.y + r + 14)
    }
  }
  
  // 跑 100 帧
  for (let i = 0; i < 100; i++) tick()
}
</script>

<style scoped>
.home-split {
  display: flex;
  height: calc(100vh - 50px);
  overflow: hidden;
}
.left-sidebar {
  width: 120px;
  min-width: 120px;
  background: #f5f7fa;
  border-right: 1px solid #e0e0e0;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
}
.sidebar-header {
  padding: 4px 6px;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
  position: sticky;
  top: 0;
  z-index: 1;
  display: flex;
  gap: 2px;
}
.tab-btn {
  flex: 1;
  padding: 4px 2px;
  font-size: 11px;
  text-align: center;
  cursor: pointer;
  border: 1px solid #d0d0d0;
  border-radius: 3px;
  background: #fff;
  color: #333;
}
.tab-btn.active {
  color: #fff;
  background: #1989fa;
  border-color: #1989fa;
  font-weight: 600;
}
.sidebar-list { flex: 1; overflow-y: auto; }
.sidebar-item {
  display: flex;
  align-items: center;
  padding: 6px 8px;
  border-bottom: 1px solid #eee;
  cursor: pointer;
  gap: 2px;
}
.sidebar-item:hover { background: #e8f0fe; }
.sidebar-item.active { background: #d0e3ff; }
.rank-num { width: 16px; font-size: 10px; color: #999; text-align: right; margin-right: 2px; }
.rank-name { flex: 1; font-size: 12px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rank-code { font-size: 10px; color: #999; }
.rank-days { font-size: 10px; color: #e74c3c; font-weight: 600; }
.sidebar-empty { padding: 15px; text-align: center; color: #999; font-size: 12px; }

/* 中间消息区 */
.msg-center {
  flex: 1;
  overflow-y: auto;
  background: #f7f8fa;
}
.search-box { background: #fff; }
.search-results { background: #fff; }

.message-list {
  padding: 8px 12px;
}
.section-title {
  padding: 8px 0;
  font-size: 15px;
  font-weight: 700;
  color: #323233;
  display: flex;
  justify-content: space-between;
  align-items: center;
}
.refresh-btn {
  font-size: 12px;
  color: #1989fa;
  font-weight: 400;
  cursor: pointer;
}
.msg-card {
  background: #fff;
  border-radius: 8px;
  padding: 12px;
  margin-bottom: 10px;
  box-shadow: 0 1px 3px rgba(0,0,0,0.06);
  cursor: pointer;
  transition: transform 0.1s;
}
.msg-card:active { transform: scale(0.98); }
.msg-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 6px;
}
.msg-date { font-size: 11px; color: #999; }
.msg-title { font-size: 15px; font-weight: 600; color: #323233; margin-bottom: 4px; }
.msg-summary { font-size: 13px; color: #666; margin-bottom: 8px; }
.msg-action { text-align: right; }

/* 产业链视图 */
.chain-view {
  height: 100vh;
  overflow-y: auto;
  background: #f7f8fa;
}
.chain-content {
  padding-bottom: 40px;
}
.graph-section {
  margin-top: 8px;
  background: #fff;
}
.graph-container {
  padding: 16px;
  min-height: 300px;
}

/* 快捷入口 */
.quick-links {
  margin-top: 12px;
  background: #fff;
  border-radius: 8px;
  overflow: hidden;
}

/* 暗色模式适配 */
:root.dark .msg-center { background: #1a1a2e; }
:root.dark .msg-card { background: #16213e; box-shadow: 0 1px 3px rgba(255,255,255,0.05); }
:root.dark .msg-title { color: #e0e0e0; }
:root.dark .msg-summary { color: #aaa; }
</style>
