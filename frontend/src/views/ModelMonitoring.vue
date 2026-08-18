<template>
  <div>
    <div class="head">
      <h2>模型监控</h2>
      <span v-if="activeId" class="active-tip">当前激活模型：<b>{{ activeName }}</b></span>
    </div>

    <el-card v-loading="loading" shadow="hover" style="margin-bottom: 16px">
      <template #header><b>模型版本列表</b></template>
      <el-empty v-if="!loading && list.length === 0" description="暂无模型版本" />
      <el-table v-else :data="list" border>
        <el-table-column prop="name" label="名称" min-width="120" />
        <el-table-column prop="version" label="版本" width="100" />
        <el-table-column prop="metric" label="评估指标" width="120" />
        <el-table-column prop="description" label="描述" min-width="160" show-overflow-tooltip />
        <el-table-column prop="created_at" label="创建时间" width="180" />
        <el-table-column label="状态" width="90" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.active || row.id === activeId" type="success" size="small">已激活</el-tag>
            <el-tag v-else type="info" size="small">未激活</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="180" fixed="right">
          <template #default="{ row }">
            <el-button
              type="primary"
              size="small"
              :disabled="row.active || row.id === activeId"
              @click="activate(row)"
            >激活</el-button>
            <el-button type="danger" size="small" @click="remove(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <el-card v-loading="uploading" shadow="hover">
      <template #header><b>上传新模型</b></template>
      <el-form :model="uploadForm" label-width="100px">
        <el-form-item label="模型文件">
          <el-upload
            :auto-upload="false"
            :show-file-list="true"
            :limit="1"
            accept=".pt,.onnx,.pth,.weights"
            @change="onFileChange"
            @remove="onFileRemove"
          >
            <el-button>选择文件</el-button>
            <template #tip><div class="tip">支持 .pt / .onnx / .pth / .weights</div></template>
          </el-upload>
        </el-form-item>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="名称"><el-input v-model="uploadForm.name" placeholder="如 YOLOv8n" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="版本"><el-input v-model="uploadForm.version" placeholder="如 v1.0.0" /></el-form-item>
          </el-col>
        </el-row>
        <el-row :gutter="16">
          <el-col :span="12">
            <el-form-item label="评估指标"><el-input v-model="uploadForm.metric" placeholder="如 mAP 0.92" /></el-form-item>
          </el-col>
          <el-col :span="12">
            <el-form-item label="上传后激活">
              <el-switch v-model="uploadForm.activate" />
            </el-form-item>
          </el-col>
        </el-row>
        <el-form-item label="描述"><el-input v-model="uploadForm.description" type="textarea" :rows="2" /></el-form-item>
        <el-form-item>
          <el-button type="primary" :disabled="!selectedFile" @click="upload">上传</el-button>
        </el-form-item>
      </el-form>
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { modelApi } from '@/api'

const loading = ref(false)
const uploading = ref(false)
const list = ref([])
const activeId = ref(null)
const selectedFile = ref(null)

const uploadForm = reactive({ name: '', version: '', metric: '', description: '', activate: false })

const activeName = computed(() => {
  const m = list.value.find((x) => x.id === activeId.value)
  return m ? m.name : ''
})

function onFileChange(file) {
  selectedFile.value = file.raw
}
function onFileRemove() {
  selectedFile.value = null
}

async function load() {
  loading.value = true
  try {
    const data = await modelApi.versions()
    list.value = data.items || []
    activeId.value = data.active_id ?? null
  } catch (e) {
    ElMessage.error('加载模型列表失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

async function activate(row) {
  try {
    await modelApi.activate(row.id)
    activeId.value = row.id
    ElMessage.success(`已激活「${row.name}」`)
  } catch (e) {
    ElMessage.error('激活失败：' + (e.response?.data?.detail || e.message))
  }
}

async function remove(row) {
  try {
    await ElMessageBox.confirm(`确认删除模型「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await modelApi.remove(row.id)
    ElMessage.success('已删除')
    await load()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

async function upload() {
  if (!selectedFile.value) {
    ElMessage.warning('请先选择模型文件')
    return
  }
  const fd = new FormData()
  fd.append('file', selectedFile.value)
  fd.append('name', uploadForm.name || selectedFile.value.name)
  fd.append('version', uploadForm.version || 'v1.0.0')
  fd.append('metric', uploadForm.metric || '')
  fd.append('description', uploadForm.description || '')
  fd.append('activate', String(uploadForm.activate))

  uploading.value = true
  try {
    await modelApi.upload(fd)
    ElMessage.success('上传成功')
    selectedFile.value = null
    uploadForm.name = ''
    uploadForm.version = ''
    uploadForm.metric = ''
    uploadForm.description = ''
    uploadForm.activate = false
    await load()
  } catch (e) {
    ElMessage.error('上传失败：' + (e.response?.data?.detail || e.message))
  } finally {
    uploading.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.active-tip { color: #67c23a; font-size: 13px; }
.tip { color: #909399; font-size: 12px; }
</style>
