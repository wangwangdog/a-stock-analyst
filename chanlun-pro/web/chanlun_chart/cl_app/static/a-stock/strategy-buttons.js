/**
 * 策略页面按钮注入脚本
 * 在 #/strategies 路由下添加"盘前策略"和"盘中策略"两个按钮
 * 
 * 这是一个非侵入式方案，不修改编译后的 Vue 代码。
 * 通过 MutationObserver 检测 DOM，找到策略页面并注入按钮。
 */

(function() {
    'use strict';

    // 检测当前路由是否为策略页面
    function isStrategiesPage() {
        return window.location.hash === '#/strategies' || 
               window.location.hash === '#/strategies/' ||
               window.location.pathname.endsWith('/strategies');
    }

    // 寻找策略页面的容器
    function findStrategyContainer() {
        // 尝试多种选择器来定位策略页面主内容区
        const selectors = [
            '.van-tabs__content',       // Vant tabs content
            '.van-pull-refresh',        // Pull refresh wrapper
            '.page-content',            // Custom page content
            '#app > div > div',         // App root children
            '.van-tab__panel',          // Tab panel (when "量化选股" tab is active)
        ];
        
        for (const sel of selectors) {
            const el = document.querySelector(sel);
            if (el) return el;
        }
        return null;
    }

    // 检查按钮是否已注入
    function isInjected() {
        return document.getElementById('strategy-action-buttons') !== null;
    }

    // 注入按钮
    function injectButtons() {
        if (isInjected()) return false;  // 已经注入
        
        const container = findStrategyContainer();
        if (!container) return false;

        // 创建按钮栏
        const btnBar = document.createElement('div');
        btnBar.id = 'strategy-action-buttons';
        btnBar.style.cssText = `
            display: flex;
            gap: 10px;
            padding: 12px 16px;
            background: #fff;
            margin: 0 0 12px 0;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
        `;

        // 盘前策略按钮
        const preMarketBtn = document.createElement('button');
        preMarketBtn.textContent = '🌅 盘前策略';
        preMarketBtn.style.cssText = `
            flex: 1;
            padding: 12px 0;
            border: none;
            border-radius: 8px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            box-shadow: 0 2px 8px rgba(102, 126, 234, 0.4);
        `;
        preMarketBtn.addEventListener('mouseenter', () => {
            preMarketBtn.style.transform = 'translateY(-1px)';
            preMarketBtn.style.boxShadow = '0 4px 12px rgba(102, 126, 234, 0.5)';
        });
        preMarketBtn.addEventListener('mouseleave', () => {
            preMarketBtn.style.transform = 'none';
            preMarketBtn.style.boxShadow = '0 2px 8px rgba(102, 126, 234, 0.4)';
        });

        // 盘中策略按钮
        const intradayBtn = document.createElement('button');
        intradayBtn.textContent = '⚡ 盘中策略';
        intradayBtn.style.cssText = `
            flex: 1;
            padding: 12px 0;
            border: none;
            border-radius: 8px;
            background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);
            color: white;
            font-size: 15px;
            font-weight: 600;
            cursor: pointer;
            transition: all 0.2s ease;
            box-shadow: 0 2px 8px rgba(245, 87, 108, 0.4);
        `;
        intradayBtn.addEventListener('mouseenter', () => {
            intradayBtn.style.transform = 'translateY(-1px)';
            intradayBtn.style.boxShadow = '0 4px 12px rgba(245, 87, 108, 0.5)';
        });
        intradayBtn.addEventListener('mouseleave', () => {
            intradayBtn.style.transform = 'none';
            intradayBtn.style.boxShadow = '0 2px 8px rgba(245, 87, 108, 0.4)';
        });

        // 结果展示区
        const resultArea = document.createElement('div');
        resultArea.id = 'strategy-result-area';
        resultArea.style.cssText = `
            margin: 12px 16px;
            padding: 16px;
            background: #fff;
            border-radius: 8px;
            box-shadow: 0 1px 3px rgba(0,0,0,0.08);
            display: none;
            font-size: 14px;
            line-height: 1.6;
            white-space: pre-wrap;
        `;

        // 加载状态
        function setLoading(btn, loading) {
            if (loading) {
                btn.disabled = true;
                btn.style.opacity = '0.7';
                btn.innerHTML = '⏳ 运行中...';
            } else {
                btn.disabled = false;
                btn.style.opacity = '1';
            }
        }

        // 恢复按钮文本
        function restoreText(btn, text) {
            if (!btn.disabled) return;
            btn.innerHTML = text;
        }

        // 显示结果
        function showResult(text, isError) {
            const area = document.getElementById('strategy-result-area');
            if (!area) return;
            area.style.display = 'block';
            area.style.backgroundColor = isError ? '#fff0f0' : '#f0faf0';
            area.style.borderLeft = isError ? '4px solid #e53935' : '4px solid #4CAF50';
            area.innerHTML = text.replace(/\n/g, '<br>');
            area.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
        }

        // 盘前策略点击事件
        preMarketBtn.addEventListener('click', async function() {
            setLoading(preMarketBtn, true);
            preMarketBtn.innerHTML = '🌅 盘前分析中...';
            try {
                const resp = await fetch('/api/v1/strategy/pre-market', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'ok') {
                    showResult(data.report || '✅ 盘前策略分析完成');
                } else {
                    showResult('❌ 盘前策略失败: ' + (data.error || '未知错误'), true);
                }
            } catch (e) {
                showResult('❌ 网络错误: ' + e.message, true);
            } finally {
                setLoading(preMarketBtn, false);
                setTimeout(() => restoreText(preMarketBtn, '🌅 盘前策略'), 100);
            }
        });

        // 盘中策略点击事件
        intradayBtn.addEventListener('click', async function() {
            setLoading(intradayBtn, true);
            intradayBtn.innerHTML = '⚡ 盘中扫描中...';
            try {
                const resp = await fetch('/api/v1/strategy/intraday', { method: 'POST' });
                const data = await resp.json();
                if (data.status === 'ok') {
                    showResult(data.report || '✅ 盘中策略扫描完成');
                } else {
                    showResult('❌ 盘中策略失败: ' + (data.error || '未知错误'), true);
                }
            } catch (e) {
                showResult('❌ 网络错误: ' + e.message, true);
            } finally {
                setLoading(intradayBtn, false);
                setTimeout(() => restoreText(intradayBtn, '⚡ 盘中策略'), 100);
            }
        });

        btnBar.appendChild(preMarketBtn);
        btnBar.appendChild(intradayBtn);

        // 插入到容器最前面
        container.insertBefore(btnBar, container.firstChild);
        
        // 把结果区也加进去
        if (container.parentNode) {
            container.parentNode.insertBefore(resultArea, container.nextSibling);
        } else {
            container.appendChild(resultArea);
        }

        return true;
    }

    // 定时检测路由变化和DOM就绪
    let lastHash = '';
    const observer = new MutationObserver(function() {
        const currentHash = window.location.hash;
        if (currentHash !== lastHash) {
            lastHash = currentHash;
            if (isStrategiesPage()) {
                setTimeout(injectButtons, 300);  // 等 Vue 渲染完成
            }
        }
    });

    // 监听 hash 变化
    window.addEventListener('hashchange', function() {
        if (isStrategiesPage()) {
            setTimeout(injectButtons, 300);
        }
    });

    // 监听 DOM 变化
    observer.observe(document.body, { childList: true, subtree: true });

    // 页面加载后立即尝试
    document.addEventListener('DOMContentLoaded', function() {
        if (isStrategiesPage()) {
            setTimeout(injectButtons, 500);
        }
    });

    // 兜底：每2秒检查一次（直到成功或5秒后）
    let attempts = 0;
    const fallbackTimer = setInterval(function() {
        attempts++;
        if (attempts > 5) {
            clearInterval(fallbackTimer);
            return;
        }
        if (isStrategiesPage() && injectButtons()) {
            clearInterval(fallbackTimer);
        }
    }, 1000);

    console.log('📋 策略页面按钮注入脚本已加载');
})();
