#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import asyncio
import re
import os
import zipfile
import xlrd
import csv
import argparse
import logging
import aiohttp
from aiohttp_socks import ProxyConnector
from tqdm import tqdm

logging.basicConfig(level=logging.WARNING, format='%(asctime)s [%(levelname)s] %(message)s')
logger = logging.getLogger(__name__)

try:
    from config import BASE_URL, HEADERS, PROXY, USE_PROXY
except ImportError:
    BASE_URL = 'http://rpsjw.cdut.edu.cn/qzbb'
    HEADERS = {'User-Agent': 'curl/7.29.0'}
    PROXY = 'socks5://127.0.0.1:10801'
    USE_PROXY = True  # 通过服务器代理访问

DEFAULT_WORKERS = 150
TIMEOUT = aiohttp.ClientTimeout(sock_connect=10, sock_read=30)
RETRIES = 6
RETRY_STATUSES = {429, 502, 503, 504}

# 预编译正则表达式
RE_CACHED = re.compile(r'report1_cachedId\s*=\s*"([^"]+)"')
RE_PARAMS = re.compile(r'name=reportParamsId\s*value=([^>\s]+)')
RE_TIME = re.compile(r't_i_m_e=(\d+)')

async def download_and_convert(session, student_id, csv_dir, semaphore):
    csv_path = os.path.join(csv_dir, f"{student_id}.csv")
    temp_path = f"{csv_path}.tmp"

    # 如果文件已存在，跳过
    if os.path.exists(csv_path):
        return "skipped"

    async with semaphore:
        try:
            for attempt in range(RETRIES):
                try:
                    # 第一步：获取报表参数
                    async with session.post(
                        f"{BASE_URL}/reportJsp/showReport.jsp?rpx=/148656-XSCJDXSD.rpx",
                        data={'selShowType': 'all', 'kclx': '0', 'xsxh': student_id},
                    ) as r:
                        if r.status in RETRY_STATUSES and attempt < RETRIES - 1:
                            await asyncio.sleep(0.3 * (2 ** attempt))
                            continue
                        r.raise_for_status()
                        text = await r.text()

                    # 使用预编译的正则表达式
                    matches = [RE_CACHED.search(text), RE_PARAMS.search(text), RE_TIME.search(text)]
                    if not all(matches):
                        return False

                    # 第二步：下载Excel
                    async with session.get(f'{BASE_URL}/reportServlet', params={
                        'action': '3', 'file': '/148656-XSCJDXSD.rpx', 'columns': '0', 'srcType': 'file',
                        'cachedId': matches[0].group(1), 'reportParamsId': matches[1].group(1),
                        't_i_m_e': matches[2].group(1), 'excelFormat': '2003', 'width': '0', 'height': '0',
                        'pageStyle': '0', 'formula': '0', 'tips': 'yes'
                    }) as x:
                        if x.status in RETRY_STATUSES and attempt < RETRIES - 1:
                            await asyncio.sleep(0.3 * (2 ** attempt))
                            continue
                        x.raise_for_status()
                        content = await x.read()

                    # 转换为CSV，直接写入临时文件以减少内存占用
                    workbook = xlrd.open_workbook(file_contents=content)
                    sheet = workbook.sheet_by_index(0)
                    with open(temp_path, 'w', encoding='utf-8-sig', newline='') as f:
                        writer = csv.writer(f)
                        for row_idx in range(sheet.nrows):
                            writer.writerow(sheet.row_values(row_idx))

                    os.replace(temp_path, csv_path)
                    return True

                except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                    if attempt < RETRIES - 1:
                        await asyncio.sleep(0.3 * (2 ** attempt))
                        continue
                    logger.warning("下载失败 [%s]: %s", student_id, e)
                    return False

            return False
        except Exception as e:
            logger.warning("下载失败 [%s]: %s", student_id, e)
            return False
        finally:
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass

async def batch_download(ids, csv_dir, use_proxy, workers, desc="进度", total=None, initial=0):
    """异步并发下载一批学号，返回 (成功数, 失败数)。"""
    if use_proxy:
        connector = ProxyConnector.from_url(PROXY, limit=workers, limit_per_host=workers)
    else:
        connector = aiohttp.TCPConnector(limit=workers, limit_per_host=workers)

    semaphore = asyncio.Semaphore(workers)
    success = 0
    failed = 0

    async with aiohttp.ClientSession(connector=connector, headers=HEADERS, timeout=TIMEOUT) as session:
        tasks = {asyncio.ensure_future(download_and_convert(session, sid, csv_dir, semaphore)): sid for sid in ids}

        with tqdm(total=total or len(ids), initial=initial, desc=desc, unit="个") as pbar:
            for coro in asyncio.as_completed(tasks.keys()):
                result = await coro
                if result is True:
                    success += 1
                elif result is False:
                    failed += 1
                pbar.set_postfix(成功=success, 失败=failed)
                pbar.update(1)

    return success, failed

async def async_main(args):
    csv_dir = 'results_csv'
    zip_name = args.zip
    use_proxy = args.proxy or USE_PROXY

    if not os.path.exists(args.ids):
        print(f"❌ 未找到文件: {args.ids}")
        return

    with open(args.ids, 'r') as f:
        student_ids = [line.strip() for line in f if line.strip()]

    os.makedirs(csv_dir, exist_ok=True)

    # 构建待处理列表
    finished = {f[:-4] for f in os.listdir(csv_dir) if f.endswith('.csv') and not f.startswith('.')}
    pending = [sid for sid in student_ids if sid not in finished]

    print(f"🚀 总数: {len(student_ids)} | 待处理: {len(pending)} | 代理: {'启用' if use_proxy else '禁用'}")
    print(f"📂 {os.path.abspath(csv_dir)}")

    # 并发下载
    success, failed = await batch_download(pending, csv_dir, use_proxy, args.workers,
                                           desc="进度", total=len(student_ids), initial=len(finished))

    # 重试失败学号
    finished_now = {f[:-4] for f in os.listdir(csv_dir) if f.endswith('.csv') and not f.startswith('.')}
    retry_ids = [sid for sid in student_ids if sid not in finished_now]
    if retry_ids:
        print(f"\n🔄 重试 {len(retry_ids)} 个失败学号...")
        _, failed = await batch_download(retry_ids, csv_dir, use_proxy, args.workers, desc="重试")
        if failed > 0:
            print(f"⚠️ 仍有 {failed} 个学号下载失败")

    # 打包ZIP
    print("\n📦 打包中...")
    try:
        files = [f for f in os.listdir(csv_dir) if f.endswith('.csv') and not f.startswith('.')]

        with zipfile.ZipFile(zip_name, 'w', zipfile.ZIP_DEFLATED) as zf:
            for f in tqdm(files, desc="打包", unit="个"):
                zf.write(os.path.join(csv_dir, f), f)
        print(f"✅ 完成! {len(files)} 个文件 -> {os.path.abspath(zip_name)}")
    except Exception as e:
        print(f"❌ 打包失败: {e}")

def main():
    parser = argparse.ArgumentParser(description="批量成绩下载器")
    parser.add_argument('--workers', '-w', type=int, default=DEFAULT_WORKERS, help='并发数')
    parser.add_argument('--ids', '-i', default='ids.txt', help='学号文件')
    parser.add_argument('--proxy', '-p', action='store_true', help='使用代理')
    parser.add_argument('--zip', '-z', default='all_grades.zip', help='输出ZIP文件名')
    args = parser.parse_args()
    asyncio.run(async_main(args))

if __name__ == "__main__":
    main()
