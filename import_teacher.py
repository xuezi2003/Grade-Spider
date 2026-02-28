#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
从课表ZIP解析教师信息，批量UPDATE到course_score表的c_teacher字段。
用法: python import_teacher.py --zip <课表ZIP路径> [--workers N] [--dry-run]
"""
import os
import re
import argparse
import zipfile
import concurrent.futures
from collections import defaultdict
from sqlalchemy import create_engine, Column, String, Float
from sqlalchemy.orm import sessionmaker, declarative_base
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy import SmallInteger

from parse_schedule import parse_html, normalize_punct


# 进程池 worker：每个子进程打开一次 ZIP，复用句柄
_zf = None

def _init_worker(zip_path):
    global _zf
    _zf = zipfile.ZipFile(zip_path, 'r')

def _parse_one(filename):
    html = _zf.read(filename).decode('utf-8', errors='ignore')
    return parse_html(html, filename)

# 尝试导入配置
try:
    from config import DB_URI, DB_POOL_SIZE, DB_MAX_OVERFLOW, DB_POOL_RECYCLE
except ImportError:
    DB_URI = 'postgresql+psycopg2://user:pass@localhost:5432/cdut-score'
    DB_POOL_SIZE = 32
    DB_MAX_OVERFLOW = 64
    DB_POOL_RECYCLE = 3600

Base = declarative_base()

class CourseScore(Base):
    __tablename__ = 'course_score'
    s_id = Column(String(14), primary_key=True)
    c_term = Column(String(8), primary_key=True)
    c_name = Column(String(100), primary_key=True)
    c_score = Column(Float, nullable=False)
    c_type = Column(String(20), nullable=False, default='必修')
    c_hours = Column(String(10), nullable=False)
    c_credit = Column(Float, nullable=False)
    c_pass = Column(SmallInteger, nullable=False)
    c_teacher = Column(String(200), nullable=True)


def term_display_to_db(term_display):
    """
    课表学期格式 → 数据库 c_term 格式
    '2025-2026学年第一学期' → '202501'
    '2024-2025学年第二学期' → '202402'
    编码规则：c_term = 起始年份 + 01(秋)/02(春)
    """
    m = re.match(r'(\d{4})-\d{4}学年第(一|二)学期', term_display)
    if not m:
        return None
    year1 = m.group(1)
    semester = '01' if m.group(2) == '一' else '02'
    return f"{year1}{semester}"


def main():
    parser = argparse.ArgumentParser(description='导入课表教师信息到数据库')
    parser.add_argument('--zip', required=True, help='课表ZIP压缩包路径')
    parser.add_argument('--workers', type=int, default=os.cpu_count(), help='并发进程数（默认CPU核心数）')
    parser.add_argument('--batch-size', type=int, default=10000, help='每批写入条数')
    parser.add_argument('--dry-run', action='store_true', help='只解析不写入，预览结果')
    args = parser.parse_args()

    # 1. 列出ZIP中所有HTML文件名
    print(f"📂 加载 ZIP: {args.zip}")
    with zipfile.ZipFile(args.zip, 'r') as zf_main:
        html_files = [f for f in zf_main.namelist() if f.endswith('.html')]
    total_files = len(html_files)
    print(f"   共 {total_files} 个 HTML 文件")

    # 2. 多进程并发解析（CPU密集型，用ProcessPoolExecutor）
    update_records = []
    success = 0
    empty = 0
    fail = 0
    skip_term = 0

    print(f"🔄 使用 {args.workers} 个进程并发解析...")
    with concurrent.futures.ProcessPoolExecutor(max_workers=args.workers, initializer=_init_worker, initargs=(args.zip,)) as executor:
        futures = {
            executor.submit(_parse_one, filename): filename
            for filename in html_files
        }
        count = 0
        for future in concurrent.futures.as_completed(futures):
            count += 1
            if count % 1000 == 0 or count == total_files:
                print(f"\r   解析进度: {count}/{total_files} ({count*100//total_files}%)", end="", flush=True)
            try:
                filename, student, courses = future.result()
                if not courses:
                    empty += 1
                    continue

                sid = student.get('student_id', '')
                term_display = student.get('term', '')
                if not sid or not term_display:
                    empty += 1
                    continue

                db_term = term_display_to_db(term_display)
                if not db_term:
                    skip_term += 1
                    continue

                for c in courses:
                    teacher_py = c.get('teacher_py', '')
                    if teacher_py:
                        update_records.append({
                            's_id': sid,
                            'c_term': db_term,
                            'c_name': normalize_punct(c['name']),
                            'c_score': 0, 'c_type': '', 'c_hours': '0',
                            'c_credit': 0, 'c_pass': 0,
                            'c_teacher': teacher_py,
                        })
                success += 1
            except Exception as e:
                fail += 1

    print(f"\n✅ 解析完成: 有课 {success}, 空 {empty}, 失败 {fail}, 学期无法转换 {skip_term}")
    print(f"   待写入记录数: {len(update_records)}")

    if not update_records:
        print("⚠️ 没有可更新的记录")
        return

    # 3. 预览
    print(f"\n📋 预览前 10 条:")
    for rec in update_records[:10]:
        print(f"   {rec['s_id']} | {rec['c_term']} | {rec['c_name']} | {rec['c_teacher']}")

    terms = defaultdict(int)
    for rec in update_records:
        terms[rec['c_term']] += 1
    print(f"\n   按学期分布:")
    for term, cnt in sorted(terms.items()):
        print(f"     {term}: {cnt} 条")

    if args.dry_run:
        print("\n🔍 dry-run 模式，不写入数据库")
        return

    # 4. SQLAlchemy 批量 INSERT ... ON DUPLICATE KEY UPDATE（和 grade_manager 一样）
    print(f"\n💾 开始写入数据库...")
    engine = create_engine(DB_URI, pool_size=DB_POOL_SIZE,
                           max_overflow=DB_MAX_OVERFLOW, pool_recycle=DB_POOL_RECYCLE,
                           pool_pre_ping=True)
    Session = sessionmaker(autocommit=False, autoflush=False, bind=engine)
    session = Session()

    try:
        total = len(update_records)
        batch_size = args.batch_size
        print(f"📚 正在写入教师信息 ({total} 条)...")

        for i in range(0, total, batch_size):
            batch = update_records[i:i+batch_size]
            stmt = pg_insert(CourseScore).values(batch)
            update_stmt = stmt.on_conflict_do_update(
                index_elements=['s_id', 'c_term', 'c_name'],
                set_={'c_teacher': stmt.excluded.c_teacher}
            )
            session.execute(update_stmt)
            done = min(i + batch_size, total)
            print(f"\r   写入进度: {done}/{total} ({done*100//total}%)", end="", flush=True)

        session.commit()
        print(f"\n✅ 写入完成: 共 {total} 条")

    except Exception as e:
        session.rollback()
        print(f"\n❌ 写入失败: {e}")
        import traceback
        traceback.print_exc()
    finally:
        session.close()
        engine.dispose()


if __name__ == '__main__':
    main()
