<template>
  <div class="screener-page">
    <van-nav-bar title="选股筛选" left-arrow @click-left="$router.back()" />

    <van-form @submit="doScreen">
      <van-cell-group title="筛选条件">
        <van-field
          v-model="filters.industry"
          name="industry"
          label="行业"
          placeholder="如：银行、医药"
          clearable
        />
        <van-field
          v-model="filters.market_cap_min"
          name="market_cap_min"
          label="最小总市值(亿)"
          type="number"
          placeholder="如：100"
          clearable
        />
        <van-field
          v-model="filters.market_cap_max"
          name="market_cap_max"
          label="最大总市值(亿)"
          type="number"
          placeholder="如：10000"
          clearable
        />
      </van-cell-group>

      <div style="padding: 16px">
        <van-button round block type="primary" native-type="submit" :loading="loading">
          {{ loading ? '筛选中...' : '开始筛选' }}
        </van-button>
      </div>
    </van-form>

    <!-- 结果 -->
    <div v-if="results.length" class="result-area">
      <van-cell-group :title="`筛选结果 (${total}只)`">
        <van-cell
          v-for="s in results"
          :key="s.symbol"
          is-link
          @click="$router.push('/kline/' + s.symbol)"
        >
          <template #title>
            <span>{{ s.name }}</span>
            <van-tag plain style="margin-left: 8px">{{ s.symbol }}</van-tag>
          </template>
          <template #label>
            <span v-if="s.price" :style="{color: s.pct_change >= 0 ? '#ee0a24' : '#07c160'}">
              {{ s.price?.toFixed(2) }}
              {{ s.pct_change >= 0 ? '+' : '' }}{{ s.pct_change?.toFixed(2) }}%
            </span>
            <span v-if="s.industry" style="margin-left: 8px; color: #999">{{ s.industry }}</span>
          </template>
          <template #value>
            <span style="font-size:12px;color:#999">{{ formatMkt(s.market_cap) }}</span>
          </template>
        </van-cell>
      </van-cell-group>
    </div>

    <van-empty v-if="searched && !loading && !results.length" description="无匹配结果，试试放宽条件" />
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { showToast } from 'vant'
import { screenStocks } from '../utils/api.js'

const filters = ref({ industry: '', market_cap_min: '', market_cap_max: '' })
const results = ref([])
const total = ref(0)
const loading = ref(false)
const searched = ref(false)

async function doScreen() {
  loading.value = true
  searched.value = true
  try {
    const params = {}
    if (filters.value.industry) params.industry = filters.value.industry
    if (filters.value.market_cap_min) params.market_cap_min = parseFloat(filters.value.market_cap_min)
    if (filters.value.market_cap_max) params.market_cap_max = parseFloat(filters.value.market_cap_max)
    
    const res = await screenStocks(params)
    if (res.data.status === 'ok') {
      results.value = res.data.data?.slice(0, 100) || []
      total.value = res.data.total || 0
      showToast(`找到 ${total.value} 只`)
    } else {
      showToast({ message: '筛选失败', type: 'fail' })
    }
  } catch (e) {
    showToast({ message: '请求失败', type: 'fail' })
  } finally {
    loading.value = false
  }
}

function formatMkt(val) {
  if (!val) return ''
  return (val / 1e8).toFixed(0) + '亿'
}
</script>
