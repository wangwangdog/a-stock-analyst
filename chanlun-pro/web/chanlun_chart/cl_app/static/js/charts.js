// 常量定义
const SHOW_DONE_ZS = true;    // 已完成中枢（实线）
const SHOW_UNDONE_ZS = true;  // 未完成中枢（虚线）
const SHOW_ZS_SAME_DIR = false;  // 进入笔离开笔同向过滤开关（cl1不兼容前端同向检测，关掉）
const SHOW_ZS_ENTRY_EXIT_CHECK = false;  // 中枢进出合理判断开关（关掉以显示中枢）
const ZS_RECALC_MODE = 2;       // 中枢ZG/ZD重算模式：0=重叠算法, 1=中枢内所有笔, 2=前三笔重叠极值

// 辅助：根据中枢内笔重算 ZG / ZD
// mode=0 前三笔重叠，mode=1 中枢内所有笔重叠，mode=2 前三笔重叠极值
// ZG = min(顶分型高点), ZD = max(底分型低点)
function recalcZhongshuFromBis(zs, bis, mode) {
  const st = zs.points?.[0]?.time;
  const et = zs.points?.[1]?.time;
  if (!st || !et || !bis?.length) return zs;
  const inner = bis
    .filter(b => { const t = b.points?.[0]?.time; return t && t >= st && t <= et; })
    .sort((a, b) => a.points[0].time - b.points[0].time);
  if (mode === 2) {
    // 前三笔重叠极值：ZG = min(顶分型高点), ZD = max(底分型低点)
    const target = inner.slice(0, 3);
    if (target.length < 3) return zs;
    const zg = Math.min(...target.map(b => Math.max(b.points[0].price, b.points[1].price)));
    const zd = Math.max(...target.map(b => Math.min(b.points[0].price, b.points[1].price)));
    return { ...zs, points: [{ time: st, price: zg }, { time: et, price: zd }] };
  }
  const target = mode === 0 ? inner.slice(0, 3) : inner;
  if (target.length < (mode === 0 ? 3 : 1)) return zs;
  // ZG = 所有顶分型的最低值（顶分型 = BI中较高的点）
  // ZD = 所有底分型的最高值（底分型 = BI中较低的点）
  const zg = Math.min(...target.map(b => Math.max(b.points[0].price, b.points[1].price)));
  const zd = Math.max(...target.map(b => Math.min(b.points[0].price, b.points[1].price)));
  return { ...zs, points: [{ time: st, price: zg }, { time: et, price: zd }] };
}

// 辅助：判断中枢的进入笔和离开笔是否同向（不同向则跳过）
function isSameDirectionEntryExit(zs, bis) {
  const st = zs.points?.[0]?.time;
  const et = zs.points?.[1]?.time;
  if (!st || !et || !bis?.length) return true;
  const sorted = [...bis].sort((a, b) => a.points[0].time - b.points[0].time);
  // 进入笔 = 中枢前最后一笔
  let entryBi = null;
  for (let i = sorted.length - 1; i >= 0; i--) {
    if (sorted[i].points[1].time <= st) { entryBi = sorted[i]; break; }
  }
  // 离开笔 = 中枢后第一笔
  let exitBi = null;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i].points[0].time >= et) { exitBi = sorted[i]; break; }
  }
  if (!entryBi || !exitBi) return true;
  const entryDir = entryBi.points[0].price < entryBi.points[1].price ? 'up' : 'down';
  const exitDir = exitBi.points[0].price < exitBi.points[1].price ? 'up' : 'down';
  return entryDir === exitDir;
}

