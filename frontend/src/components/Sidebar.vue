<template>
  <div class="sidebar-root">
    <!-- 搜索框 -->
    <div class="sidebar-search">
      <van-search v-model="keyword" placeholder="搜股票/代码..."
                  shape="round" @search="onSearch" @clear="onClear" />
    </div>
    
    <!-- 搜索结果 -->
    <div v-if="searchResults.length" class="search-results">
      <div v-for="s in searchResults"
           :key="(s.type||'stock')+'_'+(s.code||s.name)"
           class="search-item" @click="goSearchResult(s)">
        <span class="sr-name">{{ s.name }}</span>
        <span class="sr-code">{{ s.type==='company' ? s.code : s.type }}</span>
      </div>
      <div class="search-clear" @click="searchResults=[];keyword=''">✕ 清除</div>
    </div>

    <!-- Sheet 切换 -->
    <div class="sidebar-tabs" v-if="!searchResults.length">
      <span :class="['sidebar-tab', {active: sidebarSheet==='bigbuy'}]"
            @click="sidebarSheet='bigbuy'">大单</span>
      <span :class="['sidebar-tab', {active: sidebarSheet==='strategies'}]"
            @click="sidebarSheet='strategies'">策略</span>
      <span :class="['sidebar-tab', {active: sidebarSheet==='news'}]"
            @click="sidebarSheet='news'">新闻</span>
    </div>

    <!-- 大单 Sheet -->
    <template v-if="sidebarSheet==='bigbuy' && !searchResults.length">
      <div class="sidebar-header">
        <span :class="['tab-btn',{active:filterDays==='all'}]" @click="setFilter('all')">全量90D</span>
        <span :class="['tab-btn',{active:filterDays==='5'}]" @click="setFilter('5')">近5/1</span>
        <span :class="['tab-btn',{active:filterDays==='10'}]" @click="setFilter('10')">近10/1</span>
      </div>
      <div class="sidebar-list">
        <div v-for="(item,idx) in bigBuyRank" :key="item.symbol"
             class="sidebar-item"
             @click="$emit('select-stock', item.symbol)">
          <span class="rank-num">{{ idx+1 }}</span>
          <span class="rank-name">{{ item.name||item.symbol }}</span>
          <span class="rank-code">{{ item.symbol }}</span>
          <span class="rank-days">{{ item.days }}天</span>
        </div>
        <div v-if="!bigBuyRank.length" class="sidebar-empty">暂无数据</div>
      </div>
    </template>

    <!-- 策略 Sheet -->
    <template v-if="sidebarSheet==='strategies' && !searchResults.length">
      <div class="sidebar-strat-list">
        <!-- 状态条 -->
        <div class="strat-status" v-if="stratStatus.db_exists">
          <van-tag type="success" size="small">✅ {{ stratStatus.stock_count }}只</van-tag>
          <span class="strat-picks-badge" v-if="stratStatus.picks_today > 0">{{ stratStatus.picks_today }}选股</span>
        </div>

        <!-- 盘前 / 盘中 -->
        <div class="strat-action-stack">
          <van-button class="strat-btn-full" icon="clock-o" size="small" plain type="warning"
                      :loading="preLoading" @click="runPreMarket">🌅 盘前策略</van-button>
          <van-button class="strat-btn-full" icon="trending-up" size="small" plain type="danger"
                      :loading="intraLoading" @click="runIntraday">⚡ 盘中策略</van-button>
        </div>

        <!-- 多策略 + 同步 -->
        <div class="strat-action-stack">
          <van-button class="strat-btn-full" size="small" plain type="primary"
                      :loading="loadingMulti2" @click="doMultiPicks(2,2)">🎯 同时满足2个策略条件</van-button>
          <van-button class="strat-btn-full" size="small" plain type="danger"
                      :loading="loadingMulti3" @click="doMultiPicks(3)">🔥 同时满足3+个策略条件</van-button>
          <van-button class="strat-btn-full" size="small" plain type="primary"
                      :loading="syncing" @click="doSync">📥 每日同步</van-button>
        </div>

        <!-- 初筛 -->
        <div class="strat-chushai">
          <van-field v-model="chushaiRank" type="number" placeholder="起始排名" input-align="center"
                     style="width:58px;flex-shrink:0" :border="true" size="small" />
          <van-button icon="search" size="small" plain type="warning"
                      :loading="loadingChushai" @click="doChushai">🔍 初筛</van-button>
          <span v-if="chushaiTotal>0" class="chushai-total">{{ chushaiTotal }}只</span>
        </div>

        <!-- 策略列表 -->
        <div class="strat-grid">
          <div v-for="s in strategyList" :key="s.key"
               class="strat-item"
               :class="{ active: selectedKey === s.key }"
               @click="selectStrategy(s.key)">
            <span class="strat-item-name">{{ s.name }}</span>
            <span class="strat-item-desc">{{ s.desc }}</span>
            <span class="strat-item-badge" v-if="strategyPicks[s.key]?.length">
              {{ strategyPicks[s.key].length }}
            </span>
          </div>
          <div v-if="!strategyList.length" class="strat-empty">加载中...</div>
        </div>
      </div>
    </template>

    <!-- 新闻 Sheet -->
    <template v-if="sidebarSheet==='news' && !searchResults.length">
      <div class="sidebar-news-list">
        <div v-for="item in newsList" :key="item.id" class="news-item" @click="onNewsClick(item)">
          <div class="news-dot" :class="'src-' + item.source"></div>
          <div class="news-text">
            <div class="news-title">{{ item.title }}</div>
            <div class="news-sub">
              <span class="news-source">{{ item.source_name }}</span>
              <span class="news-time">{{ fmtTime(item.fetched_at) }}</span>
            </div>
          </div>
        </div>
        <div v-if="!newsList.length" class="news-empty">
          <van-icon name="newspaper-o" size="24" color="#ddd" />
          <p style="color:#bbb;font-size:11px;margin-top:6px">加载中...</p>
        </div>
        <div v-if="newsList.length >= 50" class="news-more" @click="loadMoreNews">加载更多 ↓</div>
      </div>
    </template>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { showToast, showLoadingToast, closeToast, showDialog } from 'vant'

