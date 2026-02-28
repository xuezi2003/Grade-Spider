"""将推免名单解析结果导入数据库 recommendation 表"""
import os

try:
    from config import DB_URI
except ImportError:
    DB_URI = 'postgresql+psycopg2://user:pass@localhost:5432/cdut-score'

from sqlalchemy import create_engine, text
from parse_recommendation import parse_pdf, parse_markdown, deduplicate


def load_all_records():
    base = os.path.dirname(os.path.abspath(__file__))
    all_records = []

    md_file = os.path.join(base, '2024名单.md')
    if os.path.exists(md_file):
        all_records.extend(deduplicate(parse_markdown(md_file, 2024)))

    for fn, yr in [('2025名单.pdf', 2025), ('2026名单.pdf', 2026)]:
        fp = os.path.join(base, fn)
        if os.path.exists(fp):
            all_records.extend(deduplicate(parse_pdf(fp, yr)))

    return all_records


def import_to_db(records):
    engine = create_engine(DB_URI, pool_pre_ping=True)

    insert_sql = text("""
        INSERT INTO recommendation
            (s_id, year, name, gender, political, college, major,
             course_gpa, course_avg, perf_score, comp_score, comp_rank, major_total, remark)
        VALUES
            (:s_id, :year, :name, :gender, :political, :college, :major,
             :course_gpa, :course_avg, :perf_score, :comp_score, :comp_rank, :major_total, :remark)
        ON CONFLICT (s_id, year) DO UPDATE SET
            name=EXCLUDED.name, gender=EXCLUDED.gender, political=EXCLUDED.political,
            college=EXCLUDED.college, major=EXCLUDED.major,
            course_gpa=EXCLUDED.course_gpa, course_avg=EXCLUDED.course_avg,
            perf_score=EXCLUDED.perf_score, comp_score=EXCLUDED.comp_score,
            comp_rank=EXCLUDED.comp_rank, major_total=EXCLUDED.major_total,
            remark=EXCLUDED.remark
    """)

    with engine.begin() as conn:
        batch = []
        for r in records:
            batch.append({
                's_id': r['s_id'],
                'year': r['year'],
                'name': r['name'],
                'gender': r['gender'],
                'political': r['political_status'],
                'college': r.get('college', ''),
                'major': r.get('major', ''),
                'course_gpa': r['course_gpa'],
                'course_avg': r['course_avg'],
                'perf_score': r['performance_score'],
                'comp_score': r['composite_score'],
                'comp_rank': r['composite_rank'],
                'major_total': r['major_total'],
                'remark': r['remark'],
            })
            if len(batch) >= 500:
                conn.execute(insert_sql, batch)
                print(f"\r  写入 {len(batch)} 条...", end="", flush=True)
                batch = []
        if batch:
            conn.execute(insert_sql, batch)

    print(f"\n完成，共写入 {len(records)} 条")


if __name__ == '__main__':
    print("加载推免名单...")
    records = load_all_records()
    print(f"共 {len(records)} 条记录")

    print("写入数据库...")
    import_to_db(records)
