<template>
  <div class="home-split">
    <!-- ====== 左侧 Sidebar（共享组件）====== -->
    <Sidebar @select-stock="onBigbuyClick" />

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
import { ref, onMounted } from 'vue'
import { useRouter } from 'vue-router'
import { showToast } from 'vant'
import TupuPanel from '../components/TupuPanel.vue'
import Sidebar from '../components/Sidebar.vue'

const router = useRouter()
const rightView = ref('')
const rightSymbol = ref('')

function onBigbuyClick(symbol) {
  router.push('/kline/' + symbol)
}

onMounted(() => {
  const h = new Date().getHours()
  const msgs = ['还不睡？🌙','早上好 ☀️','上午好 📊','中午好 🥟','下午好 📈','晚上好 ☕']
  showToast(msgs[Math.min(Math.floor(h/4),5)]||msgs[5])
})
</script>

<style scoped>
.home-split { display:flex; height:calc(100vh - 50px); overflow:hidden; }

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
