<template>
  <div>
    <van-nav-bar title="🔗 常用链接" left-arrow @click-left="$router.back()" />
    <div class="links-container" style="padding:16px">
      <van-cell-group>
        <van-cell title="📈 深交所公告" is-link @click="open('https://www.szse.cn/disclosure/notice/index.html')" />
        <van-cell title="📈 上交所公告" is-link @click="open('https://www.sse.com.cn/disclosure/announcement/')" />
        <van-cell title="📊 东方财富" is-link @click="open('https://www.eastmoney.com')" />
        <van-cell title="📊 同花顺" is-link @click="open('https://www.10jqka.com.cn')" />
        <van-cell title="📰 财联社" is-link @click="open('https://www.cls.cn')" />
        <van-cell title="📰 华尔街见闻" is-link @click="open('https://wallstreetcn.com')" />
        <van-cell title="📋 巨潮资讯网" is-link @click="open('http://www.cninfo.com.cn')" />
        <van-cell title="💬 雪球" is-link @click="open('https://xueqiu.com')" />
      </van-cell-group>
    </div>
  </div>
</template>

<script setup>
const open = (url) => window.open(url, '_blank')
</script>
