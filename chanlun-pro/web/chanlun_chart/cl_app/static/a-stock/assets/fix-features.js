// 修复：sidebar搜索框 + 头部大单天数统计
(function() {
  'use strict';

  var INJECTED = false;

  // ===== 1. 左侧栏搜索框 =====
  function injectSidebarSearch() {
    var header = document.querySelector('.sidebar-header');
    if (!header) return;
    // 检查是否已注入
    if (header.nextElementSibling && header.nextElementSibling.classList.contains('ss-wrapper')) return;

    var wrapper = document.createElement('div');
    wrapper.className = 'ss-wrapper';
    wrapper.style.cssText = 'display:flex; align-items:center; padding:4px 8px; border-bottom:1px solid #eee;';
    
    var input = document.createElement('input');
    input.type = 'text';
    input.placeholder = '输入股票代码回车跳转';
    input.style.cssText = 'flex:1; border:1px solid #ddd; border-radius:4px; padding:6px 8px; font-size:13px; outline:none;';
    
    input.addEventListener('keydown', function(e) {
      if (e.key === 'Enter') {
        var code = input.value.trim();
        if (code) {
          window.location.hash = '/kline/' + code;
        }
      }
    });

    wrapper.appendChild(input);
    header.parentNode.insertBefore(wrapper, header.nextSibling);
  }

  // ===== 2. 头部大单天数统计 =====
  function injectHeaderStats() {
    var title = document.querySelector('.van-nav-bar__title');
    if (!title) return;
    // 检查是否已注入
    if (title.querySelector('.bdays')) return;

    var match = title.textContent.trim().match(/^(\d{6})\s/);
    if (!match) return;
    var code = match[1];

    var daysEl = document.createElement('span');
    daysEl.className = 'bdays';
    daysEl.style.cssText = 'font-size:11px; color:#999; margin-left:6px; white-space:nowrap;';
    daysEl.textContent = '加载中...';
    title.appendChild(daysEl);

    fetch('/api/v1/big-buy-days/' + code)
      .then(function(r) { return r.json(); })
      .then(function(data) {
        daysEl.textContent = '5日' + data.d5 + '次/10日' + data.d10 + '次/20日' + data.d20 + '次';
      })
      .catch(function() {
        daysEl.textContent = '';
      });
  }

  // ===== 3. 执行 =====
  function apply() {
    if (window.location.hash.indexOf('/kline/') !== -1) {
      injectSidebarSearch();
      injectHeaderStats();
    }
  }

  // 页面加载后执行
  if (document.readyState === 'loading') {
    document.addEventListener('DOMContentLoaded', apply);
  } else {
    apply();
  }

  // SPA 路由变化
  window.addEventListener('hashchange', function() {
    setTimeout(apply, 400);
  });

  // MutationObserver 兜底（只在未注入时触发）
  var observer = new MutationObserver(function() {
    if (!document.querySelector('.ss-wrapper') || !document.querySelector('.bdays')) {
      apply();
    }
  });
  var app = document.getElementById('app');
  if (app) observer.observe(app, { childList: true, subtree: true });
})();
