<template>
  <div>
    <h2>告警中心</h2>

    <!-- 告警规则 -->
    <el-card v-loading="rulesLoading" shadow="hover" style="margin-bottom: 16px">
      <template #header>
        <div class="card-head">
          <b>告警规则</b>
          <el-button type="primary" size="small" @click="openRuleDialog()">+ 新建规则</el-button>
        </div>
      </template>
      <el-empty v-if="!rulesLoading && rules.length === 0" description="暂无告警规则" />
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
        <el-table-column label="启用" width="80" align="center">
          <template #default="{ row }">
            <el-switch v-model="row.enabled" @change="(v) => toggleRule(row, v)" />
          </template>
        </el-table-column>
        <el-table-column label="操作" width="160" fixed="right">
          <template #default="{ row }">
            <el-button size="small" @click="openRuleDialog(row)">编辑</el-button>
            <el-button type="danger" size="small" @click="removeRule(row)">删除</el-button>
          </template>
        </el-table-column>
      </el-table>
    </el-card>

    <!-- 告警事件 -->
    <el-card v-loading="eventsLoading" shadow="hover">
      <template #header>
        <div class="card-head">
          <b>告警事件</b>
          <el-radio-group v-model="ackFilter" size="small" @change="loadEvents">
            <el-radio-button label="all">全部</el-radio-button>
            <el-radio-button label="unack">未确认</el-radio-button>
            <el-radio-button label="ack">已确认</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <el-empty v-if="!eventsLoading && events.length === 0" description="暂无告警事件" />
      <el-table v-else :data="events" border size="small">
        <el-table-column prop="timestamp" label="时间" width="200" />
        <el-table-column prop="camera_id" label="摄像头" width="140" />
        <el-table-column prop="message" label="消息" min-width="200" show-overflow-tooltip />
        <el-table-column label="级别" width="100" align="center">
          <template #default="{ row }">
            <el-tag :type="severityType(row.severity)" size="small">{{ row.severity }}</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="数值" width="100">
          <template #default="{ row }">{{ row.value }}</template>
        </el-table-column>
        <el-table-column label="状态" width="100" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.acknowledged" type="success" size="small">已确认</el-tag>
            <el-tag v-else type="warning" size="small">待确认</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="110" fixed="right">
          <template #default="{ row }">
            <el-button
              v-if="!row.acknowledged"
              type="primary"
              size="small"
              @click="acknowledge(row)"
            >确认</el-button>
            <span v-else>—</span>
          </template>
        </el-table-column>
      </el-table>

      <el-pagination
        v-if="eventsTotal > 0"
        style="margin-top: 16px; justify-content: flex-end"
        layout="total, prev, pager, next"
        :total="eventsTotal"
        :current-page="eventsPage"
        :page-size="eventsPageSize"
        @current-change="onEventsPage"
      />
    </el-card>

    <!-- 规则编辑对话框 -->
    <el-dialog v-model="ruleDialog" :title="editingRule ? '编辑规则' : '新建规则'" width="460px">
      <el-form :model="ruleForm" label-width="100px">
        <el-form-item label="名称"><el-input v-model="ruleForm.name" /></el-form-item>
        <el-form-item label="指标">
          <el-select v-model="ruleForm.metric" style="width: 100%">
            <el-option label="缺陷率" value="defect_rate" />
            <el-option label="缺陷数" value="defect_count" />
            <el-option label="处理耗时(ms)" value="processing_time_ms" />
          </el-select>
        </el-form-item>
        <el-form-item label="运算符">
          <el-select v-model="ruleForm.operator" style="width: 100%">
            <el-option label="大于 (>)" value="gt" />
            <el-option label="大于等于 (≥)" value="ge" />
            <el-option label="小于 (<)" value="lt" />
            <el-option label="小于等于 (≤)" value="le" />
          </el-select>
        </el-form-item>
        <el-form-item label="阈值"><el-input-number v-model="ruleForm.threshold" :step="0.1" style="width: 100%" /></el-form-item>
        <el-form-item label="作用域">
          <el-select v-model="ruleForm.scope" style="width: 100%">
            <el-option label="全部摄像头" value="all" />
            <el-option v-for="c in cameras" :key="c.id" :label="c.name || c.id" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="通知邮箱"><el-input v-model="ruleForm.notify_email" placeholder="可选" /></el-form-item>
        <el-form-item label="启用"><el-switch v-model="ruleForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="ruleDialog = false">取消</el-button>
        <el-button type="primary" :loading="ruleSaving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { alertsApi, cameraApi } from '@/api'

const rulesLoading = ref(false)
const rules = ref([])
const cameras = ref([])

