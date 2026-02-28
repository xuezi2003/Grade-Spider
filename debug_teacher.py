"""
找出课表ZIP中含有全角逗号的教师字段的HTML文件
"""
import re
import zipfile
import sys
from bs4 import BeautifulSoup


def find_fullwidth_comma_in_zip(zip_path):
    """扫描ZIP中所有HTML，找出教师字段含全角逗号的文件"""
    results = []
    
    with zipfile.ZipFile(zip_path, 'r') as zf:
        html_files = [f for f in zf.namelist() if f.endswith('.html')]
        print(f"共 {len(html_files)} 个HTML文件")
        
        for filename in html_files:
            html = zf.read(filename).decode('utf-8', errors='ignore')
            
            # 找所有 师[...] 模式
            teachers = re.findall(r'师\[([^\]]*)\]', html)
            for t in teachers:
                if '，' in t:  # 全角逗号
                    results.append({
                        'file': filename,
                        'teacher_raw': t,
                        'html': html,
                    })
                    break  # 一个文件只记录一次
    
    return results


def main():
    if len(sys.argv) < 2:
        print("用法: python debug_teacher.py <课表ZIP路径>")
        print("示例: python debug_teacher.py 课表_2022.zip")
        sys.exit(1)
    
    zip_path = sys.argv[1]
    print(f"扫描: {zip_path}")
    
    results = find_fullwidth_comma_in_zip(zip_path)
    
    if not results:
        print("\n✅ 没有找到含全角逗号的教师字段")
        return
    
    print(f"\n⚠️ 找到 {len(results)} 个文件含全角逗号:")
    
    for i, r in enumerate(results[:5]):  # 只显示前5个
        print(f"\n{'='*60}")
        print(f"文件: {r['file']}")
        print(f"教师原文: {r['teacher_raw']}")
        
        # 解析并显示上下文
        soup = BeautifulSoup(r['html'], 'html.parser')
        
        # 找到包含该教师的td
        for td in soup.find_all('td', class_='detail'):
            td_text = str(td)
            if r['teacher_raw'] in td_text:
                # 提取课程名
                b = td.find('b', class_='fontcourse')
                if b:
                    print(f"课程: {b.get_text()[:60]}...")
                
                # 打印师[...]部分的上下文
                match = re.search(r'师\[' + re.escape(r['teacher_raw']) + r'\]', td_text)
                if match:
                    start = max(0, match.start() - 50)
                    end = min(len(td_text), match.end() + 50)
                    context = td_text[start:end]
                    print(f"上下文: ...{context}...")
                break
    
    if len(results) > 5:
        print(f"\n... 还有 {len(results) - 5} 个文件")


if __name__ == '__main__':
    main()
