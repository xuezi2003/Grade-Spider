"""解析推免名单 PDF，提取结构化数据"""
import re
import fitz  # PyMuPDF


def normalize_punct(s):
    """全角ASCII标点 → 半角"""
    if not s:
        return s
    return s.replace('（', '(').replace('）', ')').replace('：', ':').replace('，', ',')


def parse_pdf(filepath, year):
    """解析单个 PDF 文件，返回记录列表"""
    records = []
    doc = fitz.open(filepath)
    
    # 合并所有页的文本
    all_lines = []
    for page in doc:
        text = page.get_text()
        all_lines.extend(text.split('\n'))
    doc.close()
    
    # 按学号分割为记录块
    buffer = ''
    for line in all_lines:
        line = line.strip()
        if not line:
            continue
        if re.search(r'20[12]\d{9}', line):
            if buffer:
                rec = _parse_record(buffer, year)
                if rec:
                    records.append(rec)
            buffer = line
        else:
            buffer += ' ' + line
    # 处理最后一条
    if buffer:
        rec = _parse_record(buffer, year)
        if rec:
            records.append(rec)
    
    return records


def _parse_record(text, year):
    """从一段文本中解析单条记录"""
    # 学号
    sid_match = re.search(r'(20[12]\d{9})', text)
    if not sid_match:
        return None
    sid = sid_match.group(1)
    
    # 提取6个数字：绩点 均分 表现分 综合分 名次 人数
    # 前4个可能是整数或浮点数（如表现分可能为 0、10 等整数）
    nums_pattern = r'(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+(?:\.\d+)?)\s+(\d+)\s+(\d+(?:\.\d+)?)'
    nums_match = re.search(nums_pattern, text)
    if not nums_match:
        return None
    
    gpa = float(nums_match.group(1))
    avg = float(nums_match.group(2))
    perf = float(nums_match.group(3))
    comp = float(nums_match.group(4))
    rank = int(nums_match.group(5))
    total = int(float(nums_match.group(6)))
    
    # 备注（6个数字之后的内容）
    after_nums = text[nums_match.end():].strip()
    # 清理掉页码等无关内容
    after_nums = re.sub(r'第\d+页.*', '', after_nums).strip()
    # 清理末尾的纯数字（下一条记录的序号）
    after_nums = re.sub(r'\s*\d+\s*$', '', after_nums).strip()
    remark = normalize_punct(after_nums)
    
    # 政治面貌
    political_options = [
        '中共预备党员', '中共党员', '预备党员', '正式党员',
        '共青团员', '团员', '群众'
    ]
    political = ''
    for opt in political_options:
        if opt in text:
            political = opt
            break
    
    # 姓名：学号后面的2-4个汉字
    after_sid = text[sid_match.end():]
    name_match = re.search(r'([\u4e00-\u9fa5]{2,4})', after_sid)
    name = name_match.group(1) if name_match else ''
    
    # 性别
    gender_match = re.search(r'(男|女)', after_sid)
    gender = gender_match.group(1) if gender_match else ''
    
    # 学院：包含「学院」的中文片段（可能带括号后缀）
    before_nums = text[:nums_match.start()].strip()
    college_match = re.search(r'([\u4e00-\u9fa5]+(?:学院|研究院)(?:[（(][\u4e00-\u9fa5]+[）)])?)', before_nums)
    college = college_match.group(1) if college_match else ''
    # 去除可能被贪婪匹配吃进来的政治面貌前缀
    for p in political_options:
        if college.startswith(p):
            college = college[len(p):]
            break
    # 统一全角括号为半角
    college = college.replace('（', '(').replace('）', ')')
    
    # 专业：学院之后、数字之前的最后一段中文（可能带括号）
    major = ''
    if college_match:
        after_college = before_nums[college_match.end():]
    else:
        after_college = before_nums
    major_match = re.search(r'([\u4e00-\u9fa5][\u4e00-\u9fa5（）\(\)]+)\s*$', after_college.strip())
    major = major_match.group(1) if major_match else ''
    major = major.replace('（', '(').replace('）', ')')
    
    return {
        'year': year,
        's_id': sid,
        'name': name,
        'gender': gender,
        'political_status': political,
        'college': college,
        'major': major,
        'course_gpa': gpa,
        'course_avg': avg,
        'performance_score': perf,
        'composite_score': comp,
        'composite_rank': rank,
        'major_total': total,
        'remark': remark,
    }


def parse_markdown(filepath, year):
    """解析 Markdown 表格格式的推免名单（如 2024 名单）"""
    records = []
    with open(filepath, encoding='utf-8') as f:
        for line in f:
            line = line.strip()
            if not line.startswith('|') or '序号' in line or '---' in line:
                continue
            cols = [c.strip() for c in line.split('|')[1:-1]]
            if len(cols) < 10:
                continue
            sid = cols[1]
            if not re.match(r'20[0-2]\d{9}$', sid):
                continue
            records.append({
                'year': year,
                's_id': sid,
                'name': cols[2],
                'gender': cols[3],
                'political_status': cols[4],
                'college': cols[5].replace('（', '(').replace('）', ')'),
                'major': cols[6].replace('（', '(').replace('）', ')'),
                'course_gpa': float(cols[7]),
                'course_avg': None,
                'performance_score': None,
                'composite_score': float(cols[8]),
                'composite_rank': int(cols[9]),
                'major_total': None,
                'remark': normalize_punct(cols[10]) if len(cols) > 10 else '',
            })
    return records


