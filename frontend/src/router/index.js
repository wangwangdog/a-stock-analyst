import { createRouter, createWebHashHistory } from 'vue-router'
import Home from '../views/Home.vue'
import Kline from '../views/Kline.vue'
import Fundamentals from '../views/Fundamentals.vue'
import Screener from '../views/Screener.vue'

const routes = [
  { path: '/', name: 'Home', component: Home },
  { path: '/kline/:symbol', name: 'Kline', component: Kline, props: true },
  { path: '/fund/:symbol', name: 'Fund', component: Fundamentals, props: true },
  { path: '/screener', name: 'Screener', component: Screener },
]

export default createRouter({
  history: createWebHashHistory(),
  routes,
})
