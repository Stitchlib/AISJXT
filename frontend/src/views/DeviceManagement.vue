<template>
  <div>
    <div class="head">
      <h2>设备管理</h2>
      <div class="controls">
        <el-button type="primary" @click="scan" :loading="scanning">扫描网络摄像头</el-button>
        <el-button type="warning" @click="openDiscover" :loading="discovering">发现并自动添加</el-button>
        <el-button type="success" @click="openAdd">+ 添加设备</el-button>
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
              :preview-src-list="[previewShotUrl(row.id)]"
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
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-tag v-if="row.id === activeId" type="success" size="small" style="margin-right: 6px">当前</el-tag>
            <el-button v-else type="primary" link size="small" @click="setActive(row)">设为当前</el-button>
            <el-button type="success" link size="small" @click="openPreview(row)">预览</el-button>
            <el-button type="danger" link size="small" @click="remove(row)">删除</el-button>
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
      <div v-if="addPreviewUrl" class="add-preview">
        <div class="add-preview-head">
          <span>实时预览（保存前先确认可取流）</span>
          <el-button size="small" text type="primary" @click="reloadAddPreview">刷新预览</el-button>
        </div>
        <div class="add-preview-wrap">
          <img v-if="addPreviewUrl" :key="addPreviewKey" :src="addPreviewUrl" class="add-preview-img" alt="摄像头预览" @error="onAddPreviewError" />
          <el-alert v-if="addPreviewError" type="warning" :closable="false" :title="addPreviewError" />
        </div>
      </div>
      <template #footer>
        <el-button @click="addDialog = false">取消</el-button>
        <el-button :loading="testing" @click="testAdd">测试连接</el-button>
        <el-button type="primary" :loading="saving" @click="add">保存</el-button>
      </template>
    </el-dialog>

    <el-dialog v-model="previewDialog" title="实时画面预览" width="700px">
      <div class="preview-wrap">
        <img v-if="previewUrl" :key="previewKey" :src="previewUrl" class="preview" alt="实时画面预览" @error="onPreviewError" />
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

const discoverDialog = ref(false)
const dform = reactive({ subnet: '192.168.1', username: '', password: '' })
const discoverCreds = reactive({ username: '', password: '' })

// 实时画面预览
const previewDialog = ref(false)
const previewId = ref('')
const previewReload = ref(0)
const previewError = ref('')
const previewUrl = computed(() => (previewId.value ? cameraApi.videoUrl(previewId.value, 12) : ''))
const previewKey = computed(() => `${previewId.value}-${previewReload.value}`)

// 添加对话框内嵌"临时预览"：填了来源就直接验证是否可取流，存之前先看画面
const addPreviewReload = ref(0)
const addPreviewError = ref('')
const addPreviewUrl = computed(() =>
  form.source && form.source.trim()
    ? cameraApi.previewUrl(form.source.trim(), form.username, form.password, 12)
    : ''
)
const addPreviewKey = computed(() => `add-${addPreviewReload.value}`)
function onAddPreviewError() {
  addPreviewError.value = '该来源暂时取不到画面（地址/凭据/网络不可达，或设备未联网）'
}
function reloadAddPreview() {
  addPreviewError.value = ''
  addPreviewReload.value += 1
}

// 缩略图自动刷新（10s 一次），避免浏览器长期缓存旧画面
const thumbTick = ref(0)
let thumbTimer = null
function snapshotUrl(id) {
  return cameraApi.snapshotUrl(id, true, 70) + `&_t=${thumbTick.value}`
}
function previewShotUrl(id) {
  return cameraApi.snapshotUrl(id, true, 90) + `&_t=${thumbTick.value}`
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
}
function onPreviewError() {
  previewError.value = '预览加载失败：摄像头可能已停用、网络不可达或令牌失效'
}
function reloadPreview() {
  previewError.value = ''
  previewReload.value += 1
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
  }
)

async function load() {
  loading.value = true
  error.value = ''
  try {
    const list = await cameraApi.list()
    cameras.value = list
    store.cameras = list
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

onMounted(() => {
  load()
  thumbTimer = setInterval(() => {
    thumbTick.value += 1
  }, 10000)
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
</style>