def deduplicate(records):
    """按 s_id + year 去重，保留第一条"""
    seen = set()
    unique = []
    for r in records:
        key = (r['s_id'], r['year'])
        if key not in seen:
            seen.add(key)
            unique.append(r)
    return unique


if __name__ == '__main__':
    import os
    base = os.path.dirname(os.path.abspath(__file__))
    
    all_records = []
    
    # 解析 2024 Markdown 名单
    md_file = os.path.join(base, '2024名单.md')
    if os.path.exists(md_file):
        records = parse_markdown(md_file, 2024)
        records = deduplicate(records)
        all_records.extend(records)
        print(f"=== 2024名单.md (year=2024) ===")
        print(f"解析到 {len(records)} 条记录")
        for i, r in enumerate(records[:3]):
            print(f"  [{i+1}] {r['s_id']} {r['name']} {r['gender']} "
                  f"政治={r['political_status']} "
                  f"学院={r['college']} 专业={r['major']} "
                  f"GPA={r['course_gpa']} 综合={r['composite_score']} "
                  f"名次={r['composite_rank']} "
                  f"备注={r['remark']}")
        print(f"  ...")
    else:
        print(f"文件不存在: {md_file}")

    for filename, year in [('2025名单.pdf', 2025), ('2026名单.pdf', 2026)]:
        filepath = os.path.join(base, filename)
        if not os.path.exists(filepath):
            print(f"文件不存在: {filepath}")
            continue
        records = parse_pdf(filepath, year)
        
        # 调试：重新扫描找出被丢弃的记录
        import fitz
        doc = fitz.open(filepath)
        dropped = []
        for page_idx, page in enumerate(doc):
            text = page.get_text()
            sids_in_page = re.findall(r'20[12]\d{9}', text)
            parsed_sids = {r['s_id'] for r in records}
            for sid in sids_in_page:
                if sid not in parsed_sids:
                    # 找到这个学号附近的文本
                    idx = text.find(sid)
                    context = text[max(0,idx-20):idx+80].replace('\n', ' | ')
                    dropped.append((page_idx+1, sid, context))
        doc.close()
        
        if dropped:
            print(f"\n*** 被丢弃的学号 ({len(dropped)} 个): ***")
            for pg, sid, ctx in dropped[:20]:
                print(f"  p{pg} {sid}: {ctx}")
        
        records = deduplicate(records)
        all_records.extend(records)
        print(f"\n=== {filename} (year={year}) ===")
        print(f"解析到 {len(records)} 条记录")
        
        # 打印前5条
        for i, r in enumerate(records[:5]):
            print(f"  [{i+1}] {r['s_id']} {r['name']} {r['gender']} "
                  f"政治={r['political_status']} "
                  f"学院={r['college']} 专业={r['major']} "
                  f"GPA={r['course_gpa']} 均分={r['course_avg']} "
                  f"表现={r['performance_score']} 综合={r['composite_score']} "
                  f"名次={r['composite_rank']}/{r['major_total']} "
                  f"备注={r['remark']}")
        
        # 打印最后3条
        print(f"  ...")
        for i, r in enumerate(records[-3:]):
            print(f"  [{len(records)-2+i}] {r['s_id']} {r['name']} {r['gender']} "
                  f"政治={r['political_status']} "
                  f"学院={r['college']} 专业={r['major']} "
                  f"GPA={r['course_gpa']} 均分={r['course_avg']} "
                  f"表现={r['performance_score']} 综合={r['composite_score']} "
                  f"名次={r['composite_rank']}/{r['major_total']} "
                  f"备注={r['remark']}")
    
    print(f"\n总计: {len(all_records)} 条记录")
    
    # 检查学号是否都是12位
    bad_ids = [r for r in all_records if len(r['s_id']) != 12]
    print(f"非12位学号: {len(bad_ids)} 条")
    
    # 检查缺失字段
    no_name = [r for r in all_records if not r['name']]
    no_political = [r for r in all_records if not r['political_status']]
    no_college = [r for r in all_records if not r.get('college')]
    no_major = [r for r in all_records if not r.get('major')]
    print(f"缺失姓名: {len(no_name)} 条")
    print(f"缺失政治面貌: {len(no_political)} 条")
    print(f"缺失学院: {len(no_college)} 条")
    print(f"缺失专业: {len(no_major)} 条")
    if no_college:
        for r in no_college[:10]:
            print(f"  无学院: {r['s_id']} {r['name']}")
    if no_major:
        for r in no_major[:10]:
            print(f"  无专业: {r['s_id']} {r['name']}")

    # 输出到 txt
    out_path = os.path.join(base, 'recommendation_parsed.txt')
    with open(out_path, 'w', encoding='utf-8') as f:
        f.write("year\ts_id\tname\tgender\tpolitical_status\tcollege\tmajor\tcourse_gpa\tcourse_avg\tperformance_score\tcomposite_score\tcomposite_rank\tmajor_total\tremark\n")
        for r in all_records:
            f.write(f"{r['year']}\t{r['s_id']}\t{r['name']}\t{r['gender']}\t{r['political_status']}\t"
                    f"{r['college']}\t{r['major']}\t"
                    f"{r['course_gpa']}\t{r['course_avg']}\t{r['performance_score']}\t"
                    f"{r['composite_score']}\t{r['composite_rank']}\t{r['major_total']}\t{r['remark']}\n")
    print(f"\n已输出到: {out_path}")
