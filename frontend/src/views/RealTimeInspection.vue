<template>
  <div>
    <div class="head">
      <h2>实时质检</h2>
      <div class="controls">
        <!-- G5 多摄并发：多选启动 -->
        <el-select
          v-model="selectedCameras"
          multiple
          collapse-tags
          collapse-tags-tooltip
          placeholder="选择摄像头（可多选）"
          style="width: 280px"
          :disabled="store.inspection.running"
        >
          <el-option
            v-for="c in store.cameras"
            :key="c.id"
            :label="c.name || c.id"
            :value="c.id"
          />
        </el-select>
        <el-button
          type="primary"
          :disabled="store.inspection.running || !selectedCameras.length"
          @click="start"
        >
          开始检测
        </el-button>
        <el-button
          type="primary"
          plain
          :disabled="store.inspection.running"
          @click="startAll"
        >
          全部启动
        </el-button>
        <el-button
          type="danger"
          :disabled="!store.inspection.running"
          @click="stop"
        >
          停止检测
        </el-button>
        <el-tag :type="store.inspection.running ? 'success' : 'info'">
          状态：{{ runningText }}
        </el-tag>
        <span class="counter">累计处理：<b>{{ store.inspection.total_processed }}</b></span>
      </div>
    </div>

    <!-- G4 批次管理：当前批次显示 + 新建/结束 -->
    <div class="batch-bar">
      <span class="batch-label">当前批次：</span>
      <el-select
        v-model="activeBatchId"
        placeholder="选择批次（可选）"
        clearable
        style="width: 240px"
      >
        <el-option
          v-for="b in openBatches"
          :key="b.batch_no"
          :label="b.batch_no + (b.product ? '（' + b.product + '）' : '')"
          :value="b.batch_no"
        />
      </el-select>
      <el-tag
        v-if="!activeBatchId"
        type="info"
      >
        未绑定
      </el-tag>
      <el-button
        size="small"
        type="success"
        @click="openBatchDialog"
      >
        新建批次
      </el-button>
      <el-button
        size="small"
        type="warning"
        :disabled="!activeBatchId"
        @click="endBatch"
      >
        结束批次
      </el-button>
    </div>

    <el-alert
      v-if="cameraError"
      type="warning"
      :closable="false"
      :title="cameraError"
      style="margin-bottom: 12px"
    />
    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      style="margin-bottom: 12px"
    />

    <el-row :gutter="16">
      <el-col :span="10">
        <el-card
          shadow="hover"
          style="min-height: 280px"
        >
          <div class="card-title">
            实时画面
            <span class="ts">{{ streamStatus }}</span>
          </div>
          <div class="video-wrap">
            <img
              v-if="videoSrc"
              :key="reloadKey"
              :src="videoSrc"
              class="video"
              alt="实时画面"
              @error="onVideoError"
            >
            <el-empty
              v-else
              description="请先选择摄像头"
            />
            <el-alert
              v-if="videoError"
              class="video-err"
              type="error"
              :closable="false"
              :title="videoError"
            />
          </div>
          <div class="video-bar">
            <el-select
              v-model="viewCamera"
              size="small"
              style="width: 170px"
              placeholder="查看画面"
            >
              <el-option
                v-for="c in store.cameras"
                :key="c.id"
                :label="c.name || c.id"
                :value="c.id"
              />
            </el-select>
            <el-button
              size="small"
              :disabled="!videoSrc"
              @click="reloadVideo"
            >
              刷新画面
            </el-button>
            <el-switch
              v-model="annotateVideo"
              active-text="叠加缺陷框"
              size="small"
            />
          </div>
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card
          shadow="hover"
          style="min-height: 280px"
        >
          <div class="card-title">
            最新检测结果
            <span
              v-if="displayResult"
              class="ts"
            >{{ displayResult.timestamp }}</span>
          </div>
          <!-- G5：多摄产生结果时可切换查看各摄最新一帧 -->
          <el-select
            v-if="resultCams.length > 1"
            v-model="resultCam"
            size="small"
            style="width: 200px; margin-bottom: 8px"
          >
            <el-option
              v-for="cid in resultCams"
              :key="cid"
              :label="camLabel(cid)"
              :value="cid"
            />
          </el-select>
          <template v-if="displayResult">
            <p class="metrics">
              摄像头：<b>{{ camLabel(displayResult.camera_id) }}</b>
              ｜ 缺陷数：<b>{{ displayResult.defect_count }}</b>
              ｜ 总数：<b>{{ displayResult.total_count }}</b>
              ｜ 不良率：<b>{{ (displayResult.defect_rate * 100).toFixed(1) }}%</b>
              ｜ 耗时：<b>{{ displayResult.processing_time_ms }}ms</b>
            </p>
            <el-table
              v-if="displayResult.defects && displayResult.defects.length"
              :data="displayResult.defects"
              size="small"
              border
              max-height="180"
            >
              <el-table-column
                prop="class_name"
                label="瑕疵类别"
              />
              <el-table-column label="置信度">
                <template #default="{ row }">
                  {{ (row.confidence * 100).toFixed(1) }}%
                </template>
              </el-table-column>
            </el-table>
            <el-empty
              v-else
              description="本帧无缺陷"
              :image-size="80"
            />
          </template>
          <el-empty
            v-else
            description="暂无检测数据，点击「开始检测」"
          />
        </el-card>
      </el-col>
    </el-row>

    <!-- G4 新建批次对话框 -->
    <el-dialog
      v-model="batchDialog"
      title="新建批次"
      width="420px"
    >
      <el-form
        :model="batchForm"
        label-width="80px"
      >
        <el-form-item
          label="批次号"
          required
        >
          <el-input
            v-model="batchForm.batch_no"
            placeholder="如 B20260903-01"
          />
        </el-form-item>
        <el-form-item label="产品">
          <el-input
            v-model="batchForm.product"
            placeholder="可选，如 衬衫-白色"
          />
        </el-form-item>
        <el-form-item label="备注">
          <el-input
            v-model="batchForm.note"
            type="textarea"
            :rows="2"
            placeholder="可选"
          />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="batchDialog = false">
          取消
        </el-button>
        <el-button
          type="primary"
          :loading="batchSaving"
          @click="createBatch"
        >
          创建批次
        </el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { useStore, actions } from '@/store'
