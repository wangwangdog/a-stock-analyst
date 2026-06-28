<template>
  <div class="news-chain-panel">
    <!-- 顶栏 -->
    <div class="ncp-header">
      <span class="ncp-title">{{ headerTitle }}</span>
      <div class="ncp-header-actions">
        <van-button v-if="!loading && data" size="mini" plain
                    :type="editMode ? 'danger' : 'default'"
                    @click="toggleEditMode" style="margin-right:4px">
          {{ editMode ? '完成编辑' : '✎ 编辑' }}
        </van-button>
        <van-icon name="cross" class="ncp-close" @click="$emit('close')" />
      </div>
    </div>

    <!-- 编辑工具栏 -->
    <div class="ncp-edit-toolbar" v-if="editMode && !loading && data">
      <span class="edit-hint">右键菜单操作节点 · 拖拽连线创建边</span>
    </div>

    <!-- 思考步骤 -->
    <div class="ncp-thinking" v-if="loading && visibleSteps.length">
      <div class="ncp-step" v-for="(step, i) in visibleSteps" :key="i">
        <span class="step-icon">{{ step.icon }}</span>
        <span class="step-text">{{ step.label }}</span>
        <span class="step-dot" v-if="i === visibleSteps.length - 1 && i < totalSteps - 1">⏳</span>
        <span class="step-dot" v-else>✅</span>
      </div>
    </div>

    <!-- 图谱区域 -->
    <div class="ncp-body" v-if="!loading && data" ref="bodyEl">
      <div class="ncp-half" v-for="(half, hi) in halves" :key="hi">
        <div class="ncp-half-title">
          {{ hi === 0 ? '🇨🇳' : '🌐' }} <b>{{ half.title }}</b> 产业链
          <span class="ncp-node-count">{{ half.nodes.length }}节点</span>
        </div>
        <div class="ncp-half-content">
          <div class="ncp-node-list">
            <div v-for="n in half.nodes" :key="n.id"
                 :class="['ncp-node-tag', n.type, { main: n.main }]"
                 @dblclick="expandNodeFromTag(n, hi === 0 ? 'domestic' : 'foreign')">
              {{ n.label }}
              <span class="ncp-node-type">{{ typeLabel(n.type) }}</span>
            </div>
          </div>
          <div :ref="el => setContainerRef(el, hi === 0 ? 'domestic' : 'foreign')"
               class="ncp-graph-container"></div>
        </div>
      </div>

      <canvas ref="bridgeCanvas" class="ncp-bridge"></canvas>
    </div>

    <!-- 加载/空占位 -->
    <div class="ncp-loading" v-if="loading && !visibleSteps.length">
      <van-loading color="#fff" size="24" />
      <span style="color:#999;font-size:12px;margin-top:8px">匹配产业链数据...</span>
    </div>
    <div class="ncp-empty" v-if="!loading && !data">
      <span style="color:#666">无匹配产业链数据</span>
    </div>

    <!-- 添加节点对话框 -->
    <van-dialog v-model:show="showAddDialog" title="添加节点" @confirm="confirmAddNode">
      <van-field v-model="addSearch" placeholder="搜公司/行业/产品..." clearable
                 @search="doAddSearch" @clear="addResults=[]" />
      <div v-if="addResults.length" class="add-results">
        <div v-for="r in addResults" :key="r.code || r.name"
             :class="['add-result-item', {active: selectedAdd?.code === r.code}]"
             @click="selectedAdd = r">
          <span class="ar-name">{{ r.name }}</span>
          <span class="ar-type">{{ r.type }}</span>
          <span class="ar-code">{{ r.code }}</span>
        </div>
      </div>
    </van-dialog>
  </div>
</template>

<script setup>
import { ref, computed, watch, nextTick, onMounted, onUnmounted } from 'vue'
import { showToast, showDialog } from 'vant'
import { Graph } from '@antv/g6'

const props = defineProps({
  news: { type: Object, default: () => ({}) },
})
const emit = defineEmits(['close'])

