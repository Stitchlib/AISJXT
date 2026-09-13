<template>
  <div>
    <div class="head">
      <h2>历史记录</h2>
      <el-button
        :loading="exporting"
        @click="exportCsv"
      >
        导出 CSV
      </el-button>
    </div>

    <el-card
      shadow="hover"
      style="margin-bottom: 16px"
    >
      <el-form
        :inline="true"
        @submit.prevent
      >
        <el-form-item label="摄像头">
          <el-select
            v-model="filters.camera_id"
            placeholder="全部"
            clearable
            style="width: 200px"
            @change="onFilter"
          >
            <el-option
              v-for="c in cameras"
              :key="c.id"
              :label="c.name || c.id"
              :value="c.id"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="批次">
          <el-select
            v-model="filters.batch_id"
            placeholder="全部"
            clearable
            style="width: 200px"
            @change="onFilter"
          >
            <el-option
              v-for="b in batches"
              :key="b.batch_no"
              :label="b.batch_no + (b.product ? '（' + b.product + '）' : '')"
              :value="b.batch_no"
            />
          </el-select>
        </el-form-item>
        <el-form-item label="仅看有缺陷">
          <el-switch
            v-model="filters.defect_only"
            @change="onFilter"
          />
        </el-form-item>
      </el-form>
    </el-card>

    <el-alert
      type="info"
      :closable="false"
      show-icon
      style="margin-bottom: 16px"
    >
      <template #title>
        口径说明：表中「不良率」为<b>单帧缺陷率</b> = 该帧缺陷框数 / 检出对象总数；
        质检报告页的批次 / 按日不良率为<b>聚合口径</b> = 缺陷帧数 / 总帧数，两者不可混用。
      </template>
    </el-alert>

    <el-card
      v-loading="loading"
      shadow="hover"
    >
      <el-empty
        v-if="!loading && items.length === 0"
        description="暂无检测记录"
      />
      <el-table
        v-else
        :data="items"
        border
        row-key="id"
      >
        <el-table-column type="expand">
          <template #default="{ row }">
            <div
              v-if="row.defects && row.defects.length"
              class="defect-list"
            >
              <div
                v-for="(d, i) in row.defects"
                :key="i"
                class="defect-item"
              >
                <el-tag size="small">
                  {{ d.class_name }}
                </el-tag>
                <span>置信度：{{ (d.confidence * 100).toFixed(1) }}%</span>
                <span v-if="d.bbox">位置：x={{ d.bbox.x }} y={{ d.bbox.y }} w={{ d.bbox.width }} h={{ d.bbox.height }}</span>
              </div>
            </div>
            <div
              v-else
              class="defect-list"
            >
              无缺陷
            </div>
          </template>
        </el-table-column>
        <el-table-column
          prop="timestamp"
          label="时间"
          width="200"
        />
        <el-table-column
          prop="camera_id"
          label="摄像头"
          width="140"
        />
        <el-table-column
          label="现场图"
          width="110"
          align="center"
        >
          <template #default="{ row }">
            <el-image
              v-if="thumbs[row.id]"
              :src="thumbs[row.id]"
              :preview-src-list="[thumbs[row.id]]"
              fit="cover"
              preview-teleported
              style="width: 80px; height: 60px; border-radius: 4px"
            />
            <el-tooltip
              v-else-if="row.image_path"
              content="图片可能已被保留期/配额清理"
              placement="top"
            >
              <span class="img-gone">已清理</span>
            </el-tooltip>
            <span v-else>—</span>
          </template>
        </el-table-column>
        <el-table-column
          label="缺陷数/总数"
          width="140"
        >
          <template #default="{ row }">
            {{ row.defect_count }} / {{ row.total_count }}
          </template>
        </el-table-column>
        <el-table-column
          label="不良率"
          width="100"
        >
          <template #default="{ row }">
            {{ (row.defect_rate * 100).toFixed(1) }}%
          </template>
        </el-table-column>
        <el-table-column
          prop="processing_time_ms"
          label="耗时(ms)"
          width="110"
        />
        <el-table-column
          label="仿真"
          width="90"
          align="center"
        >
          <template #default="{ row }">
            <el-tag
              v-if="row.is_simulation"
              size="small"
              type="warning"
            >
              仿真
            </el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="total > 0"
        style="margin-top: 16px; justify-content: flex-end"
        layout="total, prev, pager, next, sizes"
        :total="total"
        :current-page="page"
        :page-size="pageSize"
        :page-sizes="[10, 20, 50, 100]"
        @current-change="onPageChange"
        @size-change="onSizeChange"
      />
    </el-card>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage } from 'element-plus'
import { detectionApi, cameraApi, batchApi } from '@/api'
import { downloadBlob } from '@/utils/download'

const loading = ref(false)
const exporting = ref(false)
const items = ref([])
const cameras = ref([])
const batches = ref([])
const total = ref(0)
const page = ref(1)
const pageSize = ref(20)

const filters = reactive({ camera_id: '', batch_id: '', defect_only: false })

async function loadCameras() {
  try {
    cameras.value = await cameraApi.list()
  } catch {
    cameras.value = []
  }
}

async function loadBatches() {
  try {
    batches.value = await batchApi.list()
  } catch {
    batches.value = []
  }
}

async function load() {
  loading.value = true
  try {
    const data = await detectionApi.list({
      page: page.value,
      page_size: pageSize.value,
      camera_id: filters.camera_id || undefined,
      batch_id: filters.batch_id || undefined,
      defect_only: filters.defect_only,
    })
    items.value = data.items || []
    total.value = data.total || 0
  } catch (e) {
    ElMessage.error('加载历史记录失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function onFilter() {
  page.value = 1
  load()
}
function onPageChange(p) {
  page.value = p
  load()
}
function onSizeChange(s) {
  pageSize.value = s
  page.value = 1
  load()
}

async function exportCsv() {
  exporting.value = true
  try {
    const blob = await detectionApi.exportCsv()
    downloadBlob(blob, `detection_results_${Date.now()}.csv`)
    ElMessage.success('CSV 已导出')
  } catch (e) {
    ElMessage.error('导出失败：' + (e.response?.data?.detail || e.message))
  } finally {
    exporting.value = false
  }
}

onMounted(() => {
  loadCameras()
  loadBatches()
  load()
})
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.defect-list { padding: 8px 12px; }
.defect-item { display: flex; gap: 16px; align-items: center; padding: 2px 0; font-size: 13px; color: #606266; }
.img-gone { font-size: 12px; color: #c0c4cc; }
</style>