import { createWebSocket } from '@/utils/websocket'
import { cameraApi, inspectionApi, batchApi } from '@/api'

const store = useStore()
// G5 多摄并发：selectedCameras 为启动目标（多选）；viewCamera 为画面查看对象
const selectedCameras = ref([])
const viewCamera = ref('')
const cameraError = ref('')
const error = ref('')
let ws = null

const reloadKey = ref(0)
const videoError = ref('')
const annotateVideo = ref(true)
// M7：实时画面地址改为一次性 stream ticket（?ticket=），避免 JWT 进 URL / 访问日志
const videoSrc = ref('')
async function loadVideo() {
  const id = viewCamera.value
  if (!id) {
    videoSrc.value = ''
    return
  }
  try {
    videoSrc.value = await cameraApi.videoUrl(id, 15, annotateVideo.value)
  } catch (e) {
    videoSrc.value = ''
    videoError.value = '画面地址获取失败：' + (e.response?.data?.detail || e.message)
  }
}
const streamStatus = computed(() => (store.inspection.running ? '检测直播中' : '画面预览中'))

watch([viewCamera, annotateVideo], () => {
  videoError.value = ''
  reloadKey.value += 1
  loadVideo()
})

function onVideoError() {
  videoError.value = '画面加载失败：请确认摄像头已启用、网络可达，且登录令牌有效'
}
function reloadVideo() {
  videoError.value = ''
  reloadKey.value += 1
  loadVideo()
}

// ---- G5 分摄结果：按 camera_id 缓存各摄最新一帧，可切换查看 ----
const resultsByCam = reactive({})
const resultCam = ref('')
const resultCams = computed(() => Object.keys(resultsByCam))
const displayResult = computed(() => {
  if (resultCam.value && resultsByCam[resultCam.value]) return resultsByCam[resultCam.value]
  return store.inspection.last_result
})
function camLabel(cid) {
  const c = (store.cameras || []).find((x) => x.id === cid)
  return c ? c.name || c.id : cid
}
const runningCameras = computed(() => store.inspection.running_cameras || [])
const runningText = computed(() => {
  if (!store.inspection.running) return '空闲'
  const n = runningCameras.value.length
  const scope = n > 1 ? `${n} 路` : runningCameras.value[0]?.camera_id || ''
  return `运行中（${scope} · ${store.inspection.detector_mode}）`
})

