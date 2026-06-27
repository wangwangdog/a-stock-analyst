<template>
  <div class="home-split">
    <!-- ====== 左侧 Sidebar 120px ====== -->
    <div class="left-sidebar">
      <div class="sidebar-tabs">
        <span :class="['sidebar-tab', {active: sidebarSheet === 'bigbuy'}]"
              @click="sidebarSheet = 'bigbuy'">大单</span>
        <span :class="['sidebar-tab', {active: sidebarSheet === 'news'}]"
              @click="sidebarSheet = 'news'">新闻</span>
      </div>

      <!-- 大单 Sheet -->
      <template v-if="sidebarSheet === 'bigbuy'">
        <div class="sidebar-header">
          <span :class="['tab-btn', {active: filterDays === 'all'}]"
                @click="setFilter('all')">全量</span>
          <span :class="['tab-btn', {active: filterDays === '5'}]"
                @click="setFilter('5')">近5</span>
          <span :class="['tab-btn', {active: filterDays === '10'}]"
                @click="setFilter('10')">近10</span>
        </div>
        <div class="sidebar-list">
          <div v-for="(item, idx) in bigBuyRank" :key="item.symbol"
               class="sidebar-item" :class="{ active: rightSymbol === item.symbol && rightView === 'kline' }"
               @click="onBigbuyClick(item)">
            <span class="rank-num">{{ idx + 1 }}</span>
            <span class="rank-name">{{ item.name || item.symbol }}</span>
            <span class="rank-code">{{ item.symbol }}</span>
            <span class="rank-days">{{ item.days }}天</span>
          </div>
          <div v-if="!bigBuyRank.length" class="sidebar-empty">暂无数据</div>
        </div>
      </template>

      <!-- 新闻 Sheet（占位 → 点击触发右侧tupu） -->
      <template v-else>
        <div class="sidebar-news-list">
          <div class="news-placeholder-item" @click="onNewsDemoClick">
            <div class="news-dot"></div>
            <div class="news-text">
              <div class="news-title">产业链图谱</div>
              <div class="news-sub">点击查看示例</div>
            </div>
          </div>
          <div class="news-empty">
            <van-icon name="newspaper-o" size="24" color="#ddd" />
            <p style="color:#bbb;font-size:11px;margin-top:6px">新闻流接入中</p>
          </div>
        </div>
      </template>
    </div>

    <!-- ====== 中间：搜索 + 消息列表 ====== -->
    <div class="msg-center">
      <van-nav-bar title="AI 量化工具-DOGE" left-text="胖磊 🦞">
        <template #right>
          <span style="font-size:12px;color:#999;margin-right:8px" v-if="username">{{ username }}</span>
          <van-icon name="logout" @click="doLogout" style="padding:4px" />
        </template>
      </van-nav-bar>

      <div class="search-box">
        <van-search v-model="keyword" placeholder="搜索股票/产品/行业..."
                    @search="onSearch" @clear="onClear" />
      </div>

      <!-- 搜索结果 -->
      <div v-if="searchResults.length" class="search-results">
        <van-cell-group title="搜索结果">
          <van-cell v-for="s in searchResults"
                    :key="(s.type||'stock') + '_' + (s.code||s.name)"
                    :title="s.name" :label="s.code || s.type" is-link
                    @click="goSearchResult(s)">
            <template #icon>
              <van-tag round plain size="small"
                       :type="s.type==='industry'?'warning':s.type==='product'?'success':'primary'"
                       style="margin-right:8px">{{ s.type==='company'?s.code:s.type }}</van-tag>
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
        <div v-for="msg in messages" :key="msg.id" class="msg-card"
             @click="onMsgClick(msg)">
          <div class="msg-header">
            <van-tag :type="msg.type==='big_deal'?'danger':'primary'" size="small" plain>
              {{ msg.type==='big_deal'?'大单':'系统' }}</van-tag>
            <span class="msg-date">{{ msg.date }}</span>
          </div>
          <div class="msg-title">{{ msg.title }}</div>
          <div class="msg-summary">{{ msg.summary }}</div>
          <div class="msg-action" v-if="msg.action==='view_chain'">
            <van-button size="small" type="primary" plain>产业链 →</van-button>
          </div>
        </div>

        <!-- 快捷入口 -->
        <div class="quick-links">
          <van-grid :column-num="4" :border="false" icon-size="22">
            <van-grid-item icon="chart-trending-o" text="K线" @click="openRightKline('000001')" />
            <van-grid-item icon="cluster-o" text="图谱" @click="openRightTupu('000001')" />
            <van-grid-item icon="gem-o" text="策略" @click="$router.push('/strategies')" />
            <van-grid-item icon="link-o" text="链接" @click="$router.push('/links')" />
          </van-grid>
        </div>
      </div>
    </div>

    <!-- ====== 右侧：可切换主显示区 ====== -->
    <div class="right-panel" v-if="rightView">
      <!-- 视图切换条 -->
      <div class="right-tabs">
        <span :class="['right-tab', {active: rightView === 'kline'}]"
              @click="switchRightView('kline')">📈 K线</span>
        <span :class="['right-tab', {active: rightView === 'tupu'}]"
              @click="switchRightView('tupu')">🗺️ 图谱</span>
        <van-icon name="cross" class="right-close" @click="rightView = ''" />
      </div>

      <!-- K线视图 -->
      <div v-show="rightView === 'kline'" class="right-kline-wrap">
        <iframe v-if="rightSymbol" :src="`/#/kline/${rightSymbol}`"
                class="kline-iframe" frameborder="0" />
      </div>

      <!-- 图谱视图 -->
      <div v-show="rightView === 'tupu'" class="right-tupu-wrap">
        <TupuPanel :symbol="rightSymbol" />
      </div>
    </div>

    <!-- 右侧空态 -->
    <div class="right-empty" v-else>
      <van-icon name="arrow-left" size="40" color="#ddd" />
      <p style="color:#ccc;font-size:14px;margin-top:12px">← 点击左侧股票查看</p>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import TupuPanel from '../components/TupuPanel.vue'