// 辅助：中枢进出合理判断
// 上涨中枢：进入笔起点 < 其他笔底分型最低值，离开笔结束点 > 其他笔顶分型最高值
// 下降中枢：进入笔起点 > 其他笔顶分型最高值，离开笔结束点 < 其他笔底分型最低值
function isValidZhongshuEntryExit(zs, bis) {
  const st = zs.points?.[0]?.time;
  const et = zs.points?.[1]?.time;
  if (!st || !et || !bis?.length) return true;
  const sorted = [...bis].sort((a, b) => a.points[0].time - b.points[0].time);
  // 进入笔 = 中枢前最后一笔
  let entryBi = null;
  for (let i = sorted.length - 1; i >= 0; i--) {
    if (sorted[i].points[1].time <= st) { entryBi = sorted[i]; break; }
  }
  // 离开笔 = 中枢后第一笔
  let exitBi = null;
  for (let i = 0; i < sorted.length; i++) {
    if (sorted[i].points[0].time >= et) { exitBi = sorted[i]; break; }
  }
  if (!entryBi || !exitBi) return true;
  // 中枢内的其他笔
  const inner = sorted.filter(b => b.points[0].time >= st && b.points[0].time <= et);
  if (inner.length < 3) return true;
  // 根据进入笔方向判断是上涨中枢还是下降中枢
  const isUp = entryBi.points[0].price < entryBi.points[1].price;
  const minDiInner = Math.min(...inner.map(b => Math.min(b.points[0].price, b.points[1].price)));
  const maxDingInner = Math.max(...inner.map(b => Math.max(b.points[0].price, b.points[1].price)));
  if (isUp) {
    // 上涨中枢：进入笔起点 < 其他笔底分型低点，离开笔结束点 > 其他笔顶分型高点
    if (entryBi.points[0].price >= minDiInner) return false;
    if (exitBi.points[1].price <= maxDingInner) return false;
  } else {
    // 下降中枢：进入笔起点 > 其他笔顶分型高点，离开笔结束点 < 其他笔底分型低点
    if (entryBi.points[0].price <= maxDingInner) return false;
    if (exitBi.points[1].price >= minDiInner) return false;
  }
  return true;
}

const CHART_CONFIG = {
  COLORS: {
    DING: "#888888",
    DI: "#888888",
    BI: "#888888",
    XD: "#888888",
    ZSD: "#888888",
    BI_ZSS: "#888888",
    XD_ZSS: "#888888",
    ZSD_ZSS: "#888888",
    BCS: "#BBBBBB",
    BC_TEXT: "#000000",
    MMD_UP: "#888888",
    MMD_DOWN: "#888888",
    AI_PRED: "#8E44AD",
  },
  LINE_STYLES: {
    SOLID: 0,
    DOTTED: 1,
    DASHED: 2,
  },
  CHART_TYPES: [
    "fxs",
    "bis",
    "xds",
    "zsds",
    "bi_zss",
    "xd_zss",
    "zsd_zss",
    "bcs",
    "mmds",
    "trends",
  ],
};

// 防抖函数
function debounce(func, wait) {
  let timeout;
  return function (...args) {
    clearTimeout(timeout);
    timeout = setTimeout(() => func.apply(this, args), wait);
  };
}