function ensureWs() {
  if (ws) return
  ws = createWebSocket((msg) => {
    if (msg.type === 'detection_result') {
      actions.setInspection({ last_result: msg.data, running: true })
      store.inspection.total_processed += 1
      const d = msg.data
      if (d.camera_id) {
        resultsByCam[d.camera_id] = d
        if (!resultCam.value) resultCam.value = d.camera_id
      }
      actions.setInspection({ detector_mode: d.is_simulation ? 'simulation' : 'yolo' })
    } else if (msg.type === 'control') {
      if (msg.action === 'stop') actions.setInspection({ running: false })
      if (msg.action === 'start') actions.setInspection({ running: true })
    }
  })
}

function start() {
  if (!selectedCameras.value.length) {
    ElMessage.warning('请先选择摄像头')
    return
  }
  ensureWs()
  // G5：多选以逗号列表下发；G4：开始检测时绑定当前批次（若已选）
  ws.send({
    action: 'start',
    camera_id: selectedCameras.value.join(','),
    batch_id: activeBatchId.value || undefined,
  })
  actions.setInspection({ running: true })
}

function startAll() {
  ensureWs()
  // G5：camera_id=all 启动全部启用摄像头
  ws.send({ action: 'start', camera_id: 'all', batch_id: activeBatchId.value || undefined })
  actions.setInspection({ running: true })
}

function stop() {
  if (ws) ws.send({ action: 'stop' })
  actions.setInspection({ running: false })
}

// ---- G4 批次管理 ----
const batches = ref([])
const activeBatchId = ref('')
const batchDialog = ref(false)
const batchSaving = ref(false)
const batchForm = reactive({ batch_no: '', product: '', note: '' })
const openBatches = computed(() => batches.value.filter((b) => !b.ended_at))

async function loadBatches() {
  try {
    batches.value = await batchApi.list()
  } catch {
    batches.value = []
  }
}
function openBatchDialog() {
  batchForm.batch_no = ''
  batchForm.product = ''
  batchForm.note = ''
  batchDialog.value = true
}
async function createBatch() {
  if (!batchForm.batch_no) {
    ElMessage.warning('请填写批次号')
    return
  }
  batchSaving.value = true
  try {
    const created = await batchApi.create({
      batch_no: batchForm.batch_no,
      product: batchForm.product || '',
      note: batchForm.note || '',
    })
    activeBatchId.value = created.batch_no || batchForm.batch_no
    batchDialog.value = false
    await loadBatches()
    ElMessage.success('批次已创建')
  } catch (e) {
    ElMessage.error('创建失败：' + (e.response?.data?.detail || e.message))
  } finally {
    batchSaving.value = false
  }
}
async function endBatch() {
  if (!activeBatchId.value) return
  try {
    await ElMessageBox.confirm(
      `确认结束批次「${activeBatchId.value}」？结束后将不再绑定新检测记录`,
      '提示',
      { type: 'warning' },
    )
  } catch {
    return
  }
  try {
    await batchApi.end(activeBatchId.value)
    ElMessage.success('批次已结束')
  } catch (e) {
    ElMessage.error('结束失败：' + (e.response?.data?.detail || e.message))
  } finally {
    activeBatchId.value = ''
    await loadBatches()
  }
}

async function loadCameras() {
  try {
    const list = await cameraApi.list()
    store.cameras = list
    if (list && list.length) {
      viewCamera.value = list[0].id
      selectedCameras.value = [list[0].id]
    }
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
      running_cameras: st.running_cameras || [],
    })
  } catch (e) {
    error.value = '获取检测状态失败：' + (e.response?.data?.detail || e.message)
  }
}

onMounted(() => {
  loadCameras()
  syncStatus()
  loadBatches()
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
