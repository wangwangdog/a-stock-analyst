<template>
  <div class="home-split">
    <!-- ====== 左侧 Sidebar ====== -->
    <div class="left-sidebar">
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
        <span :class="['sidebar-tab', {active: sidebarSheet==='news'}]"
              @click="sidebarSheet='news'">新闻</span>
      </div>

      <!-- 大单 Sheet -->
      <template v-if="sidebarSheet==='bigbuy' && !searchResults.length">
        <div class="sidebar-header">
          <span :class="['tab-btn',{active:filterDays==='all'}]" @click="setFilter('all')">全量</span>
          <span :class="['tab-btn',{active:filterDays==='5'}]" @click="setFilter('5')">近5</span>
          <span :class="['tab-btn',{active:filterDays==='10'}]" @click="setFilter('10')">近10</span>
        </div>
        <div class="sidebar-list">
          <div v-for="(item,idx) in bigBuyRank" :key="item.symbol"
               class="sidebar-item" :class="{active: rightSymbol===item.symbol && rightView==='kline'}"
               @click="onBigbuyClick(item)">
            <span class="rank-num">{{ idx+1 }}</span>
            <span class="rank-name">{{ item.name||item.symbol }}</span>
            <span class="rank-code">{{ item.symbol }}</span>
            <span class="rank-days">{{ item.days }}天</span>
          </div>
          <div v-if="!bigBuyRank.length" class="sidebar-empty">暂无数据</div>
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

    <!-- ====== 右侧：图谱视图 ====== -->
    <div class="right-panel" v-if="rightView === 'tupu'">
      <div class="right-tabs">
        <span class="right-tab active">🗺️ 产业链图谱</span>
        <van-icon name="cross" class="right-close" @click="rightView=''" />
      </div>
      <div class="right-tupu-wrap">
        <TupuPanel :symbol="rightSymbol" />
      </div>
    </div>

    <div class="right-empty" v-else>
      <van-icon name="arrow-left" size="40" color="#ddd" />
      <p style="color:#ccc;font-size:14px;margin-top:12px">← 点击左侧查看</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted, watch } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import TupuPanel from '../components/TupuPanel.vue'

const router = useRouter()
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

const rightView = ref('')
const rightSymbol = ref('')

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
function onBigbuyClick(item) { router.push('/kline/' + item.symbol) }
function openRightTupu(sym) { rightSymbol.value=sym; rightView.value='tupu' }
function switchRightView(v) { rightView.value=v }
function onNewsDemoClick() { openRightTupu('000001') }

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
  if (s.type==='company') router.push('/kline/' + s.code)
  else openRightTupu(s.code||'000001')
}

// RSS 新闻
function fmtTime(ts) {
  if (!ts) return ''
  const d = new Date(ts * 1000)
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
    const resp = await fetch('/rss-api/list?limit=50&offset=' + off)
    if (!resp.ok) {
      console.error('news fetch failed:', resp.status)
      return
    }
    const data = await resp.json()
    if (data && data.news && data.news.length) {
      if (append) newsList.value.push(...data.news)
      else newsList.value = data.news
      newsOffset.value = off + data.news.length
    }
  } catch(e) {
    console.error('load news error', e)
    // 如果首次加载失败，显示重试提示
    if (!newsList.value.length) {
      newsList.value = [{id:'retry', title:'加载失败，点击重试', link:'', source:'retry'}]
    }
  }
  newsLoading.value = false
}
function loadMoreNews() {
  loadNews(true)
}
function onNewsClick(item) {
  if (item.link) window.open(item.link, '_blank')
  else if (item.id === 'retry') {
    newsList.value = []
    loadNews()
  }
}

// 切换到新闻 tab 时自动加载
watch(sidebarSheet, (val) => {
  if (val === 'news' && !newsList.value.length && !newsLoading.value) {
    loadNews()
  }
})

onMounted(async () => {
  loadBigBuyRank()
  loadNews()
  try {
    const resp = await fetch('/api/v1/stocks')
    const data = await resp.json()
    if (data.status==='ok') allStocks.value = data.data
  } catch(e) {}
  const h = new Date().getHours()
  const msgs = ['还不睡？🌙','早上好 ☀️','上午好 📊','中午好 🥟','下午好 📈','晚上好 ☕']
  showToast(msgs[Math.min(Math.floor(h/4),5)]||msgs[5])
})
</script>

<style scoped>
.home-split { display:flex; height:calc(100vh - 50px); overflow:hidden; }

/* ====== Sidebar ====== */
.left-sidebar {
  width:150px; min-width:150px; background:#f5f7fa;
  border-right:1px solid #e0e0e0; display:flex; flex-direction:column; overflow:hidden;
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
.sidebar-item.active { background:#d0e3ff; }
.rank-num { width:14px; font-size:10px; color:#999; text-align:right; margin-right:2px; }
.rank-name { flex:1; font-size:11px; white-space:nowrap; overflow:hidden; text-overflow:ellipsis; }
.rank-code { font-size:9px; color:#999; }
.rank-days { font-size:9px; color:#e74c3c; font-weight:600; }
.sidebar-empty { padding:15px; text-align:center; color:#999; font-size:11px; }

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

/* ====== 右侧 ====== */
.right-panel {
  flex:1; min-width:0; display:flex; flex-direction:column;
  background:#fff; border-left:1px solid #e0e0e0;
}
.right-tabs {
  display:flex; align-items:center; border-bottom:1px solid #e0e0e0;
  background:#fafafa; padding:0 8px; height:36px; gap:4px;
}
.right-tab {
  padding:6px 14px; font-size:13px; cursor:pointer;
  border-radius:4px 4px 0 0; color:#666; border-bottom:2px solid transparent;
}
.right-tab.active { color:#1989fa; border-bottom-color:#1989fa; font-weight:600; background:#fff; }
.right-close { margin-left:auto; cursor:pointer; font-size:18px; color:#999; padding:4px; }
.right-tupu-wrap { flex:1; overflow-y:auto; }
.right-empty {
  flex:1; min-width:0; display:flex; flex-direction:column;
  align-items:center; justify-content:center; background:#fafafa;
  border-left:1px solid #e0e0e0;
}
</style>
