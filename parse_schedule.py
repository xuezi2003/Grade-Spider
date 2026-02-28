"""
解析 viewtable.do 返回的课表 HTML，提取每门课的教师信息。
支持: 单个HTML文件、目录、ZIP文件（不解压直接读取）
用法: python parse_schedule.py <html文件|目录|zip文件> [--workers N]
"""
import re
import sys
import os
import zipfile
from concurrent.futures import ProcessPoolExecutor, as_completed
from bs4 import BeautifulSoup
from pypinyin import pinyin, Style


def normalize_punct(s):
    """全角ASCII标点 → 半角"""
    if not s:
        return s
    return s.replace('（', '(').replace('）', ')').replace('：', ':').replace('，', ',')


def name_to_py(name):
    """中文姓名转 '姓+名拼音首字母' 格式，如 张三→张s，过滤掉省略号等无效值"""
    name = name.strip()
    if not name or name == '...':
        return ''
    if len(name) == 1:
        return name  # 单字姓名，直接返回
    surname = name[0]  # 姓氏保留中文
    given = name[1:]   # 名字转拼音首字母
    given_py = ''.join(p[0] for p in pinyin(given, style=Style.FIRST_LETTER))
    return surname + given_py


def parse_student_info(soup):
    """从 tab3 表格提取学生基本信息"""
    tab3 = soup.find('table', class_='tab3')
    if not tab3:
        return {}
    text = tab3.get_text()
    info = {}
    m = re.search(r'学号[:：]?\s*(\d+)', text)
    if m:
        info['student_id'] = m.group(1)
    m = re.search(r'姓名[:：]?\s*(\S+)', text)
    if m:
        info['name'] = m.group(1)
    m = re.search(r'班级[:：]?\s*(\S+)', text)
    if m:
        info['class'] = m.group(1)
    m = re.search(r'学院/专业[:：]?\s*(.+?)(?:\s{2,}|$)', text)
    if m:
        info['major'] = m.group(1).strip()
    m = re.search(r'(\d{4}-\d{4}学年第[一二]学期)', text)
    if m:
        info['term'] = m.group(1)
    return info


def parse_courses(soup):
    """从 tab2 表格提取课程信息，重点是课程名和教师"""
    tab2 = soup.find('table', class_='tab2')
    if not tab2:
        return []

    courses = []
    for td in tab2.find_all('td', class_='detail'):
        b = td.find('b', class_='fontcourse')
        if not b:
            continue

        b_text = b.get_text()
        m = re.match(r'\((.+?)\)\s*(.+?)\[(.+?)\]\s*学分\[(.+?)\]', b_text)
        if not m:
            continue

        abbr = m.group(1)
        course_name = normalize_punct(m.group(2).strip())
        course_code = m.group(3)
        credit = m.group(4)

        td_html = str(td)
        after_b = td_html.split('</b>', 1)[-1]
        rooms = re.findall(r'室\[(.+?)\]', after_b)
        hours = re.findall(r'时\[(.+?)\]', after_b)

        # 按 <br> 分段，每段对应一行授课信息（可能是理论或实践）
        segments = re.split(r'<br\s*/?>', after_b)
        type_teacher_parts = []  # [(类型, 教师字符串), ...]
        all_teachers_flat = []

        for seg in segments:
            seg_type = re.findall(r'\[(理|实)\]', seg)
            seg_teachers = re.findall(r'师\[(.*?)\]', seg)
            if not seg_teachers:
                continue
            teacher_str = seg_teachers[0]  # 该段的教师（可能逗号分隔多人）
            teacher_str = normalize_punct(teacher_str).strip().rstrip(',').strip()  # 清理全角+尾部逗号
            tp = seg_type[0] if seg_type else ''
            type_teacher_parts.append((tp, teacher_str))
            for name in teacher_str.split(','):
                name = name.strip()
                if name and name not in all_teachers_flat:
                    all_teachers_flat.append(name)

        # 拼接 teacher_display（中文全名）和 teacher_py（拼音缩写）
        # 只有一段或所有段教师相同 → 直接用教师名
        # 多段教师不同 → "理论:xxx 实践:yyy"
        unique_teachers = list(dict.fromkeys(t for _, t in type_teacher_parts))
        type_label = {'理': '理论', '实': '实践'}
        if len(unique_teachers) <= 1:
            teacher_display = unique_teachers[0] if unique_teachers else ''
            # 拼音：逗号分隔的多人各自转换
            if teacher_display:
                py_names = [name_to_py(n) for n in teacher_display.split(',')]
                teacher_py = ','.join(p for p in py_names if p)
            else:
                teacher_py = ''
        else:
            display_parts = []
            py_parts = []
            for tp, t in type_teacher_parts:
                label = type_label.get(tp, tp)
                display_parts.append(f"{label}:{t}" if label else t)
                # 拼音：每段教师逗号分隔各自转换
                py_names = [name_to_py(n) for n in t.split(',')]
                py_str = ','.join(p for p in py_names if p)
                py_parts.append(f"{label}:{py_str}" if label else py_str)
            teacher_display = ' '.join(display_parts)
            teacher_py = ' '.join(py_parts)

        courses.append({
            'abbr': abbr,
            'name': course_name,
            'code': course_code,
            'credit': credit,
            'teachers': all_teachers_flat,
            'teacher_display': teacher_display,
            'teacher_py': teacher_py,
            'rooms': rooms,
            'hours': hours,
            'types': [tp for tp, _ in type_teacher_parts],
        })

    return courses