// 图表工具类
const ChartUtils = {
  // 创建图表形状
  createShape(chart, points, options = {}) {
    const defaults = {
      lock: true,
      disableSelection: true,
      disableSave: true,
      disableUndo: true,
      showInObjectsTree: false,
      overrides: {},
    };

    const config = { ...defaults, ...options };
    return config.shape === "trend_line" ||
      config.shape === "rectangle" ||
      config.shape === "circle"
      ? chart.createMultipointShape(points, config)
      : chart.createShape(points, config);
  },

  // 创建分型点
  createFxShape(chart, fx, options = {}) {
    const color =
      fx.text === "ding" ? CHART_CONFIG.COLORS.DING :
      fx.text === "PROBLEM" ? "#000000" :
      CHART_CONFIG.COLORS.DI;
    return this.createShape(chart, fx.points, {
      shape: "circle",
      overrides: {
        backgroundColor: color,
        color: color,
        linewidth: 1,
        ...options.overrides,
      },
      ...options,
    });
  },

  // 创建线段
  createLineShape(chart, line, options = {}) {
    return this.createShape(chart, line.points, {
      shape: "trend_line",
      overrides: {
        linestyle: parseInt(line.linestyle) || 0,
        linewidth: options.linewidth || 1,
        linecolor: options.color || CHART_CONFIG.COLORS.BI,
        ...options.overrides,
      },
      ...options,
    });
  },

  // 创建中枢
  createZhongshuShape(chart, zs, options = {}) {
    const linestyle = parseInt(zs.linestyle);
    if (linestyle === 0 && !SHOW_DONE_ZS) return;    // 实线：已完成中枢
    if (linestyle === 1 && !SHOW_UNDONE_ZS) return;  // 虚线：未完成中枢
    return this.createShape(chart, zs.points, {
      shape: "rectangle",
      overrides: {
        linestyle: parseInt(zs.linestyle) || 0,
        linewidth: options.linewidth || 1,
        linecolor: options.color || CHART_CONFIG.COLORS.BI,
        backgroundColor: options.color || CHART_CONFIG.COLORS.BI,
        transparency: 95,
        color: options.color,
        "trendline.linecolor": options.color,
        fillBackground: true,
        filled: true,
        ...options.overrides,
      },
      ...options,
    });
  },

  // 创建文字标签
  createTextLabel(chart, point, text, options = {}) {
    return chart.createShape(point, {
      shape: "text",
      text: text,
      overrides: {
        fontSize: 10,
        color: "#333333",
        bold: true,
        ...options.overrides,
      },
      ...options,
    });
  },
  createMmdShape(chart, mmd, options = {}) {
    const isBuy = mmd.text.includes("B");
    const color = CHART_CONFIG.COLORS.MMD_UP;
    const shape = isBuy ? "arrow_up" : "arrow_down";

    return this.createShape(chart, mmd.points, {
      shape,
      text: mmd.text,
      overrides: {
        markerColor: color,
        backgroundColor: color,
        color: color,
        textColor: "#000000",
        fontsize: 12,
        transparency: 80,
        ...options.overrides,
      },
      ...options,
    });
  },

  // 创建趋势标注（气泡）
  createTrendLabel(chart, trend, options = {}) {
    const labelText = trend.text || trend.trend_type || "";
    const isUp = trend.direction === "up" || trend.trend_type?.includes("上涨");
    // 上涨用箭头↑，下跌用箭头↓
    const arrow = isUp ? "↑" : "↓";
    const displayText = `${arrow} ${labelText}`;
    return this.createShape(chart, trend.points, {
      shape: "balloon",
      text: displayText,
      overrides: {
        markerColor: CHART_CONFIG.COLORS.MMD_UP,
        backgroundColor: CHART_CONFIG.COLORS.MMD_UP,
        textColor: "#000000",
        fontsize: 14,
        transparency: 50,
        ...options.overrides,
      },
      ...options,
    });
  },

  createBcShape(chart, bc, options = {}) {
    return this.createShape(chart, bc.points, {
      shape: "balloon",
      text: bc.text,
      overrides: {
        markerColor: CHART_CONFIG.COLORS.BCS,
        backgroundColor: CHART_CONFIG.COLORS.BCS,
        textColor: CHART_CONFIG.COLORS.BC_TEXT,
        transparency: 70,
        backgroundTransparency: 70,
        fontsize: 12,
        ...options.overrides,
      },
      ...options,
    });
  },
};

// 图表管理类
class ChartManager {
  constructor(id) {
    this.id = id;
    this.obj_charts = {};
    this.widget = null;
    this.udf_datafeed = null;
    this.chart = null;
    this.debouncedDrawChanlun = debounce(() => this.draw_chanlun(), 1000);
  }

  // 初始化图表
  init() {
    this.udf_datafeed = new Datafeeds.UDFCompatibleDatafeed("/tv", 30000);
    this.widget = window.tvWidget = new TradingView.widget({
      debug: false,
      autosize: true,
      fullscreen: false,
      container: "tv_chart_container_" + this.id,
      symbol: Utils.get_market() + ":" + Utils.get_code(),
      interval: Utils.get_local_data(
        Utils.get_market() + "_interval_" + this.id
      ),
      datafeed: this.udf_datafeed,
      library_path: "static/charting_library/",
      theme: Utils.get_local_data("theme"),
      numeric_formatting: { decimal_sign: "." },
      loading_screen: { backgroundColor: "#FFFEF5" },
      time_frames: [],
      timezone: "Asia/Shanghai",
      locale: "zh",
      symbol_search_request_delay: 100,
      auto_save_delay: 5,
      study_count_limit: 100,
      disabled_features: ["go_to_date"],
      enabled_features: ["study_templates", "seconds_resolution"],
      saved_data_meta_info: {
        uid: 1,
        name: "default",
        description: "default",
      },
      charts_storage_url: "/tv",
      charts_storage_api_version: "1.1",
      client_id: "chanlun_pro_" + Utils.get_market() + "_" + this.id,
      user_id: "999",
      load_last_chart: true,
      custom_indicators_getter: this.getCustomIndicators,
      /* 强制使用蜡烛图 */
      chart_style: 1, // 1 = Candles (0=Bar 1=Candle 2=Line 3=Area 4=Renko...)
      overrides: {
        "paneProperties.background": "#FFFEF5",
        "paneProperties.backgroundType": "solid",
        "paneProperties.vertGridProperties.color": "#f5f0e0",
        "paneProperties.horzGridProperties.color": "#f5f0e0",
        "paneProperties.crossHairProperties.color": "#e8e0c8",
        "scalesProperties.textColor": "#333",
        "scalesProperties.backgroundColor": "#FFFEF5",
        "scalesProperties.lineColor": "#e8e0c8",
        "mainSeriesProperties.candleStyle.upColor": "#ee0a24",
        "mainSeriesProperties.candleStyle.downColor": "#07c160",
        "mainSeriesProperties.candleStyle.borderUpColor": "#ee0a24",
        "mainSeriesProperties.candleStyle.borderDownColor": "#07c160",
        "mainSeriesProperties.candleStyle.wickUpColor": "#ee0a24",
        "mainSeriesProperties.candleStyle.wickDownColor": "#07c160",
      },
    });

    this.setupEventListeners();
    return this;
  }

