<template>
  <div>
    <h2>告警中心</h2>

    <!-- 判定统计（G2）：误报率趋势卡片 -->
    <el-card shadow="hover" style="margin-bottom: 16px" v-loading="statsLoading">
      <template #header>
        <div class="card-head">
          <b>判定统计（近 {{ statsDays }} 天）</b>
          <el-radio-group v-model="statsDays" size="small" @change="loadStatistics">
            <el-radio-button :label="7">7 天</el-radio-button>
            <el-radio-button :label="30">30 天</el-radio-button>
            <el-radio-button :label="90">90 天</el-radio-button>
          </el-radio-group>
        </div>
      </template>
      <el-row :gutter="16">
        <el-col :span="4"><div class="stat"><div class="stat-num">{{ stats.false_positive_rate != null ? (stats.false_positive_rate * 100).toFixed(1) + '%' : '—' }}</div><div class="stat-label">误报率</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="stat-num">{{ stats.confirmed_rate != null ? (stats.confirmed_rate * 100).toFixed(1) + '%' : '—' }}</div><div class="stat-label">确认率</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="stat-num warn">{{ stats.pending }}</div><div class="stat-label">待判定</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="stat-num">{{ stats.false_positive }}</div><div class="stat-label">误报</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="stat-num">{{ stats.confirmed }}</div><div class="stat-label">确认缺陷</div></div></el-col>
        <el-col :span="4"><div class="stat"><div class="stat-num">{{ stats.missed }}</div><div class="stat-label">漏报</div></div></el-col>
      </el-row>
    </el-card>

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
        <el-table-column label="Webhook" width="120" align="center">
          <template #default="{ row }">
            <el-tag v-if="row.webhook_url" size="small" type="success">{{ webhookText(row.webhook_type) }}</el-tag>
            <span v-else>—</span>
          </template>
        </el-table-column>
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
        <el-table-column label="判定" width="110" align="center">
          <template #default="{ row }">
            <el-tooltip v-if="row.verdict && row.verdict !== 'pending'" placement="top">
              <template #content>
                <div>判定人：{{ row.judged_by || '—' }}</div>
                <div v-if="row.judged_at">时间：{{ row.judged_at }}</div>
                <div v-if="row.remark">备注：{{ row.remark }}</div>
              </template>
              <el-tag :type="verdictType(row.verdict)" size="small">{{ verdictText(row.verdict) }}</el-tag>
            </el-tooltip>
            <el-tag v-else type="info" size="small">待判定</el-tag>
          </template>
        </el-table-column>
        <el-table-column label="操作" width="230" fixed="right">
          <template #default="{ row }">
            <el-button v-if="row.result_id" size="small" @click="showEventImage(row)">现场图</el-button>
            <el-button
              v-if="canVerdict"
              type="primary"
              size="small"
              plain
              @click="openVerdictDialog(row)"
            >判定</el-button>
            <el-button
              v-if="!row.acknowledged"
              size="small"
              @click="acknowledge(row)"
            >确认</el-button>
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

    <!-- 人工判定对话框（G2） -->
    <el-dialog v-model="verdictDialog" title="告警人工判定" width="440px">
      <el-form label-width="80px">
        <el-form-item label="事件">
          <span class="verdict-event">#{{ verdictTarget?.id }} {{ verdictTarget?.message }}</span>
        </el-form-item>
        <el-form-item label="判定">
          <el-radio-group v-model="verdictForm.verdict">
            <el-radio label="confirmed">确认缺陷</el-radio>
            <el-radio label="false_positive">误报</el-radio>
            <el-radio label="missed">漏报</el-radio>
          </el-radio-group>
        </el-form-item>
        <el-form-item label="备注">
          <el-input v-model="verdictForm.remark" type="textarea" :rows="2" placeholder="可选，如：背景纹理干扰" />
        </el-form-item>
      </el-form>
      <template #footer>
        <el-button @click="verdictDialog = false">取消</el-button>
        <el-button type="primary" :loading="verdictSaving" @click="saveVerdict">提交判定</el-button>
      </template>
    </el-dialog>

    <!-- 现场图查看对话框（G1/G2 联动） -->
    <el-dialog v-model="imageDialog" title="告警现场图" width="720px">
      <div v-loading="imageLoading" class="event-image-box">
        <el-image
          v-if="eventImageUrl"
          :src="eventImageUrl"
          fit="contain"
          :preview-src-list="[eventImageUrl]"
          preview-teleported
          style="width: 100%; max-height: 480px"
        />
        <el-empty v-else-if="!imageLoading" description="该事件关联的检测记录无现场图（可能未开启留存或已被清理）" />
      </div>
    </el-dialog>

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
        <el-form-item label="冷却(秒)">
          <el-input-number
            v-model="ruleForm.cooldown_seconds"
            :min="0"
            :max="604800"
            :step="30"
            style="width: 100%"
          />
          <div class="cooldown-tip">冷却窗口内重复命中不重复通知，仅累计次数；0=不冷却</div>
        </el-form-item>
        <el-form-item label="作用域">
          <el-select v-model="ruleForm.scope" style="width: 100%">
            <el-option label="全部摄像头" value="all" />
            <el-option v-for="c in cameras" :key="c.id" :label="c.name || c.id" :value="c.id" />
          </el-select>
        </el-form-item>
        <el-form-item label="通知邮箱"><el-input v-model="ruleForm.notify_email" placeholder="可选" /></el-form-item>
        <!-- G3 多渠道通知：Webhook 渠道 -->
        <el-form-item label="Webhook 类型">
          <el-select v-model="ruleForm.webhook_type" style="width: 100%">
            <el-option label="关闭" value="" />
            <el-option label="通用 (generic)" value="generic" />
            <el-option label="钉钉" value="dingtalk" />
            <el-option label="飞书" value="feishu" />
            <el-option label="企业微信" value="wecom" />
          </el-select>
        </el-form-item>
        <el-form-item label="Webhook URL">
          <el-input v-model="ruleForm.webhook_url" placeholder="可选；留空则不推送 Webhook" />
        </el-form-item>
        <el-form-item label="启用"><el-switch v-model="ruleForm.enabled" /></el-form-item>
      </el-form>
      <template #footer>
        <el-button v-if="editingRule" :loading="webhookTesting" @click="testWebhook">测试发送</el-button>
        <el-button @click="ruleDialog = false">取消</el-button>
        <el-button type="primary" :loading="ruleSaving" @click="saveRule">保存</el-button>
      </template>
    </el-dialog>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, onBeforeUnmount } from 'vue'