const loading = ref(false)
const data = ref(null)
const containerRefs = {}
const bridgeCanvas = ref(null)
const bodyEl = ref(null)
const totalSteps = ref(0)
const visibleSteps = ref([])
let stepTimer = null
const expanding = ref(false)
const editMode = ref(false)
const showAddDialog = ref(false)
const addSearch = ref('')
const addResults = ref([])
const selectedAdd = ref(null)
const addTargetSide = ref('domestic')

let graphs = { domestic: null, foreign: null }
const expandedNodes = new Set()
const graphEditLog = { domestic: [], foreign: [] }

// 右键菜单位置
const ctxMenu = ref({ show: false, x: 0, y: 0, node: null, edge: null, side: 'domestic' })

const headerTitle = computed(() => {
  if (loading) return '🤖 Hermes 分析中...'
  if (data.value) return `📊 ${data.value.main_domestic?.name || ''} ↔ ${data.value.main_foreign?.name || ''}`
  return props.news?.title || ''
})

const halves = computed(() => {
  if (!data.value) return []
  return [
    { title: data.value.main_domestic?.name || '国内', nodes: data.value.graph_domestic?.nodes || [], graphKey: 'graph_domestic' },
    { title: data.value.main_foreign?.name || '全球', nodes: data.value.graph_foreign?.nodes || [], graphKey: 'graph_foreign' },
  ]
})

const COLORS = {
  company: '#4fc3f7', industry: '#ffb74d', product: '#81c784',
  material: '#e57373', downstream: '#ce93d8',
  country: '#64b5f6', category: '#ff8a65',
}
const NODE_RADII = { company: 12, industry: 16, product: 10, material: 10, downstream: 10, country: 12, category: 14 }

function typeLabel(t) { return ({ company:'公司', industry:'行业', product:'产品', material:'材料', downstream:'下游', country:'国家', category:'分类' })[t] || t }

function setContainerRef(el, side) {
  if (el) containerRefs[side] = el
}

// ===== 编辑模式 =====

function toggleEditMode() {
  editMode.value = !editMode.value
  if (!editMode.value && graphEditLog.domestic.length + graphEditLog.foreign.length > 0) {
    flushEdits()
  }
}

async function flushEdits() {
  for (const side of ['domestic', 'foreign']) {
    const edits = graphEditLog[side]
    if (!edits.length) continue
    try {
      await fetch('/api/v1/chain/graph-edit', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ action: 'batch_save', source: side, edits }),
      })
    } catch (e) { console.error('save edits failed', e) }
    graphEditLog[side] = []
  }
}

function logEdit(side, edit) {
  graphEditLog[side].push(edit)
}

// ===== G6 图谱渲染 =====

