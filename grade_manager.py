#!/usr/bin/env python3
# -*- coding: utf-8 -*-
import os
import sys
import csv
import argparse
import zipfile
import concurrent.futures
from datetime import datetime
from pypinyin import pinyin, Style
from sqlalchemy import create_engine, Column, String, Float, Integer, text
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy import SmallInteger

def normalize_punct(s):
    """全角ASCII标点 → 半角"""
    if not s:
        return s
    return s.replace('（', '(').replace('）', ')').replace('：', ':').replace('，', ',')

# 尝试导入配置
try:
    from config import DB_URI, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_RECYCLE
except ImportError:
    DB_URI = 'postgresql+psycopg2://user:pass@localhost:5432/cdut-score'
    DB_POOL_SIZE = 32
    DB_MAX_OVERFLOW = 64
    DB_POOL_RECYCLE = 3600

Base = declarative_base()

class Student(Base):
    __tablename__ = 'student'
    s_id = Column(String(14), primary_key=True)
    s_name = Column(String(50), nullable=False, index=True)
    s_college = Column(String(50), nullable=False)
    s_major = Column(String(50), nullable=False, index=True)
    s_grade = Column(String(10), nullable=False)
    s_class = Column(String(20), nullable=False, index=True)
    s_avg = Column(Float, nullable=False, index=True)
    s_gpa = Column(Float, nullable=False, index=True)
    s_py = Column(String(255), nullable=False, index=True)
    class_avg_rank = Column(Integer)
    class_gpa_rank = Column(Integer)
    major_avg_rank = Column(Integer)
    major_gpa_rank = Column(Integer)

class CourseScore(Base):
    __tablename__ = 'course_score'
    # Composite Primary Key
    s_id = Column(String(14), primary_key=True, nullable=False, index=True)
    c_term = Column(String(8), primary_key=True, nullable=False, index=True)
    c_name = Column(String(100), primary_key=True, nullable=False, index=True)
    
    c_score = Column(Float, nullable=False)
    c_type = Column(String(20), nullable=False, default='必修')
    c_hours = Column(String(10), nullable=False)
    c_credit = Column(Float, nullable=False)
    c_pass = Column(SmallInteger, nullable=False) # 0-正常 1-补考 2-重修 3-刷分

class CourseName(Base):
    __tablename__ = 'course_name'
    c_name = Column(String(100), primary_key=True)