import { ElMessage, ElMessageBox } from 'element-plus'
import { alertsApi, cameraApi, detectionApi, mediaApi } from '@/api'
import { useStore } from '@/store'

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
const verdictForm = reactive({ verdict: 'confirmed', remark: '' })

// ---- 现场图查看（G1/G2）----
const imageDialog = ref(false)
const imageLoading = ref(false)
const eventImageUrl = ref('')
let eventImageObjectUrl = ''

const ruleDialog = ref(false)
const ruleSaving = ref(false)
const webhookTesting = ref(false)
const editingRule = ref(null)
const ruleForm = reactive({
  name: '',
  metric: 'defect_rate',
  operator: 'gt',
  threshold: 0.1,
  scope: 'all',
  notify_email: '',
  webhook_type: '',
  webhook_url: '',
  enabled: true,
})

function metricText(m) {
  return { defect_rate: '缺陷率', defect_count: '缺陷数', processing_time_ms: '处理耗时(ms)' }[m] || m
}
function webhookText(t) {
  return { generic: '通用', dingtalk: '钉钉', feishu: '飞书', wecom: '企业微信' }[t] || 'Webhook'
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
    ruleForm.cooldown_seconds = rule.cooldown_seconds ?? 0
    ruleForm.notify_email = rule.notify_email || ''
    ruleForm.webhook_type = rule.webhook_type || ''
    ruleForm.webhook_url = rule.webhook_url || ''
    ruleForm.enabled = !!rule.enabled
  } else {
    ruleForm.name = ''
    ruleForm.metric = 'defect_rate'
    ruleForm.operator = 'gt'
    ruleForm.threshold = 0.1
    ruleForm.scope = 'all'
    ruleForm.notify_email = ''
    ruleForm.webhook_type = ''
    ruleForm.webhook_url = ''
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
    cooldown_seconds: ruleForm.cooldown_seconds ?? 0,
    notify_email: ruleForm.notify_email || undefined,
    webhook_type: ruleForm.webhook_type || undefined,
    webhook_url: ruleForm.webhook_url || undefined,
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
function verdictText(v) {
  return { confirmed: '确认缺陷', false_positive: '误报', missed: '漏报', pending: '待判定' }[v] || v
}
function verdictType(v) {
  return { confirmed: 'success', false_positive: 'danger', missed: 'warning', pending: 'info' }[v] || 'info'
}

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
  verdictForm.verdict = row.verdict && row.verdict !== 'pending' ? row.verdict : 'confirmed'
  verdictForm.remark = row.remark || ''
  verdictDialog.value = true
}

async function saveVerdict() {
  verdictSaving.value = true
  try {
    const updated = await alertsApi.setVerdict(verdictTarget.value.id, {
      verdict: verdictForm.verdict,
      remark: verdictForm.remark || undefined,
    })
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

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
.stat { text-align: center; padding: 4px 0; }
.stat-num { font-size: 24px; font-weight: 600; line-height: 1.4; }
.stat-num.warn { color: #e6a23c; }
.stat-label { font-size: 12px; color: #909399; }
.cooldown-tip { font-size: 12px; color: #909399; line-height: 1.4; }
.verdict-event { color: #606266; font-size: 13px; }
.event-image-box { min-height: 200px; display: flex; align-items: center; justify-content: center; }
</style>
