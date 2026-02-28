// ==UserScript==
// @name         成都理工大学教务工具箱
// @namespace    http://tampermonkey.net/
// @version      3.0
// @description  批量获取学号 + 批量采集课表，打包为ZIP下载
// @author       DinaHelper
// @match        https://jw.cdut.edu.cn/jsxsd/xskb/xsqtkb.do*
// @require      https://cdnjs.cloudflare.com/ajax/libs/jszip/3.10.1/jszip.min.js
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function () {
    'use strict';

    const KBJCMSID = '7E5976C91D9A4146930951FD11516BCC';
    let allStudents = [];
    let allSchedules = {};
    let isRunning = false;

    // ========== 通用工具 ==========

    function sleep(ms) { return new Promise(r => setTimeout(r, ms)); }

    function showToast(message) {
        const toast = document.createElement('div');
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
            background: rgba(0,0,0,0.8); color: white; padding: 15px 30px;
            border-radius: 8px; font-size: 14px; z-index: 9999999; animation: fadeInOut 2s;
        `;
        if (!document.getElementById('toast-anim-style')) {
            const style = document.createElement('style');
            style.id = 'toast-anim-style';
            style.textContent = `
                @keyframes fadeInOut {
                    0% { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
                    20% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
                    80% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
                    100% { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
                }
            `;
            document.head.appendChild(style);
        }
        document.body.appendChild(toast);
        setTimeout(() => { if (toast.parentNode) document.body.removeChild(toast); }, 2000);
    }

    function isValidStudentId(xh) {
        return xh && /^\d{12}$/.test(xh);
    }

    function getAvailableTerms() {
        const select = document.getElementById('xnxq01id');
        if (!select) return [];
        return Array.from(select.options).map(opt => opt.value).filter(v => v);
    }

    function getEnrollYear(studentId) {
        return parseInt(studentId.substring(0, 4));
    }

    function getStartTerm(enrollYear) {
        return `${enrollYear}-${enrollYear + 1}-1`;
    }

    function getTermsForStudent(studentId, allTerms) {
        const enrollYear = getEnrollYear(studentId);
        const startTerm = getStartTerm(enrollYear);
        const startIdx = allTerms.indexOf(startTerm);
        if (startIdx === -1) {
            const laterTerms = allTerms.filter(t => t >= startTerm);
            return laterTerms.length > 0 ? laterTerms.reverse() : allTerms.slice().reverse();
        }
        return allTerms.slice(0, startIdx + 1).reverse();
    }

    function getTermsForPrefix(prefix, allTerms) {
        const year = parseInt(prefix.substring(0, 4));
        if (isNaN(year) || year < 2000 || year > 2099) return allTerms;
        const startTerm = getStartTerm(year);
        const startIdx = allTerms.indexOf(startTerm);
        if (startIdx === -1) {
            return allTerms.filter(t => t >= startTerm);
        }
        return allTerms.slice(0, startIdx + 1);
    }

    async function fetchStudentsByKeyword(keyword, startWith) {
        const response = await fetch('/jsxsd/xskb/cxxs', {
            method: 'POST',
            headers: {
                'Content-Type': 'application/x-www-form-urlencoded; charset=UTF-8',
                'X-Requested-With': 'XMLHttpRequest'
            },
            body: `maxRow=100000000&xsmc=${encodeURIComponent(keyword)}`
        });
        const data = await response.json();
        if (data.result && data.list && data.list.length > 0) {
            let list = startWith ? data.list.filter(item => item.xh && item.xh.startsWith(keyword)) : data.list;
            const before = list.length;
            list = list.filter(item => isValidStudentId(item.xh));
            const filtered = before - list.length;
            if (filtered > 0) console.log(`已过滤 ${filtered} 个非法学号（非12位纯数字）`);
            return list;
        }
        return [];
    }

    // ========== 功能一：批量获取学号 ==========

    function createStudentIdBox() {
        const box = document.createElement('div');
        box.id = 'student-ids-box';
        box.innerHTML = `
            <div style="
                position: fixed; top: 100px; right: 20px; width: 350px; max-height: 500px;
                background: white; border: 2px solid #4CAF50; border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.2); z-index: 99999; display: none;
                font-family: Arial, sans-serif;
            ">
                <div style="
                    background: #4CAF50; color: white; padding: 12px; border-radius: 6px 6px 0 0;
                    display: flex; justify-content: space-between; align-items: center;
                ">
                    <span style="font-weight: bold; font-size: 16px;">📋 学号列表</span>
                    <button id="close-box" style="
                        background: none; border: none; color: white; font-size: 20px;
                        cursor: pointer; padding: 0; width: 24px; height: 24px;
                    ">×</button>
                </div>
                <div style="padding: 15px;">
                    <div style="margin-bottom: 10px; color: #666; font-size: 14px;">
                        共获取 <span id="student-count" style="color: #4CAF50; font-weight: bold;">0</span> 个学号
                    </div>
                    <div id="filter-info"></div>
                    <div id="student-list" style="
                        max-height: 300px; overflow-y: auto; border: 1px solid #ddd;
                        border-radius: 4px; padding: 10px; background: #f9f9f9;
                        margin-bottom: 12px; font-size: 13px; line-height: 1.6;
                    "></div>
                    <button id="download-ids-btn" style="
                        width: 100%; padding: 10px; background: #4CAF50; color: white;
                        border: none; border-radius: 4px; cursor: pointer;
                        font-size: 14px; font-weight: bold;
                    ">⬇️ 下载为TXT文件</button>
                    <button id="copy-ids-btn" style="
                        width: 100%; padding: 10px; background: #2196F3; color: white;
                        border: none; border-radius: 4px; cursor: pointer;
                        font-size: 14px; font-weight: bold; margin-top: 8px;
                    ">📋 复制学号列表</button>
                </div>
            </div>
        `;
        document.body.appendChild(box);
        document.getElementById('close-box').onclick = () => { box.querySelector('div').style.display = 'none'; };
        document.getElementById('download-ids-btn').onclick = () => {
            if (allStudents.length === 0) { alert('没有学号可以下载！'); return; }
            const blob = new Blob([allStudents.map(i => i.xh).join('\n')], { type: 'text/plain;charset=utf-8' });
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a'); a.href = url;
            a.download = `学号列表_${new Date().toISOString().slice(0,10)}.txt`;
            document.body.appendChild(a); a.click(); document.body.removeChild(a);
            URL.revokeObjectURL(url); showToast('✅ 下载成功！');
        };
        document.getElementById('copy-ids-btn').onclick = () => {
            if (allStudents.length === 0) { alert('没有学号可以复制！'); return; }
            const content = allStudents.map(i => i.xh).join('\n');
            navigator.clipboard.writeText(content).then(() => showToast('✅ 已复制到剪贴板！')).catch(() => {
                const ta = document.createElement('textarea'); ta.value = content;
                document.body.appendChild(ta); ta.select(); document.execCommand('copy');
                document.body.removeChild(ta); showToast('✅ 已复制到剪贴板！');
            });
        };
    }

    function showStudentIds(keyword, startWith) {
        const box = document.getElementById('student-ids-box').querySelector('div');
        document.getElementById('student-count').textContent = allStudents.length;
        const filterInfo = document.getElementById('filter-info');
        if (filterInfo) {
            filterInfo.innerHTML = (startWith && keyword) ? `<div style="
                background: #e3f2fd; border-left: 4px solid #2196F3; padding: 8px 12px;
                margin-bottom: 10px; border-radius: 4px; font-size: 13px; color: #1976D2;
            ">🔍 已过滤：只显示以"<strong>${keyword}</strong>"开头的学号</div>` : '';
        }
        document.getElementById('student-list').innerHTML = allStudents.map((item, i) =>
            `<div style="padding: 4px 0; border-bottom: 1px solid #eee;">
                <span style="color: #999; margin-right: 8px;">${i + 1}.</span>
                <span style="color: #333; font-weight: 500;">${item.xh}</span>
                <span style="color: #666; margin-left: 8px; font-size: 12px;">${item.xsmc}</span>
            </div>`
        ).join('');
        box.style.display = 'block';
    }

    async function showFetchStudentsDialog() {
        const dialog = document.createElement('div');
        dialog.innerHTML = `
            <div style="
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.5); z-index: 999998;
                display: flex; align-items: center; justify-content: center;
            ">
                <div style="
                    background: white; padding: 30px; border-radius: 10px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.3); min-width: 400px;
                ">
                    <h3 style="margin: 0 0 20px 0; color: #333; font-size: 18px;">🔍 批量获取学号</h3>
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; color: #666; font-size: 14px;">搜索关键词：</label>
                        <input type="text" id="sid-keyword" value="2022" style="
                            width: 100%; padding: 10px; border: 1px solid #ddd;
                            border-radius: 4px; font-size: 14px; box-sizing: border-box;
                        " placeholder="请输入关键词，如：2022、2021等">
                    </div>
                    <div style="margin-bottom: 25px;">
                        <label style="display: flex; align-items: center; cursor: pointer; font-size: 14px; color: #333;">
                            <input type="checkbox" id="sid-starts-with" checked style="width: 18px; height: 18px; margin-right: 8px; cursor: pointer;">
                            <span>只获取以关键词<strong>开头</strong>的学号</span>
                        </label>
                        <div style="margin-left: 26px; margin-top: 5px; font-size: 12px; color: #999;">
                            例如：搜索"2022"时，只匹配"2022xxxxx"，不匹配"200709020222"
                        </div>
                    </div>
                    <div style="display: flex; gap: 10px;">
                        <button id="sid-confirm" style="flex: 1; padding: 12px; background: #4CAF50; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: bold;">确定</button>
                        <button id="sid-cancel" style="flex: 1; padding: 12px; background: #999; color: white; border: none; border-radius: 4px; cursor: pointer; font-size: 14px; font-weight: bold;">取消</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(dialog);
        const result = await new Promise(resolve => {
            document.getElementById('sid-confirm').onclick = () => {
                const kw = document.getElementById('sid-keyword').value.trim();
                const sw = document.getElementById('sid-starts-with').checked;
                document.body.removeChild(dialog); resolve({ keyword: kw, startWith: sw });
            };
            document.getElementById('sid-cancel').onclick = () => { document.body.removeChild(dialog); resolve(null); };
            document.getElementById('sid-keyword').onkeypress = e => { if (e.key === 'Enter') document.getElementById('sid-confirm').click(); };
        });
        if (!result || !result.keyword) return;

        const loading = document.createElement('div');
        loading.innerHTML = `<div style="position: fixed; top: 50%; left: 50%; transform: translate(-50%, -50%);
            background: white; padding: 30px 50px; border-radius: 10px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.3); z-index: 999999; text-align: center;">
            <div style="font-size: 18px; margin-bottom: 15px;">🔍 正在获取学号...</div>
            <div style="color: #666;">请稍候</div></div>`;
        document.body.appendChild(loading);

        try {
            allStudents = await fetchStudentsByKeyword(result.keyword, result.startWith);
            document.body.removeChild(loading);
            if (allStudents.length === 0) { alert(`未找到以"${result.keyword}"开头的学号！`); return; }
            showStudentIds(result.keyword, result.startWith);
        } catch (err) {
            document.body.removeChild(loading);
            alert('获取学号失败：' + err.message);
        }
    }

    // ========== 功能二：批量采集课表 ==========

    function createButtons() {
        const container = document.createElement('div');
        container.style.cssText = 'position: fixed; top: 20px; right: 20px; z-index: 99999; display: flex; gap: 10px;';

        const btnStyle = `padding: 12px 20px; color: white; border: none; border-radius: 6px;
            cursor: pointer; font-size: 14px; font-weight: bold;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1); transition: all 0.3s;`;

        const btn1 = document.createElement('button');
        btn1.innerHTML = '🎯 批量获取学号';
        btn1.style.cssText = btnStyle + 'background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);';
        btn1.onmouseover = () => { btn1.style.transform = 'translateY(-2px)'; };
        btn1.onmouseout = () => { btn1.style.transform = 'translateY(0)'; };
        btn1.onclick = showFetchStudentsDialog;

        const btn2 = document.createElement('button');
        btn2.innerHTML = '📅 批量采集课表';
        btn2.style.cssText = btnStyle + 'background: linear-gradient(135deg, #f093fb 0%, #f5576c 100%);';
        btn2.onmouseover = () => { btn2.style.transform = 'translateY(-2px)'; };
        btn2.onmouseout = () => { btn2.style.transform = 'translateY(0)'; };
        btn2.onclick = showConfigDialog;

        container.appendChild(btn1);
        container.appendChild(btn2);
        document.body.appendChild(container);
    }

    function updateTermPreview(prefix) {
        const info = document.getElementById('kb-term-info');
        if (!info) return;
        const allTerms = getAvailableTerms();
        if (!prefix || prefix.length < 4) {
            info.innerHTML = '<span style="color: #999;">请输入至少4位学号前缀以自动计算学期范围</span>';
            return;
        }
        const terms = getTermsForPrefix(prefix, allTerms);
        if (terms.length === 0) {
            info.innerHTML = '<span style="color: #f44336;">未找到匹配的学期！</span>';
            return;
        }
        const last = terms[terms.length - 1];
        const first = terms[0];
        info.innerHTML = `<span style="color: #1976D2;">将获取 <strong>${last}</strong> ~ <strong>${first}</strong>，共 <strong>${terms.length}</strong> 个学期</span>`;
    }

    function showConfigDialog() {
        if (isRunning) { alert('正在采集中，请等待完成！'); return; }

        const allTerms = getAvailableTerms();
        const currentTerm = allTerms.length > 0 ? allTerms[0] : '未知';

        const dialog = document.createElement('div');
        dialog.id = 'kb-config-dialog';
        dialog.innerHTML = `
            <div style="
                position: fixed; top: 0; left: 0; right: 0; bottom: 0;
                background: rgba(0,0,0,0.5); z-index: 999998;
                display: flex; align-items: center; justify-content: center;
            ">
                <div style="
                    background: white; padding: 30px; border-radius: 12px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.3); min-width: 480px;
                ">
                    <h3 style="margin: 0 0 20px 0; color: #333;">📅 批量采集课表（多学期）</h3>

                    <div style="margin-bottom: 15px;">
                        <label style="display: block; margin-bottom: 6px; color: #666; font-size: 13px;">学号前缀（如 2022、202218）：</label>
                        <input type="text" id="kb-prefix" value="2022" style="
                            width: 100%; padding: 10px; border: 1px solid #ddd;
                            border-radius: 4px; font-size: 14px; box-sizing: border-box;
                        ">
                    </div>

                    <div style="margin-bottom: 15px; padding: 10px; background: #e3f2fd; border-radius: 4px; border-left: 4px solid #2196F3;">
                        <div style="font-size: 12px; color: #666; margin-bottom: 4px;">📆 自动计算的学期范围：</div>
                        <div id="kb-term-info" style="font-size: 13px;"></div>
                    </div>

                    <div style="margin-bottom: 15px; display: flex; gap: 10px;">
                        <div style="flex: 1;">
                            <label style="display: block; margin-bottom: 6px; color: #666; font-size: 13px;">请求间隔（毫秒）：</label>
                            <input type="number" id="kb-delay" value="200" min="50" max="5000" style="
                                width: 100%; padding: 10px; border: 1px solid #ddd;
                                border-radius: 4px; font-size: 14px; box-sizing: border-box;
                            ">
                        </div>
                        <div style="flex: 1;">
                            <label style="display: block; margin-bottom: 6px; color: #666; font-size: 13px;">并发数：</label>
                            <input type="number" id="kb-concurrency" value="10" min="1" style="
                                width: 100%; padding: 10px; border: 1px solid #ddd;
                                border-radius: 4px; font-size: 14px; box-sizing: border-box;
                            ">
                        </div>
                    </div>

                    <div style="margin-bottom: 20px; padding: 10px; background: #fff3cd; border-radius: 4px; font-size: 12px; color: #856404;">
                        ⚠️ 提示：根据学号前缀自动判断入学年份，从入学学期开始逐学期获取课表。<br>
                        非12位数字学号将被自动过滤。获取不到的学期会跳过。<br>
                        并发数越大速度越快，但被封风险越高。<br>
                        当前系统可用学期：${allTerms.length} 个（最新: ${currentTerm}）
                    </div>

                    <div style="display: flex; gap: 10px;">
                        <button id="kb-start-btn" style="
                            flex: 1; padding: 12px; background: #4CAF50; color: white;
                            border: none; border-radius: 4px; cursor: pointer;
                            font-size: 14px; font-weight: bold;
                        ">🚀 开始采集</button>
                        <button id="kb-cancel-btn" style="
                            flex: 1; padding: 12px; background: #999; color: white;
                            border: none; border-radius: 4px; cursor: pointer;
                            font-size: 14px; font-weight: bold;
                        ">取消</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(dialog);

        // 初始化学期预览
        updateTermPreview('2022');
        document.getElementById('kb-prefix').addEventListener('input', e => updateTermPreview(e.target.value.trim()));

        document.getElementById('kb-cancel-btn').onclick = () => document.body.removeChild(dialog);
        document.getElementById('kb-start-btn').onclick = () => {
            const prefix = document.getElementById('kb-prefix').value.trim();
            const delay = parseInt(document.getElementById('kb-delay').value) || 200;
            const concurrency = Math.max(1, parseInt(document.getElementById('kb-concurrency').value) || 10);
            document.body.removeChild(dialog);
            if (!prefix || prefix.length < 4) { alert('请输入至少4位学号前缀！'); return; }
            startBatchFetch(prefix, delay, concurrency);
        };
    }

    function createProgressPanel() {
        const panel = document.createElement('div');
        panel.id = 'kb-progress-panel';
        panel.innerHTML = `
            <div style="
                position: fixed; top: 80px; right: 20px; width: 400px;
                background: white; border: 2px solid #4CAF50; border-radius: 8px;
                box-shadow: 0 4px 12px rgba(0,0,0,0.2); z-index: 99999;
                font-family: Arial, sans-serif;
            ">
                <div style="background: #4CAF50; color: white; padding: 12px; border-radius: 6px 6px 0 0;">
                    <span style="font-weight: bold; font-size: 15px;">📅 课表采集进度</span>
                </div>
                <div style="padding: 15px;">
                    <div id="kb-status" style="margin-bottom: 10px; font-size: 14px; color: #333;">准备中...</div>
                    <div style="background: #eee; border-radius: 4px; height: 20px; margin-bottom: 10px; overflow: hidden;">
                        <div id="kb-progress-bar" style="background: #4CAF50; height: 100%; width: 0%; transition: width 0.3s; border-radius: 4px;"></div>
                    </div>
                    <div id="kb-detail" style="font-size: 12px; color: #666; max-height: 200px; overflow-y: auto;"></div>
                    <button id="kb-stop-btn" style="
                        width: 100%; padding: 8px; margin-top: 10px;
                        background: #f44336; color: white; border: none;
                        border-radius: 4px; cursor: pointer; font-size: 13px;
                    ">⏹ 停止采集</button>
                </div>
            </div>
        `;
        document.body.appendChild(panel);
        document.getElementById('kb-stop-btn').onclick = () => { isRunning = false; };
    }

    function updateProgress(status, percent, detail) {
        if (status !== null && status !== undefined) {
            const el = document.getElementById('kb-status');
            if (el) el.textContent = status;
        }
        if (percent !== null && percent !== undefined) {
            const bar = document.getElementById('kb-progress-bar');
            if (bar) bar.style.width = percent + '%';
        }
        if (detail) {
            const d = document.getElementById('kb-detail');
            if (d) { d.innerHTML = detail + d.innerHTML; }
        }
    }

    async function fetchScheduleHtml(studentId, term) {
        const url = `/jsxsd/xskb/viewtable.do?xnxq01id=${term}&kbjcmsid=${KBJCMSID}&xs0101id=${studentId}&lx=xs0101id`;
        const response = await fetch(url);
        const fullHtml = await response.text();
        // 只保留 parse_schedule.py 需要的 table.tab3（学生信息）和 table.tab2（课表）
        const doc = new DOMParser().parseFromString(fullHtml, 'text/html');
        const tab3 = doc.querySelector('table.tab3');
        const tab2 = doc.querySelector('table.tab2');
        if (!tab3 && !tab2) return '';
        return (tab3 ? tab3.outerHTML : '') + (tab2 ? tab2.outerHTML : '');
    }

    async function startBatchFetch(prefix, delay, concurrency) {
        isRunning = true;
        allStudents = [];
        allSchedules = {};

        const allTerms = getAvailableTerms();

        createProgressPanel();
        updateProgress('正在获取学号列表...', 0);

        try {
            // Step 1: 获取学号（已自动过滤非12位）
            allStudents = await fetchStudentsByKeyword(prefix, true);
            if (allStudents.length === 0) {
                updateProgress(`未找到以 "${prefix}" 开头的有效学号（12位数字）！`, 0);
                isRunning = false;
                return;
            }

            // Step 2: 构建扁平任务队列 [{stu, term}, ...]
            const tasks = [];
            for (const stu of allStudents) {
                const terms = getTermsForStudent(stu.xh, allTerms);
                for (const term of terms) {
                    tasks.push({ stu, term });
                }
            }
            const totalRequests = tasks.length;

            updateProgress(`找到 ${allStudents.length} 个学号，共 ${totalRequests} 个请求（并发=${concurrency}），开始采集...`, 3);
            await sleep(500);

            // Step 3: 并发执行，边采集边写入 ZIP（避免 OOM）
            const zip = new JSZip();
            const folder = zip.folder(`课表_${prefix}`);
            let completed = 0;
            let successTerms = 0;
            let emptyTerms = 0;
            let failTerms = 0;
            const studentNames = {};

            let taskIndex = 0;

            async function worker() {
                while (taskIndex < tasks.length && isRunning) {
                    const idx = taskIndex++;
                    if (idx >= tasks.length) break;

                    const { stu, term } = tasks[idx];

                    try {
                        const html = await fetchScheduleHtml(stu.xh, term);

                        if (!html) {
                            emptyTerms++;
                        } else {
                            studentNames[stu.xh] = stu.xsmc;
                            folder.file(`${stu.xh}_${stu.xsmc}/${term}.html`, html);
                            successTerms++;
                        }

                    } catch (err) {
                        failTerms++;
                        updateProgress(null, null,
                            `<div style="color: orange;">⚠️ ${stu.xh} ${term}: ${err.message}</div>`
                        );
                    }

                    completed++;
                    const pct = Math.round((completed / totalRequests) * 90 + 5);
                    updateProgress(
                        `请求 ${completed}/${totalRequests} | 有效 ${successTerms} 空 ${emptyTerms} 失败 ${failTerms} | 并发=${concurrency}`,
                        pct
                    );

                    if (delay > 0) await sleep(delay);
                }
            }

            // 启动 N 个并发 worker
            const workers = [];
            for (let w = 0; w < concurrency; w++) {
                workers.push(worker());
            }
            await Promise.all(workers);

            const stoppedEarly = !isRunning;

            // 学号列表
            folder.file('学号列表.txt', Object.keys(studentNames).join('\n'));

            // Step 4: 打包下载
            const fileCount = Object.keys(zip.files).length;
            if (fileCount > 1) {
                const statusPrefix = stoppedEarly ? '⏹ 已停止，保存已有结果' : '✅ 完成';
                updateProgress('正在打包 ZIP...（可能需要一些时间）', 95);
                const blob = await zip.generateAsync({ type: 'blob' });
                const url = URL.createObjectURL(blob);
                const a = document.createElement('a');
                a.href = url;
                a.download = `课表_${prefix}_${new Date().toISOString().slice(0, 10)}.zip`;
                document.body.appendChild(a);
                a.click();
                document.body.removeChild(a);
                URL.revokeObjectURL(url);
                updateProgress(`${statusPrefix}！完成 ${completed}/${totalRequests}，失败 ${failTerms}，ZIP 已下载`, 100);
            } else {
                updateProgress(stoppedEarly ? '已停止，没有已采集的数据可保存' : '没有获取到任何课表数据！', 100);
            }

        } catch (err) {
            updateProgress(`出错: ${err.message}`, 0);
        }

        isRunning = false;
        const stopBtn = document.getElementById('kb-stop-btn');
        if (stopBtn) {
            stopBtn.textContent = '✖ 关闭面板';
            stopBtn.style.background = '#666';
            stopBtn.onclick = () => {
                const panel = document.getElementById('kb-progress-panel');
                if (panel) document.body.removeChild(panel);
            };
        }
    }

    // ========== 初始化 ==========
    window.addEventListener('load', () => {
        createStudentIdBox();
        createButtons();
        console.log('✅ 成都理工大学教务工具箱已加载！');
    });

})();
