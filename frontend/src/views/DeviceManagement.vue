<template>
  <div>
    <div class="head">
      <h2>设备管理</h2>
      <div class="controls">
        <el-button type="primary" @click="scan" :loading="scanning">扫描网络摄像头</el-button>
        <el-button v-if="canOperate" type="warning" @click="openDiscover" :loading="discovering">发现并自动添加</el-button>
        <el-button v-if="canOperate" type="success" @click="openAdd">+ 添加设备</el-button>
      </div>
    </div>

    <el-alert v-if="error" type="error" :closable="false" :title="error" style="margin-bottom: 12px" />

    <el-alert
      v-if="scanResult !== null"
      :title="'在网段 ' + scanSubnet + ' 中发现 ' + scanResult.length + ' 个候选设备'"
      type="info"
      style="margin-bottom: 12px"
    />

    <el-card v-loading="loading" shadow="hover">
      <el-empty v-if="!loading && cameras.length === 0" description="暂无设备，请添加或扫描" />
      <el-table v-else :data="cameras" border>
        <el-table-column label="实时缩略图" width="110" align="center">
          <template #default="{ row }">
            <el-image
              v-if="row.enabled"
              :src="snapshotUrl(row.id)"
              :preview-src-list="previewShotUrl(row.id) ? [previewShotUrl(row.id)] : []"
              fit="cover"
              class="thumb"
              hide-on-click-modal
            >
              <template #error>
                <div class="thumb-placeholder">加载中</div>
              </template>
            </el-image>
            <div v-else class="thumb-placeholder disabled">已停用</div>
          </template>
        </el-table-column>
        <el-table-column prop="id" label="设备ID" min-width="140" />
        <el-table-column prop="name" label="名称" min-width="140" />
        <el-table-column prop="type" label="类型" width="120">
          <template #default="{ row }">
            {{ typeLabel(row.type) }}
          </template>
        </el-table-column>
        <el-table-column prop="source" label="来源" min-width="160" show-overflow-tooltip />
        <el-table-column label="启用" width="90" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="(v) => toggleEnabled(row, v)" />
          </template>
        </el-table-column>
        <el-table-column prop="status" label="状态" width="110">
          <template #default="{ row }">
            <el-tag :type="row.status === 'online' ? 'success' : 'info'" size="small">{{ row.status }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column prop="resolution" label="分辨率" width="120" />
        <el-table-column label="操作" width="340" fixed="right">
          <template #default="{ row }">
            <el-tag v-if="row.id === activeId" type="success" size="small" style="margin-right: 6px">当前</el-tag>
            <el-button v-else-if="canOperate" type="primary" link size="small" @click="setActive(row)">设为当前</el-button>
            <el-button type="success" link size="small" @click="openPreview(row)">预览</el-button>
            <el-button v-if="canOperate" type="info" link size="small" @click="openEdit(row)">编辑</el-button>
            <el-button type="warning" link size="small" @click="openRoi(row)">
              ROI{{ row.roi && row.roi.length ? '(' + row.roi.length + ')' : '' }}
            </el-button>
            <el-button v-if="canAdmin" type="danger" link size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-dialog v-model="discoverDialog" title="发现并自动添加网络摄像头" width="460px">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
        title="将扫描网段、逐一探测常见 RTSP 地址，验证可取流后自动写入配置并设为当前摄像头。" />
      <el-form :model="dform" label-width="92px">
        <el-form-item label="网段"><el-input v-model="dform.subnet" placeholder="如 192.168.1" /></el-form-item>
        <el-form-item label="账号"><el-input v-model="dform.username" placeholder="匿名可留空" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="dform.password" type="password" placeholder="匿名可留空" show-password /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="discoverDialog = false">取消</el-button>
        <el-button type="warning" :loading="discovering" @click="doDiscover">开始发现</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="addDialog" title="添加设备" width="460px">
      <el-form :model="form" label-width="90px">
        <el-form-item label="设备ID"><el-input v-model="form.id" placeholder="如 cam_002" /></el-form-item>
        <el-form-item label="名称"><el-input v-model="form.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="form.type" style="width: 100%">
            <el-option label="RTSP" value="rtsp" />
            <el-option label="USB" value="usb" />
            <el-option label="HTTP" value="http" />
            <el-option label="仿真" value="simulation" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源"><el-input v-model="form.source" placeholder="rtsp://... 或 0" /></el-form-item>
        <el-form-item label="账号"><el-input v-model="form.username" placeholder="匿名可留空" /></el-form-item>
        <el-form-item label="密码"><el-input v-model="form.password" type="password" placeholder="匿名可留空" show-password /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="form.enabled" /></el-form-item>
      </el-form>
      <div v-if="addPreviewSrc" class="add-preview">
        <div class="add-preview-head">
          <span>实时预览（保存前先确认可取流）</span>
          <el-button size="small" text type="primary" @click="reloadAddPreview">刷新预览</el-button>
        </div>
        <div class="add-preview-wrap">
          <img v-if="addPreviewSrc" :key="addPreviewKey" :src="addPreviewSrc" class="add-preview-img" alt="摄像头预览" @error="onAddPreviewError" />
          <el-alert v-if="addPreviewError" type="warning" :closable="false" :title="addPreviewError" />
        </div>
      </div>
      <template #footer>
        <el-button @click="addDialog = false">取消</el-button>
        <el-button :loading="testing" @click="testAdd">测试连接</el-button>
        <el-button type="primary" :loading="saving" @click="add">保存</el-button>
      </template>
    </el-dialog>

    <!-- 第三期 1.1/1.2：编辑设备。来源/凭据仅 admin 可改；账号密码留空=不修改 -->
    <el-dialog v-model="editDialog" :title="'编辑设备 — ' + (editForm.id || '')" width="460px">
      <el-alert type="info" :closable="false" style="margin-bottom: 12px"
        title="来源与账号/密码仅管理员可修改；账号、密码留空表示保持不变。" />
      <el-form :model="editForm" label-width="90px">
        <el-form-item label="名称"><el-input v-model="editForm.name" /></el-form-item>
        <el-form-item label="类型">
          <el-select v-model="editForm.type" style="width: 100%" :disabled="!canAdmin">
            <el-option label="RTSP" value="rtsp" />
            <el-option label="USB" value="usb" />
            <el-option label="HTTP" value="http" />
            <el-option label="仿真" value="simulation" />
          </el-select>
        </el-form-item>
        <el-form-item label="来源">
          <el-input v-model="editForm.source" :disabled="!canAdmin" placeholder="rtsp://... 或 0" />
        </el-form-item>
        <el-form-item label="账号">
          <el-input v-model="editForm.username" :disabled="!canAdmin" placeholder="留空=不修改" />
        </el-form-item>
        <el-form-item label="密码">
          <el-input v-model="editForm.password" type="password" :disabled="!canAdmin" placeholder="留空=不修改" show-password />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="editForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="editDialog = false">取消</el-button>
        <el-button type="primary" :loading="saving" @click="saveEdit">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialog" title="实时画面预览" width="700px">
      <div class="preview-wrap">
        <img v-if="previewSrc" :key="previewKey" :src="previewSrc" class="preview" alt="实时画面预览" @error="onPreviewError" />
        <el-empty v-else description="无可预览设备" />
        <el-alert
          v-if="previewError"
          type="error"
          :closable="false"
          :title="previewError"
          style="margin-top: 8px"
        />
      </div>
      <template #footer>
        <el-button @click="previewDialog = false">关闭</el-button>
        <el-button type="primary" @click="reloadPreview">刷新预览</el-button>
      </template>
    </el-dialog>

    <!-- G6 ROI 检测区域编辑：在画面上拖拽矩形，归一化存储 -->
    <el-dialog v-model="roiDialog" :title="'ROI 检测区域 — ' + (roiCamera?.name || roiCamera?.id || '')" width="720px">
      <el-alert
        type="info"
        :closable="false"
        style="margin-bottom: 10px"
        title="在画面上按住鼠标拖拽画出检测区域（可画多个）；只有区域内的目标会被检测，区域外干扰（传送带边缘、隔壁工位）不再计入。不配置则全画面检测。"
      />
      <div
        ref="roiCanvas"
        class="roi-canvas"
        @mousedown="onRoiMouseDown"
        @mousemove="onRoiMouseMove"
        @mouseup="onRoiMouseUp"
        @mouseleave="onRoiMouseUp"
      >
        <img v-if="roiSnapshot" :key="roiSnapKey" :src="roiSnapshot" class="roi-bg" alt="ROI 底图" @error="roiSnapshot = ''" />
        <div v-else class="roi-bg-placeholder">快照加载失败，仍可直接拖拽画框</div>
        <div
          v-for="(r, i) in roiRects"
          :key="i"
          class="roi-rect"
          :style="{ left: r.x * 100 + '%', top: r.y * 100 + '%', width: r.w * 100 + '%', height: r.h * 100 + '%' }"
        >
          <span class="roi-tag">ROI {{ i + 1 }}</span>
          <span class="roi-del" title="删除" @mousedown.stop @click="removeRoi(i)">×</span>
        </div>
        <div
          v-if="drawingRect"
          class="roi-rect drawing"
          :style="{ left: drawingRect.x * 100 + '%', top: drawingRect.y * 100 + '%', width: drawingRect.w * 100 + '%', height: drawingRect.h * 100 + '%' }"
        />
      </div>
      <div class="roi-list">
        <span v-if="!roiRects.length" class="roi-empty">未配置（全画面检测）</span>
        <code v-for="(r, i) in roiRects" :key="i" class="roi-item">
          ROI{{ i + 1 }}: x={{ r.x.toFixed(2) }}, y={{ r.y.toFixed(2) }}, w={{ r.w.toFixed(2) }}, h={{ r.h.toFixed(2) }}
        </code>
      </div>
      <template #footer>
        <el-button @click="clearRoi">清空（全画面）</el-button>
        <el-button @click="roiDialog = false">取消</el-button>
        <el-button type="primary" :loading="roiSaving" @click="saveRoi">保存 ROI</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onUnmounted, watch } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cameraApi, configApi } from '@/api'
