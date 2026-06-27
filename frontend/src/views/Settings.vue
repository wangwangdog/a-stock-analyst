<template>
  <div>
    <van-nav-bar title="👤 我的" left-arrow @click-left="$router.back()" />
    <div style="padding:16px">
      <!-- 用户信息 -->
      <div style="text-align:center;padding:24px 0">
        <van-icon name="contact" size="64" color="#1989fa" />
        <div style="margin-top:12px;font-size:18px;font-weight:bold">{{ username || '未登录' }}</div>
      </div>

      <van-cell-group title="设置">
        <van-cell title="股票代码前缀" value="SH/SZ 自动" is-link />
        <van-cell title="默认分析模型" value="DeepSeek" is-link />
        <van-cell title="K线默认周期" value="日K" is-link />
      </van-cell-group>

      <van-cell-group title="关于" style="margin-top:16px">
        <van-cell title="版本" value="v0.14" />
        <van-cell title="数据来源" value="AKShare / Baostock" />
        <van-cell title="AI 引擎" value="DeepSeek / TradingAgents-CN" />
      </van-cell-group>

      <van-button
        type="danger"
        block
        plain
        style="margin-top:24px"
        @click="doLogout"
      >
        退出登录
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { ref } from 'vue'
import { useRouter } from 'vue-router'
import { showConfirmDialog } from 'vant'

const router = useRouter()
const username = ref(localStorage.getItem('username') || '')

const doLogout = async () => {
  try {
    await showConfirmDialog({ title: '提示', message: '确定退出登录？' })
    localStorage.removeItem('username')
    localStorage.removeItem('token')
    router.push('/login')
  } catch {}
}
</script>
