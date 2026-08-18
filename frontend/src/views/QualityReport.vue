<template>
  <div>
    <div class="head">
      <h2>质检报告</h2>
      <div class="ops">
        <el-select v-model="bucket" style="width: 140px" @change="load">
          <el-option label="按天" value="day" />
          <el-option label="按小时" value="hour" />
          <el-option label="按周" value="week" />
          <el-option label="按月" value="month" />
        </el-select>
        <el-button :loading="exportingExcel" @click="exportExcel">导出 Excel</el-button>
        <el-button :loading="exportingCsv" @click="exportCsv">导出 CSV</el-button>
      </div>
    </div>

    <el-row :gutter="16" v-loading="loading">
      <el-col :span="6">
        <el-card shadow="hover"><el-statistic title="总检测数" :value="summary.total" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover"><el-statistic title="缺陷总数" :value="summary.defect_count" /></el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="不良率" :value="(summary.defect_rate * 100).toFixed(2) + '%'" />
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          <el-statistic title="平均耗时(ms)" :value="Math.round(summary.avg_processing_ms || 0)" />
        </el-card>
      </el-col>
    </el-row>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="10">
        <el-card v-loading="loading" shadow="hover">
          <div ref="pieChart" style="height: 320px"></div>
          <el-empty v-if="!loading && byType.length === 0" description="暂无瑕疵分类数据" />
        </el-card>
      </el-col>
      <el-col :span="14">
        <el-card v-loading="loading" shadow="hover">
          <div ref="trendChart" style="height: 320px"></div>
          <el-empty v-if="!loading && trend.length === 0" description="暂无趋势数据" />
        </el-card>
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, reactive, onMounted, onUnmounted, nextTick } from 'vue'
import * as echarts from 'echarts'
import { ElMessage } from 'element-plus'
import { reportsApi } from '@/api'
import { downloadBlob } from '@/utils/download'

const loading = ref(false)
const exportingExcel = ref(false)
const exportingCsv = ref(false)
const bucket = ref('day')

const summary = reactive({ total: 0, defect_count: 0, defect_rate: 0, avg_processing_ms: 0 })
const byType = ref([])
const trend = ref([])

const pieChart = ref(null)
const trendChart = ref(null)
let pieInst = null
let trendInst = null

async function load() {
  loading.value = true
  try {
    const data = await reportsApi.summary({ bucket: bucket.value })
    summary.total = data.total || 0
    summary.defect_count = data.defect_count || 0
    summary.defect_rate = data.defect_rate || 0
    summary.avg_processing_ms = data.avg_processing_ms || 0
    byType.value = data.by_type || []
    trend.value = data.trend || []
    await nextTick()
    renderPie()
    renderTrend()
  } catch (e) {
    ElMessage.error('加载报告失败：' + (e.response?.data?.detail || e.message))
  } finally {
    loading.value = false
  }
}

function renderPie() {
  if (!pieChart.value) return
  if (!pieInst) pieInst = echarts.init(pieChart.value)
  pieInst.setOption({
    title: { text: '瑕疵类型占比', left: 'center' },
    tooltip: { trigger: 'item' },
    legend: { bottom: 0 },
    series: [
      {
        type: 'pie',
        radius: ['40%', '65%'],
        data: byType.value.map((d) => ({ name: d.class_name, value: d.count })),
        label: { formatter: '{b}: {c}' },
      },
    ],
  })
}

function renderTrend() {
  if (!trendChart.value) return
  if (!trendInst) trendInst = echarts.init(trendChart.value)
  trendInst.setOption({
    title: { text: '不良率趋势', left: 'center' },
    tooltip: { trigger: 'axis' },
    legend: { bottom: 0, data: ['不良率(%)', '检测数'] },
    xAxis: { type: 'category', data: trend.value.map((t) => t.bucket) },
    yAxis: [
      { type: 'value', name: '不良率(%)' },
      { type: 'value', name: '检测数' },
    ],
    series: [
      {
        name: '不良率(%)',
        type: 'line',
        smooth: true,
        data: trend.value.map((t) => +(t.defect_rate * 100).toFixed(2)),
        itemStyle: { color: '#f56c6c' },
      },
      {
        name: '检测数',
        type: 'bar',
        yAxisIndex: 1,
        data: trend.value.map((t) => t.total),
        itemStyle: { color: '#409eff' },
      },
    ],
  })
}

async function exportExcel() {
  exportingExcel.value = true
  try {
    const blob = await reportsApi.exportExcel()
    downloadBlob(blob, `quality_report_${Date.now()}.xlsx`)
    ElMessage.success('Excel 已导出')
  } catch (e) {
    ElMessage.error('导出失败：' + (e.response?.data?.detail || e.message))
  } finally {
    exportingExcel.value = false
  }
}

async function exportCsv() {
  exportingCsv.value = true
  try {
    const blob = await reportsApi.exportCsv()
    downloadBlob(blob, `quality_report_${Date.now()}.csv`)
    ElMessage.success('CSV 已导出')
  } catch (e) {
    ElMessage.error('导出失败：' + (e.response?.data?.detail || e.message))
  } finally {
    exportingCsv.value = false
  }
}

function onResize() {
  pieInst && pieInst.resize()
  trendInst && trendInst.resize()
}

onMounted(() => {
  load()
  window.addEventListener('resize', onResize)
})
onUnmounted(() => {
  window.removeEventListener('resize', onResize)
  pieInst && pieInst.dispose()
  trendInst && trendInst.dispose()
})
</script>

<style scoped>
.head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.ops { display: flex; gap: 8px; }
</style>