import { actions, useStore } from '@/store'

const store = useStore()
const loading = ref(false)
const scanning = ref(false)
const discovering = ref(false)
const saving = ref(false)
const error = ref('')
const cameras = ref([])
const scanResult = ref(null)
const scanSubnet = ref('192.168.1')
const activeId = ref('')

const addDialog = ref(false)
const form = reactive({ id: '', name: '', type: 'rtsp', source: '', enabled: true, username: '', password: '' })
const testing = ref(false)

// 角色能力（第三期 1.1，与后端权限矩阵一致）：
// operator+ 可增改普通字段/设当前/发现；删除与来源/凭据修改仅 admin
const canOperate = computed(() => ['admin', 'operator'].includes(store.user?.role || ''))
const canAdmin = computed(() => store.user?.role === 'admin')

// 编辑设备：来源默认显示掩码值；账号/密码留空=不修改；
// 含 ":***@" 的掩码回传由后端视为"未修改"，绝不写穿真实凭据
const editDialog = ref(false)
const editForm = reactive({ id: '', name: '', type: 'rtsp', source: '', username: '', password: '', enabled: true })
const editOriginal = reactive({ source: '' })

function openEdit(row) {
  editForm.id = row.id
  editForm.name = row.name
  editForm.type = row.type
  editForm.source = row.source_masked || row.source || ''
  editForm.username = ''
  editForm.password = ''
  editForm.enabled = row.enabled !== false
  editOriginal.source = row.source_masked || row.source || ''
  editDialog.value = true
}

