/**
 * 告警中心展示文案/标签类型映射（规则表与事件表共用，保证口径一致）。
 */
const METRIC_LABELS = { defect_rate: '缺陷率', defect_count: '缺陷数', processing_time_ms: '处理耗时(ms)' }
const WEBHOOK_LABELS = { generic: '通用', dingtalk: '钉钉', feishu: '飞书', wecom: '企业微信' }
const SEVERITY_TYPES = { critical: 'danger', high: 'warning', warning: 'warning', info: 'info' }
const VERDICT_LABELS = { confirmed: '确认缺陷', false_positive: '误报', missed: '漏报', pending: '待判定' }
const VERDICT_TYPES = { confirmed: 'success', false_positive: 'danger', missed: 'warning', pending: 'info' }

export function useAlertLabels() {
  return {
    metricText: (m) => METRIC_LABELS[m] || m,
    webhookText: (t) => WEBHOOK_LABELS[t] || 'Webhook',
    severityType: (s) => SEVERITY_TYPES[s] || 'info',
    verdictText: (v) => VERDICT_LABELS[v] || v,
    verdictType: (v) => VERDICT_TYPES[v] || 'info',
  }
}
