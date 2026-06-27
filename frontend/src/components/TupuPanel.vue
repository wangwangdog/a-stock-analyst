<template>
  <div class="tupu-panel">
    <van-loading v-if="loading" style="padding: 40px; text-align: center" />

    <div v-if="!loading && data" class="tupu-content">
      <!-- 公司信息 -->
      <van-cell-group title="🏢 公司信息">
        <van-cell :title="data.name" :label="data.code">
          <template #value>{{ data.fullname }}</template>
        </van-cell>
      </van-cell-group>

      <!-- 所属行业 -->
      <van-cell-group v-if="data.industries?.length" title="🏭 所属行业">
        <van-cell v-for="ind in data.industries" :key="ind.code"
                  :title="ind.name" is-link @click="viewIndustry(ind.name)" />
      </van-cell-group>

      <!-- 主营产品 -->
      <van-cell-group v-if="data.main_products?.length" title="📦 主营产品">
        <van-cell v-for="(prod, i) in data.main_products.slice(0, 10)" :key="i"
                  :title="prod.name" is-link @click="viewProduct(prod.name)" />
        <van-cell v-if="data.main_products.length > 10"
                  :title="`+${data.main_products.length - 10} 更多...`" />
      </van-cell-group>

      <!-- 上游原材料 -->
      <van-cell-group v-if="data.upstream?.length" title="⬆️ 上游原材料">
        <van-cell v-for="(up, i) in data.upstream.slice(0, 10)" :key="'up'+i"
                  :title="up.material" :label="`用于生产: ${up.product}`" />
      </van-cell-group>

      <!-- 下游应用 -->
      <van-cell-group v-if="data.downstream?.length" title="⬇️ 下游应用">
        <van-cell v-for="(down, i) in data.downstream.slice(0, 10)" :key="'down'+i"
                  :title="down.product" :label="`使用: ${down.uses}`" />
      </van-cell-group>

      <!-- 同行业公司 -->
      <van-cell-group v-if="data.peers?.length" title="👥 同行业公司">
        <van-cell v-for="p in data.peers.slice(0, 10)" :key="p.code"
                  :title="p.name" :label="p.code" is-link @click="viewChain(p.code)" />
      </van-cell-group>

      <!-- 图谱 Canvas -->
      <div v-if="data.graph?.nodes?.length" class="graph-section">
        <div class="section-title">🗺️ 产业链图谱</div>
        <div ref="graphEl" class="graph-canvas"></div>
      </div>

      <van-empty v-if="!data.industries?.length && !data.main_products?.length"
                 description="暂无产业链数据" />
    </div>
  </div>
</template>

<script setup>
import { ref, watch, nextTick, onMounted } from 'vue'

const props = defineProps({ symbol: { type: String, default: '000001' } })
const emit = defineEmits(['viewIndustry', 'viewProduct', 'viewChain'])

const loading = ref(false)
const data = ref(null)
const graphEl = ref(null)

async function loadChain(code) {
  if (!code) return
  loading.value = true
  data.value = null
  try {
    const resp = await fetch(`/api/v1/chain/stock/${code}`)
    const d = await resp.json()
    data.value = d
  } catch (e) {
    data.value = null
  } finally {
    loading.value = false
    await nextTick()
    if (data.value?.graph?.nodes?.length) renderGraph()
  }
}

function viewIndustry(name) { emit('viewIndustry', name) }
function viewProduct(name) { emit('viewProduct', name) }
function viewChain(code) {
  loadChain(code)
}

watch(() => props.symbol, (val) => { if (val) loadChain(val) }, { immediate: true })