const emit = defineEmits(['select-stock', 'view-news-chain'])

const keyword = ref('')
const searchResults = ref([])
const allStocks = ref([])

const bigBuyRank = ref([])
const filterDays = ref('all')
const sidebarSheet = ref('bigbuy')

// RSS 新闻
const newsList = ref([])
const newsOffset = ref(0)
const newsLoading = ref(false)

// ===== 策略 =====
const syncing = ref(false)
const preLoading = ref(false)
const intraLoading = ref(false)
const loadingMulti2 = ref(false)
const loadingMulti3 = ref(false)
const loadingChushai = ref(false)
const strategyList = ref([])
const strategyPicks = ref({})
const selectedKey = ref(null)
const stratStatus = ref({})
const chushaiRank = ref(1)
const chushaiTotal = ref(0)

function setFilter(days) {
  filterDays.value = days
  const d = days==='all'?90:Number(days)
  const exact = days!=='all'
  loadBigBuyRank(d, exact)
}
async function loadBigBuyRank(days=90, exact=false) {
  try {
    const resp = await fetch(`/api/v1/bigbuy-rank?days=${days}${exact?'&exact=1':''}`)
    bigBuyRank.value = await resp.json()
  } catch {}
}

function onSearch(val) {
  if (!val.trim()) return
  const q = val.trim().toLowerCase()
  searchResults.value = []
  if (allStocks.value.length) {
    searchResults.value = allStocks.value.filter(s => {
      const c = (s.code||s.symbol||'').toLowerCase()
      const n = (s.name||'').toLowerCase()
      return c.includes(q)||n.includes(q)
    }).slice(0,15).map(s=>({type:'company',code:s.code||s.symbol,name:s.name}))
  }
  fetch(`/api/v1/chain/search?q=${encodeURIComponent(q)}&limit=10`)
    .then(r=>r.json()).then(d=>{if(d.results?.length)searchResults.value=[...searchResults.value,...d.results]})
}
function onClear() { searchResults.value=[] }
function goSearchResult(s) {
  if (s.type==='company') {
    searchResults.value=[]
    keyword.value=''
    emit('select-stock', s.code)
  }
}