function buildG6Data(graphData, side) {
  if (!graphData?.nodes) return { nodes: [], edges: [] }

  // 应用已保存的编辑
  const edits = graphEditLog[side] || []
  let nodes = [...graphData.nodes]
  let edges = [...graphData.edges]

  for (const e of edits) {
    if (e.action === 'add_node') {
      if (!nodes.find(n => n.id === e.node_id))
        nodes.push({ id: e.node_id, label: e.node_label, type: e.node_type })
    } else if (e.action === 'remove_node') {
      nodes = nodes.filter(n => n.id !== e.node_id)
      edges = edges.filter(ed => ed.source !== e.node_id && ed.target !== e.node_id)
    } else if (e.action === 'add_edge') {
      if (!edges.find(ed => ed.source === e.edge_source && ed.target === e.edge_target))
        edges.push({ source: e.edge_source, target: e.edge_target, label: e.edge_label || '' })
    } else if (e.action === 'remove_edge') {
      edges = edges.filter(ed => !(ed.source === e.edge_source && ed.target === e.edge_target))
    }
  }

  return {
    nodes: nodes.map(n => ({
      id: n.id,
      data: { type: n.type, label: n.label, main: !!n.main },
      style: {
        size: NODE_RADII[n.type] || 10,
        labelText: n.label,
        labelFontSize: n.main ? 12 : 9,
        labelFill: n.main ? '#fff' : 'rgba(255,255,255,0.7)',
        labelFontWeight: n.main ? 'bold' : 'normal',
        labelOffsetY: (NODE_RADII[n.type] || 10) + (n.main ? 14 : 10),
        fill: n.main ? '#ffffff' : (COLORS[n.type] || '#666'),
        stroke: 'transparent',
        lineWidth: 0,
        cursor: 'pointer',
        opacity: 1,
      },
    })),
    edges: edges.map(e => {
      const et = e.edgeType || ''
      let stroke, arrow
      if (et === 'upstream') { stroke = '#4fc3f7'; arrow = true }
      else if (et === 'downstream') { stroke = '#81c784'; arrow = true }
      else if (et === 'competitor') { stroke = '#e57373'; arrow = false }
      else if (et === 'foreign_peer') { stroke = '#ce93d8'; arrow = false }
      else if (et === 'belongs_to') { stroke = '#64b5f6'; arrow = false }
      else if (et === 'produces') { stroke = '#aed581'; arrow = false }
      else if (et === 'bridge') { stroke = '#ffb74d'; arrow = false }
      else { stroke = 'rgba(255,255,255,0.12)'; arrow = false }
      return {
        id: `${e.source}->${e.target}`,
        source: e.source,
        target: e.target,
        data: { label: e.label || '', edgeType: et },
        style: {
          stroke, lineWidth: 0.8, endArrow: arrow,
          labelText: et === 'competitor' ? (e.label || '') : '',
          labelFontSize: et === 'competitor' ? 8 : 0,
          labelFill: '#e57373',
          labelBackground: true,
          labelBackgroundFill: '#1a1a1a',
          labelBackgroundOpacity: 0.8,
        },
      }
    }),
  }
}

function createGraph(side) {
  const container = containerRefs[side]
  if (!container) return null

  const graphData = side === 'domestic' ? data.value?.graph_domestic : data.value?.graph_foreign
  if (!graphData) return null

  const g6Data = buildG6Data(graphData, side)

  const graph = new Graph({
    container,
    data: g6Data,
    width: container.clientWidth || 400,
    height: container.clientHeight || 280,
    animation: false,
    node: {
      style: {
        size: d => d.style?.size || 10,
        fill: d => d.style?.fill || '#666',
        stroke: 'transparent', lineWidth: 0,
        labelText: d => d.style?.labelText || '',
        labelFontSize: d => d.style?.labelFontSize || 9,
        labelFill: d => d.style?.labelFill || 'rgba(255,255,255,0.7)',
        labelFontWeight: d => d.style?.labelFontWeight || 'normal',
        labelOffsetY: d => d.style?.labelOffsetY || 20,
        cursor: 'pointer', opacity: 1,
      },
    },
    edge: {
      style: { stroke: 'rgba(255,255,255,0.08)', lineWidth: 0.5, endArrow: false, labelText: '', labelFontSize: 0 },
    },
    layout: { type: 'force', linkDistance: 150, preventOverlap: true, nodeSize: d => (d.style?.size || 10) * 2, animation: false, minMovement: 0.05 },
    behaviors: ['zoom-canvas', 'drag-canvas', 'drag-element'],
    autoResize: true,
    zoomRange: [0.2, 5],
    autoFit: { type: 'center', animation: false },
    plugins: [],
  })

    // 双击展开
  graph.on('node:dblclick', (ev) => {
    const nid = ev.target.id
    const orig = (side === 'domestic' ? data.value?.graph_domestic : data.value?.graph_foreign)?.nodes?.find(n => n.id === nid)
    if (orig) doExpand(orig, side)
  })

  // 编辑模式：右键菜单
  if (editMode.value) {
    graph.on('node:contextmenu', (ev) => {
      ev.preventDefault()
      showCtxMenu(ev, side, 'node')
    })
    graph.on('canvas:contextmenu', (ev) => {
      ev.preventDefault()
      showCtxMenu(ev, side, 'canvas')
    })
  }

  graph.render()
  return graph
}