const router = useRouter()
const keyword = ref('')
const searchResults = ref([])
const loading = ref(false)
const allStocks = ref([])
const username = ref(localStorage.getItem('username') || '')

// 左侧大单
const bigBuyRank = ref([])
const filterDays = ref('all')
const sidebarSheet = ref('bigbuy')

// 消息
const messages = ref([])
const msgLoading = ref(false)

// 右侧视图
const rightView = ref('')       // '' | 'kline' | 'tupu'
const rightSymbol = ref('')

// ---- 左侧大单 ----
function setFilter(days) {
  filterDays.value = days
  loadBigBuyRank(days === 'all' ? '' : days)
}
async function loadBigBuyRank(days = '') {
  try {
    const resp = await fetch('/api/v1/bigbuy-rank' + (days ? '?days=' + days : ''))
    bigBuyRank.value = await resp.json()
  } catch {}
}
function onBigbuyClick(item) {
  openRightKline(item.symbol)
}

// ---- 右侧视图切换 ----
function openRightKline(symbol) {
  rightSymbol.value = symbol
  rightView.value = 'kline'
}
function openRightTupu(symbol) {
  rightSymbol.value = symbol
  rightView.value = 'tupu'
}
function switchRightView(view) {
  rightView.value = view
}

// ---- 新闻占位 ----
function onNewsDemoClick() {
  openRightTupu('000001')
}

// ---- 消息 ----
async function loadMessages() {
  msgLoading.value = true
  try {
    const resp = await fetch('/api/v1/messages?days=7')
    const data = await resp.json()
    messages.value = data.messages || []
  } catch (e) { messages.value = [] }
  finally { msgLoading.value = false }
}
function onMsgClick(msg) {
  if (msg.action === 'view_chain' && msg.action_target) {
    openRightTupu(msg.action_target)
  } else if (msg.action === 'industry_list') {
    openRightTupu('000001')
  }
}

// ---- 搜索 ----
function onSearch(val) {
  if (!val.trim()) return
  loading.value = true
  const q = val.trim().toLowerCase()
  searchResults.value = []
  if (allStocks.value.length) {
    searchResults.value = allStocks.value.filter(s => {
      const code = (s.code || s.symbol || '').toLowerCase()
      const name = (s.name || '').toLowerCase()
      return code.includes(q) || name.includes(q)
    }).slice(0, 10).map(s => ({ type: 'company', code: s.code || s.symbol, name: s.name }))
  }
  fetch(`/api/v1/chain/search?q=${encodeURIComponent(q)}&limit=10`)
    .then(r => r.json())
    .then(d => { if (d.results?.length) searchResults.value = [...searchResults.value, ...d.results] })
    .finally(() => { loading.value = false })
}
function onClear() { searchResults.value = [] }
function goSearchResult(s) {
  if (s.type === 'company') openRightKline(s.code)
  else if (s.type === 'product' || s.type === 'industry') openRightTupu(s.code || '000001')
}

// ---- 其它 ----
function doLogout() {
  localStorage.removeItem('username')
  router.push('/login')
}

onMounted(async () => {
  loadBigBuyRank()
  loadMessages()
  try {
    const resp = await fetch('/api/v1/stocks')
    const data = await resp.json()
    if (data.status === 'ok') allStocks.value = data.data
  } catch (e) {}
  const h = new Date().getHours()
  const msgs = ['还不睡？🌙','早上好 ☀️','上午好 📊','中午好 🥟','下午好 📈','晚上好 ☕']
  showToast(msgs[Math.min(Math.floor(h/4), 5)] || msgs[5])
})
</script>

<style scoped>
.home-split {
  display: flex;
  height: calc(100vh - 50px);
  overflow: hidden;
}

