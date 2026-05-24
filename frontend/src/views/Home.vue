<template>
  <div class="home-split">
    <!-- 左侧：大笔买入排名 -->
    <div class="left-sidebar">
      <div class="sidebar-header">📊 大笔买入排名</div>
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

    <!-- 右侧：原有主页面内容 -->
    <div class="right-content" v-if="!activeStock">
      <van-nav-bar title="AI量化工具-DOGE" left-text="胖磊 🦞">
        <template #right>
          <span style="font-size:12px;color:#999;margin-right:8px" v-if="username">{{ username }}</span>
          <van-icon name="logout" @click="doLogout" style="padding:4px" />
        </template>
      </van-nav-bar>
      <div class="search-box">
        <van-search
          v-model="keyword"
          placeholder="输入股票代码或名称，如 000001"
          @search="onSearch"
          @clear="onClear"
          autofocus
        />
      </div>

      <div class="quick-links">
        <van-grid :column-num="3" :border="false">
          <van-grid-item icon="chart-trending-o" text="热门K线" to="/kline/000001" />
          <van-grid-item icon="info-o" text="自选股" @click="showFavorites = true; loadFavs()" />
          <van-grid-item icon="gem-o" text="策略选股" to="/strategies" />
          <van-grid-item icon="gem-o" text="量化选股" to="/strategies" />
        </van-grid>
      </div>

      <div v-if="recentStocks.length" class="recent-section">
        <van-cell-group title="最近查看">
          <van-cell
            v-for="s in recentStocks"
            :key="s.symbol"
            :title="s.name"
            :label="s.symbol"
            is-link
            @click="$router.push('/kline/' + s.symbol)"
          >
            <template #icon>
              <van-tag round plain type="primary" style="margin-right:8px">{{ s.symbol }}</van-tag>
            </template>
          </van-cell>
        </van-cell-group>
      </div>

      <div v-if="results.length" class="result-section">
        <van-cell-group title="搜索结果">
          <van-cell
            v-for="s in results"
            :key="s.symbol || s.code"
            :title="s.name"
            :label="s.symbol || s.code"
            is-link
            @click="goStock(s)"
          >
            <template #icon>
              <van-tag round plain type="primary" style="margin-right:8px">{{ s.symbol || s.code }}</van-tag>
            </template>
          </van-cell>
        </van-cell-group>
      </div>

      <van-empty v-if="!loading && keyword && !results.length && !recentStocks.length" description="没有匹配结果" />
      
      <van-action-sheet v-model:show="showFavorites" title="自选股">
        <div style="padding: 16px;">
          <van-cell-group v-if="favList.length">
            <van-cell
              v-for="f in favList" :key="f.symbol"
              :title="f.name || f.symbol"
              :label="f.symbol"
              is-link
              @click="$router.push('/kline/' + f.symbol); showFavorites = false"
            >
              <template #icon>
                <van-tag round plain type="primary" style="margin-right:8px">{{ f.symbol }}</van-tag>
              </template>
            </van-cell>
          </van-cell-group>
          <van-empty v-else description="暂无自选股，搜索后添加到自选" />
        </div>
      </van-action-sheet>
    </div>

  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import { getStockList } from '../utils/api.js'

const router = useRouter()
const keyword = ref('')
const results = ref([])
const loading = ref(false)
const allStocks = ref([])
const recentStocks = ref([])
const showFavorites = ref(false)
const favList = ref([])
const username = ref(localStorage.getItem('username') || '')

// 左侧大单排名
const bigBuyRank = ref([])
const activeStock = ref('')
const activeStockName = ref('')

function getU() { return localStorage.getItem('username') || '' }

function selectStock(item) {
  router.push('/kline/' + item.symbol)
}

async function loadFavs() {
  const u = getU()
  if (!u) return
  try {
    const resp = await fetch('/api/v1/favorites?username=' + encodeURIComponent(u))
    favList.value = await resp.json()
  } catch {}
}

async function loadBigBuyRank() {
  try {
    const resp = await fetch('/api/v1/bigbuy-rank')
    bigBuyRank.value = await resp.json()
  } catch {}
}

async function doLogout() {
  localStorage.removeItem('username')
  router.push('/login')
}

onMounted(async () => {
  loadFavs()
  loadBigBuyRank()
})

onMounted(async () => {
  // 尝试加载股票列表（预缓存）
  try {
    const res = await getStockList()
    if (res.data.status === 'ok') {
      allStocks.value = res.data.data
    }
  } catch (e) {
    // 静默失败
  }
  loadRecent()
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
  
  // 先从已缓存列表中搜索
  if (allStocks.value.length) {
    results.value = allStocks.value.filter(s => {
      const code = (s.code || s.symbol || '').toLowerCase()
      const name = (s.name || '').toLowerCase()
      return code.includes(q) || name.includes(q)
    }).slice(0, 20)
  }
  loading.value = false
}

function onClear() {
  results.value = []
}

function goStock(s) {
  const symbol = s.symbol || s.code
  addRecent(symbol, s.name || symbol)
  router.push('/kline/' + symbol)
}

function addRecent(symbol, name) {
  const existing = recentStocks.value.findIndex(s => s.symbol === symbol)
  if (existing >= 0) {
    recentStocks.value.splice(existing, 1)
  }
  recentStocks.value.unshift({ symbol, name: name || symbol })
  if (recentStocks.value.length > 10) {
    recentStocks.value = recentStocks.value.slice(0, 10)
  }
  localStorage.setItem('recent_stocks', JSON.stringify(recentStocks.value))
}

function loadRecent() {
  try {
    const saved = localStorage.getItem('recent_stocks')
    if (saved) recentStocks.value = JSON.parse(saved)
  } catch (e) {}
}
</script>

<style scoped>
.home-split {
  display: flex;
  height: 100vh;
  overflow: hidden;
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
.right-content {
  flex: 1;
  overflow-y: auto;
}
.search-box { background: #fff; }
.quick-links { margin: 8px 0; background: #fff; }
.recent-section { margin-top: 8px; }
.result-section { margin-top: 8px; }
</style>
