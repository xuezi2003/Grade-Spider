// ==UserScript==
// @name         成都理工大学学号批量获取工具
// @namespace    http://tampermonkey.net/
// @version      1.0
// @description  在课表查询页面批量获取学号并支持导出
// @author       Your Name
// @match        https://jw.cdut.edu.cn/jsxsd/xskb/xsqtkb.do*
// @grant        none
// @run-at       document-end
// ==/UserScript==

(function() {
    'use strict';

    let allStudents = [];

    // 创建悬浮框
    function createFloatingBox() {
        const floatingBox = document.createElement('div');
        floatingBox.id = 'student-ids-box';
        floatingBox.innerHTML = `
            <div style="
                position: fixed;
                top: 100px;
                right: 20px;
                width: 350px;
                max-height: 500px;
                background: white;
                border: 2px solid #4CAF50;
                border-radius: 8px;
                box-shadow: 0 4px 8px rgba(0,0,0,0.2);
                z-index: 99999;
                display: none;
                font-family: Arial, sans-serif;
            ">
                <div style="
                    background: #4CAF50;
                    color: white;
                    padding: 12px;
                    border-radius: 6px 6px 0 0;
                    display: flex;
                    justify-content: space-between;
                    align-items: center;
                ">
                    <span style="font-weight: bold; font-size: 16px;">📋 学号列表</span>
                    <button id="close-box" style="
                        background: none;
                        border: none;
                        color: white;
                        font-size: 20px;
                        cursor: pointer;
                        padding: 0;
                        width: 24px;
                        height: 24px;
                    ">×</button>
                </div>
                <div style="padding: 15px;">
                    <div style="margin-bottom: 10px; color: #666; font-size: 14px;">
                        共获取 <span id="student-count" style="color: #4CAF50; font-weight: bold;">0</span> 个学号
                    </div>
                    <div id="filter-info"></div>
                    <div id="student-list" style="
                        max-height: 300px;
                        overflow-y: auto;
                        border: 1px solid #ddd;
                        border-radius: 4px;
                        padding: 10px;
                        background: #f9f9f9;
                        margin-bottom: 12px;
                        font-size: 13px;
                        line-height: 1.6;
                    "></div>
                    <button id="download-btn" style="
                        width: 100%;
                        padding: 10px;
                        background: #4CAF50;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        font-size: 14px;
                        font-weight: bold;
                        transition: background 0.3s;
                    " onmouseover="this.style.background='#45a049'"
                       onmouseout="this.style.background='#4CAF50'">
                        ⬇️ 下载为TXT文件
                    </button>
                    <button id="copy-btn" style="
                        width: 100%;
                        padding: 10px;
                        background: #2196F3;
                        color: white;
                        border: none;
                        border-radius: 4px;
                        cursor: pointer;
                        font-size: 14px;
                        font-weight: bold;
                        margin-top: 8px;
                        transition: background 0.3s;
                    " onmouseover="this.style.background='#0b7dda'"
                       onmouseout="this.style.background='#2196F3'">
                        📋 复制学号列表
                    </button>
                </div>
            </div>
        `;
        document.body.appendChild(floatingBox);

        // 绑定关闭按钮
        document.getElementById('close-box').onclick = () => {
            floatingBox.querySelector('div').style.display = 'none';
        };

        // 绑定下载按钮
        document.getElementById('download-btn').onclick = downloadStudentIds;

        // 绑定复制按钮
        document.getElementById('copy-btn').onclick = copyStudentIds;
    }

    // 创建获取按钮
    function createFetchButton() {
        const button = document.createElement('button');
        button.innerHTML = '🎯 批量获取学号';
        button.style.cssText = `
            position: fixed;
            top: 20px;
            right: 20px;
            padding: 12px 24px;
            background: linear-gradient(135deg, #667eea 0%, #764ba2 100%);
            color: white;
            border: none;
            border-radius: 6px;
            cursor: pointer;
            font-size: 14px;
            font-weight: bold;
            box-shadow: 0 4px 6px rgba(0,0,0,0.1);
            z-index: 99999;
            transition: all 0.3s;
        `;

        button.onmouseover = () => {
            button.style.transform = 'translateY(-2px)';
            button.style.boxShadow = '0 6px 12px rgba(0,0,0,0.15)';
        };

        button.onmouseout = () => {
            button.style.transform = 'translateY(0)';
            button.style.boxShadow = '0 4px 6px rgba(0,0,0,0.1)';
        };

        button.onclick = fetchAllStudents;
        document.body.appendChild(button);
    }

    // 批量获取学号
    async function fetchAllStudents() {
        // 创建自定义对话框
        const dialog = document.createElement('div');
        dialog.innerHTML = `
            <div style="
                position: fixed;
                top: 0;
                left: 0;
                right: 0;
                bottom: 0;
                background: rgba(0,0,0,0.5);
                z-index: 999998;
                display: flex;
                align-items: center;
                justify-content: center;
            " id="custom-dialog">
                <div style="
                    background: white;
                    padding: 30px;
                    border-radius: 10px;
                    box-shadow: 0 4px 20px rgba(0,0,0,0.3);
                    min-width: 400px;
                ">
                    <h3 style="margin: 0 0 20px 0; color: #333; font-size: 18px;">🔍 批量获取学号</h3>
                    <div style="margin-bottom: 20px;">
                        <label style="display: block; margin-bottom: 8px; color: #666; font-size: 14px;">
                            搜索关键词：
                        </label>
                        <input type="text" id="keyword-input" value="2022" style="
                            width: 100%;
                            padding: 10px;
                            border: 1px solid #ddd;
                            border-radius: 4px;
                            font-size: 14px;
                            box-sizing: border-box;
                        " placeholder="请输入关键词，如：2022、2021等">
                    </div>
                    <div style="margin-bottom: 25px;">
                        <label style="display: flex; align-items: center; cursor: pointer; font-size: 14px; color: #333;">
                            <input type="checkbox" id="start-with-checkbox" style="
                                width: 18px;
                                height: 18px;
                                margin-right: 8px;
                                cursor: pointer;
                            ">
                            <span>只获取以关键词<strong>开头</strong>的学号</span>
                        </label>
                        <div style="margin-left: 26px; margin-top: 5px; font-size: 12px; color: #999;">
                            例如：搜索"2022"时，只匹配"2022xxxxx"，不匹配"200709020222"
                        </div>
                    </div>
                    <div style="display: flex; gap: 10px;">
                        <button id="confirm-btn" style="
                            flex: 1;
                            padding: 12px;
                            background: #4CAF50;
                            color: white;
                            border: none;
                            border-radius: 4px;
                            cursor: pointer;
                            font-size: 14px;
                            font-weight: bold;
                        ">确定</button>
                        <button id="cancel-btn" style="
                            flex: 1;
                            padding: 12px;
                            background: #999;
                            color: white;
                            border: none;
                            border-radius: 4px;
                            cursor: pointer;
                            font-size: 14px;
                            font-weight: bold;
                        ">取消</button>
                    </div>
                </div>
            </div>
        `;
        document.body.appendChild(dialog);

        // 等待用户输入
        const result = await new Promise((resolve) => {
            document.getElementById('confirm-btn').onclick = () => {
                const keyword = document.getElementById('keyword-input').value.trim();
                const startWith = document.getElementById('start-with-checkbox').checked;
                document.body.removeChild(dialog);
                resolve({ keyword, startWith });
            };
            document.getElementById('cancel-btn').onclick = () => {
                document.body.removeChild(dialog);
                resolve(null);
            };
            // 按Enter键确认
            document.getElementById('keyword-input').onkeypress = (e) => {
                if (e.key === 'Enter') {
                    document.getElementById('confirm-btn').click();
                }
            };
        });

        if (!result || !result.keyword) return;

        const { keyword, startWith } = result;

        // 显示加载提示
        const loadingDiv = document.createElement('div');
        loadingDiv.innerHTML = `
            <div style="
                position: fixed;
                top: 50%;
                left: 50%;
                transform: translate(-50%, -50%);
                background: white;
                padding: 30px 50px;
                border-radius: 10px;
                box-shadow: 0 4px 20px rgba(0,0,0,0.3);
                z-index: 999999;
                text-align: center;
            ">
                <div style="font-size: 18px; margin-bottom: 15px;">🔍 正在获取学号...</div>
                <div style="color: #666;">请稍候</div>
            </div>
        `;
        document.body.appendChild(loadingDiv);

        try {
            // 发送请求
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
                // 根据复选框过滤结果
                if (startWith) {
                    allStudents = data.list.filter(item => item.xh.startsWith(keyword));
                    if (allStudents.length === 0) {
                        alert(`未找到以"${keyword}"开头的学号！\n服务器返回了 ${data.list.length} 个匹配结果，但都不是以"${keyword}"开头。`);
                        document.body.removeChild(loadingDiv);
                        return;
                    }
                } else {
                    allStudents = data.list;
                }

                showStudentIds(keyword, startWith);
                document.body.removeChild(loadingDiv);
            } else {
                alert('未找到匹配的学号！');
                document.body.removeChild(loadingDiv);
            }
        } catch (error) {
            console.error('获取学号失败:', error);
            alert('获取学号失败：' + error.message);
            document.body.removeChild(loadingDiv);
        }
    }

    // 显示学号列表
    function showStudentIds(keyword = '', startWith = false) {
        const box = document.getElementById('student-ids-box').querySelector('div');
        const listDiv = document.getElementById('student-list');
        const countSpan = document.getElementById('student-count');

        // 更新数量和过滤信息
        countSpan.textContent = allStudents.length;

        // 如果启用了过滤，显示过滤信息
        const filterInfo = document.getElementById('filter-info');
        if (filterInfo) {
            if (startWith && keyword) {
                filterInfo.innerHTML = `<div style="
                    background: #e3f2fd;
                    border-left: 4px solid #2196F3;
                    padding: 8px 12px;
                    margin-bottom: 10px;
                    border-radius: 4px;
                    font-size: 13px;
                    color: #1976D2;
                ">
                    🔍 已过滤：只显示以"<strong>${keyword}</strong>"开头的学号
                </div>`;
            } else {
                filterInfo.innerHTML = '';
            }
        }

        // 生成学号列表HTML
        const html = allStudents.map((item, index) => {
            return `<div style="padding: 4px 0; border-bottom: 1px solid #eee;">
                <span style="color: #999; margin-right: 8px;">${index + 1}.</span>
                <span style="color: #333; font-weight: 500;">${item.xh}</span>
                <span style="color: #666; margin-left: 8px; font-size: 12px;">${item.xsmc}</span>
            </div>`;
        }).join('');

        listDiv.innerHTML = html;
        box.style.display = 'block';
    }

    // 下载学号为TXT文件
    function downloadStudentIds() {
        if (allStudents.length === 0) {
            alert('没有学号可以下载！');
            return;
        }

        // 生成学号文本（每行一个）
        const content = allStudents.map(item => item.xh).join('\n');

        // 创建Blob
        const blob = new Blob([content], { type: 'text/plain;charset=utf-8' });

        // 创建下载链接
        const url = URL.createObjectURL(blob);
        const a = document.createElement('a');
        a.href = url;
        a.download = `学号列表_${new Date().toISOString().slice(0,10)}.txt`;

        // 触发下载
        document.body.appendChild(a);
        a.click();
        document.body.removeChild(a);
        URL.revokeObjectURL(url);

        // 显示成功提示
        showToast('✅ 下载成功！');
    }

    // 复制学号列表
    function copyStudentIds() {
        if (allStudents.length === 0) {
            alert('没有学号可以复制！');
            return;
        }

        const content = allStudents.map(item => item.xh).join('\n');

        // 使用Clipboard API复制
        navigator.clipboard.writeText(content).then(() => {
            showToast('✅ 已复制到剪贴板！');
        }).catch(() => {
            // 降级方案
            const textarea = document.createElement('textarea');
            textarea.value = content;
            document.body.appendChild(textarea);
            textarea.select();
            document.execCommand('copy');
            document.body.removeChild(textarea);
            showToast('✅ 已复制到剪贴板！');
        });
    }

    // 显示提示信息
    function showToast(message) {
        const toast = document.createElement('div');
        toast.textContent = message;
        toast.style.cssText = `
            position: fixed;
            top: 50%;
            left: 50%;
            transform: translate(-50%, -50%);
            background: rgba(0, 0, 0, 0.8);
            color: white;
            padding: 15px 30px;
            border-radius: 8px;
            font-size: 14px;
            z-index: 9999999;
            animation: fadeInOut 2s;
        `;

        // 添加动画
        const style = document.createElement('style');
        style.textContent = `
            @keyframes fadeInOut {
                0% { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
                20% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
                80% { opacity: 1; transform: translate(-50%, -50%) scale(1); }
                100% { opacity: 0; transform: translate(-50%, -50%) scale(0.9); }
            }
        `;
        document.head.appendChild(style);

        document.body.appendChild(toast);
        setTimeout(() => {
            document.body.removeChild(toast);
        }, 2000);
    }

    // 初始化
    window.addEventListener('load', () => {
        createFloatingBox();
        createFetchButton();
        console.log('✅ 学号批量获取工具已加载！');
    });

})();
