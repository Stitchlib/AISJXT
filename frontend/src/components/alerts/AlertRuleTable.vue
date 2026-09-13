<template>
  <el-card v-loading="loading" shadow="hover" style="margin-bottom: 16px">
    <template #header>
      <div class="card-head">
        <b>告警规则</b>
        <el-button type="primary" size="small" @click="emit('create')">+ 新建规则</el-button>
      </div>
    </template>
    <el-empty v-if="!loading && rules.length === 0" description="暂无告警规则" />
    <el-table v-else :data="rules" border size="small">
      <el-table-column prop="name" label="名称" min-width="140" />
      <el-table-column label="指标" width="150">
        <template #default="{ row }">{{ metricText(row.metric) }}</template>
      </el-table-column>
      <el-table-column label="条件" width="140">
        <template #default="{ row }">{{ row.operator }} {{ row.threshold }}</template>
      </el-table-column>
      <el-table-column label="作用域" width="120">
        <template #default="{ row }">{{ row.scope === 'all' ? '全部摄像头' : row.scope }}</template>
      </el-table-column>
      <el-table-column prop="notify_email" label="通知邮箱" min-width="160" show-overflow-tooltip />
      <el-table-column label="Webhook" width="120" align="center">
        <template #default="{ row }">
          <el-tag v-if="row.webhook_url" size="small" type="success">{{ webhookText(row.webhook_type) }}</el-tag>
          <span v-else>—</span>
        </template>
      </el-table-column>
      <el-table-column label="启用" width="80" align="center">
        <template #default="{ row }">
          <el-switch v-model="row.enabled" @change="(v) => emit('toggle', row, v)" />
        </template>
      </el-table-column>
      <el-table-column label="操作" width="160" fixed="right">
        <template #default="{ row }">
          <el-button size="small" @click="emit('edit', row)">编辑</el-button>
          <el-button type="danger" size="small" @click="emit('remove', row)">删除</el-button>
        </template>
      </el-table-column>
    </el-table>
  </el-card>
</template>

<script setup>
import { useAlertLabels } from '@/composables/alertLabels'

defineProps({
  rules: { type: Array, default: () => [] },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['create', 'edit', 'remove', 'toggle'])
const { metricText, webhookText } = useAlertLabels()
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
</style>
