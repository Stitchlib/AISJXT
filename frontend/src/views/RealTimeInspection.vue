<template>
  <div>
    <div class="head">
      <h2>实时质检</h2>
      <div class="controls">
        <el-select v-model="selectedCamera" placeholder="选择摄像头" style="width: 220px" :disabled="store.inspection.running">
          <el-option v-for="c in store.cameras" :key="c.id" :label="c.name || c.id" :value="c.id" />
        </el-select>
        <el-button type="primary" :disabled="store.inspection.running || !selectedCamera" @click="start">开始检测</el-button>
        <el-button type="danger" :disabled="!store.inspection.running" @click="stop">停止检测</el-button>
        <el-tag :type="store.inspection.running ? 'success' : 'info'">
          状态：{{ store.inspection.running ? '运行中（' + store.inspection.detector_mode + '）' : '空闲' }}
        </el-tag>
        <span class="counter">累计处理：<b>{{ store.inspection.total_processed }}</b></span>
      </div>
    </div>

    <el-alert v-if="cameraError" type="warning" :closable="false" :title="cameraError" style="margin-bottom: 12px" />
    <el-alert v-if="error" type="error" :closable="false" :title="error" style="margin-bottom: 12px" />

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card shadow="hover" style="min-height: 280px">
          <div class="card-title">
            实时画面
            <span class="ts">{{ streamStatus }}</span>
          </div>
          <div class="video-wrap">
            <img
              v-if="videoUrl"
              :key="reloadKey"
              :src="videoUrl"
              class="video"
              alt="实时画面"
              @error="onVideoError"
            />
            <el-empty v-else description="请先选择摄像头" />
            <el-alert
              v-if="videoError"
              class="video-err"
              type="error"
              :closable="false"
              :title="videoError"
            />
          </div>
          <div class="video-bar">
            <el-button size="small" :disabled="!videoUrl" @click="reloadVideo">刷新画面</el-button>
            <span class="hint">{{ selectedCamera || '—' }}</span>
          </div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card shadow="hover" style="min-height: 280px">
          <div class="card-title">
            最新检测结果
            <span v-if="lastResult" class="ts">{{ lastResult.timestamp }}</span>
          </div>
          <template v-if="lastResult">
            <p class="metrics">
              缺陷数：<b>{{ lastResult.defect_count }}</b>
              ｜ 总数：<b>{{ lastResult.total_count }}</b>
              ｜ 不良率：<b>{{ (lastResult.defect_rate * 100).toFixed(1) }}%</b>
              ｜ 耗时：<b>{{ lastResult.processing_time_ms }}ms</b>
            </p>
            <el-table v-if="lastResult.defects && lastResult.defects.length" :data="lastResult.defects" size="small" border max-height="180">
              <el-table-column prop="class_name" label="瑕疵类别" />
              <el-table-column label="置信度">
                <template #default="{ row }">{{ (row.confidence * 100).toFixed(1) }}%</template>
              </el-table-column>
            </el-table>
            <el-empty v-else description="本帧无缺陷" :image-size="80" />
          </template>
          <el-empty v-else description="暂无检测数据，点击「开始检测」" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { inject, ref, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage } from 'element-plus'
import { useStore, actions } from '@/store'
import { createWebSocket } from '@/utils/websocket'
import { cameraApi, inspectionApi } from '@/api'

const store = useStore()
const selectedCamera = ref('')
const cameraError = ref('')
const error = ref('')
let ws = null

const reloadKey = ref(0)
const videoError = ref('')
const videoUrl = computed(() => (selectedCamera.value ? cameraApi.videoUrl(selectedCamera.value, 15) : ''))
const streamStatus = computed(() => (store.inspection.running ? '检测直播中' : '画面预览中'))

watch(selectedCamera, () => {
  videoError.value = ''
  reloadKey.value += 1
})

function onVideoError() {
  videoError.value = '画面加载失败：请确认摄像头已启用、网络可达，且登录令牌有效'
}
function reloadVideo() {
  videoError.value = ''
  reloadKey.value += 1
}

const lastResult = computed(() => store.inspection.last_result)

function ensureWs() {
  if (ws) return
  ws = createWebSocket((msg) => {
    if (msg.type === 'detection_result') {
      actions.setInspection({ last_result: msg.data, running: true })
      store.inspection.total_processed += 1
      const d = msg.data
      actions.setInspection({ detector_mode: d.is_simulation ? 'simulation' : 'yolo' })
    } else if (msg.type === 'control') {
      if (msg.action === 'stop') actions.setInspection({ running: false })
      if (msg.action === 'start') actions.setInspection({ running: true })
    }
  })
}

function start() {
  if (!selectedCamera.value) {
    ElMessage.warning('请先选择摄像头')
    return
  }
  ensureWs()
  ws.send({ action: 'start', camera_id: selectedCamera.value })
  actions.setInspection({ running: true })
}

function stop() {
  if (ws) ws.send({ action: 'stop' })
  actions.setInspection({ running: false })
}

async function loadCameras() {
  try {
    const list = await cameraApi.list()
    store.cameras = list
    if (list && list.length) selectedCamera.value = list[0].id
  } catch (e) {
    cameraError.value = '摄像头列表加载失败：' + (e.response?.data?.detail || e.message)
  }
}

async function syncStatus() {
  try {
    const st = await inspectionApi.status()
    actions.setInspection({
      running: !!st.running,
      detector_mode: st.detector_mode || store.inspection.detector_mode,
      total_processed: st.total_processed || store.inspection.total_processed,
      last_result: st.last_result || store.inspection.last_result,
    })
  } catch (e) {
    error.value = '获取检测状态失败：' + (e.response?.data?.detail || e.message)
  }
}

onMounted(() => {
  loadCameras()
  syncStatus()
})
onUnmounted(() => ws && ws.close())
</script>

<style scoped>
.head { margin-bottom: 12px; }
.controls { display: flex; align-items: center; gap: 12px; flex-wrap: wrap; margin-top: 8px; }
.counter { font-size: 13px; color: #606266; }
.card-title { font-weight: 600; margin-bottom: 12px; color: #303133; }
.card-title .ts { float: right; font-size: 12px; color: #909399; font-weight: 400; }
.metrics { font-size: 14px; color: #606266; margin: 4px 0 12px; }
.frame-info { font-size: 14px; color: #606266; }
.path { color: #909399; word-break: break-all; }
.video-wrap { position: relative; width: 100%; min-height: 220px; background: #000; border-radius: 6px; overflow: hidden; display: flex; align-items: center; justify-content: center; }
.video { width: 100%; display: block; }
.video-err { position: absolute; left: 8px; right: 8px; bottom: 8px; }
.video-bar { display: flex; align-items: center; gap: 12px; margin-top: 10px; }
.video-bar .hint { font-size: 12px; color: #909399; word-break: break-all; }
</style>
