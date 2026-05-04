<template>
  <van-config-provider :theme="theme">
    <router-view />
    <van-tabbar v-model="active" route active-color="#1989fa" :border="true" safe-area-inset-bottom>
      <van-tabbar-item icon="search" to="/">搜索</van-tabbar-item>
      <van-tabbar-item icon="chart-trending-o" to="/kline/000001">K线</van-tabbar-item>
      <van-tabbar-item icon="info-o" to="/fund/000001">基本面</van-tabbar-item>
      <van-tabbar-item icon="filter-o" to="/screener">筛选</van-tabbar-item>
    </van-tabbar>
  </van-config-provider>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const theme = ref('light')
const route = useRoute()

const tabMap = { '/': 0, '/kline/000001': 1, '/fund/000001': 2, '/screener': 3 }
const active = ref(tabMap[route.path] || 0)
</script>

<style>
:root {
  --van-nav-bar-height: 44px;
  --van-tabbar-height: 50px;
}
</style>
