<template>
  <el-card
    v-loading="loading"
    shadow="hover"
  >
    <el-empty
      v-if="!loading && cameras.length === 0"
      description="暂无设备，请添加或扫描"
    />
    <el-table
      v-else
      :data="cameras"
      border
    >
      <el-table-column
        label="实时缩略图"
        width="110"
        align="center"
      >
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
              <div class="thumb-placeholder">
                加载中
              </div>
            </template>
          </el-image>
          <div
            v-else
            class="thumb-placeholder disabled"
          >
            已停用
          </div>
        </template>
      </el-table-column>
      <el-table-column
        prop="id"
        label="设备ID"
        min-width="140"
      />
      <el-table-column
        prop="name"
        label="名称"
        min-width="140"
      />
      <el-table-column
        prop="type"
        label="类型"
        width="120"
      >
        <template #default="{ row }">
          {{ typeLabel(row.type) }}
        </template>
      </el-table-column>
      <el-table-column
        prop="source"
        label="来源"
        min-width="160"
        show-overflow-tooltip
      />
      <el-table-column
        label="启用"
        width="90"
        align="center"
      >
        <template #default="{ row }">
          <el-switch
            v-model="row.enabled"
            @change="(v) => emit('toggle-enabled', row, v)"
          />
        </template>
      </el-table-column>
      <el-table-column
        prop="status"
        label="状态"
        width="110"
      >
        <template #default="{ row }">
          <el-tag
            :type="row.status === 'online' ? 'success' : 'info'"
            size="small"
          >
            {{ row.status }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        prop="resolution"
        label="分辨率"
        width="120"
      />
      <el-table-column
        label="操作"
        width="340"
        fixed="right"
      >
        <template #default="{ row }">
          <el-tag
            v-if="row.id === activeId"
            type="success"
            size="small"
            style="margin-right: 6px"
          >
            当前
          </el-tag>
          <el-button
            v-else-if="canOperate"
            type="primary"
            link
            size="small"
            @click="emit('set-active', row)"
          >
            设为当前
          </el-button>
          <el-button
            type="success"
            link
            size="small"
            @click="emit('preview', row)"
          >
            预览
          </el-button>
          <el-button
            v-if="canOperate"
            type="info"
            link
            size="small"
            @click="emit('edit', row)"
          >
            编辑
          </el-button>
          <el-button
            type="warning"
            link
            size="small"
            @click="emit('roi', row)"
          >
            ROI{{ row.roi && row.roi.length ? '(' + row.roi.length + ')' : '' }}
          </el-button>
          <el-button
            v-if="canAdmin"
            type="danger"
            link
            size="small"
            @click="emit('remove', row)"
          >
            删除
          </el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { onMounted, onUnmounted, watch } from 'vue'
import { useCameraSnapshots } from '@/composables/useCameraSnapshots'

const props = defineProps({
  cameras: { type: Array, default: () => [] },
  activeId: { type: String, default: '' },
  loading: { type: Boolean, default: false },
  canOperate: { type: Boolean, default: false },
  canAdmin: { type: Boolean, default: false },
})
const emit = defineEmits(['toggle-enabled', 'set-active', 'preview', 'edit', 'roi', 'remove'])

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

const { snapshotUrl, previewShotUrl, refreshSnaps } = useCameraSnapshots(() => props.cameras)
// 列表变化（加载/增删）后立刻换一轮 ticket
watch(() => props.cameras, refreshSnaps, { deep: false })

let thumbTimer = null
onMounted(() => {
  refreshSnaps()
  thumbTimer = setInterval(refreshSnaps, 10000)
})
onUnmounted(() => {
  if (thumbTimer) clearInterval(thumbTimer)
})
</script>

<style scoped>
.thumb { width: 90px; height: 50px; border-radius: 4px; overflow: hidden; background: #111; display: block; }
.thumb-placeholder { width: 90px; height: 50px; border-radius: 4px; background: #f4f4f5; color: #909399; font-size: 12px; display: flex; align-items: center; justify-content: center; }
.thumb-placeholder.disabled { background: #f0f0f0; color: #c0c4cc; }
</style>
