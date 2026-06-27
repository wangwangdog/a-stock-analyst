"""
ChanlunX 算法 Python 实现
原版: https://github.com/kldcty/ChanlunX (C++ 通达信插件)

算法流程:
  原始K线 → K线包含处理(KxianChuLi) → 笔识别(BiChuLi) → 线段(Duan) → 中枢(ZS)
"""
from typing import List, Tuple, Optional


# ── 数据结构 ──

class Kxian:
    """合并后的K线"""
    __slots__ = ('gao', 'di', 'fangXiang', 'kaiShi', 'jieShu', 'zhongJian')
    def __init__(self, gao: float, di: float, fangXiang: int, kaiShi: int, jieShu: int, zhongJian: int):
        self.gao = gao
        self.di = di
        self.fangXiang = fangXiang  # 1=up, -1=down
        self.kaiShi = kaiShi
        self.jieShu = jieShu
        self.zhongJian = zhongJian


class Bi:
    """笔"""
    __slots__ = ('fangXiang', 'kaiShi', 'jieShu', 'gao', 'di', 'kxian_list')
    def __init__(self, fangXiang: int, kaiShi: int, jieShu: int, gao: float, di: float):
        self.fangXiang = fangXiang
        self.kaiShi = kaiShi
        self.jieShu = jieShu
        self.gao = gao
        self.di = di
        self.kxian_list: List[Kxian] = []


# ── 1. K线包含处理 ──

def kxian_chuli(highs: List[float], lows: List[float]) -> List[Kxian]:
    """
    K线包含处理。
    输入: high/low 序列 (原始K线)
    输出: 合并后的K线列表
    """
    kxian_list: List[Kxian] = []
    for i in range(len(highs)):
        gao, di = highs[i], lows[i]
        if not kxian_list:
            # 第一根K线假设方向向上
            kxian_list.append(Kxian(gao, di, 1, 0, 0, 0))
        else:
            last = kxian_list[-1]
            if gao > last.gao and di > last.di:
                # 向上
                ks = last.jieShu + 1
                kxian_list.append(Kxian(gao, di, 1, ks, ks, ks))
            elif gao < last.gao and di < last.di:
                # 向下
                ks = last.jieShu + 1
                kxian_list.append(Kxian(gao, di, -1, ks, ks, ks))
            elif gao <= last.gao and di >= last.di:
                # 前包含 (新K线被前K线包含)
                if last.fangXiang == 1:
                    last.di = di  # 向上取高高中的低
                else:
                    last.gao = gao  # 向下取低低中的高
                last.jieShu += 1
            else:
                # 后包含 (前K线被新K线包含)
                if last.fangXiang == 1:
                    last.gao = gao
                else:
                    last.di = di
                last.jieShu += 1
                last.zhongJian = last.jieShu
    return kxian_list


# ── 2. 笔识别 ──

def _if_chengbi(temp_kxian: List[Kxian], direction: int) -> bool:
    """检查临时K线列表是否能成笔"""
    if len(temp_kxian) < 4:
        return False
    if direction == -1:
        # 向下成笔: 找连续3根下降K线，然后出现更低点
        i = 2
        while i < len(temp_kxian):
            found = False
            for j in range(i, len(temp_kxian)):
                if (temp_kxian[j].di < temp_kxian[j-1].di and
                    temp_kxian[j-1].di < temp_kxian[j-2].di):
                    i = j
                    found = True
                    break
            if not found:
                return False
            zui_di = temp_kxian[i].di
            for j in range(i + 1, len(temp_kxian)):
                if temp_kxian[j].di < zui_di:
                    return True
            i += 1
        return False
    else:
        # 向上成笔: 找连续3根上升K线，然后出现更高点
        i = 2
        while i < len(temp_kxian):
            found = False
            for j in range(i, len(temp_kxian)):
                if (temp_kxian[j].gao > temp_kxian[j-1].gao and
                    temp_kxian[j-1].gao > temp_kxian[j-2].gao):
                    i = j
                    found = True
                    break
            if not found:
                return False
            zui_gao = temp_kxian[i].gao
            for j in range(i + 1, len(temp_kxian)):
                if temp_kxian[j].gao > zui_gao:
                    return True
            i += 1
        return False


