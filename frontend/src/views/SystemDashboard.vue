<template>
  <div>
    <h2>系统仪表盘</h2>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover">CPU 使用率：<b>{{ health?.cpu_percent ?? '--' }}%</b></el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">内存使用率：<b>{{ health?.memory_percent ?? '--' }}%</b></el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">磁盘使用率：<b>{{ health?.disk_percent ?? '--' }}%</b></el-card>
      </el-col>
    </el-row>

    <el-card shadow="hover" style="margin-top: 16px">
      <div ref="chart" style="height: 300px"></div>
    </el-card>

    <el-row :gutter="16" style="margin-top: 16px">
      <el-col :span="8">
        <el-statistic title="检测总数" :value="stats.total" />
      </el-col>
      <el-col :span="8">
        <el-statistic title="缺陷总数" :value="stats.defect_count" />
      </el-col>
      <el-col :span="8">
        <el-statistic title="缺陷率" :value="(stats.defect_rate * 100).toFixed(1) + '%'" />
      </el-col>
    </el-row>
  </div>
</template>

<script setup>
import { ref, onMounted, onUnmounted } from 'vue'
import * as echarts from 'echarts'
import { healthApi, detectionApi } from '@/api'

const health = ref(null)
const stats = ref({ total: 0, defect_count: 0, defect_rate: 0 })
const chart = ref(null)
let inst = null
let timer = null

async function load() {
  try {
    health.value = await healthApi.system()
    stats.value = await detectionApi.statistics()
    renderChart()
  } catch (e) {
    /* 后端未启动时不阻塞页面 */
  }
}

function renderChart() {
  if (!chart.value) return
  if (!inst) inst = echarts.init(chart.value)
  inst.setOption({
    title: { text: '系统资源占用 (%)' },
    tooltip: {},
    xAxis: { type: 'category', data: ['CPU', '内存', '磁盘'] },
    yAxis: { type: 'value', max: 100 },
    series: [
      {
        type: 'bar',
        data: [
          health.value?.cpu_percent || 0,
          health.value?.memory_percent || 0,
          health.value?.disk_percent || 0,
        ],
        itemStyle: { color: '#409eff' },
      },
    ],
  })
}

onMounted(() => {
  load()
  timer = setInterval(load, 5000)
})
onUnmounted(() => {
  clearInterval(timer)
  inst && inst.dispose()
})
</script>
