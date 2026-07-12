import axios from 'axios'

const api = axios.create({
  baseURL: '/api/v1',
  timeout: 30000,
})

export function getKline(symbol, params = {}) {
  return api.get(`/kline/${symbol}`, { params })
}

export function getFundamentals(symbol) {
  return api.get(`/fundamentals/${symbol}`)
}

export function getHealth() {
  return api.get('/health')
}

export function screenStocks(params = {}) {
  return api.get('/screener', { params })
}

export function getStockList() {
  return api.get('/stocks', { timeout: 60000 })
}

export function getBigBuy(symbol, days = 60) {
  return api.get(`/bigbuy/${symbol}`, { params: { days } })
}

export function getBigDealSummary(symbol, limit = 60) {
  return api.get(`/big-deal-summary/${symbol}`, { params: { limit } })
}

export function getBigBuySummary(symbol, limit = 60) {
  return api.get(`/big-buy-summary/${symbol}`, { params: { limit } })
}

export function getBigBuyNet(symbol, days = 60) {
  return api.get(`/big-buy-summary/${symbol}`, { params: { limit: days } })
}