// ====== Canvas 力导向图谱 ======
function renderGraph() {
  const el = graphEl.value
  if (!el || !data.value?.graph) return
  el.innerHTML = ''

  const { nodes, edges } = data.value.graph
  if (!nodes.length) return

  const W = el.clientWidth || 350
  const H = 300
  const canvas = document.createElement('canvas')
  canvas.width = W; canvas.height = H
  canvas.style.cssText = `width:${W}px;height:${H}px`
  el.appendChild(canvas)
  const ctx = canvas.getContext('2d')

  const colors = {
    company: '#1989fa', industry: '#ff976a', product: '#07c160',
    material: '#ee0a24', downstream_product: '#9768d1',
  }

  const cx = W / 2, cy = H / 2, r = Math.min(W, H) * 0.32
  nodes.forEach((n, i) => {
    const a = (2 * Math.PI * i) / nodes.length - Math.PI / 2
    n.x = cx + r * Math.cos(a); n.y = cy + r * Math.sin(a)
    n.vx = 0; n.vy = 0
  })

  function tick() {
    for (let i = 0; i < nodes.length; i++) {
      for (let j = i + 1; j < nodes.length; j++) {
        const dx = nodes[i].x - nodes[j].x, dy = nodes[i].y - nodes[j].y
        const d = Math.max(Math.sqrt(dx*dx+dy*dy), 1)
        const f = 200 / (d*d)
        nodes[i].vx += (dx/d)*f*.1; nodes[i].vy += (dy/d)*f*.1
        nodes[j].vx -= (dx/d)*f*.1; nodes[j].vy -= (dy/d)*f*.1
      }
    }
    for (const e of edges) {
      const s = nodes.find(n => n.id === e.source), t = nodes.find(n => n.id === e.target)
      if (!s || !t) continue
      const dx = t.x - s.x, dy = t.y - s.y, d = Math.max(Math.sqrt(dx*dx+dy*dy), 1)
      const f = .01 * d
      s.vx += (dx/d)*f; s.vy += (dy/d)*f
      t.vx -= (dx/d)*f; t.vy -= (dy/d)*f
    }
    for (const n of nodes) {
      n.vx += (cx-n.x)*.001; n.vy += (cy-n.y)*.001
      n.x += n.vx; n.y += n.vy
      n.vx *= .9; n.vy *= .9
      n.x = Math.max(15, Math.min(W-15, n.x))
      n.y = Math.max(15, Math.min(H-15, n.y))
    }
    ctx.clearRect(0, 0, W, H)
    for (const e of edges) {
      const s = nodes.find(n => n.id === e.source), t = nodes.find(n => n.id === e.target)
      if (!s || !t) continue
      ctx.beginPath(); ctx.moveTo(s.x, s.y); ctx.lineTo(t.x, t.y)
      ctx.strokeStyle = '#ddd'; ctx.lineWidth = 1; ctx.stroke()
      if (e.label) {
        const mx = (s.x+t.x)/2, my = (s.y+t.y)/2
        ctx.fillStyle = '#999'; ctx.font = '8px sans-serif'; ctx.textAlign = 'center'
        ctx.fillText(e.label, mx, my-3)
      }
    }
    for (const n of nodes) {
      const color = colors[n.type] || '#666', rad = n.type === 'company' ? 10 : 7
      ctx.beginPath(); ctx.arc(n.x, n.y, rad, 0, 2*Math.PI)
      ctx.fillStyle = color; ctx.fill()
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 1.5; ctx.stroke()
      ctx.fillStyle = '#333'; ctx.font = '9px sans-serif'; ctx.textAlign = 'center'
      const lbl = n.label.length > 6 ? n.label.slice(0,5)+'…' : n.label
      ctx.fillText(lbl, n.x, n.y+rad+11)
    }
  }
  for (let i = 0; i < 100; i++) tick()
}
</script>

<style scoped>
.tupu-panel { min-height: 200px; }
.tupu-content { padding-bottom: 40px; }
.graph-section { margin-top: 8px; background: #fff; }
.section-title {
  padding: 10px 16px; font-size: 14px; font-weight: 600;
  background: #f7f8fa; border-top: 1px solid #ebedf0;
}
.graph-canvas { padding: 12px; min-height: 200px; }
</style>
