<template>
  <div class="panda-container">
    <van-nav-bar
      title="📊 Panda Quantflow 策略管理"
      left-arrow
      @click-left="$router.back()"
    >
      <template #right>
        <van-icon name="replay" @click="refreshIframe" style="padding: 4px" />
      </template>
    </van-nav-bar>
    <iframe
      ref="iframeRef"
      :src="iframeUrl"
      frameborder="0"
      class="panda-iframe"
    ></iframe>
  </div>
</template>

<script setup>
import { ref } from 'vue'

const iframeRef = ref(null)
const iframeUrl = ref('/quantflow/')

function refreshIframe() {
  // Force refresh by re-setting the URL
  iframeUrl.value = ''
  setTimeout(() => {
    iframeUrl.value = '/quantflow/'
  }, 50)
}
</script>

<style scoped>
.panda-container {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background: #fff;
}
.panda-iframe {
  flex: 1;
  width: 100%;
  border: none;
}
</style>