def parse_html(html, filename=''):
    """解析 HTML 字符串，返回 (filename, student, courses)"""
    soup = BeautifulSoup(html, 'html.parser')
    student = parse_student_info(soup)
    courses = parse_courses(soup)
    return filename, student, courses


def format_result(filename, student, courses):
    """格式化单条结果为字符串"""
    lines = []
    lines.append(f"\n{'='*60}")
    lines.append(f"文件: {filename}")
    if student:
        lines.append(f"学号: {student.get('student_id', '?')}  "
                     f"姓名: {student.get('name', '?')}  "
                     f"班级: {student.get('class', '?')}")
        lines.append(f"专业: {student.get('major', '?')}")
        lines.append(f"学期: {student.get('term', '?')}")
    lines.append(f"共 {len(courses)} 门课程")
    lines.append('-'*60)

    for i, c in enumerate(courses, 1):
        td = c.get('teacher_display', ', '.join(c['teachers'])) or '未知'
        tpy = c.get('teacher_py', '') or ''
        lines.append(f"  {i:2d}. [{c['code']}] {c['name']}")
        lines.append(f"      学分: {c['credit']}  教师: {td}  拼音: {tpy}")
        if c['rooms']:
            lines.append(f"      教室: {', '.join(c['rooms'])}")

    return '\n'.join(lines)


def load_from_zip(zip_path):
    """从 ZIP 文件中读取所有 HTML，返回 [(filename, html_str), ...]"""
    items = []
    with zipfile.ZipFile(zip_path, 'r') as zf:
        for name in zf.namelist():
            if name.endswith('.html'):
                html = zf.read(name).decode('utf-8', errors='ignore')
                items.append((name, html))
    return items


def load_from_dir(dir_path):
    """从目录递归读取所有 HTML，返回 [(filename, html_str), ...]"""
    items = []
    for root, dirs, files in os.walk(dir_path):
        for f in sorted(files):
            if f.endswith('.html'):
                fp = os.path.join(root, f)
                with open(fp, 'r', encoding='utf-8') as fh:
                    items.append((fp, fh.read()))
    return items


def _worker(args):
    """进程池 worker：解析单个 (filename, html)"""
    filename, html = args
    return parse_html(html, filename)