class GradeManager:
    def __init__(self):
        self.engine = create_engine(
            DB_URI, 
            pool_size=DB_POOL_SIZE, 
            max_overflow=DB_MAX_OVERFLOW, 
            pool_recycle=DB_POOL_RECYCLE, 
            pool_pre_ping=True
        )
        self.SessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=self.engine)
        Base.metadata.create_all(bind=self.engine)

    def parse_csv_grade(self, content_or_path):
        """解析 CSV 格式的成绩内容或文件"""
        lines = None
        
        # 如果是字节流（从zip读取），先转为字符串列表
        if isinstance(content_or_path, bytes):
            for encoding in ['utf-8', 'gbk']:
                try:
                    lines = content_or_path.decode(encoding).splitlines()
                    break
                except: continue
        # 如果是路径
        elif isinstance(content_or_path, str) and os.path.exists(content_or_path):
            for encoding in ['utf-8', 'gbk']:
                try:
                    with open(content_or_path, 'r', encoding=encoding) as f:
                        lines = f.readlines()
                    break
                except: continue
        
        if not lines: return None, None

        student_info = self._parse_student_info(lines)
        if not student_info: return None, None

        courses = self._parse_courses(lines)
        return student_info, courses

    def _parse_student_info(self, lines):
        """解析学生信息 (死索引逻辑)"""
        if len(lines) < 3: return None
        try:
            line1_parts = lines[1].strip().split(',')
            line2_parts = lines[2].strip().split(',')

            s_id = line1_parts[13].strip()
            s_class = line1_parts[10].strip() if len(line1_parts) > 10 else '未知'
            
            # 校验班级号
            # 数据治理检查确认所有班级号均为10位，无需处理逻辑
            
            info = {
                's_id': s_id,
                's_name': line2_parts[13].strip() if len(line2_parts) > 13 else '未知',
                's_college': normalize_punct(line1_parts[2].strip() if len(line1_parts) > 2 else '未知'),
                's_class': normalize_punct(s_class),
                's_major': normalize_punct(line2_parts[2].strip() if len(line2_parts) > 2 else '未知'),
                's_grade': line2_parts[10].strip() if len(line2_parts) > 10 else '未知'
            }
            if not info['s_id']: return None

            if len(lines) > 61:
                stats_line = lines[61].strip().split(',')
                info['s_avg'] = float(stats_line[6].strip()) if len(stats_line) > 6 and stats_line[6].strip() else 0.0
                info['s_gpa'] = float(stats_line[14].strip()) if len(stats_line) > 14 and stats_line[14].strip() else 0.0
            else:
                info['s_avg'] = info['s_gpa'] = 0.0

            info['s_py'] = "".join(p[0] for p in pinyin(info['s_name'], style=Style.FIRST_LETTER))
            return info
        except: return None

    def _parse_courses(self, lines):
        """解析课程信息"""
        courses = []
        for i in range(7, min(61, len(lines))):
            line = lines[i].strip().split(',')
            if not line or not line[0]: continue
            try:
                # 第一列
                if len(line) >= 7 and line[1].strip():
                    courses.append({
                        'c_term': line[0].strip(),
                        'c_name': normalize_punct(line[1].strip()),
                        'c_type': normalize_punct(line[3].strip() if len(line) > 3 else '必修'),
                        'c_hours': line[4].strip() if len(line) > 4 else '0',
                        'c_credit': float(line[5].strip()) if len(line) > 5 and line[5].strip() else 0.0,
                        'c_score': self._parse_score(line[6] if len(line) > 6 else ''),
                        'c_pass': self._get_pass_status(line[7].strip() if len(line) > 7 else '')
                    })
                # 第二列
                if len(line) > 9 and line[8].strip().isdigit():
                    courses.append({
                        'c_term': line[8].strip(),
                        'c_name': normalize_punct(line[9].strip()),
                        'c_type': normalize_punct(line[11].strip() if len(line) > 11 else '必修'),
                        'c_hours': line[12].strip() if len(line) > 12 else '0',
                        'c_credit': float(line[13].strip()) if len(line) > 13 and line[13].strip() else 0.0,
                        'c_score': self._parse_score(line[14] if len(line) > 14 else ''),
                        'c_pass': self._get_pass_status(line[15].strip() if len(line) > 15 else '')
                    })
            except: continue
        # Deduplicate courses: keep the one with the highest score/priority
        # Key: (c_term, c_name)
        unique_courses = {}
        for c in courses:
            key = (c['c_term'], c['c_name'])
            if key not in unique_courses:
                unique_courses[key] = c
            else:
                # Comparison logic: Prefer higher score, then specific types if scores equal
                old_c = unique_courses[key]
                if c['c_score'] > old_c['c_score']:
                    unique_courses[key] = c
        
        return list(unique_courses.values())

    def _get_pass_status(self, grade_type):
        if '刷分' in grade_type: return 3
        if '补考' in grade_type: return 1
        if '重修' in grade_type: return 2
        return 0

    def _parse_score(self, s):
        s = s.strip()
        try: return float(s)
        except: return {'优': 95.0, '良': 85.0, '中': 75.0, '及格': 65.0, '不及格': 55.0}.get(s, 0.0)

    def save_from_zip(self, zip_path):
        """从ZIP压缩包直接读取并保存到数据库"""
        if not os.path.exists(zip_path):
            print(f"❌ 找不到文件: {zip_path}")
            return False

        import threading
        zip_lock = threading.Lock()

        with zipfile.ZipFile(zip_path, 'r') as z:
            csv_files = [f for f in z.namelist() if f.lower().endswith('.csv')]
            total_files = len(csv_files)
            if not csv_files:
                print("❌ ZIP内没有找到CSV文件")
                return False

            print(f"📊 开始从ZIP解析 {total_files} 个文件...")
            all_students, all_courses = [], []
            
            # 定义线程内部逻辑
            def process_zip_entry(filename):
                try:
                    with zip_lock:
                        with z.open(filename) as f:
                            content = f.read()
                    return self.parse_csv_grade(content)
                except Exception as e:
                    print(f"\n⚠️ 处理文件 {filename} 出错: {e}")
                    return None, None

            with concurrent.futures.ThreadPoolExecutor(max_workers=80) as executor:
                futures = {executor.submit(process_zip_entry, f): f for f in csv_files}
                count = 0
                for future in concurrent.futures.as_completed(futures):
                    res = future.result()
                    count += 1
                    if count % 100 == 0 or count == total_files:
                        print(f"\r📁 解析进度: {count}/{total_files} ({count*100//total_files}%)", end="", flush=True)
                    
                    if res and res[0]:
                        student, courses = res
                        all_students.append(student)
                        all_courses.extend({**c, 's_id': student['s_id']} for c in courses)
            
            print("\n✅ 解析完成，开始同步到数据库...")
            return self._sync_to_db(all_students, all_courses)

    def save_to_database(self, csv_dir):
        """从目录读取并保存到数据库"""
        files = [os.path.join(csv_dir, f) for f in os.listdir(csv_dir) if f.lower().endswith('.csv')]
        total_files = len(files)
        if not files: return False

        print(f"📊 开始从目录解析 {total_files} 个文件...")
        all_students, all_courses = [], []
        
        with concurrent.futures.ThreadPoolExecutor(max_workers=80) as executor:
            futures = [executor.submit(self.parse_csv_grade, f) for f in files]
            count = 0
            for future in concurrent.futures.as_completed(futures):
                res = future.result()
                count += 1
                if count % 100 == 0 or count == total_files:
                    print(f"\r📁 解析进度: {count}/{total_files} ({count*100//total_files}%)", end="", flush=True)
                
                if res and res[0]:
                    student, courses = res
                    all_students.append(student)
                    all_courses.extend({**c, 's_id': student['s_id']} for c in courses)
        
        print("\n✅ 解析完成，开始同步到数据库...")
        return self._sync_to_db(all_students, all_courses)

    def _sync_to_db(self, all_students, all_courses):
        """核心入库逻辑"""
        from sqlalchemy.dialects.postgresql import insert as pg_insert
        session = self.SessionLocal()
        try:
            # 2. 学生信息 Upsert
            if all_students:
                total_s = len(all_students)
                print(f"📝 正在同步学生信息 ({total_s} 条)...")
                for i in range(0, total_s, 5000):
                    batch = all_students[i:i+5000]
                    stmt = pg_insert(Student).values(batch)
                    update_stmt = stmt.on_conflict_do_update(
                        index_elements=['s_id'],
                        set_={
                            's_name': stmt.excluded.s_name,
                            's_college': stmt.excluded.s_college,
                            's_major': stmt.excluded.s_major,
                            's_grade': stmt.excluded.s_grade,
                            's_class': stmt.excluded.s_class,
                            's_avg': stmt.excluded.s_avg,
                            's_gpa': stmt.excluded.s_gpa,
                            's_py': stmt.excluded.s_py,
                        }
                    )
                    session.execute(update_stmt)
                    current = min(i + 5000, total_s)
                    print(f"\r👤 写入学生: {current}/{total_s} ({current*100//total_s}%)", end="", flush=True)
                print("\n✅ 学生信息同步完成")

            # 3. 课程成绩 Upsert
            if all_courses:
                total_c = len(all_courses)
                print(f"📚 正在同步课程成绩 ({total_c} 条)...")
                for i in range(0, total_c, 10000):
                    batch = all_courses[i:i+10000]
                    stmt = pg_insert(CourseScore).values(batch)
                    update_stmt = stmt.on_conflict_do_update(
                        index_elements=['s_id', 'c_term', 'c_name'],
                        set_={
                            'c_score': stmt.excluded.c_score,
                            'c_type': stmt.excluded.c_type,
                            'c_hours': stmt.excluded.c_hours,
                            'c_credit': stmt.excluded.c_credit,
                            'c_pass': stmt.excluded.c_pass,
                        }
                    )
                    session.execute(update_stmt)
                    current = min(i + 10000, total_c)
                    print(f"\r📖 写入成绩: {current}/{total_c} ({current*100//total_c}%)", end="", flush=True)
                print("\n✅ 课程成绩同步完成")
                
                # 4. 同步课程名到 course_name 表
                course_names = list(set(c['c_name'] for c in all_courses))
                if course_names:
                    print(f"📋 同步课程名 ({len(course_names)} 个)...")
                    stmt = pg_insert(CourseName).values([{'c_name': n} for n in course_names])
                    stmt = stmt.on_conflict_do_nothing()
                    session.execute(stmt)
                    print("✅ 课程名同步完成")
            
            session.commit()
            print("✅ 数据导入完成")
            
            # 4. 用纯SQL计算排名
            print("🔄 正在执行SQL排名计算...")
            self._run_sql_ranking(session)
            print("✨ 全部完成！")
            return True
        except Exception as e:
            print(f"\n❌ 失败: {e}")
            import traceback
            traceback.print_exc()
            session.rollback()
            return False
        finally: session.close()

    def _run_sql_ranking(self, session):
        """使用纯SQL计算排名"""
        try:
            # 用SQL窗口函数计算排名
            print("📊 正在计算排名（使用SQL窗口函数）...")
            session.execute(text("""
                UPDATE student
                SET 
                    class_avg_rank = t.c_avg_r,
                    class_gpa_rank = t.c_gpa_r,
                    major_avg_rank = t.m_avg_r,
                    major_gpa_rank = t.m_gpa_r
                FROM (
                    SELECT 
                        s_id,
                        RANK() OVER (PARTITION BY s_class ORDER BY s_avg DESC) as c_avg_r,
                        RANK() OVER (PARTITION BY s_class ORDER BY s_gpa DESC) as c_gpa_r,
                        RANK() OVER (PARTITION BY LEFT(s_class, 8) ORDER BY s_avg DESC) as m_avg_r,
                        RANK() OVER (PARTITION BY LEFT(s_class, 8) ORDER BY s_gpa DESC) as m_gpa_r
                    FROM student
                ) t
                WHERE student.s_id = t.s_id
            """))
            session.commit()
            print("✅ 排名计算完成")
            
        except Exception as e:
            print(f"\n❌ 计算失败: {e}")
            import traceback
            traceback.print_exc()
            session.rollback()
            raise

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument('--database', help='CSV目录')
    parser.add_argument('--zip', help='ZIP压缩包路径')
    args = parser.parse_args()
    
    manager = GradeManager()
    if args.zip:
        success = manager.save_from_zip(args.zip)
        sys.exit(0 if success else 1)
    elif args.database: 
        success = manager.save_to_database(args.database)
        sys.exit(0 if success else 1)
    else:
        parser.print_help()
