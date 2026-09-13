<template>
  <el-card
    v-loading="loading"
    shadow="hover"
  >
    <template #header>
      <div class="card-head">
        <b>告警事件</b>
        <el-radio-group
          :model-value="ackFilter"
          size="small"
          @update:model-value="emit('update:ackFilter', $event)"
        >
          <el-radio-button label="all">
            全部
          </el-radio-button>
          <el-radio-button label="unack">
            未确认
          </el-radio-button>
          <el-radio-button label="ack">
            已确认
          </el-radio-button>
        </el-radio-group>
      </div>
    </template>
    <el-empty
      v-if="!loading && events.length === 0"
      description="暂无告警事件"
    />
    <el-table
      v-else
      :data="events"
      border
      size="small"
    >
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
        prop="message"
        label="消息"
        min-width="200"
        show-overflow-tooltip
      />
      <el-table-column
        label="级别"
        width="100"
        align="center"
      >
        <template #default="{ row }">
          <el-tag
            :type="severityType(row.severity)"
            size="small"
          >
            {{ row.severity }}
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="数值"
        width="100"
      >
        <template #default="{ row }">
          {{ row.value }}
        </template>
      </el-table-column>
      <el-table-column
        label="状态"
        width="100"
        align="center"
      >
        <template #default="{ row }">
          <el-tag
            v-if="row.acknowledged"
            type="success"
            size="small"
          >
            已确认
          </el-tag>
          <el-tag
            v-else
            type="warning"
            size="small"
          >
            待确认
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="判定"
        width="110"
        align="center"
      >
        <template #default="{ row }">
          <el-tooltip
            v-if="row.verdict && row.verdict !== 'pending'"
            placement="top"
          >
            <template #content>
              <div>判定人：{{ row.judged_by || '—' }}</div>
              <div v-if="row.judged_at">
                时间：{{ row.judged_at }}
              </div>
              <div v-if="row.remark">
                备注：{{ row.remark }}
              </div>
            </template>
            <el-tag
              :type="verdictType(row.verdict)"
              size="small"
            >
              {{ verdictText(row.verdict) }}
            </el-tag>
          </el-tooltip>
          <el-tag
            v-else
            type="info"
            size="small"
          >
            待判定
          </el-tag>
        </template>
      </el-table-column>
      <el-table-column
        label="操作"
        width="230"
        fixed="right"
      >
        <template #default="{ row }">
          <el-button
            v-if="row.result_id"
            size="small"
            @click="emit('show-image', row)"
          >
            现场图
          </el-button>
          <el-button
            v-if="canVerdict"
            type="primary"
            size="small"
            plain
            @click="emit('verdict', row)"
          >
            判定
          </el-button>
          <el-button
            v-if="!row.acknowledged"
            size="small"
            @click="emit('acknowledge', row)"
          >
            确认
          </el-button>
        </template>
      </el-table-column>
    </el-table>

    <el-pagination
      v-if="total > 0"
      style="margin-top: 16px; justify-content: flex-end"
      layout="total, prev, pager, next"
      :total="total"
      :current-page="page"
      :page-size="pageSize"
      @current-change="emit('page-change', $event)"
    />
  </el-card>
</template>

<script setup>
import { useAlertLabels } from '@/composables/alertLabels'

defineProps({
  events: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
  total: { type: Number, default: 0 },
  page: { type: Number, default: 1 },
  pageSize: { type: Number, default: 20 },
  ackFilter: { type: String, default: 'all' },
  canVerdict: { type: Boolean, default: false },
})
const emit = defineEmits(['update:ackFilter', 'page-change', 'verdict', 'acknowledge', 'show-image'])
const { severityType, verdictText, verdictType } = useAlertLabels()
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
</style>