  // 获取自定义指标
  getCustomIndicators(PineJS) {
    return Promise.resolve([
      TvIdxAMA.idx(PineJS),
      TvIdxATR.idx(PineJS),
      TvIdxCDBB.idx(PineJS),
      TvIdxCMCM.idx(PineJS),
      TvIdxDemo.idx(PineJS),
      TvIdxFCX.idx(PineJS),
      TvIdxHDLY.idx(PineJS),
      TvIdxHeima.idx(PineJS),
      TvIdxHLBLW.idx(PineJS),
      TvIdxHLFTX.idx(PineJS),
      TvIdxKDJ.idx(PineJS),
      TvIdxLTQS.idx(PineJS),
      TvIdxMA.idx(PineJS),
      TvIdxMACDBL.idx(PineJS),
      TvIdxVegasMA.idx(PineJS),
      TvIdxVOL.idx(PineJS),
      TvIdxRSX.idx(PineJS),
    ]);
  }

  // 设置事件监听
  setupEventListeners() {
    // 创建几个 button 按钮
    const global_widget = this.widget;
    const manager = this;
    this.widget.headerReady().then(function () {
      // 重新加载数据的按钮
      var buttonReload = global_widget.createButton();
      buttonReload.textContent = "重新加载数据";
      buttonReload.addEventListener("click", function () {
        global_widget.resetCache();
        global_widget.activeChart().resetData();
      });
      // 增加隐藏标记的按钮
      var buttonDeleteMark = global_widget.createButton();
      buttonDeleteMark.textContent = "隐藏标记";
      buttonDeleteMark.addEventListener("click", function () {
        global_widget.activeChart().clearMarks();
      });
      // 增加删除标记的按钮
      var buttonDeleteMark = global_widget.createButton();
      buttonDeleteMark.textContent = "删除标记";
      buttonDeleteMark.addEventListener("click", function () {
        let symbol = global_widget.symbolInterval();
        console.log(symbol);
        $.post({
          type: "POST",
          url: "/tv/del_marks",
          dataType: "json",
          data: {
            symbol: symbol.symbol,
          },
          success: function (res) {
            if (res.status == "ok") {
              global_widget.activeChart().clearMarks();
              layer.msg("删除标记成功");
            } else {
              layer.msg("删除标记失败");
            }
          },
        });
      });
      var buttonAiPredict = global_widget.createButton();
      buttonAiPredict.textContent = "AI预测";
      buttonAiPredict.addEventListener("click", function () {
        if (window.AIPrediction) {
          window.AIPrediction.predict(manager);
        }
      });
      var buttonLoadAiPredict = global_widget.createButton();
      buttonLoadAiPredict.textContent = "显示AI预测";
      buttonLoadAiPredict.addEventListener("click", function () {
        if (window.AIPrediction) {
          window.AIPrediction.loadLatest(manager);
        }
      });
      var buttonClearAiPredict = global_widget.createButton();
      buttonClearAiPredict.textContent = "清除AI预测";
      buttonClearAiPredict.addEventListener("click", function () {
        if (window.AIPrediction) {
          window.AIPrediction.clear(manager);
        }
      });
      var buttonDeleteAiPredict = global_widget.createButton();
      buttonDeleteAiPredict.textContent = "删除AI预测";
      buttonDeleteAiPredict.addEventListener("click", function () {
        if (window.AIPrediction) {
          window.AIPrediction.deleteLatest(manager);
        }
      });
    });
    this.widget.onChartReady(() => {
      this.chart = this.widget.activeChart();
      if (!this.chart) {
        console.error("Failed to get active chart");
        return;
      }

      // 订阅事件
      this.chart
        .onSymbolChanged()
        .subscribe(null, (symbol) => this.handleSymbolChange(symbol));
      this.chart
        .onIntervalChanged()
        .subscribe(null, (interval) => this.handleIntervalChange(interval));

      // 数据加载事件
      this.chart
        .onDataLoaded()
        .subscribe(null, () => this.handleDataLoaded(), true);

      // 数据准备事件
      this.chart.dataReady(() => this.handleDataReady());

      // 数据更新事件
      this.widget.subscribe("onTick", () => this.handleTick());

      // 可视区域变化事件
      this.chart
        .onVisibleRangeChanged()
        .subscribe(null, () => this.handleVisibleRangeChange());

      // 强制应用配色覆盖（双保险）
      try {
        this.chart.applyOverrides({
          "paneProperties.background": "#FFFEF5",
          "paneProperties.backgroundType": "solid",
          "paneProperties.vertGridProperties.color": "#f5f0e0",
          "paneProperties.horzGridProperties.color": "#f5f0e0",
          "paneProperties.crossHairProperties.color": "#e8e0c8",
          "scalesProperties.textColor": "#333",
          "scalesProperties.backgroundColor": "#FFFEF5",
          "scalesProperties.lineColor": "#e8e0c8",
          "mainSeriesProperties.candleStyle.upColor": "#ee0a24",
          "mainSeriesProperties.candleStyle.downColor": "#07c160",
          "mainSeriesProperties.candleStyle.borderUpColor": "#ee0a24",
          "mainSeriesProperties.candleStyle.borderDownColor": "#07c160",
          "mainSeriesProperties.candleStyle.wickUpColor": "#ee0a24",
          "mainSeriesProperties.candleStyle.wickDownColor": "#07c160",
        });
      } catch(e) {
        console.warn('applyOverrides failed:', e);
      }
    });
  }

