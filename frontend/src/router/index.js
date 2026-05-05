import { createRouter, createWebHashHistory } from 'vue-router'
import Login from '../views/Login.vue'
import Home from '../views/Home.vue'
import Kline from '../views/Kline.vue'
import Fundamentals from '../views/Fundamentals.vue'
import Screener from '../views/Screener.vue'

const routes = [
  { path: '/login', name: 'Login', component: Login },
  { path: '/', name: 'Home', component: Home, meta: { requiresAuth: true } },
  { path: '/kline/:symbol', name: 'Kline', component: Kline, props: true, meta: { requiresAuth: true } },
  { path: '/fund/:symbol', name: 'Fund', component: Fundamentals, props: true, meta: { requiresAuth: true } },
  { path: '/screener', name: 'Screener', component: Screener, meta: { requiresAuth: true } },
]

const router = createRouter({
  history: createWebHashHistory(),
  routes,
})

// Auth guard: check localStorage
router.beforeEach((to, from, next) => {
  if (to.meta.requiresAuth) {
    const username = localStorage.getItem('username')
    if (!username) {
      next('/login')
      return
    }
  }
  next()
})

// Helper: get current username
export function getUsername() {
  return localStorage.getItem('username') || ''
}

export default router