def bi_chuli(kxian_list: List[Kxian]) -> List[Bi]:
    """
    笔识别。
    输入: 合并后的K线列表
    输出: 笔列表
    """
    bi_list: List[Bi] = []
    temp_kxian: List[Kxian] = []

    for kx in kxian_list:
        if not bi_list:
            # 第一笔假设向上
            bi_list.append(Bi(1, kx.kaiShi, kx.jieShu, kx.gao, kx.di))
            bi_list[-1].kxian_list.append(kx)
        else:
            last_bi = bi_list[-1]
            if last_bi.fangXiang == 1:
                # 上一笔是向上
                if kx.gao >= last_bi.gao:
                    # 延续
                    last_bi.jieShu = kx.jieShu
                    last_bi.gao = kx.gao
                    last_bi.kxian_list.extend(temp_kxian)
                    temp_kxian.clear()
                    last_bi.kxian_list.append(kx)
                else:
                    temp_kxian.append(kx)
                    if _if_chengbi(temp_kxian, -1):
                        bi_list.append(Bi(-1, last_bi.jieShu, temp_kxian[-1].jieShu,
                                          last_bi.gao, temp_kxian[-1].di))
                        bi_list[-1].kxian_list = list(temp_kxian)
                        temp_kxian.clear()
            else:
                # 上一笔是向下
                if kx.di <= last_bi.di:
                    # 延续
                    last_bi.jieShu = kx.jieShu
                    last_bi.di = kx.di
                    last_bi.kxian_list.extend(temp_kxian)
                    temp_kxian.clear()
                    last_bi.kxian_list.append(kx)
                else:
                    temp_kxian.append(kx)
                    if _if_chengbi(temp_kxian, 1):
                        bi_list.append(Bi(1, last_bi.jieShu, temp_kxian[-1].jieShu,
                                          temp_kxian[-1].gao, last_bi.di))
                        bi_list[-1].kxian_list = list(temp_kxian)
                        temp_kxian.clear()

    # 末尾未成笔的处理
    if len(temp_kxian) >= 4 and bi_list:
        last_bi = bi_list[-1]
        if last_bi.fangXiang == 1 and _if_chengbi(temp_kxian, -1):
            bi_list.append(Bi(-1, last_bi.jieShu, temp_kxian[-1].jieShu,
                              last_bi.gao, temp_kxian[-1].di))
            bi_list[-1].kxian_list = list(temp_kxian)
        elif last_bi.fangXiang == -1 and _if_chengbi(temp_kxian, 1):
            bi_list.append(Bi(1, last_bi.jieShu, temp_kxian[-1].jieShu,
                              temp_kxian[-1].gao, last_bi.di))
            bi_list[-1].kxian_list = list(temp_kxian)

    return bi_list


# ── 3. 线段 (Duan1 标准画法) ──

def duan1(nCount: int, bi_signal: List[float],
          highs: List[float], lows: List[float]) -> List[float]:
    """
    线段标准画法。
    输入: 笔信号(1=顶, -1=底, 0=无), raw highs/lows
    输出: 线段信号(1=线段顶, -1=线段底, 0=无)
    """
    pOut = [0.0] * nCount
    nState = 0
    nLastD = 0
    nLastG = 0
    fTop0 = fTop1 = fTop2 = 0.0
    fBot0 = fBot1 = fBot2 = 0.0

    for i in range(nCount):
        if bi_signal[i] == 1:
            fTop1, fTop2 = fTop2, highs[i]
        elif bi_signal[i] == -1:
            fBot1, fBot2 = fBot2, lows[i]

        if nState == 0:
            if bi_signal[i] == 1:
                nState = 1
                nLastG = i
                pOut[nLastG] = 1
                fTop0 = fBot0 = 0.0
            elif bi_signal[i] == -1:
                nState = -1
                nLastD = i
                pOut[nLastD] = -1
                fTop0 = fBot0 = 0.0
        elif nState == 1:
            if bi_signal[i] == 1:
                if highs[i] > highs[nLastG]:
                    pOut[nLastG] = 0
                    nLastG = i
                    pOut[nLastG] = 1
                    fTop0 = fBot0 = 0.0
            elif bi_signal[i] == -1:
                if lows[i] < lows[nLastD]:
                    nState = -1
                    nLastD = i
                    pOut[nLastD] = -1
                    fTop0 = fBot0 = 0.0
                elif (fTop1 > 0 and fTop2 > 0 and fBot1 > 0 and fBot2 > 0 and
                      fTop2 < fTop1 and fBot2 < fBot1):
                    nState = -1
                    nLastD = i
                    pOut[nLastD] = -1
                    fTop0 = fBot0 = 0.0
                else:
                    if fBot0 == 0:
                        fBot0 = lows[i]
                    elif lows[i] < fBot0:
                        nState = -1
                        nLastD = i
                        pOut[nLastD] = -1
                        fTop0 = fBot0 = 0.0
        elif nState == -1:
            if bi_signal[i] == -1:
                if lows[i] < lows[nLastD]:
                    pOut[nLastD] = 0
                    nLastD = i
                    pOut[nLastD] = -1
                    fTop0 = fBot0 = 0.0
            elif bi_signal[i] == 1:
                if highs[i] > highs[nLastG]:
                    nState = 1
                    nLastG = i
                    pOut[nLastG] = 1
                    fTop0 = fBot0 = 0.0
                elif (fTop1 > 0 and fTop2 > 0 and fBot1 > 0 and fBot2 > 0 and
                      fTop2 > fTop1 and fBot2 > fBot1):
                    nState = 1
                    nLastG = i
                    pOut[nLastG] = 1
                    fTop0 = fBot0 = 0.0
                else:
                    if fTop0 == 0:
                        fTop0 = highs[i]
                    elif highs[i] > fTop0:
                        nState = 1
                        nLastG = i
                        pOut[nLastG] = 1
                        fTop0 = fBot0 = 0.0
    return pOut