  // 处理标的变化
  handleSymbolChange(symbol) {
    if (!symbol?.ticker) return;

    const [market, code] = symbol.ticker.split(":");
    if (!market || !code) return;

    if (Utils.get_market() !== market) {
      Utils.set_local_data("market", market);
      location.reload();
      return;
    }

    Utils.set_local_data("market", market);
    Utils.set_local_data(`${market}_code`, code);

    console.log(`${this.id} 标的变化：${symbol.ticker}`);

    this.clear_draw_chanlun();

    if (typeof ZiXuan.render_zixuan_opts === "function") {
      ZiXuan.render_zixuan_opts();
    }

    this.debouncedDrawChanlun();
  }

  // 处理周期变化
  handleIntervalChange(interval) {
    if (!interval) return;

    const market = Utils.get_market();
    if (!market) return;

    Utils.set_local_data(`${market}_interval_${this.id}`, interval);
    console.log(`${this.id} 周期变化: ${interval}`);

    if (window.AIPrediction) {
      window.AIPrediction.clear(this);
    }
    this.clear_draw_chanlun();
    this.debouncedDrawChanlun();
  }

  // 处理数据加载
  handleDataLoaded() {
    console.log("数据重新加载");
    this.clear_draw_chanlun();
    this.debouncedDrawChanlun();
  }

  // 处理数据准备
  handleDataReady() {
    console.log("数据准备");
    this.clear_draw_chanlun();
    this.debouncedDrawChanlun();
  }

  // 处理tick事件
  handleTick() {
    console.log("数据更新");
    this.clear_draw_chanlun("last");
    this.debouncedDrawChanlun();
  }

  // 处理可视区域变化
  handleVisibleRangeChange() {
    this.debouncedDrawChanlun();
  }

