import { createApp } from 'vue'
import ElementPlus from 'element-plus'
import 'element-plus/dist/index.css'
import App from './App.vue'
import router from './router'
import { setupStore, actions } from './store'
import { authApi } from './api'
import { clearToken } from './api/client'

const app = createApp(App)
app.use(router)
app.use(ElementPlus)

const { token } = setupStore(app)

// 启动时若有 token，恢复当前登录用户信息（刷新后保持登录态）
if (token) {
  authApi
    .me()
    .then((u) => actions.setUser(u))
    .catch(() => {
      clearToken()
      if (window.location.hash !== '#/login') window.location.hash = '#/login'
    })
}

app.mount('#app')
