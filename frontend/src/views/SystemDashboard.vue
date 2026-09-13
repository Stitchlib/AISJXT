<template>
  <div>
    <h2>系统仪表盘</h2>
    <el-row :gutter="16">
      <el-col :span="8">
        <el-card shadow="hover">
          CPU 使用率：<b>{{ health?.cpu_percent ?? '--' }}%</b>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          内存使用率：<b>{{ health?.memory_percent ?? '--' }}%</b>
        </el-card>
      </el-col>
      <el-col :span="8">
        <el-card shadow="hover">
          磁盘使用率：<b>{{ health?.disk_percent ?? '--' }}%</b>
        </el-card>
      </el-col>
    </el-row>

    <!-- L9 业务级健康指标 -->
    <el-row
      :gutter="16"
      style="margin-top: 16px"
    >
      <el-col :span="6">
        <el-card shadow="hover">
          推理延迟 P50：<b>{{ health?.inference_latency_ms?.p50 ?? '--' }} ms</b>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          推理延迟 P95：<b>{{ health?.inference_latency_ms?.p95 ?? '--' }} ms</b>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          帧丢帧率：<b>{{ health?.frame_drop_rate != null ? (health.frame_drop_rate * 100).toFixed(2) : '--' }}%</b>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          WS 在线连接：<b>{{ health?.websocket_clients ?? '--' }}</b>
        </el-card>
      </el-col>
    </el-row>
    <el-row
      :gutter="16"
      style="margin-top: 16px"
    >
      <el-col :span="6">
        <el-card shadow="hover">
          DB 大小：<b>{{ health?.db_size_mb ?? '--' }} MB</b>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          写入 QPS：<b>{{ health?.write_qps ?? '--' }}</b>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          检测器模式：<b>{{ health?.detector_mode ?? '--' }}</b>
        </el-card>
      </el-col>
      <el-col :span="6">
        <el-card shadow="hover">
          配置状态：
          <el-tag
            v-if="health?.config_degraded"
            type="danger"
            size="small"
          >
            降级
          </el-tag>
          <el-tag
            v-else
            type="success"
            size="small"
          >
            正常
          </el-tag>
        </el-card>
      </el-col>
    </el-row>

    <el-card
      shadow="hover"
      style="margin-top: 16px"
    >
      <div
        ref="chart"
        style="height: 300px"
      />
    </el-card>

    <el-row
      :gutter="16"
      style="margin-top: 16px"
    >
      <el-col :span="8">
        <el-statistic
          title="检测总数"
          :value="stats.total"
        />
      </el-col>
      <el-col :span="8">
        <el-statistic
          title="缺陷总数"
          :value="stats.defect_count"
        />
      </el-col>
      <el-col :span="8">
        <el-statistic
          title="缺陷率"
          :value="(stats.defect_rate * 100).toFixed(1) + '%'"
        />
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
