import requests
import re
import os
import xlrd
import csv
import sys

# 配置
BASE_URL = 'http://rpsjw.cdut.edu.cn/qzbb'
PROXIES = {
    'http': 'socks5h://127.0.0.1:10801',
    'https': 'socks5h://127.0.0.1:10801'
}

def download_grade(student_id):
    session = requests.Session()
    session.proxies.update(PROXIES)
    session.headers.update({'User-Agent': 'curl/7.29.0'})

    try:
        # Step 1: 获取页面参数
        print(f"[*] 正在获取学号 {student_id} 的参数...")
        url = f"{BASE_URL}/reportJsp/showReport.jsp?rpx=/148656-XSCJDXSD.rpx"
        data = {'selShowType': 'all', 'kclx': '0', 'xsxh': student_id}
        r = session.post(url, data=data, timeout=30)
        
        cached_id = re.search(r'report1_cachedId\s*=\s*"([^"]+)"', r.text).group(1)
        params_id = re.search(r'name=reportParamsId\s*value=([^>\s]+)', r.text).group(1)
        time_val = re.search(r't_i_m_e=(\d+)', r.text).group(1)

        # Step 2: 下载 Excel
        print("[*] 正在下载 Excel...")
        download_params = {
            'action': '3', 'file': '/148656-XSCJDXSD.rpx', 'srcType': 'file',
            'cachedId': cached_id, 'reportParamsId': params_id, 't_i_m_e': time_val,
            'excelFormat': '2003'
        }
        x = session.get(f'{BASE_URL}/reportServlet', params=download_params, timeout=30)

        # Step 3: 转 CSV
        print("[*] 正在保存为 CSV...")
        workbook = xlrd.open_workbook(file_contents=x.content)
        sheet = workbook.sheet_by_index(0)
        
        filename = f"{student_id}.csv"
        with open(filename, 'w', newline='', encoding='utf-8-sig') as f:
            writer = csv.writer(f)
            for i in range(sheet.nrows):
                writer.writerow(sheet.row_values(i))
        
        print(f"成功! 文件已保存: {filename}")

    except Exception as e:
        print(f"失败: {e}")

if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("用法: python single_download.py <学号>")
    else:
        download_grade(sys.argv[1])
