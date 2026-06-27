#!/usr/bin/env python3
"""并发增量补5m数据 - ThreadPoolExecutor"""
import sys, os, time, sqlite3, re
from concurrent.futures import ThreadPoolExecutor, as_completed

sys.path.insert(0, os.path.expanduser("~/.openclaw/workspace/a-stock-analyst/chanlun-pro/src"))
os.environ['CHANLUN_PRO_PATH'] = os.path.expanduser("~/.chanlun_pro")

DB = os.path.expanduser("~/.chanlun_pro/db/chanlun_klines.sqlite")
_TODAY = "2026-06-02"
_N_WORKERS = 4

def get_stale():
    c = sqlite3.connect(DB, timeout=30)
    stale = [r[0] for r in c.execute(
        "SELECT DISTINCT symbol FROM kline_cache WHERE period='5m' "
        "GROUP BY symbol HAVING MAX(trade_date) < ?", (_TODAY,)
    ).fetchall()]
    c.close()
    return stale

def tdx_klines_direct(code_sz_sh, symbol):
    """直接从TDX获取最新页5m数据，使用原始socket协议"""
    import socket, struct, time as _time
    # TDX市场代码: 0=深圳, 1=上海
    market = 1 if code_sz_sh.startswith('SH.') else 0
    raw_code = code_sz_sh.replace('SH.', '').replace('SZ.', '')
    
    # 连接TDX
    sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    sock.settimeout(8)
    try:
        sock.connect(('119.147.212.81', 7709))
    except:
        return (symbol, [])
    
    try:
        # 证券代码转6位 + 市场
        code_bytes = raw_code.zfill(6).encode()
        market_byte = struct.pack('B', market)
        
        # TDX 5分钟K线请求 (category 7 = 5分钟)
        # 发送 0x01c8 请求获取K线数据
        pkg = bytearray()
        pkg.extend(struct.pack('<H', 0x01c8))  # 功能号
        pkg.extend(b'\x00' * 2)  # 保留
        pkg.extend(code_bytes)  # 6位代码
        pkg.extend(market_byte)  # 市场
        pkg.extend(struct.pack('<H', 7))  # category: 5分钟
        pkg.extend(struct.pack('<H', 0))  # start
        pkg.extend(struct.pack('<H', 800))  # count
        
        # 发送请求
        sock.sendall(pkg)
        
        # 接收数据
        data = b''
        while len(data) < 4:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        
        if len(data) < 4:
            return (symbol, [])
        
        data_len = struct.unpack('<H', data[2:4])[0]
        while len(data) < data_len + 4:
            chunk = sock.recv(4096)
            if not chunk:
                break
            data += chunk
        
        # 解析K线数据 (每32字节一条)
        body = data[4:]
        rows = []
        for i in range(0, len(body) - 32, 32):
            rec = body[i:i+32]
            year = struct.unpack('<H', rec[0:2])[0]
            month = rec[2]
            day = rec[3]
            hour = rec[4]
            minute = rec[5]
            open_p = struct.unpack('<I', rec[8:12])[0] / 1000.0
            high = struct.unpack('<I', rec[12:16])[0] / 1000.0
            low = struct.unpack('<I', rec[16:20])[0] / 1000.0
            close = struct.unpack('<I', rec[20:24])[0] / 1000.0
            vol = struct.unpack('<I', rec[28:32])[0]
            
            dt = f"{year:04d}-{month:02d}-{day:02d} {hour:02d}:{minute:02d}:00"
            if dt >= '2026-05-28':
                rows.append((symbol, 'tdx', '5m', dt, open_p, close, high, low, float(vol), 0.0))
        
        return (symbol, rows)
    except:
        return (symbol, [])
    finally:
        try:
            sock.close()
        except:
            pass

def main():
    t0 = time.time()
    stale = get_stale()
    print(f"需更新: {len(stale)}只", flush=True)
    
    # 先做前缀转换
    tasks = []
    for s in stale:
        full = f"SH.{s}" if s.startswith(('6','688','900','7')) else f"SZ.{s}"
        tasks.append((full, s))
    
    total_rows = 0
    done = 0
    batch_rows = []
    
    with ThreadPoolExecutor(max_workers=_N_WORKERS) as pool:
        futures = {pool.submit(tdx_klines_direct, f, s): s for f, s in tasks}
        
        for fut in as_completed(futures):
            symbol, rows = fut.result()
            done += 1
            if rows:
                batch_rows.extend(rows)
                total_rows += len(rows)
            
            if len(batch_rows) >= 5000 or done % 200 == 0:
                if batch_rows:
                    c = sqlite3.connect(DB, timeout=60)
                    try:
                        c.executemany(
                            "INSERT OR IGNORE INTO kline_cache (symbol,source,period,trade_date,open,close,high,low,volume,amount) VALUES (?,?,?,?,?,?,?,?,?,?)",
                            batch_rows
                        )
                        c.commit()
                    finally:
                        c.close()
                    batch_rows = []
                
                el = time.time() - t0
                rate = done / el if el > 0 else 0
                eta = (len(stale) - done) / rate if rate > 0 else 0
                print(f"  [{done}/{len(stale)}] +{total_rows}行 {el:.0f}s ETA:{eta:.0f}s", flush=True)
    
    # 最后一批
    if batch_rows:
        c = sqlite3.connect(DB, timeout=60)
        try:
            c.executemany(...)
            c.commit()
        finally:
            c.close()
    
    el = time.time() - t0
    print(f"完成! {done}/{len(stale)}只, +{total_rows}行, {el:.0f}s", flush=True)

if __name__ == '__main__':
    main()