function showCtxMenu(ev, side, type) {
  ctxMenu.value = { show: true, x: ev.clientX, y: ev.clientY, node: type === 'node' ? ev.target.id : null, edge: null, side }
}

function updateGraphData(side) {
  const graph = graphs[side]
  const graphData = side === 'domestic' ? data.value?.graph_domestic : data.value?.graph_foreign
  if (!graph || !graphData) return
  const g6Data = buildG6Data(graphData, side)
  graph.setData(g6Data)
  graph.render()
  graph.fitView()
}

function destroyGraphs() {
  Object.values(graphs).forEach(g => { if (g) { g.destroy(); g = null } })
  graphs = { domestic: null, foreign: null }
}

// ===== 右键操作 =====

function removeNode(side) {
  if (!ctxMenu.value.node) return
  const nid = ctxMenu.value.node
  logEdit(side, { action: 'remove_node', node_id: nid })
  updateGraphData(side)
  ctxMenu.value.show = false
  if (!editMode.value) flushEdits()
}

function addNode(side) {
  addTargetSide.value = side
  showAddDialog.value = true
  addSearch.value = ''
  addResults.value = []
  selectedAdd.value = null
  ctxMenu.value.show = false
}

function connectNodes(side, sourceId, targetId) {
  logEdit(side, { action: 'add_edge', edge_source: sourceId, edge_target: targetId, edge_label: '关联' })
  updateGraphData(side)
  if (!editMode.value) flushEdits()
}

async function doAddSearch() {
  if (!addSearch.value.trim()) return
  try {
    const r = await fetch(`/api/v1/chain/search?q=${encodeURIComponent(addSearch.value)}&limit=15`)
    const d = await r.json()
    addResults.value = d.results || []
  } catch (e) { addResults.value = [] }
}

function confirmAddNode() {
  if (!selectedAdd.value) { showToast('请选择一个节点'); return }
  const side = addTargetSide.value
  const item = selectedAdd.value
  const nid = item.type === 'company' ? `co_${item.code}` : `custom_${Date.now()}`
  const ntype = item.type === 'company' ? 'company' : (item.type === 'industry' ? 'industry' : 'product')

  logEdit(side, { action: 'add_node', node_id: nid, node_label: item.name, node_type: ntype })
  updateGraphData(side)
  showToast(`已添加 ${item.name}`)
}

// ===== 加载流程 =====

async function loadGraph() {
  const title = props.news?.title || ''
  const summary = props.news?.summary || ''
  if (!title) return

  loading.value = true
  data.value = null
  visibleSteps.value = []
  totalSteps.value = 0
  graphEditLog.domestic = []
  graphEditLog.foreign = []

  // 第一步：提交分析请求
  try {
    const submitResp = await fetch('/api/v1/chain/news-request', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ title, summary }),
    })
    const submitData = await submitResp.json()
    if (!submitData.task_id) {
      data.value = null; loading.value = false
      showToast({ message: '提交分析请求失败', type: 'fail' })
      return
    }

    const taskId = submitData.task_id
    visibleSteps.value = [{ icon: '🤖', label: 'Hermes 分析中...' }]
    totalSteps.value = 1

    // 第二步：轮询结果
    let pollCount = 0
    const pollTimer = setInterval(async () => {
      pollCount++
      try {
        const pollResp = await fetch(`/api/v1/chain/news-request/${taskId}`)
        const pollData = await pollResp.json()
        if (pollData.status === 'done' && pollData.result) {
          clearInterval(pollTimer)
          const d = pollData.result
          if (d.status === 'ok') {
            data.value = d
            if (d.steps?.length) {
              totalSteps.value = d.steps.length
              animateSteps(d.steps)
            } else {
              loading.value = false
              nextTick(() => renderBoth())
            }
          } else {
            data.value = null
            loading.value = false
            showToast({ message: d.message || '分析无结果', type: 'fail' })
          }
        } else if (pollData.status === 'error') {
          clearInterval(pollTimer)
          data.value = null; loading.value = false
          showToast({ message: pollData.message || '分析失败', type: 'fail' })
        } else if (pollCount > 180) {
          // 超时 6 分钟
          clearInterval(pollTimer)
          data.value = null; loading.value = false
          showToast({ message: '分析超时', type: 'fail' })
        }
      } catch (e) {
        console.error('poll error', e)
      }
    }, 2000)
  } catch (e) {
    console.error('news-request error', e)
    data.value = null
    loading.value = false
    showToast({ message: '请求失败', type: 'fail' })
  }
}