  // 清除已绘制的图表
  clear_draw_chanlun(clear_type) {
    // 如果  clear_type == 'last' ，则按照 time 从低到高排序，删除 time 值最大的一个对象
    console.log("清除已绘制的图表 : " + clear_type);
    if (clear_type == "last") {
      for (const symbolKey in this.obj_charts) {
        CHART_CONFIG.CHART_TYPES.forEach((chartType) => {
          const chartItems = this.obj_charts[symbolKey][chartType] || [];
          if (chartItems.length == 0) {
            return;
          }
          const maxTime = Math.max(
            ...chartItems.map((item) => item.time)
          );
          for (const _i in chartItems) {
            const item = chartItems[_i];
            if (item.time == maxTime) {
              item.id.then((_id) => this.chart.removeEntity(_id));
              console.log("remove ", symbolKey, chartType, item);
            }
          }
          this.obj_charts[symbolKey][chartType] = chartItems.filter(
            (item) => item.time != maxTime
          );
        });
      }
    } else {
      Object.values(this.obj_charts).forEach((symbolData) => {
        CHART_CONFIG.CHART_TYPES.forEach((chartType) => {
          const chartItems = symbolData[chartType] || [];
          chartItems.forEach((item) => {
            try {
              item.id.then((_id) => this.chart.removeEntity(_id));
              console.log("remove ", chartType, item);
            } catch (e) {
              console.warn("Failed to remove chart entity:", e);
            }
          });
          symbolData[chartType] = [];
        });
      });
    }
  }

  // 获取图表数据
  getChartData() {
    const symbolInterval = this.widget.symbolInterval();
    if (!symbolInterval) return null;

    const symbolResKey = `${symbolInterval.symbol
      .toString()
      .toLowerCase()}${symbolInterval.interval.toString().toLowerCase()}`;
    const barsResult =
      this.udf_datafeed?._historyProvider?.bars_result?.get(symbolResKey);
    if (!barsResult) return null;

    const visibleRange = this.chart.getVisibleRange();
    const from = visibleRange?.from || 0;
    const symbolKey = `${symbolInterval.symbol}_${symbolInterval.interval}`;

    return { symbolKey, barsResult, from };
  }

  // 初始化图表容器
  initChartContainer(symbolKey) {
    if (!this.obj_charts[symbolKey]) {
      this.obj_charts[symbolKey] = {};
      CHART_CONFIG.CHART_TYPES.forEach((type) => {
        this.obj_charts[symbolKey][type] = [];
      });
    }
    return this.obj_charts[symbolKey];
  }