/* ====== 左侧 Sidebar 120px ====== */
.left-sidebar {
  width: 120px; min-width: 120px;
  background: #f5f7fa;
  border-right: 1px solid #e0e0e0;
  display: flex; flex-direction: column;
  overflow: hidden;
}
.sidebar-tabs {
  display: flex;
  background: #fff;
  border-bottom: 1px solid #e0e0e0;
}
.sidebar-tab {
  flex: 1; padding: 8px 0; text-align: center;
  font-size: 13px; font-weight: 500; color: #666;
  cursor: pointer;
  border-bottom: 2px solid transparent;
  transition: all .2s;
}
.sidebar-tab.active { color: #1989fa; border-bottom-color: #1989fa; font-weight: 600; }
.sidebar-header {
  padding: 4px 6px; background: #fff;
  border-bottom: 1px solid #e0e0e0;
  display: flex; gap: 2px;
}
.tab-btn {
  flex: 1; padding: 4px 2px; font-size: 11px; text-align: center;
  cursor: pointer; border: 1px solid #d0d0d0; border-radius: 3px;
  background: #fff; color: #333;
}
.tab-btn.active { color: #fff; background: #1989fa; border-color: #1989fa; font-weight: 600; }
.sidebar-list { flex: 1; overflow-y: auto; }
.sidebar-item {
  display: flex; align-items: center; padding: 5px 6px;
  border-bottom: 1px solid #eee; cursor: pointer; gap: 2px;
}
.sidebar-item:hover { background: #e8f0fe; }
.sidebar-item.active { background: #d0e3ff; }
.rank-num { width: 14px; font-size: 10px; color: #999; text-align: right; margin-right: 2px; }
.rank-name { flex: 1; font-size: 11px; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
.rank-code { font-size: 9px; color: #999; }
.rank-days { font-size: 9px; color: #e74c3c; font-weight: 600; }
.sidebar-empty { padding: 15px; text-align: center; color: #999; font-size: 11px; }

/* 新闻 Sheet */
.sidebar-news-list { flex: 1; overflow-y: auto; padding: 8px 6px; }
.news-placeholder-item {
  display: flex; align-items: center; gap: 6px;
  padding: 8px; background: #fff; border-radius: 6px;
  margin-bottom: 8px; cursor: pointer;
  box-shadow: 0 1px 2px rgba(0,0,0,.04);
}
.news-dot { width: 6px; height: 6px; border-radius: 50%; background: #1989fa; flex-shrink: 0; }
.news-title { font-size: 12px; font-weight: 600; color: #323233; }
.news-sub { font-size: 10px; color: #999; }
.news-empty { text-align: center; padding: 30px 10px; }

/* ====== 中间 ====== */
.msg-center {
  flex: 1; overflow-y: auto; background: #f7f8fa;
  min-width: 0;
}
.search-box { background: #fff; }
.search-results { background: #fff; }
.message-list { padding: 8px 12px; }
.section-title {
  padding: 8px 0; font-size: 15px; font-weight: 700;
  color: #323233; display: flex; justify-content: space-between; align-items: center;
}
.refresh-btn { font-size: 12px; color: #1989fa; font-weight: 400; cursor: pointer; }
.msg-card {
  background: #fff; border-radius: 8px; padding: 10px 12px;
  margin-bottom: 8px; box-shadow: 0 1px 3px rgba(0,0,0,.06);
  cursor: pointer; transition: transform .1s;
}
.msg-card:active { transform: scale(.98); }
.msg-header { display: flex; align-items: center; gap: 8px; margin-bottom: 4px; }
.msg-date { font-size: 11px; color: #999; }
.msg-title { font-size: 14px; font-weight: 600; color: #323233; margin-bottom: 2px; }
.msg-summary { font-size: 12px; color: #666; margin-bottom: 6px; }
.msg-action { text-align: right; }
.quick-links { margin-top: 10px; background: #fff; border-radius: 8px; overflow: hidden; }

/* ====== 右侧视图区 ====== */
.right-panel {
  width: 0; flex: 2; min-width: 0;
  display: flex; flex-direction: column;
  background: #fff; border-left: 1px solid #e0e0e0;
}
.right-tabs {
  display: flex; align-items: center;
  border-bottom: 1px solid #e0e0e0; background: #fafafa;
  padding: 0 8px; height: 36px; gap: 4px;
}
.right-tab {
  padding: 6px 14px; font-size: 13px; cursor: pointer;
  border-radius: 4px 4px 0 0; color: #666;
  border-bottom: 2px solid transparent;
}
.right-tab.active { color: #1989fa; border-bottom-color: #1989fa; font-weight: 600; background: #fff; }
.right-close { margin-left: auto; cursor: pointer; font-size: 18px; color: #999; padding: 4px; }
.right-kline-wrap { flex: 1; overflow: hidden; }
.kline-iframe { width: 100%; height: 100%; border: none; }
.right-tupu-wrap { flex: 1; overflow-y: auto; }
.right-empty {
  width: 0; flex: 2; min-width: 0;
  display: flex; flex-direction: column; align-items: center; justify-content: center;
  background: #fafafa; border-left: 1px solid #e0e0e0;
}
</style>