function animateSteps(steps) {
  visibleSteps.value = []
  let i = 0
  clearInterval(stepTimer)
  stepTimer = setInterval(() => {
    if (i < steps.length) {
      visibleSteps.value.push(steps[i])
      i++
    }
    if (i >= steps.length) {
      clearInterval(stepTimer)
      stepTimer = null
      nextTick(() => { loading.value = false; nextTick(() => renderBoth()) })
    }
  }, 600)
}

function renderBoth() {
  if (!data.value) return
  destroyGraphs()
  nextTick(() => {
    graphs.domestic = createGraph('domestic')
    graphs.foreign = createGraph('foreign')
    setTimeout(() => drawBridge(), 1000)
  })
}

// ===== 双击展开 =====

function expandNodeFromTag(node, side) {
  if (expanding.value) return
  doExpand(node, side)
}

async function doExpand(node, side) {
  if (!data.value) return
  const nodeId = node.id
  if (expandedNodes.has(nodeId)) {
    showToast({ message: `${node.label} 已展开`, type: 'success' })
    return
  }

  expanding.value = true
  showToast({ message: `展开 ${node.label}...`, type: 'loading', duration: 0 })

  try {
    let result = null
    const targetGraph = side === 'domestic' ? data.value.graph_domestic : data.value.graph_foreign
    if (!targetGraph) return

    if (node.type === 'company' && nodeId.startsWith('co_')) {
      const code = nodeId.replace('co_', '')
      // 智能展开：查供应链DB + Ollama分析上下游 → 返回图数据
      const resp = await fetch(`/api/v1/chain/expand-smart?code=${code}&name=${encodeURIComponent(node.label)}`)
      result = await resp.json()
    } else if (node.type === 'industry') {
      const resp = await fetch(`/api/v1/chain/industry/${encodeURIComponent(node.label)}?limit=10`)
      const d = await resp.json()
      if (d.companies?.length) {
        const resp2 = await fetch(`/api/v1/chain/stock/${d.companies[0].code}`)
        result = await resp2.json()
      }
    } else if (node.type === 'product' || node.type === 'material') {
      const resp = await fetch(`/api/v1/chain/product/${encodeURIComponent(node.label)}`)
      const d = await resp.json()
      if (d.producers?.length) {
        const resp2 = await fetch(`/api/v1/chain/stock/${d.producers[0].code}`)
        result = await resp2.json()
      }
    }

    if (result?.status === 'ok' && result.graph?.nodes?.length) {
      const existingIds = new Set(targetGraph.nodes.map(n => n.id))
      const newNodes = result.graph.nodes.filter(n => !existingIds.has(n.id))
      const newEdges = result.graph.edges.filter(e =>
        !targetGraph.edges.some(ee => ee.source === e.source && ee.target === e.target)
      )
      if (!newNodes.length) { showToast({ message: `${node.label} 无更多数据`, type: 'fail' }); return }
      targetGraph.nodes.push(...newNodes)
      targetGraph.edges.push(...newEdges)
      expandedNodes.add(nodeId)
      updateGraphData(side)
      showToast({ message: `展开 ${node.label}: +${newNodes.length}节点`, type: 'success' })
    } else {
      showToast({ message: `${node.label} 无产业链数据`, type: 'fail' })
    }
  } catch (e) { console.error('expand error', e); showToast({ message: '展开失败', type: 'fail' }) }

  expanding.value = false
}

// ===== 桥接线 =====