// RSS 新闻
function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts)
  if (isNaN(d.getTime())) return ''
  const now = new Date()
  const diff = (now - d) / 1000
  if (diff < 60) return '刚刚'
  if (diff < 3600) return Math.floor(diff/60) + '分钟前'
  if (diff < 86400) return Math.floor(diff/3600) + '小时前'
  return Math.floor(diff/86400) + '天前'
}
async function loadNews(append=false) {
  if (newsLoading.value) return
  newsLoading.value = true
  try {
    const off = append ? newsOffset.value : 0
    const resp = await fetch('/rss-api/list?limit=50&offset=' + off + '&_=' + Date.now())
    if (!resp.ok) { console.error('news fetch failed:', resp.status); return }
    const data = await resp.json()
    if (data && data.news && data.news.length) {
      if (append) newsList.value.push(...data.news)
      else newsList.value = data.news
      newsOffset.value = off + data.news.length
    }
  } catch(e) {
    console.error('load news error', e)
    if (!newsList.value.length) {
      newsList.value = [{id:'retry', title:'加载失败，点击重试', link:'', source:'retry'}]
    }
  }
  newsLoading.value = false
}
function loadMoreNews() { loadNews(true) }
function onNewsClick(item) {
  if (item.link) emit('view-news-chain', item)
  else if (item.id === 'retry') { newsList.value = []; loadNews() }
}