  // 绘制图表元素
  drawChartElements(chartData) {
    const { symbolKey, barsResult, from } = chartData;
    const chartContainer = this.initChartContainer(symbolKey);

    // console.log("bars result", barsResult);
    // console.log("chart container ", chartContainer);

    this.clear_draw_chanlun("last");

    // 分型球顶已关闭（如需开启取消注释）
    // if (barsResult.fxs) {
    //   barsResult.fxs.forEach((fx) => {
    //     if (fx.points?.[0]?.time >= from) {
    //       const key = JSON.stringify(fx);
    //       const existed = chartContainer.fxs.find((item) => item.key === key);
    //       if (existed) return;
    //       chartContainer.fxs.push({
    //         time: fx.points[0].time,
    //         key,
    //         id: ChartUtils.createFxShape(this.chart, fx),
    //       });
    //     }
    //   });
    // }

    // 绘制笔
    if (barsResult.bis) {
      // 收集所有中枢的进入笔/离开笔索引
      const entryIdx = new Set();
      const exitIdx = new Set();
      if (barsResult.bi_zss) {
        barsResult.bi_zss.forEach(zs => {
          if (zs.entry_bi_idx != null) entryIdx.add(zs.entry_bi_idx);
          if (zs.exit_bi_idx != null) exitIdx.add(zs.exit_bi_idx);
        });
      }
      barsResult.bis.forEach((bi) => {
        if (bi.points?.[0]?.time >= from) {
          const key = JSON.stringify(bi);
          const existed = chartContainer.bis.find((item) => item.key === key);
          if (existed) return;
          const isEntry = entryIdx.has(bi.index);
          const isExit = exitIdx.has(bi.index);
          let biColor = CHART_CONFIG.COLORS.BI;
          let biWidth = 1;
          if (isEntry) { biColor = '#6A1B9A'; biWidth = 3; }  // 进入笔：深紫色
          if (isExit)  { biColor = '#FFC107'; biWidth = 3; }  // 离开笔：黄色
          chartContainer.bis.push({
            time: bi.points[0].time,
            key,
            id: ChartUtils.createLineShape(this.chart, bi, {
              color: biColor,
              linewidth: biWidth,
            }),
          });
          // BI 序号标识（在终点上方）
          if (bi.points?.[1]) {
            ChartUtils.createTextLabel(this.chart,
              { time: bi.points[1].time, price: bi.points[1].price },
              '' + bi.index,
              { overrides: { color: '#E53935', fontSize: 11 } }
            );
          }
        }
      });
    }

    // 绘制线段
    if (barsResult.xds) {
      barsResult.xds.forEach((xd) => {
        if (xd.points?.[0]?.time >= from) {
          const key = JSON.stringify(xd);
          const existed = chartContainer.xds.find((item) => item.key === key);
          if (existed) return;
          chartContainer.xds.push({
            time: xd.points[0].time,
            key,
            id: ChartUtils.createLineShape(this.chart, xd, {
              color: CHART_CONFIG.COLORS.XD,
              linewidth: 2,
            }),
          });
        }
      });
    }

    // 绘制走势段
    if (barsResult.zsds) {
      barsResult.zsds.forEach((zsd) => {
        if (zsd.points?.[0]?.time >= from) {
          const key = JSON.stringify(zsd);
          const existed = chartContainer.zsds.find((item) => item.key === key);
          if (existed) return;
          chartContainer.zsds.push({
            time: zsd.points[0].time,
            key,
            id: ChartUtils.createLineShape(this.chart, zsd, {
              color: CHART_CONFIG.COLORS.ZSD,
              linewidth: 3,
            }),
          });
        }
      });
    }

    // 绘制笔中枢
    if (barsResult.bi_zss && (SHOW_DONE_ZS || SHOW_UNDONE_ZS)) {
      barsResult.bi_zss.forEach((bi_zs, zsIdx) => {
        if (bi_zs.points?.[0]?.time >= from) {
          const key = JSON.stringify(bi_zs);
          const existed = chartContainer.bi_zss.find(
            (item) => item.key === key
          );
          if (existed) return;
          // 重算中枢 ZG/ZD
          const recalcZs = recalcZhongshuFromBis(bi_zs, barsResult.bis, ZS_RECALC_MODE);
          // 进入笔离开笔同向过滤
          if (SHOW_ZS_SAME_DIR && !isSameDirectionEntryExit(recalcZs, barsResult.bis)) return;
          // 中枢进出合理判断
          if (SHOW_ZS_ENTRY_EXIT_CHECK && !isValidZhongshuEntryExit(recalcZs, barsResult.bis)) return;
          chartContainer.bi_zss.push({
            time: recalcZs.points[0].time,
            key,
            id: ChartUtils.createZhongshuShape(this.chart, recalcZs, {
              color: CHART_CONFIG.COLORS.BI_ZSS,
              linewidth: 1,
            }),
          });
          // 在中枢内显示ZS编号
          const midTime = (recalcZs.points[0].time + recalcZs.points[1].time) / 2;
          const labelPrice = recalcZs.points[0].price - (recalcZs.points[0].price - recalcZs.points[1].price) * 0.25;
          ChartUtils.createTextLabel(this.chart,
            { time: midTime, price: labelPrice },
            'ZS' + zsIdx,
            { overrides: { color: '#000000', fontSize: 14 } }
          );
          // 在中枢上方标注"N笔"
          if (recalcZs.line_num >= 5) {
            ChartUtils.createTextLabel(this.chart,
              { time: midTime, price: recalcZs.points[0].price },
              recalcZs.line_num + '笔',
              { overrides: { color: '#666666', fontSize: 9 } }
            );
          }
          // 在中枢下方显示验证结果（正确/不正确）- bi_zs[5] 是验证结果字符串
          if (bi_zs[5]) {
            const validText = bi_zs[5];
            const validColor = validText === "正确" ? '#00AA00' : '#AA0000';
            ChartUtils.createTextLabel(this.chart,
              { time: midTime, price: recalcZs.points[1].price + (recalcZs.points[0].price - recalcZs.points[1].price) * 0.1 },
              validText,
              { overrides: { color: validColor, fontSize: 12, bold: true } }
            );
          }
        }
      });
    }

    // 绘制线段中枢
    if (barsResult.xd_zss && (SHOW_DONE_ZS || SHOW_UNDONE_ZS)) {
      barsResult.xd_zss.forEach((xd_zs) => {
        if (xd_zs.points?.[0]?.time >= from) {
          const key = JSON.stringify(xd_zs);
          const existed = chartContainer.xd_zss.find(
            (item) => item.key === key
          );
          if (existed) return;
          chartContainer.xd_zss.push({
            time: xd_zs.points[0].time,
            key,
            id: ChartUtils.createZhongshuShape(this.chart, xd_zs, {
              color: CHART_CONFIG.COLORS.XD_ZSS,
              linewidth: 2,
            }),
          });
        }
      });
    }

    // 绘制走势段中枢
    if (barsResult.zsd_zss && (SHOW_DONE_ZS || SHOW_UNDONE_ZS)) {
      barsResult.zsd_zss.forEach((zsd_zs) => {
        if (zsd_zs.points?.[0]?.time >= from) {
          const key = JSON.stringify(zsd_zs);
          const existed = chartContainer.zsd_zss.find(
            (item) => item.key === key
          );
          if (existed) return;
          chartContainer.zsd_zss.push({
            time: zsd_zs.points[0].time,
            key,
            id: ChartUtils.createZhongshuShape(this.chart, zsd_zs, {
              color: CHART_CONFIG.COLORS.ZSD_ZSS,
              linewidth: 2,
            }),
          });
        }
      });
    }

    // 绘制背驰
    if (barsResult.bcs) {
      barsResult.bcs.forEach((bc) => {
        if (bc.points?.time >= from) {
          const key = JSON.stringify(bc);
          const existed = chartContainer.bcs.find((item) => item.key === key);
          if (existed) return;
          chartContainer.bcs.push({
            time: bc.points.time,
            key,
            id: ChartUtils.createBcShape(this.chart, bc),
          });
        }
      });
    }

    // 绘制买卖点
    if (barsResult.mmds) {
      barsResult.mmds.forEach((mmd) => {
        if (mmd.points?.time >= from) {
          const key = JSON.stringify(mmd);
          const existed = chartContainer.mmds.find((item) => item.key === key);
          if (existed) return;
          chartContainer.mmds.push({
            time: mmd.points.time,
            key,
            id: ChartUtils.createMmdShape(this.chart, mmd),
          });
        }
      });
    }

    // 绘制走势类型标识（中文）
    if (barsResult.trends) {
      barsResult.trends.forEach((trend) => {
        if (trend.points?.time >= from) {
          // 趋势标识重新定位到对应中枢的右上角
          let pos = trend.points;
          if ((trend.direction === 'up' || trend.trend_type?.includes('上涨')) && barsResult.bi_zss?.length) {
            const lastZs = [...barsResult.bi_zss]
              .filter(zs => zs.points?.[1]?.time <= trend.points.time)
              .sort((a, b) => b.points[1].time - a.points[1].time)[0];
            if (lastZs) {
              const recalcZs = recalcZhongshuFromBis(lastZs, barsResult.bis, ZS_RECALC_MODE);
              pos = { time: recalcZs.points[1].time, price: recalcZs.points[1].price };
            }
          }
          const trendWithPos = { ...trend, points: pos };
          const key = JSON.stringify(trendWithPos);
          const existed = chartContainer.trends.find((item) => item.key === key);
          if (existed) return;
          chartContainer.trends.push({
            time: pos.time,
            key,
            id: ChartUtils.createTrendLabel(this.chart, trendWithPos),
          });
        }
      });
    }
  }

  // 绘制缠论图表
  draw_chanlun() {
    const code_start = performance.now();

    const chartData = this.getChartData();
    if (!chartData) return;

    console.log("Drawing chart for:", chartData.symbolKey);

    // 绘制所有图表元素
    this.drawChartElements(chartData);

    const code_end = performance.now();
    console.log(
      `${chartData.symbolKey} 运行时间: ${code_end - code_start} 毫秒`
    );
  }
}

var Charts = (function () {
  const managers = {};

  return {
    // 图表展示
    show_tv_chart: function (id) {
      const chartManager = new ChartManager(id).init();
      managers[id] = chartManager;
      return chartManager.widget;
    },
    get_manager: function (id) {
      return managers[id];
    },
  };
})();