function drawBridge() {
  const bridge = bridgeCanvas.value
  const body = bodyEl.value
  if (!bridge || !body || !data.value) return
  const gD = graphs.domestic, gF = graphs.foreign
  if (!gD || !gF) return
  const mainD = data.value.graph_domestic?.nodes?.find(n => n.main)
  const mainF = data.value.graph_foreign?.nodes?.find(n => n.main)
  if (!mainD || !mainF) return

  let dNode, fNode
  try { dNode = gD.getNodeData(mainD.id); fNode = gF.getNodeData(mainF.id) } catch (e) { return }

  const dcEl = containerRefs.domestic, fcEl = containerRefs.foreign
  if (!dcEl || !fcEl) return
  const bodyRect = body.getBoundingClientRect()
  const dcRect = dcEl.getBoundingClientRect(), fcRect = fcEl.getBoundingClientRect()

  const x1 = dcRect.left - bodyRect.left + (dNode?.x || dcRect.width / 2)
  const y1 = dcRect.top - bodyRect.top + (dNode?.y || dcRect.height / 2)
  const x2 = fcRect.left - bodyRect.left + (fNode?.x || fcRect.width / 2)
  const y2 = fcRect.top - bodyRect.top + (fNode?.y || fcRect.height / 2)

  bridge.width = body.clientWidth; bridge.height = body.clientHeight
  bridge.style.width = body.clientWidth + 'px'; bridge.style.height = body.clientHeight + 'px'

  const ctx = bridge.getContext('2d')
  ctx.clearRect(0, 0, bridge.width, bridge.height)
  const grad = ctx.createLinearGradient(x1, y1, x2, y2)
  grad.addColorStop(0, 'rgba(255,255,255,0.25)')
  grad.addColorStop(1, 'rgba(100,181,246,0.25)')
  ctx.beginPath(); ctx.setLineDash([4, 6]); ctx.moveTo(x1, y1); ctx.lineTo(x2, y2)
  ctx.strokeStyle = grad; ctx.lineWidth = 1; ctx.stroke(); ctx.setLineDash([])
  ;[mainD, mainF].forEach((n, i) => {
    ctx.beginPath(); ctx.arc(i === 0 ? x1 : x2, i === 0 ? y1 : y2, 2, 0, 2 * Math.PI)
    ctx.fillStyle = i === 0 ? 'rgba(255,255,255,0.35)' : 'rgba(100,181,246,0.35)'; ctx.fill()
  })
}

watch(() => props.news, () => {
  expandedNodes.clear(); destroyGraphs(); graphEditLog.domestic = []; graphEditLog.foreign = []
  if (props.news?.title) loadGraph()
}, { immediate: true })

// 关闭右键菜单
document.addEventListener('click', () => { ctxMenu.value.show = false })

onUnmounted(() => { destroyGraphs(); clearInterval(stepTimer); window.removeEventListener('resize', onResize) })
let resizeTimer = null
function onResize() {
  clearTimeout(resizeTimer)
  resizeTimer = setTimeout(() => {
    if (data.value) { ['domestic','foreign'].forEach(s => graphs[s]?.resize()); drawBridge() }
  }, 200)
}
onMounted(() => window.addEventListener('resize', onResize))
</script>

