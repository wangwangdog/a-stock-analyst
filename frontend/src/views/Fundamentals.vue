<template>
  <div class="fund-page">
    <van-nav-bar
      :title="fundData?.name || symbol"
      left-arrow
      @click-left="$router.back()"
    />

    <van-loading v-if="loading" style="margin-top:60px" />

    <template v-if="fundData">
      <!-- 公司概要 -->
      <van-cell-group title="公司概要">
        <van-cell title="股票代码" :value="symbol" />
        <van-cell title="公司名称" :value="fundData.name" />
        <van-cell title="所属行业" :value="fundData.industry || '-'" />
        <van-cell title="上市日期" :value="fundData.listing_date || '-'" />
      </van-cell-group>

      <!-- 市值信息 -->
      <van-cell-group title="市值信息">
        <van-cell title="总市值">
          <template #value>
            <span class="num-highlight">{{ formatMoney(fundData.market_cap) }}</span>
          </template>
        </van-cell>
        <van-cell title="流通市值">
          <template #value>
            <span class="num-highlight">{{ formatMoney(fundData.circulating_market_cap) }}</span>
          </template>
        </van-cell>
        <van-cell title="总股本" :value="formatShares(fundData.total_shares)" />
        <van-cell title="流通股本" :value="formatShares(fundData.circulating_shares)" />
      </van-cell-group>

      <!-- 财务数据（占位） -->
      <van-cell-group title="财务指标（开发中）">
        <van-cell>
          <template #title>
            <van-tag plain type="warning">即将推出</van-tag>
            PE、PB、ROE、营收增长等指标将在后续版本中提供
          </template>
        </van-cell>
      </van-cell-group>
    </template>

    <van-empty v-if="!loading && !fundData" description="无法获取基本面数据" />
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRoute } from 'vue-router'
import { showToast } from 'vant'
import { getFundamentals } from '../utils/api.js'

const props = defineProps({ symbol: { type: String, default: '000001' } })
const route = useRoute()
const fundData = ref(null)
const loading = ref(true)

onMounted(async () => {
  const sym = route.params.symbol || props.symbol
  try {
    const res = await getFundamentals(sym)
    if (res.data.status === 'ok' && res.data.data) {
      fundData.value = res.data.data
    }
  } catch (e) {
    showToast({ message: '获取失败', type: 'fail' })
  } finally {
    loading.value = false
  }
})

function formatMoney(val) {
  if (!val) return '-'
  const y = val / 1e8
  if (y > 10000) return (y / 10000).toFixed(2) + '万亿'
  return y.toFixed(2) + '亿'
}

function formatShares(val) {
  if (!val) return '-'
  const y = val / 1e8
  return y.toFixed(2) + '亿股'
}
</script>

<style scoped>
.num-highlight {
  color: #1989fa;
  font-weight: 500;
}
</style>
