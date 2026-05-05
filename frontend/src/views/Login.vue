<template>
  <div class="login-page">
    <div class="login-box">
      <div class="login-title">🦞 A-Stock Analyst</div>
      <div class="login-subtitle">请输入用户名开始使用</div>
      <van-field
        v-model="username"
        placeholder="输入用户名（自动注册）"
        clearable
        autofocus
        @keypress.enter="doLogin"
      />
      <van-button type="primary" block :loading="loading" @click="doLogin" style="margin-top:16px">
        进入
      </van-button>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'

const router = useRouter()
const username = ref('')
const loading = ref(false)

onMounted(async () => {
  try {
    const resp = await fetch('/api/auth/me')
    const data = await resp.json()
    if (data.logged_in) {
      router.push('/')
    }
  } catch {}
})

async function doLogin() {
  if (!username.value.trim()) {
    showToast('请输入用户名')
    return
  }
  loading.value = true
  try {
    const resp = await fetch('/api/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ username: username.value.trim() })
    })
    const data = await resp.json()
    if (data.success) {
      router.push('/')
    }
  } catch (e) {
    showToast('登录失败')
  } finally {
    loading.value = false
  }
}
</script>

<style scoped>
.login-page {
  display: flex;
  justify-content: center;
  align-items: center;
  min-height: 100vh;
  background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
  padding: 20px;
}
.login-box {
  background: #fff;
  padding: 32px 24px;
  border-radius: 16px;
  width: 100%;
  max-width: 360px;
  box-shadow: 0 8px 32px rgba(0,0,0,0.15);
}
.login-title {
  font-size: 24px;
  font-weight: 700;
  text-align: center;
  margin-bottom: 4px;
}
.login-subtitle {
  font-size: 13px;
  color: #999;
  text-align: center;
  margin-bottom: 24px;
}
</style>