// ===== 策略功能 =====
async function runPreMarket() {
  preLoading.value = true
  try {
    const r = await fetch('/api/v1/strategy/pre-market', { method: 'POST' })
    const data = await r.json()
    if (data.status === 'ok') {
      showDialog({ title: '🌅 盘前策略', message: data.report || JSON.stringify(data.result?.slice(0, 10) || [], null, 2) })
    } else {
      showToast({ message: data.error || '盘前策略执行失败', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    preLoading.value = false
  }
}
async function runIntraday() {
  intraLoading.value = true
  try {
    const r = await fetch('/api/v1/strategy/intraday', { method: 'POST' })
    const data = await r.json()
    if (data.status === 'ok') {
      showDialog({ title: '⚡ 盘中策略', message: data.report || JSON.stringify(data.result?.slice(0, 10) || [], null, 2) })
    } else {
      showToast({ message: data.error || '盘中策略执行失败', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    intraLoading.value = false
  }
}
async function doMultiPicks(minCount, maxCount = null) {
  selectedKey.value = null
  if (minCount === 2 && maxCount === 2) loadingMulti2.value = true
  else loadingMulti3.value = true
  const label = maxCount === 2 ? '满足2个策略' : '满足3+策略'
  try {
    const params = `min_count=${minCount}${maxCount ? `&max_count=${maxCount}` : ''}`
    const r = await fetch(`/api/v1/strategy/multi-picks?${params}`)
    const data = await r.json()
    if (data.status === 'ok' && data.data?.length) {
      const stocks = data.data.map(d => d.symbol).join(', ')
      showDialog({ title: `🎯 ${label} — ${data.total}只`, message: stocks })
    } else {
      showToast({ message: '无匹配结果', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    loadingMulti2.value = false
    loadingMulti3.value = false
  }
}
async function doSync() {
  syncing.value = true
  const toast = showLoadingToast({ message: '🔄 同步中...', duration: 0 })
  try {
    const r = await fetch('/api/v1/strategy/sync', { method: 'POST' })
    const data = await r.json()
    if (data.status === 'started') {
      const poll = setInterval(async () => {
        try {
          const sr = await fetch('/api/v1/strategy/sync/status')
          const sd = await sr.json()
          if (!sd.in_progress && sd.result) {
            clearInterval(poll); closeToast()
            if (sd.result.status === 'ok') {
              showDialog({ title: '同步完成', message: `✅ 写入 ${sd.result.sync_count} 条\n已选 ${sd.result.total_picks} 只` })
              loadStrategies()
            } else {
              showToast({ message: sd.result.error || '同步失败', type: 'fail' })
            }
          }
        } catch {}
      }, 2000)
    } else {
      closeToast()
      showToast({ message: data.error || '同步启动失败', type: 'fail' })
    }
  } catch (e) {
    closeToast()
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    syncing.value = false
  }
}
async function doChushai() {
  loadingChushai.value = true
  chushaiTotal.value = 0
  const start = parseInt(chushaiRank.value) || 1
  const end = start + 199
  try {
    await fetch('/api/v1/strategy/vol20day/refresh', { method: 'POST' })
    const r = await fetch(`/api/v1/strategy/vol20day?min_rank=${start}&max_rank=${end}`)
    const data = await r.json()
    if (data.status === 'ok' && data.data?.length) {
      const stocks = data.data.map(d => `${d.symbol} ${d.name||''} ${d.return_20d>=0?'+':''}${d.return_20d?.toFixed(2)}%`).join('\n')
      chushaiTotal.value = data.total || 0
      showDialog({ title: `🔍 初筛 排名${start}-${end} (共${data.total}只)`, message: stocks })
    } else {
      showToast({ message: '初筛无结果', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    loadingChushai.value = false
  }
}
function selectStrategy(key) {
  selectedKey.value = selectedKey.value === key ? null : key
  const picks = strategyPicks.value[key]
  if (picks?.length) {
    showDialog({ title: `📊 ${STRATEGY_LABELS[key]||key} — ${picks.length}只`, message: picks.join(', ') })
  } else {
    showToast({ message: '该策略暂无选股', type: 'fail' })
  }
}
const STRATEGY_LABELS = {
  ma_volume: '均线放量', turtle_trade: '海龟交易', high_tight_flag: '高窄旗形',
  limit_up_shakeout: '涨停洗盘', uptrend_limit_down: '跌停反包', rps_breakout: 'RPS突破',
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
async function loadStratStatus() {
  try {
    const r = await fetch('/api/v1/strategy/status')
    stratStatus.value = await r.json()
  } catch { stratStatus.value = {} }
}

// 切换到策略 tab 时自动加载数据
watch(sidebarSheet, (val) => {
  if (val === 'strategies' && !strategyList.value.length) {
    loadStrategies(); loadPicks(); loadStratStatus()
  }
  if (val === 'news' && !newsList.value.length && !newsLoading.value) {
    loadNews()
  }
})

onMounted(() => {
  setTimeout(() => {
    loadBigBuyRank()
    loadNews()
    fetch('/api/v1/stocks')
      .then(r => r.json())
      .then(d => { if (d.status==='ok') allStocks.value = d.data })
      .catch(() => {})
  }, 100)
})
</script>

<style scoped>
.sidebar-root {
  width:240px; min-width:240px; background:#f5f7fa;
  border-right:1px solid #e0e0e0; display:flex; flex-direction:column; overflow:hidden;
  height:100%;
}
.sidebar-search { background:#fff; }
.sidebar-search :deep(.van-search){ padding:6px 8px; }
.sidebar-search :deep(.van-search__content){ background:#f5f7fa; border-radius:16px; }
.sidebar-search :deep(.van-field__control){ font-size:12px; }
.search-results { flex:1; overflow-y:auto; background:#fff; }
.search-item {
  display:flex; justify-content:space-between; align-items:center;
  padding:10px 12px; border-bottom:1px solid #f0f0f0; cursor:pointer;
}
.search-item:hover { background:#f5f8ff; }
.sr-name { font-size:13px; color:#323233; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.sr-code { font-size:11px; color:#999; margin-left:8px; }
.search-clear { padding:10px; text-align:center; color:#1989fa; font-size:13px; cursor:pointer; background:#fff; }

.sidebar-tabs { display:flex; background:#fff; border-bottom:1px solid #e0e0e0; }
.sidebar-tab {
  flex:1; padding:8px 0; text-align:center; font-size:13px; font-weight:500;
  color:#666; cursor:pointer; border-bottom:2px solid transparent; transition:all .2s;
}
.sidebar-tab.active { color:#1989fa; border-bottom-color:#1989fa; font-weight:600; }

.sidebar-header { padding:4px 6px; background:#fff; border-bottom:1px solid #e0e0e0; display:flex; gap:2px; }
.tab-btn {
  flex:1; padding:4px 2px; font-size:11px; text-align:center; cursor:pointer;
  border:1px solid #d0d0d0; border-radius:3px; background:#fff; color:#333;
}
.tab-btn.active { color:#fff; background:#1989fa; border-color:#1989fa; font-weight:600; }
.sidebar-list { flex:1; overflow-y:auto; }
.sidebar-item {
  display:flex; align-items:center; padding:5px 6px; border-bottom:1px solid #eee;
  cursor:pointer; gap:2px;
}
.sidebar-item:hover { background:#e8f0fe; }
.rank-num { width:14px; font-size:11px; color:#999; text-align:right; margin-right:2px; }
.rank-name { flex:1; font-size:12px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rank-code { font-size:10px; color:#999; }
.rank-days { font-size:10px; color:#e74c3c; font-weight:600; }
.sidebar-empty { padding:15px; text-align:center; color:#999; font-size:11px; }

/* ===== 策略 ===== */
.sidebar-strat-list { flex:1; overflow-y:auto; padding:4px; }
.strat-status {
  display:flex; align-items:center; justify-content:space-between;
  padding:4px 6px; margin-bottom:4px; background:#fff; border-radius:4px;
}
.strat-picks-badge {
  background:#ee0a24; color:#fff; border-radius:8px; padding:1px 6px; font-size:10px; font-weight:600;
}
.strat-action-stack {
  display:flex; flex-direction:column; gap:3px; margin-bottom:4px;
}
.strat-btn-full {
  width:100% !important; font-size:11px !important; min-height:30px;
}
.strat-chushai {
  display:flex; align-items:center; gap:4px; padding:4px 2px;
  background:#fff; border-radius:4px; margin-bottom:4px;
}
.strat-chushai :deep(.van-field) { padding:0 4px; }
.strat-chushai :deep(.van-field__control) { font-size:11px; }
.chushai-total { font-size:10px; color:#999; white-space:nowrap; }
.strat-grid { display:flex; flex-direction:column; gap:2px; }
.strat-item {
  display:flex; align-items:center; gap:4px; padding:6px 8px;
  background:#fff; border-radius:4px; cursor:pointer; transition:all .15s;
  border-left:3px solid transparent;
}
.strat-item:hover { background:#e8f0fe; }
.strat-item.active { border-left-color:#1989fa; background:#f0f5ff; }
.strat-item-name { font-size:12px; color:#323233; font-weight:500; flex-shrink:0; }
.strat-item-desc { font-size:10px; color:#999; flex:1; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.strat-item-badge {
  background:#ee0a24; color:#fff; border-radius:8px; padding:0 5px; font-size:10px; font-weight:600; line-height:16px;
}
.strat-empty { padding:15px; text-align:center; color:#999; font-size:11px; }

/* ===== 新闻 ===== */
.sidebar-news-list { flex:1; overflow-y:auto; padding:4px 4px; }
.news-item {
  display:flex; align-items:flex-start; gap:5px; padding:6px 5px;
  background:#fff; border-radius:4px; margin-bottom:4px; cursor:pointer;
  box-shadow:0 1px 1px rgba(0,0,0,.03); transition:background .15s;
}
.news-item:hover { background:#e8f0fe; }
.news-dot { width:5px; height:5px; border-radius:50%; background:#1989fa; flex-shrink:0; margin-top:4px; }
.news-dot.src-buzzing_hn { background:#e74c3c; }
.news-dot.src-buzzing_ph { background:#f39c12; }
.news-dot.src-trendradar { background:#1989fa; }
.news-text { flex:1; min-width:0; }
.news-title { font-size:11px; color:#323233; line-height:1.35; display:-webkit-box; -webkit-line-clamp:2; -webkit-box-orient:vertical; overflow:hidden; }
.news-sub { display:flex; justify-content:space-between; margin-top:2px; }
.news-source { font-size:9px; color:#999; }
.news-time { font-size:9px; color:#bbb; }
.news-empty { text-align:center; padding:20px 10px; }
.news-more { text-align:center; padding:6px; font-size:10px; color:#1989fa; cursor:pointer; }
</style>
