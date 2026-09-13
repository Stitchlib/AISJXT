<template>
  <div>
    <h2>告警中心</h2>

    <AlertStatsCard v-model:days="statsDays" :stats="stats" :loading="statsLoading" @change="loadStatistics" />

    <AlertRuleTable
      :rules="rules"
      :loading="rulesLoading"
      @create="openRuleDialog(null)"
      @edit="openRuleDialog"
      @remove="removeRule"
      @toggle="toggleRule"
    />

    <AlertEventTable
      v-model:ack-filter="ackFilter"
      :events="events"
      :loading="eventsLoading"
      :total="eventsTotal"
      :page="eventsPage"
      :page-size="eventsPageSize"
      :can-verdict="canVerdict"
      @page-change="onEventsPage"
      @verdict="openVerdictDialog"
      @acknowledge="acknowledge"
      @show-image="showEventImage"
    />

    <VerdictDialog
      v-model="verdictDialog"
      :target="verdictTarget"
      :saving="verdictSaving"
      @save="saveVerdict"
    />

    <EventImageDialog v-model="imageDialog" :url="eventImageUrl" :loading="imageLoading" />

    <AlertRuleDialog
      v-model="ruleDialog"
      :rule="editingRule"
      :cameras="cameras"
      :saving="ruleSaving"
      :webhook-testing="webhookTesting"
      @invalid="ElMessage.warning"
      @save="saveRule"
      @test-webhook="testWebhook"
    />
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { alertsApi, cameraApi, detectionApi, mediaApi } from '@/api'
import { useStore } from '@/store'
import AlertStatsCard from '@/components/alerts/AlertStatsCard.vue'
import AlertRuleTable from '@/components/alerts/AlertRuleTable.vue'
import AlertEventTable from '@/components/alerts/AlertEventTable.vue'
import VerdictDialog from '@/components/alerts/VerdictDialog.vue'
import EventImageDialog from '@/components/alerts/EventImageDialog.vue'
import AlertRuleDialog from '@/components/alerts/AlertRuleDialog.vue'

const store = useStore()

const rulesLoading = ref(false)
const rules = ref([])
const cameras = ref([])

const eventsLoading = ref(false)
const events = ref([])
const eventsTotal = ref(0)
const eventsPage = ref(1)
const eventsPageSize = ref(20)
const ackFilter = ref('all')

// ---- 判定统计（G2）----
const statsLoading = ref(false)
const statsDays = ref(30)
const stats = ref({})

// ---- 人工判定（G2）----
const canVerdict = computed(() => ['admin', 'operator'].includes(store.user?.role))
const verdictDialog = ref(false)
const verdictSaving = ref(false)
const verdictTarget = ref(null)

// ---- 现场图查看（G1/G2）----
const imageDialog = ref(false)
const imageLoading = ref(false)
const eventImageUrl = ref('')
let eventImageObjectUrl = ''

// ---- 规则编辑 ----
const ruleDialog = ref(false)
const ruleSaving = ref(false)
const webhookTesting = ref(false)
const editingRule = ref(null)

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

async function loadEvents() {
  eventsLoading.value = true
  try {
    const params = { page: eventsPage.value, page_size: eventsPageSize.value }
    if (ackFilter.value !== 'all') {
      params.acknowledged = ackFilter.value === 'ack'
    }
    const data = await alertsApi.events(params)
    events.value = data.items || []
    eventsTotal.value = data.total || 0
  } catch (e) {
    ElMessage.error('加载事件失败：' + (e.response?.data?.detail || e.message))
  } finally {
    eventsLoading.value = false
  }
}

// 筛选条件变化时回到第一页并重新加载
function onAckFilterChange(val) {
  ackFilter.value = val
  eventsPage.value = 1
  loadEvents()
}
// v-model 更新筛选值后回到第一页并重新加载
watch(ackFilter, onAckFilterChange)

function onEventsPage(p) {
  eventsPage.value = p
  loadEvents()
}

function openRuleDialog(rule) {
  editingRule.value = rule || null
  ruleDialog.value = true
}

async function saveRule(payload) {
  ruleSaving.value = true
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

// G3 多渠道通知：测试发送（按规则已配置的 webhook 渠道）
async function testWebhook() {
  if (!editingRule.value) return
  webhookTesting.value = true
  try {
    const res = await alertsApi.testWebhook(editingRule.value.id)
    if (res && res.ok) {
      ElMessage.success('Webhook 测试发送成功' + (res.message ? '：' + res.message : ''))
    } else {
      ElMessage.warning('Webhook 测试未成功：' + (res?.message || '未知原因'))
    }
  } catch (e) {
    ElMessage.error('测试发送失败：' + (e.response?.data?.detail || e.message))
  } finally {
    webhookTesting.value = false
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

// ---------- G2：判定统计 / 人工判定 ----------
async function loadStatistics() {
  statsLoading.value = true
  try {
    stats.value = await alertsApi.statistics({ days: statsDays.value })
  } catch {
    /* 统计失败不阻塞页面 */
  } finally {
    statsLoading.value = false
  }
}

function openVerdictDialog(row) {
  verdictTarget.value = row
  verdictDialog.value = true
}

async function saveVerdict(alertId, payload) {
  verdictSaving.value = true
  try {
    const updated = await alertsApi.setVerdict(alertId, payload)
    // 局部更新，避免整表刷新打断操作
    const i = events.value.findIndex((e) => e.id === updated.id)
    if (i >= 0) events.value[i] = { ...events.value[i], ...updated }
    verdictDialog.value = false
    ElMessage.success('判定已提交')
    loadStatistics()
  } catch (e) {
    ElMessage.error('判定失败：' + (e.response?.data?.detail || e.message))
  } finally {
    verdictSaving.value = false
  }
}

// ---------- G1/G2：告警现场图 ----------
async function showEventImage(row) {
  if (eventImageObjectUrl) {
    URL.revokeObjectURL(eventImageObjectUrl)
    eventImageObjectUrl = ''
  }
  eventImageUrl.value = ''
  imageDialog.value = true
  imageLoading.value = true
  try {
    const result = await detectionApi.get(row.result_id)
    if (result.image_path) {
      eventImageUrl.value = await mediaApi.blobUrl(result.image_path)
      eventImageObjectUrl = eventImageUrl.value
    }
  } catch (e) {
    ElMessage.error('获取现场图失败：' + (e.response?.data?.detail || e.message))
  } finally {
    imageLoading.value = false
  }
}

onBeforeUnmount(() => {
  if (eventImageObjectUrl) URL.revokeObjectURL(eventImageObjectUrl)
})

onMounted(() => {
  loadRules()
  loadCameras()
  loadEvents()
  loadStatistics()
})
</script>