def print_stats(all_results):
    """统计各字段的种类数量"""
    students = set()
    terms = set()
    colleges = set()
    majors = set()
    classes = set()
    courses_set = set()
    course_codes = set()
    teachers = set()
    rooms = set()
    credits = set()
    course_teacher_pairs = set()  # (课程名, 教师)

    total_courses = 0

    for filename, student, courses in all_results:
        if student.get('student_id'):
            students.add(student['student_id'])
        if student.get('term'):
            terms.add(student['term'])
        if student.get('major'):
            colleges_major = student['major']
            # 尝试拆分学院和专业
            majors.add(colleges_major)
        if student.get('class'):
            classes.add(student['class'])

        for c in courses:
            total_courses += 1
            courses_set.add(c['name'])
            course_codes.add(c['code'])
            credits.add(c['credit'])
            for t in c['teachers']:
                teachers.add(t)
                course_teacher_pairs.add((c['name'], t))
            for r in c['rooms']:
                rooms.add(r)

    print(f"\n{'='*60}")
    print(f"📊 统计汇总")
    print(f"{'='*60}")
    print(f"  学生数:         {len(students)}")
    print(f"  学期数:         {len(terms)}  {sorted(terms)}")
    print(f"  班级数:         {len(classes)}")
    print(f"  专业数:         {len(majors)}")
    print(f"  课程名(去重):   {len(courses_set)}")
    print(f"  课程代码(去重): {len(course_codes)}")
    print(f"  教师(去重):     {len(teachers)}")
    print(f"  教室(去重):     {len(rooms)}")
    print(f"  学分种类:       {len(credits)}  {sorted(credits)}")
    print(f"  课程-教师对:    {len(course_teacher_pairs)}")
    print(f"  课程记录总数:   {total_courses}")
    print(f"{'='*60}")

    # 每个学生平均多少门课
    if students:
        print(f"  平均每学生每学期: {total_courses / len(students):.1f} 门课")

    # 教师授课门数 Top 20
    from collections import Counter
    teacher_course_cnt = Counter()
    for name, t in course_teacher_pairs:
        teacher_course_cnt[t] += 1
    print(f"\n  教师授课门数 Top 20:")
    for t, cnt in teacher_course_cnt.most_common(20):
        print(f"    {t}: {cnt} 门")

    # 验证：同一门课的理论和实践教师是否相同
    print(f"\n{'='*60}")
    print(f"🔍 理论/实践教师一致性验证")
    print(f"{'='*60}")
    # 如果 types 有 ['理','实'] 且 teachers 去重后只有1人 → 理论实践同一教师
    multi_type_courses = {}  # course_name -> {'same': 0, 'diff': 0, 'diff_examples': []}
    for filename, student, courses in all_results:
        sid = student.get('student_id', '')
        for c in courses:
            if len(c['types']) < 2:
                continue
            name = c['name']
            if name not in multi_type_courses:
                multi_type_courses[name] = {'same': 0, 'diff': 0, 'diff_examples': []}

            # types 和 teachers 一一对应吗？
            # teachers 是去重后的列表，如果只有 1 个 → 理论实践同一教师
            if len(c['teachers']) == 1:
                multi_type_courses[name]['same'] += 1
            else:
                multi_type_courses[name]['diff'] += 1
                if len(multi_type_courses[name]['diff_examples']) < 3:
                    multi_type_courses[name]['diff_examples'].append(
                        f"{sid}: {c['teachers']}"
                    )

    total_same = sum(v['same'] for v in multi_type_courses.values())
    total_diff = sum(v['diff'] for v in multi_type_courses.values())
    print(f"  含理论+实践的课程种类: {len(multi_type_courses)}")
    print(f"  理论实践教师相同: {total_same} 条")
    print(f"  理论实践教师不同: {total_diff} 条")
    print(f"  一致率: {total_same/(total_same+total_diff)*100:.1f}%" if (total_same+total_diff) > 0 else "")

    if total_diff > 0:
        print(f"\n  教师不同的课程:")
        for name, v in sorted(multi_type_courses.items(), key=lambda x: -x[1]['diff']):
            if v['diff'] > 0:
                print(f"    {name}: 相同{v['same']}次, 不同{v['diff']}次")
                for ex in v['diff_examples']:
                    print(f"      例: {ex}")

    print()


def main():
    import argparse
    parser = argparse.ArgumentParser(description='解析课表HTML，提取课程-教师信息')
    parser.add_argument('--zip', help='ZIP压缩包路径')
    parser.add_argument('--dir', help='HTML文件目录路径')
    parser.add_argument('--file', help='单个HTML文件路径')
    parser.add_argument('--workers', type=int, default=os.cpu_count(), help='并发进程数（默认CPU核心数）')
    parser.add_argument('--stats', action='store_true', default=True, help='只输出统计（默认）')
    parser.add_argument('--detail', action='store_true', help='输出每个学生的详细课表')
    args = parser.parse_args()

    workers = args.workers

    if args.zip:
        items = load_from_zip(args.zip)
        print(f"从 ZIP 中读取到 {len(items)} 个 HTML 文件")
    elif args.dir:
        items = load_from_dir(args.dir)
        print(f"从目录中读取到 {len(items)} 个 HTML 文件")
    elif args.file:
        with open(args.file, 'r', encoding='utf-8') as f:
            items = [(args.file, f.read())]
    else:
        parser.print_help()
        sys.exit(1)

    if not items:
        print("未找到任何 HTML 文件")
        sys.exit(0)

    all_results = []
    success = 0
    empty = 0
    fail = 0

    if len(items) == 1:
        filename, student, courses = parse_html(items[0][1], items[0][0])
        if args.detail:
            print(format_result(filename, student, courses))
        all_results.append((filename, student, courses))
        print_stats(all_results)
        return

    print(f"使用 {workers} 个进程并发解析...")
    with ProcessPoolExecutor(max_workers=workers) as executor:
        futures = {executor.submit(_worker, item): item[0] for item in items}
        for future in as_completed(futures):
            fname = futures[future]
            try:
                filename, student, courses = future.result()
                if courses:
                    if args.detail:
                        print(format_result(filename, student, courses))
                    all_results.append((filename, student, courses))
                    success += 1
                else:
                    empty += 1
            except Exception as e:
                print(f"\n解析失败: {fname} -> {e}")
                fail += 1

    print(f"\n文件统计: 共 {len(items)} 个, 有课 {success}, 空 {empty}, 失败 {fail}")
    print_stats(all_results)


if __name__ == '__main__':
    main()
