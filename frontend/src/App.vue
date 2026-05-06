<template>
  <van-config-provider :theme="theme">
    <router-view />
    <van-tabbar v-model="active" route active-color="#1989fa" :border="true" safe-area-inset-bottom>
      <van-tabbar-item icon="search" to="/">搜索</van-tabbar-item>
      <van-tabbar-item icon="gem-o" to="/strategies">策略</van-tabbar-item>
      <van-tabbar-item icon="link-o" to="/links">链接</van-tabbar-item>
      <van-tabbar-item icon="contact" to="/settings">我的</van-tabbar-item>
    </van-tabbar>
  </van-config-provider>
</template>

<script setup>
import { ref } from 'vue'
import { useRoute } from 'vue-router'

const theme = ref('light')
const route = useRoute()

const tabMap = { '/': 0, '/strategies': 1, '/links': 2, '/settings': 3 }
const active = ref(tabMap[route.path] || 0)
</script>

<style>
:root {
  --van-nav-bar-height: 44px;
  --van-tabbar-height: 50px;
}
</style>