const eventsLoading = ref(false)
const events = ref([])
const eventsTotal = ref(0)
const eventsPage = ref(1)
const eventsPageSize = ref(20)
const ackFilter = ref('all')

const ruleDialog = ref(false)
const ruleSaving = ref(false)
const editingRule = ref(null)
const ruleForm = reactive({
  name: '',
  metric: 'defect_rate',
  operator: 'gt',
  threshold: 0.1,
  scope: 'all',
  notify_email: '',
  enabled: true,
})

function metricText(m) {
  return { defect_rate: '缺陷率', defect_count: '缺陷数', processing_time_ms: '处理耗时(ms)' }[m] || m
}
function severityType(s) {
  return { critical: 'danger', high: 'warning', warning: 'warning', info: 'info' }[s] || 'info'
}

async function loadRules() {
  rulesLoading.value = true
  try {
    rules.value = await alertsApi.rules()
  } catch (e) {
    ElMessage.error('加载规则失败：' + (e.response?.data?.detail || e.message))
  } finally {
    rulesLoading.value = false
  }
}

async function loadCameras() {
  try {
    cameras.value = await cameraApi.list()
  } catch {
    cameras.value = []
  }
}

function ackParams() {
  if (ackFilter.value === 'all') return undefined
  return ackFilter.value === 'ack'
}

async function loadEvents() {
  eventsLoading.value = true
  try {
    const params = { page: eventsPage.value, page_size: eventsPageSize.value }
    const ack = ackParams()
    if (ack !== undefined) params.acknowledged = ack
    const data = await alertsApi.events(params)
    events.value = data.items || []
    eventsTotal.value = data.total || 0
  } catch (e) {
    ElMessage.error('加载事件失败：' + (e.response?.data?.detail || e.message))
  } finally {
    eventsLoading.value = false
  }
}

function onEventsPage(p) {
  eventsPage.value = p
  loadEvents()
}

function openRuleDialog(rule) {
  editingRule.value = rule || null
  if (rule) {
    ruleForm.name = rule.name
    ruleForm.metric = rule.metric
    ruleForm.operator = rule.operator
    ruleForm.threshold = rule.threshold
    ruleForm.scope = rule.scope || 'all'
    ruleForm.notify_email = rule.notify_email || ''
    ruleForm.enabled = !!rule.enabled
  } else {
    ruleForm.name = ''
    ruleForm.metric = 'defect_rate'
    ruleForm.operator = 'gt'
    ruleForm.threshold = 0.1
    ruleForm.scope = 'all'
    ruleForm.notify_email = ''
    ruleForm.enabled = true
  }
  ruleDialog.value = true
}

async function saveRule() {
  if (!ruleForm.name) {
    ElMessage.warning('请填写规则名称')
    return
  }
  ruleSaving.value = true
  const payload = {
    name: ruleForm.name,
    metric: ruleForm.metric,
    operator: ruleForm.operator,
    threshold: ruleForm.threshold,
    scope: ruleForm.scope,
    notify_email: ruleForm.notify_email || undefined,
    enabled: ruleForm.enabled,
  }
  try {
    if (editingRule.value) {
      await alertsApi.updateRule(editingRule.value.id, payload)
      ElMessage.success('已更新规则')
    } else {
      await alertsApi.createRule(payload)
      ElMessage.success('已新建规则')
    }
    ruleDialog.value = false
    await loadRules()
  } catch (e) {
    ElMessage.error('保存失败：' + (e.response?.data?.detail || e.message))
  } finally {
    ruleSaving.value = false
  }
}

async function toggleRule(row, val) {
  try {
    await alertsApi.updateRule(row.id, { enabled: val })
    ElMessage.success(val ? '已启用' : '已停用')
  } catch (e) {
    row.enabled = !val
    ElMessage.error('操作失败：' + (e.response?.data?.detail || e.message))
  }
}

async function removeRule(row) {
  try {
    await ElMessageBox.confirm(`确认删除规则「${row.name}」？`, '提示', { type: 'warning' })
  } catch {
    return
  }
  try {
    await alertsApi.removeRule(row.id)
    ElMessage.success('已删除')
    await loadRules()
  } catch (e) {
    ElMessage.error('删除失败：' + (e.response?.data?.detail || e.message))
  }
}

async function acknowledge(row) {
  try {
    await alertsApi.acknowledge(row.id)
    row.acknowledged = true
    ElMessage.success('已确认')
  } catch (e) {
    ElMessage.error('确认失败：' + (e.response?.data?.detail || e.message))
  }
}

onMounted(() => {
  loadRules()
  loadCameras()
  loadEvents()
})
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
</style>