<style scoped>
.news-chain-panel {
  display:flex; flex-direction:column; height:100%; background:#000; color:#fff;
}
.ncp-header {
  display:flex; align-items:center; padding:6px 10px;
  background:#111; border-bottom:1px solid #333; flex-shrink:0;
}
.ncp-header-actions { display:flex; align-items:center; }
.ncp-title { flex:1; font-size:12px; color:#ccc; overflow:hidden; text-overflow:ellipsis; white-space:nowrap; }
.ncp-close { font-size:18px; color:#666; cursor:pointer; padding:2px; }
.ncp-close:hover { color:#fff; }

.ncp-edit-toolbar {
  padding:3px 10px; background:#1a1a2e; border-bottom:1px solid #333;
  font-size:10px; color:#aaa; display:flex; align-items:center; justify-content:space-between;
}

.ncp-thinking {
  padding:8px 10px; background:#0a0a0a; border-bottom:1px solid #222; flex-shrink:0;
}
.ncp-step {
  display:flex; align-items:center; gap:6px; padding:3px 0;
  font-size:11px; color:#aaa; animation:fadeIn .3s ease-out;
}
.ncp-step .step-icon { flex-shrink:0; }
.ncp-step .step-text { flex:1; }
.ncp-step .step-dot { flex-shrink:0; font-size:10px; }
@keyframes fadeIn { from { opacity:0; transform:translateY(-4px); } to { opacity:1; transform:translateY(0); } }

.ncp-body { flex:1; display:flex; flex-direction:column; overflow:hidden; position:relative; }
.ncp-half {
  flex:1; display:flex; flex-direction:column; position:relative; min-height:0;
}
.ncp-half-title {
  padding:4px 10px; font-size:12px; color:rgba(255,255,255,0.5);
  border-bottom:1px solid rgba(255,255,255,0.08); flex-shrink:0;
  display:flex; align-items:center; gap:6px;
}
.ncp-half-title b { color:rgba(255,255,255,0.85); }
.ncp-node-count { font-size:9px; color:rgba(255,255,255,0.3); }

.ncp-half-content { flex:1; position:relative; display:flex; align-items:stretch; overflow:hidden; }

.ncp-node-list {
  width:90px; min-width:90px; overflow-y:auto; padding:4px;
  background:rgba(255,255,255,0.03); border-right:1px solid rgba(255,255,255,0.08);
  display:flex; flex-direction:column; gap:2px;
}
.ncp-node-tag {
  padding:3px 5px; border-radius:3px; font-size:10px; cursor:pointer;
  border-left:2px solid transparent; white-space:nowrap; overflow:hidden; text-overflow:ellipsis;
  transition:background .15s;
}
.ncp-node-tag:hover { background:rgba(255,255,255,0.1); }
.ncp-node-tag.company { border-left-color:#4fc3f7; color:#4fc3f7; }
.ncp-node-tag.industry { border-left-color:#ffb74d; color:#ffb74d; }
.ncp-node-tag.product { border-left-color:#81c784; color:#81c784; }
.ncp-node-tag.material { border-left-color:#e57373; color:#e57373; }
.ncp-node-tag.downstream { border-left-color:#ce93d8; color:#ce93d8; }
.ncp-node-tag.country { border-left-color:#64b5f6; color:#64b5f6; }
.ncp-node-tag.category { border-left-color:#ff8a65; color:#ff8a65; }
.ncp-node-tag.main { background:rgba(255,255,255,0.12); font-weight:700; font-size:11px; border-left-width:3px; border-left-color:#fff !important; color:#fff !important; }
.ncp-node-type { font-size:8px; color:rgba(255,255,255,0.3); margin-left:3px; }
.ncp-node-tag.main .ncp-node-type { color:rgba(255,255,255,0.5); }

.ncp-graph-container { flex:1; min-width:0; position:relative; overflow:hidden; }
.ncp-divider { height:1px; flex-shrink:0; background:rgba(255,255,255,0.8); margin:0; }
.ncp-bridge { position:absolute; top:0; left:0; pointer-events:none; z-index:10; }
.ncp-loading, .ncp-empty {
  flex:1; display:flex; flex-direction:column; align-items:center; justify-content:center;
}

/* 添加节点搜索结果 */
.add-results { max-height:300px; overflow-y:auto; padding:4px 0; }
.add-result-item {
  display:flex; align-items:center; gap:6px; padding:6px 12px; cursor:pointer;
  font-size:12px; border-bottom:1px solid #f0f0f0; transition:background .15s;
}
.add-result-item:hover { background:#e8f0fe; }
.add-result-item.active { background:#d0e4ff; }
.ar-name { flex:1; color:#333; }
.ar-type { font-size:10px; color:#999; }
.ar-code { font-size:10px; color:#1989fa; font-family:monospace; }
</style>
