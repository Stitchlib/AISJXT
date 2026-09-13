import { reactive } from 'vue'
import { cameraApi } from '@/api'

/**
 * 摄像头缩略图 ticket 管理（M7：<img> 请求使用一次性 stream ticket，避免 JWT 进 URL）。
 * @param {import('vue').Ref<Array>|(() => Array)} camerasSource 摄像头列表 ref 或 getter
 */
export function useCameraSnapshots(camerasSource) {
  // 缩略图与放大预览各需一个独立 ticket（<img> 与 el-image 预览会分别请求）
  const snaps = reactive({})
  const snapPreviews = reactive({})

  async function loadSnap(id) {
    if (!id) return
    try {
      snaps[id] = await cameraApi.snapshotUrl(id, true, 80)
      snapPreviews[id] = await cameraApi.snapshotUrl(id, true, 90)
    } catch {
      snaps[id] = ''
      snapPreviews[id] = ''
    }
  }

  function snapshotUrl(id) {
    return snaps[id] || ''
  }

  function previewShotUrl(id) {
    return snapPreviews[id] || ''
  }

  // 缩略图定期重新换取 ticket 刷新，避免浏览器长期缓存旧画面
  function refreshSnaps() {
    const list = typeof camerasSource === 'function' ? camerasSource() : camerasSource.value
    ;(list || []).forEach((c) => c.enabled && loadSnap(c.id))
  }

  return { snaps, snapPreviews, loadSnap, snapshotUrl, previewShotUrl, refreshSnaps }
}