# ── 4. 中枢 ──

class ZhongShu:
    """中枢状态机"""
    def __init__(self):
        self.bValid = False
        self.nTop1 = self.nTop2 = self.nTop3 = 0
        self.nBot1 = self.nBot2 = self.nBot3 = 0
        self.fTop1 = self.fTop2 = self.fTop3 = 0.0
        self.fBot1 = self.fBot2 = self.fBot3 = 0.0
        self.nLines = 0
        self.nStart = self.nEnd = 0
        self.fHigh = self.fLow = 0.0
        self.nDirection = 0
        self.nTerminate = 0

    def Reset(self):
        self.__init__()

    def PushHigh(self, nIndex: int, fValue: float) -> bool:
        self.nTop3, self.fTop3 = self.nTop2, self.fTop2
        self.nTop2, self.fTop2 = self.nTop1, self.fTop1
        self.nTop1, self.fTop1 = nIndex, fValue
        if self.bValid:
            if fValue < self.fLow:
                self.nTerminate = -1
                if self.nTop2 > self.nEnd:
                    self.nEnd = self.nTop2
                return True
            else:
                if self.nBot1 > self.nEnd:
                    self.nEnd = self.nBot1
        else:
            if (self.nTop3 > 0 and self.nTop2 > 0 and self.nTop1 > 0 and
                self.nBot2 > 0 and self.nBot1 > 0):
                fTempHigh = min(self.fTop1, self.fTop2)
                fTempLow = max(self.fBot1, self.fBot2)
                if self.fTop3 > self.fTop2 and fTempHigh > fTempLow:
                    self.nDirection = -1
                    self.nStart = self.nBot2
                    self.nEnd = self.nTop1
                    self.fHigh = fTempHigh
                    self.fLow = fTempLow
                    self.bValid = True
        return False

    def PushLow(self, nIndex: int, fValue: float) -> bool:
        self.nBot3, self.fBot3 = self.nBot2, self.fBot2
        self.nBot2, self.fBot2 = self.nBot1, self.fBot1
        self.nBot1, self.fBot1 = nIndex, fValue
        if self.bValid:
            if fValue > self.fHigh:
                self.nTerminate = 1
                if self.nBot2 > self.nEnd:
                    self.nEnd = self.nBot2
                return True
            else:
                if self.nTop1 > self.nEnd:
                    self.nEnd = self.nTop1
        else:
            if (self.nTop2 > 0 and self.nTop1 > 0 and
                self.nBot3 > 0 and self.nBot2 > 0 and self.nBot1 > 0):
                fTempHigh = min(self.fTop1, self.fTop2)
                fTempLow = max(self.fBot1, self.fBot2)
                if self.fBot3 < self.fBot2 and fTempHigh > fTempLow:
                    self.nDirection = 1
                    self.nStart = self.nTop2
                    self.nEnd = self.nBot1
                    self.fHigh = fTempHigh
                    self.fLow = fTempLow
                    self.bValid = True
        return False


# ── 5. 主函数 ──