async function saveEdit() {
  if (!editForm.name) {
    ElMessage.warning('请填写名称')
    return
  }
  const payload = { name: editForm.name, enabled: editForm.enabled }
  if (editForm.type) payload.type = editForm.type
  const src = (editForm.source || '').trim()
  // 仅当来源被真正改动（且不含掩码标记）才提交 → 后端按 admin 权限校验
  if (src && src !== editOriginal.source && !src.includes(':***@')) payload.source = src
  if (editForm.username.trim()) payload.username = editForm.username.trim()
  if (editForm.password) payload.password = editForm.password
  saving.value = true
  try {
    await cameraApi.update(editForm.id, payload)
    ElMessage.success('已保存')
    editDialog.value = false
    await load()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

const discoverDialog = ref(false)
const dform = reactive({ subnet: '192.168.1', username: '', password: '' })
const discoverCreds = reactive({ username: '', password: '' })

// 实时画面预览（M7：通过一次性 stream ticket 取流，避免 JWT 进 URL）
const previewDialog = ref(false)
const previewId = ref('')
const previewReload = ref(0)
const previewError = ref('')
const previewSrc = ref('')
const previewKey = computed(() => `${previewId.value}-${previewReload.value}`)
async function loadPreview() {
  const id = previewId.value
  if (!id) {
    previewSrc.value = ''
    return
  }
  previewError.value = ''
  try {
    previewSrc.value = await cameraApi.videoUrl(id, 12)
  } catch (e) {
    previewSrc.value = ''
    previewError.value = '预览地址获取失败：' + (e.response?.data?.detail || e.message)
  }
}

// 添加对话框内嵌"临时预览"：填了来源就直接验证是否可取流，存之前先看画面
const addPreviewReload = ref(0)
const addPreviewError = ref('')
const addPreviewSrc = ref('')
const addPreviewKey = computed(() => `add-${addPreviewReload.value}`)
async function loadAddPreview() {
  const src = form.source && form.source.trim()
  if (!src) {
    addPreviewSrc.value = ''
    return
  }
  addPreviewError.value = ''
  try {
    addPreviewSrc.value = await cameraApi.previewUrl(src, form.username, form.password, 12)
  } catch (e) {
    addPreviewSrc.value = ''
    addPreviewError.value = '预览地址获取失败：' + (e.response?.data?.detail || e.message)
  }
}
function onAddPreviewError() {
  addPreviewError.value = '该来源暂时取不到画面（地址/凭据/网络不可达，或设备未联网）'
}
function reloadAddPreview() {
  addPreviewError.value = ''
  addPreviewReload.value += 1
  loadAddPreview()
}

// 缩略图：每个摄像头用一次性 stream ticket 取快照，避免 JWT 进 URL（M7）
const snaps = reactive({})
const snapPreviews = reactive({})
async function loadSnap(id) {
  if (!id) return
  try {
    // 缩略图与放大预览各需一个独立 ticket（<img> 与 el-image 预览会分别请求）
    snaps[id] = await cameraApi.snapshotUrl(id, true, 80)
    snapPreviews[id] = await cameraApi.snapshotUrl(id, true, 90)
  } catch {
    snaps[id] = ''
    snapPreviews[id] = ''
  }
}
function snapshotUrl(id) {
  return snaps[id] || ''
}
function previewShotUrl(id) {
  return snapPreviews[id] || ''
}
// 缩略图每 10s 重新换取 ticket 刷新，避免浏览器长期缓存旧画面
let thumbTimer = null
function refreshSnaps() {
  cameras.value.forEach((c) => c.enabled && loadSnap(c.id))
}

const TYPE_LABELS = {
  usb: 'USB',
  rtsp: 'RTSP',
  http: 'HTTP',
  ip: 'IP',
  network: '网络',
  simulated: '仿真',
  simulation: '仿真',
}
function typeLabel(value) {
  return TYPE_LABELS[value] || value || '未知'
}
function openPreview(row) {
  previewId.value = row.id
  previewError.value = ''
  previewReload.value += 1
  previewDialog.value = true
  loadPreview()
}
function onPreviewError() {
  previewError.value = '预览加载失败：摄像头可能已停用、网络不可达或令牌失效'
}
function reloadPreview() {
  previewError.value = ''
  previewReload.value += 1
  loadPreview()
}

function openAdd() {
  form.id = ''
  form.name = ''
  form.type = 'simulation'
  form.source = ''
  form.enabled = true
  form.username = ''
  form.password = ''
  addDialog.value = true
}

// 未手动切换类型时，按来源自动推断类型：rtsp:// → rtsp，http:// → http，纯数字 → usb
watch(
  () => form.source,
  (s) => {
    if (!addDialog.value) return
    const inferred = cameraApi.inferType(s)
    if (form.type === 'simulation' || form.type === '') {
      form.type = inferred
    }
    addPreviewError.value = '' // 改了来源就清掉上一次的预览错误
    loadAddPreview() // 来源变化即重新换取预览 ticket
  }
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const list = await cameraApi.list()
    cameras.value = list
    store.cameras = list
    refreshSnaps()
    try {
      const cfg = await configApi.get()
      activeId.value = cfg.active_camera_id || (list[0] && list[0].id) || ''
      discoverCreds.username = cfg.discover_username || ''
      discoverCreds.password = cfg.discover_password || ''
    } catch {
      activeId.value = (list[0] && list[0].id) || ''
    }
  } catch (e) {
    error.value = '设备列表加载失败：' + (e.response?.data?.detail || e.message)
  } finally {
    loading.value = false
  }
}

async function scan() {
  scanning.value = true
  try {
    const r = await cameraApi.scan(scanSubnet.value)
    scanResult.value = r.found || []
    if (!r.found || !r.found.length) ElMessage.info('未发现候选设备')
  } catch (e) {
    scanResult.value = []
    ElMessage.error('扫描失败：' + (e.response?.data?.detail || e.message))
  } finally {
    scanning.value = false
  }
}

async function add() {
  if (!form.id || !form.name) {
    ElMessage.warning('请填写设备ID与名称')
    return
  }
  saving.value = true
  try {
    await cameraApi.create({ ...form })
    ElMessage.success('已添加设备')
    addDialog.value = false
    await load()
    openPreview({ id: form.id, name: form.name })
  } catch (e) {
    ElMessage.error('添加失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function toggleEnabled(row, val) {
  try {
    await cameraApi.update(row.id, { enabled: val })
    ElMessage.success(val ? '已启用' : '已停用')
    if (val) loadSnap(row.id) // 启用后立刻换取缩略图 ticket
  } catch (e) {
    row.enabled = !val
    ElMessage.error('操作失败：' + (e.response?.data?.detail || e.message))
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除设备「${row.name || row.id}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await cameraApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

function openDiscover() {
  dform.subnet = scanSubnet.value || '192.168.1'
  dform.username = discoverCreds.username
  dform.password = discoverCreds.password
  discoverDialog.value = true
}

async function testAdd() {
  if (!form.source) {
    ElMessage.warning('请先填写来源（rtsp/http 地址）')
    return
  }
  testing.value = true
  try {
    const r = await cameraApi.test({ source: form.source, username: form.username || undefined, password: form.password || undefined })
    if (r.ok) ElMessage.success('测试连接成功：' + r.message)
    else ElMessage.warning('连接失败：' + r.message)
  } catch (e) {
    ElMessage.error('测试失败：' + (e.response?.data?.detail || e.message))
  } finally {
    testing.value = false
  }
}

async function doDiscover() {
  discovering.value = true
  try {
    const r = await cameraApi.discover({ ...dform })
    if (r.count > 0) {
      ElMessage.success(`自动发现并注册 ${r.count} 个摄像头`)
      discoverDialog.value = false
      await load()
      // 发现成功后直接弹出第一个摄像头的实时预览，确认画面可达
      const first = (r.added && r.added[0]) || null
      if (first) openPreview({ id: first.id, name: first.name })
    } else {
      ElMessage.info('未发现可用网络摄像头（请确认网段、RTSP 端口或账号密码）')
    }
  } catch (e) {
    ElMessage.error('自动发现失败：' + (e.response?.data?.detail || e.message))
  } finally {
    discovering.value = false
  }
}

async function setActive(row) {
  try {
    await cameraApi.setActive(row.id)
    activeId.value = row.id
    ElMessage.success(`已将「${row.name || row.id}」设为当前检测摄像头`)
  } catch (e) {
    ElMessage.error('设置失败：' + (e.response?.data?.detail || e.message))
  }
}

// ---- G6 ROI 检测区域编辑（拖拽画矩形，归一化存储） ----
const roiDialog = ref(false)
const roiCamera = ref(null)
const roiRects = ref([])
const roiCanvas = ref(null)
const roiSaving = ref(false)
const roiSnapshot = ref('')
const roiSnapKey = ref(0)
const drawingRect = ref(null)
let roiDragStart = null

async function openRoi(row) {
  roiCamera.value = row
  roiRects.value = (row.roi || []).map((r) => ({ ...r }))
  drawingRect.value = null
  roiDragStart = null
  roiDialog.value = true
  // 取一张快照做底图（仅辅助对位，失败不影响画框）
  roiSnapshot.value = ''
  try {
    roiSnapshot.value = await cameraApi.snapshotUrl(row.id, false, 80)
    roiSnapKey.value += 1
  } catch {
    roiSnapshot.value = ''
  }
}

function roiPoint(e) {
  const el = roiCanvas.value
  if (!el) return null
  const rect = el.getBoundingClientRect()
  const x = Math.min(1, Math.max(0, (e.clientX - rect.left) / rect.width))
  const y = Math.min(1, Math.max(0, (e.clientY - rect.top) / rect.height))
  return { x, y }
}

function onRoiMouseDown(e) {
  if (e.button !== 0) return
  const p = roiPoint(e)
  if (!p) return
  roiDragStart = p
  drawingRect.value = { x: p.x, y: p.y, w: 0, h: 0 }
}

function onRoiMouseMove(e) {
  if (!roiDragStart) return
  const p = roiPoint(e)
  if (!p) return
  drawingRect.value = {
    x: Math.min(roiDragStart.x, p.x),
    y: Math.min(roiDragStart.y, p.y),
    w: Math.abs(p.x - roiDragStart.x),
    h: Math.abs(p.y - roiDragStart.y),
  }
}

function onRoiMouseUp() {
  if (!roiDragStart) return
  const r = drawingRect.value
  if (r && r.w > 0.01 && r.h > 0.01) {
    roiRects.value.push({ x: +r.x.toFixed(4), y: +r.y.toFixed(4), w: +r.w.toFixed(4), h: +r.h.toFixed(4) })
  }
  roiDragStart = null
  drawingRect.value = null
}

function removeRoi(i) {
  roiRects.value.splice(i, 1)
}

function clearRoi() {
  roiRects.value = []
}

async function saveRoi() {
  const cam = roiCamera.value
  if (!cam) return
  roiSaving.value = true
  try {
    const updated = await cameraApi.update(cam.id, { roi: roiRects.value })
    ElMessage.success(roiRects.value.length ? `已保存 ${roiRects.value.length} 个 ROI 区域` : '已清空 ROI（全画面检测）')
    roiDialog.value = false
    await load()
    void updated
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    roiSaving.value = false
  }
}

onMounted(() => {
  load()
  refreshSnaps()
  thumbTimer = setInterval(refreshSnaps, 10000)
})
onUnmounted(() => {
  if (thumbTimer) clearInterval(thumbTimer)
})
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.controls { display: flex; gap: 8px; }
.preview-wrap { width: 100%; min-height: 300px; background: #000; border-radius: 6px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.add-preview { margin: 4px 0 8px; border: 1px solid #ebeef5; border-radius: 6px; padding: 8px 10px; background: #fafafa; }
.add-preview-head { display: flex; align-items: center; justify-content: space-between; font-size: 13px; color: #606266; margin-bottom: 6px; }
.add-preview-wrap { width: 100%; min-height: 200px; background: #000; border-radius: 4px; display: flex; align-items: center; justify-content: center; overflow: hidden; }
.add-preview-img { width: 100%; display: block; }
.preview { width: 100%; display: block; }
.thumb { width: 90px; height: 50px; border-radius: 4px; overflow: hidden; background: #111; display: block; }
.thumb-placeholder { width: 90px; height: 50px; border-radius: 4px; background: #f4f4f5; color: #909399; font-size: 12px; display: flex; align-items: center; justify-content: center; }
.thumb-placeholder.disabled { background: #f0f0f0; color: #c0c4cc; }
/* G6 ROI 编辑器 */
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
