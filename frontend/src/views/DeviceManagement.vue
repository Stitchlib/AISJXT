<template>
  <div>
    <div class="head">
      <h2>设备管理</h2>
      <div class="controls">
        <el-button
          type="primary"
          :loading="scanning"
          @click="scan"
        >
          扫描网络摄像头
        </el-button>
        <el-button
          v-if="canOperate"
          type="warning"
          :loading="discovering"
          @click="discoverDialog = true"
        >
          发现并自动添加
        </el-button>
        <el-button
          v-if="canOperate"
          type="success"
          @click="addDialog = true"
        >
          + 添加设备
        </el-button>
      </div>
    </div>

    <el-alert
      v-if="error"
      type="error"
      :closable="false"
      :title="error"
      style="margin-bottom: 12px"
    />

    <el-alert
      v-if="scanResult !== null"
      :title="'在网段 ' + scanSubnet + ' 中发现 ' + scanResult.length + ' 个候选设备'"
      type="info"
      style="margin-bottom: 12px"
    />

    <CameraTable
      :active-id="activeId"
      :cameras="cameras"
      :loading="loading"
      :can-operate="canOperate"
      :can-admin="canAdmin"
      @toggle-enabled="toggleEnabled"
      @set-active="setActive"
      @preview="openPreview"
      @edit="editRow = $event; editDialog = true"
      @roi="roiRow = $event; roiDialog = true"
      @remove="remove"
    />

    <DiscoverDialog
      v-model="discoverDialog"
      :loading="discovering"
      :defaults="discoverDefaults"
      @discover="doDiscover"
    />

    <DeviceFormDialog
      v-model="addDialog"
      :saving="saving"
      :testing="testing"
      @save="add"
      @test="testAdd"
    />

    <DeviceEditDialog
      v-model="editDialog"
      :camera="editRow"
      :saving="saving"
      :can-admin="canAdmin"
      @invalid="ElMessage.warning"
      @save="saveEdit"
    />

    <PreviewDialog
      v-model="previewDialog"
      :camera-id="previewId"
    />

    <RoiEditorDialog
      v-model="roiDialog"
      :camera="roiRow"
      :saving="roiSaving"
      @save="saveRoi"
    />
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { cameraApi, configApi } from '@/api'
import { useStore } from '@/store'
import CameraTable from '@/components/device/CameraTable.vue'
import DiscoverDialog from '@/components/device/DiscoverDialog.vue'
import DeviceFormDialog from '@/components/device/DeviceFormDialog.vue'
import DeviceEditDialog from '@/components/device/DeviceEditDialog.vue'
import PreviewDialog from '@/components/device/PreviewDialog.vue'
import RoiEditorDialog from '@/components/device/RoiEditorDialog.vue'

const store = useStore()
const loading = ref(false)
const scanning = ref(false)
const discovering = ref(false)
const saving = ref(false)
const testing = ref(false)
const error = ref('')
const cameras = ref([])
const scanResult = ref(null)
const scanSubnet = ref('192.168.1')
const activeId = ref('')

// 角色能力（第三期 1.1，与后端权限矩阵一致）：
// operator+ 可增改普通字段/设当前/发现；删除与来源/凭据修改仅 admin
const canOperate = computed(() => ['admin', 'operator'].includes(store.user?.role || ''))
const canAdmin = computed(() => store.user?.role === 'admin')

// 对话框状态与当前操作对象
const addDialog = ref(false)
const discoverDialog = ref(false)
const editDialog = ref(false)
const previewDialog = ref(false)
const roiDialog = ref(false)
const previewId = ref('')
const editRow = ref(null)
const roiRow = ref(null)
const roiSaving = ref(false)
const discoverDefaults = ref({ subnet: '192.168.1', username: '', password: '' })

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
      discoverDefaults.value = {
        subnet: scanSubnet.value || '192.168.1',
        username: cfg.discover_username || '',
        password: cfg.discover_password || '',
      }
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

async function add(form) {
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

async function testAdd(form) {
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

async function saveEdit({ id, payload }) {
  saving.value = true
  try {
    await cameraApi.update(id, payload)
    ElMessage.success('已保存')
    editDialog.value = false
    await load()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    saving.value = false
  }
}

async function doDiscover(form) {
  discovering.value = true
  scanSubnet.value = form.subnet || scanSubnet.value
  try {
    const r = await cameraApi.discover({ ...form })
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

async function setActive(row) {
  try {
    await cameraApi.setActive(row.id)
    activeId.value = row.id
    ElMessage.success(`已将「${row.name || row.id}」设为当前检测摄像头`)
  } catch (e) {
    ElMessage.error('设置失败：' + (e.response?.data?.detail || e.message))
  }
}

function openPreview(row) {
  previewId.value = row.id
  previewDialog.value = true
}

// G6 ROI：保存后刷新列表，让表格中的 ROI 数量标记立即更新
async function saveRoi(camId, rects) {
  roiSaving.value = true
  try {
    await cameraApi.update(camId, { roi: rects })
    ElMessage.success(rects.length ? `已保存 ${rects.length} 个 ROI 区域` : '已清空 ROI（全画面检测）')
    roiDialog.value = false
    await load()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    roiSaving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.controls { display: flex; gap: 8px; }
</style>
