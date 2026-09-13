<template>
  <el-card
    v-loading="loading"
    shadow="hover"
    style="margin-bottom: 16px"
  >
    <template #header>
      <div class="card-head">
        <b>判定统计（近 {{ days }} 天）</b>
        <el-radio-group
          :model-value="days"
          size="small"
          @update:model-value="emit('update:days', $event); emit('change')"
        >
          <el-radio-button :label="7">
            7 天
          </el-radio-button>
          <el-radio-button :label="30">
            30 天
          </el-radio-button>
          <el-radio-button :label="90">
            90 天
          </el-radio-button>
        </el-radio-group>
      </div>
    </template>
    <el-row :gutter="16">
      <el-col :span="4">
        <div class="stat">
          <div class="stat-num">
            {{ pct(stats.false_positive_rate) }}
          </div><div class="stat-label">
            误报率
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat">
          <div class="stat-num">
            {{ pct(stats.confirmed_rate) }}
          </div><div class="stat-label">
            确认率
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat">
          <div class="stat-num warn">
            {{ stats.pending }}
          </div><div class="stat-label">
            待判定
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat">
          <div class="stat-num">
            {{ stats.false_positive }}
          </div><div class="stat-label">
            误报
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat">
          <div class="stat-num">
            {{ stats.confirmed }}
          </div><div class="stat-label">
            确认缺陷
          </div>
        </div>
      </el-col>
      <el-col :span="4">
        <div class="stat">
          <div class="stat-num">
            {{ stats.missed }}
          </div><div class="stat-label">
            漏报
          </div>
        </div>
      </el-col>
    </el-row>
  </el-card>
</template>

<script setup>
defineProps({
  stats: { type: Object, default: () => ({}) },
  days: { type: Number, default: 30 },
  loading: { type: Boolean, default: false },
})
const emit = defineEmits(['update:days', 'change'])

function pct(v) {
  return v != null ? (v * 100).toFixed(1) + '%' : '—'
}
</script>

<style scoped>
.card-head { display: flex; align-items: center; justify-content: space-between; }
.stat { text-align: center; padding: 4px 0; }
.stat-num { font-size: 24px; font-weight: 600; line-height: 1.4; }
.stat-num.warn { color: #e6a23c; }
.stat-label { font-size: 12px; color: #909399; }
</style>
