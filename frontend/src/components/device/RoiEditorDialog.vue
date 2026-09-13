<template>
  <el-dialog
    :model-value="modelValue"
    :title="'ROI 检测区域 — ' + (camera?.name || camera?.id || '')"
    width="720px"
    @update:model-value="emit('update:modelValue', $event)"
  >
    <el-alert
      type="info"
      :closable="false"
      style="margin-bottom: 10px"
      title="在画面上按住鼠标拖拽画出检测区域（可画多个）；只有区域内的目标会被检测，区域外干扰（传送带边缘、隔壁工位）不再计入。不配置则全画面检测。"
    />
    <div
      ref="canvasEl"
      class="roi-canvas"
      @mousedown="onMouseDown"
      @mousemove="onMouseMove"
      @mouseup="onMouseUp"
      @mouseleave="onMouseUp"
    >
      <img
        v-if="snapshot"
        :key="snapKey"
        :src="snapshot"
        class="roi-bg"
        alt="ROI 底图"
        @error="snapshot = ''"
      >
      <div
        v-else
        class="roi-bg-placeholder"
      >
        快照加载失败，仍可直接拖拽画框
      </div>
      <div
        v-for="(r, i) in rects"
        :key="i"
        class="roi-rect"
        :style="{ left: r.x * 100 + '%', top: r.y * 100 + '%', width: r.w * 100 + '%', height: r.h * 100 + '%' }"
      >
        <span class="roi-tag">ROI {{ i + 1 }}</span>
        <span
          class="roi-del"
          title="删除"
          @mousedown.stop
          @click="removeRect(i)"
        >×</span>
      </div>
      <div
        v-if="drawingRect"
        class="roi-rect drawing"
        :style="{ left: drawingRect.x * 100 + '%', top: drawingRect.y * 100 + '%', width: drawingRect.w * 100 + '%', height: drawingRect.h * 100 + '%' }"
      />
    </div>
    <div class="roi-list">
      <span
        v-if="!rects.length"
        class="roi-empty"
      >未配置（全画面检测）</span>
      <code
        v-for="(r, i) in rects"
        :key="i"
        class="roi-item"
      >
        ROI{{ i + 1 }}: x={{ r.x.toFixed(2) }}, y={{ r.y.toFixed(2) }}, w={{ r.w.toFixed(2) }}, h={{ r.h.toFixed(2) }}
      </code>
    </div>
    <template #footer>
      <el-button @click="clearRects">
        清空（全画面）
      </el-button>
      <el-button @click="emit('update:modelValue', false)">
        取消
      </el-button>
      <el-button
        type="primary"
        :loading="saving"
        @click="emit('save', camera.id, rects.map((r) => ({ ...r })))"
      >
        保存 ROI
      </el-button>
    </template>
  </el-dialog>
</template>

<script setup>
import { ref, watch } from 'vue'
import { cameraApi } from '@/api'

const props = defineProps({
  modelValue: { type: Boolean, default: false },
  saving: { type: Boolean, default: false },
  camera: { type: Object, default: null },
})
const emit = defineEmits(['update:modelValue', 'save'])

const canvasEl = ref(null)
const rects = ref([])
const drawingRect = ref(null)
const snapshot = ref('')
const snapKey = ref(0)
let dragStart = null

// 打开时载入既有 ROI（归一化坐标）并取一张快照做底图（仅辅助对位，失败不影响画框）
watch(
  () => [props.modelValue, props.camera],
  async ([open]) => {
    if (!open || !props.camera) return
    rects.value = (props.camera.roi || []).map((r) => ({ ...r }))
    drawingRect.value = null
    dragStart = null
    snapshot.value = ''
    try {
      snapshot.value = await cameraApi.snapshotUrl(props.camera.id, false, 80)
      snapKey.value += 1
    } catch {
      snapshot.value = ''
    }
  }
)

function point(e) {
  const el = canvasEl.value
  if (!el) return null
  const rect = el.getBoundingClientRect()
  const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height))
  return { x, y }
}

function onMouseDown(e) {
  if (e.button !== 0) return
  const p = point(e)
  if (!p) return
  dragStart = p
  drawingRect.value = { x: p.x, y: p.y, w: 0, h: 0 }
}

function onMouseMove(e) {
  if (!dragStart) return
  const p = point(e)
  if (!p) return
  drawingRect.value = {
    x: Math.min(dragStart.x, p.x),
    y: Math.min(dragStart.y, p.y),
    w: Math.abs(p.x - dragStart.x),
    h: Math.abs(p.y - dragStart.y),
  }
}

function onMouseUp() {
  if (!dragStart) return
  const r = drawingRect.value
  if (r && r.w > 0.01 && r.h > 0.01) {
    rects.value.push({ x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) })
  }
  dragStart = null
  drawingRect.value = null
}

function removeRect(i) {
  rects.value.splice(i, 1)
}
function clearRects() {
  rects.value = []
}
</script>

<style scoped>
.roi-canvas { position: relative; width: 100%; aspect-ratio: 4 / 3; background: #111; border-radius: 6px; overflow: hidden; cursor: crosshair; user-select: none; }
.roi-bg { width: 100%; height: 100%; object-fit: cover; display: block; pointer-events: none; }
.roi-bg-placeholder { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center; color: #909399; font-size: 13px; }
.roi-rect { position: absolute; border: 2px solid #f5a623; background: rgba(245, 166, 35, 0.12); box-sizing: border-box; }
.roi-rect.drawing { border-style: dashed; }
.roi-tag { position: absolute; left: 2px; top: 2px; font-size: 11px; color: #fff; background: rgba(245, 166, 35, 0.85); padding: 0 4px; border-radius: 2px; line-height: 16px; }
.roi-del { position: absolute; right: 0; top: 0; width: 18px; height: 18px; line-height: 16px; text-align: center; color: #fff; background: rgba(220, 60, 60, 0.9); cursor: pointer; font-size: 14px; border-radius: 0 0 0 3px; }
.roi-list { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 8px; min-height: 22px; }
.roi-item { font-size: 12px; background: #f4f4f5; padding: 2px 6px; border-radius: 3px; color: #606266; }
.roi-empty { font-size: 12px; color: #909399; }
</style>