def chanlunx_analyze(highs: List[float], lows: List[float]) -> Tuple[List[Bi], List[float], List[dict]]:
    """
    完整的 ChanlunX 缠论分析。
    
    返回:
        bi_list: 笔列表
        segment_signal: 线段信号 (1=顶, -1=底, 0=无)
        zhongshu_list: 中枢列表 [{"zg":..., "zd":..., "gg":..., "dd":...}]
    """
    n = len(highs)
    if n == 0:
        return [], [], []

    # 1. K线包含处理
    kxians = kxian_chuli(highs, lows)
    if not kxians:
        return [], [], []

    # 2. 笔识别
    bis = bi_chuli(kxians)
    if not bis:
        return [], [], []

    # 3. 生成笔信号 (用于线段和中枢)
    bi_signal = [0.0] * n
    for b in bis:
        if b.fangXiang == 1:
            bi_signal[b.jieShu] = 1.0
        else:
            bi_signal[b.jieShu] = -1.0

    # 4. 线段
    seg_signal = duan1(n, bi_signal, highs, lows)

    # 5. 中枢
    zhongshu_list = _calc_zhongshu(n, seg_signal, highs, lows)

    return bis, seg_signal, zhongshu_list


def _calc_zhongshu(nCount: int, pIn: List[float],
                   pHigh: List[float], pLow: List[float]) -> List[dict]:
    """计算中枢"""
    result = []
    zs = ZhongShu()
    i = 0
    while i < nCount:
        if pIn[i] == 1:
            if zs.PushHigh(i, pHigh[i]):
                pivot = _make_pivot(zs, pHigh, pLow)
                if pivot:
                    result.append(pivot)
                i = max(zs.nEnd - 1, i)
                zs.Reset()
        elif pIn[i] == -1:
            if zs.PushLow(i, pLow[i]):
                pivot = _make_pivot(zs, pHigh, pLow)
                if pivot:
                    result.append(pivot)
                i = max(zs.nEnd - 1, i)
                zs.Reset()
        i += 1

    if zs.bValid:
        pivot = _make_pivot(zs, pHigh, pLow)
        if pivot:
            result.append(pivot)

    return result


def _make_pivot(zs: ZhongShu, pHigh: List[float], pLow: List[float]) -> Optional[dict]:
    """从ZhongShu状态创建中枢字典"""
    bValid = True
    if zs.nDirection == 1 and zs.nTerminate == -1:
        bValid = False
        fHighValue = 0.0
        nHighCount = 0
        nHignIndex = 0
        nLowIndex = 0
        nLowIndexTemp = 0
        for x in range(zs.nStart, zs.nEnd + 1):
            if pIn[x] == 1:
                if nHighCount == 0:
                    nHighCount += 1
                    fHighValue = pHigh[x]
                    nHignIndex = x
                else:
                    nHighCount += 1
                    if pHigh[x] >= fHighValue:
                        if nHighCount > 2:
                            bValid = True
                        fHighValue = pHigh[x]
                        nHignIndex = x
                        nLowIndex = nLowIndexTemp
            elif pIn[x] == -1:
                nLowIndexTemp = x
        if bValid:
            zs.nEnd = nLowIndex
    elif zs.nDirection == -1 and zs.nTerminate == 1:
        bValid = False
        fLowValue = 0.0
        nLowCount = 0
        nLowIndex = 0
        nHighIndex = 0
        nHighIndexTemp = 0
        for x in range(zs.nStart, zs.nEnd + 1):
            if pIn[x] == -1:
                if nLowCount == 0:
                    nLowCount += 1
                    fLowValue = pLow[x]
                    nLowIndex = x
                else:
                    nLowCount += 1
                    if pLow[x] <= fLowValue:
                        if nLowCount > 2:
                            bValid = True
                        fLowValue = pLow[x]
                        nLowIndex = x
                        nHighIndex = nHighIndexTemp
            elif pIn[x] == 1:
                nHighIndexTemp = x
        if bValid:
            zs.nEnd = nHighIndex

    if not bValid:
        return None

    start = max(0, zs.nStart)
    end = min(len(pHigh), zs.nEnd)
    gg = max(pHigh[start+1:end]) if end > start + 1 else zs.fHigh
    dd = min(pLow[start+1:end]) if end > start + 1 else zs.fLow

    return {
        "zg": round(zs.fHigh, 2),
        "zd": round(zs.fLow, 2),
        "gg": round(gg, 2),
        "dd": round(dd, 2),
    }
