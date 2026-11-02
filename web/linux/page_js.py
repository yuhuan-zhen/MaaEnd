"""页面侧 JS：状态求值 + 输入策略。

两段都从 MaaEnd#6746（agent/cpp-algo/cloud-webview）移植，保持**逐字一致**——
它们是页面侧逻辑，与 Windows/Linux 无关；以后上游改了只要 diff 这两个字符串。

- ``PAGE_STATE_JS``  ←  ``CloudBridge.cpp`` 的 ``kPageState``
- ``INPUT_POLICY_JS`` ←  ``input_policy.h`` 的 ``kInputPolicy``

改造点只有一个：本文件用 Python raw string 承载，测试用正则从源码里抽出来跑（
和上游 ``page_state.test.mjs`` 一样的做法）。
"""

from __future__ import annotations

# 页面状态求值：一次调用返回结构化状态，决策留给调用方。
# page ∈ ended | startup_error | login | session_busy | queue | starting | stream | landing | loading
PAGE_STATE_JS = r"""
(() => {
    const visible = e => !!(e && e.getClientRects().length && getComputedStyle(e).visibility !== 'hidden');
    const video = [...document.querySelectorAll('video')].find(visible);
    const gameSurface = document.getElementById('WelinkGameVideo');
    const text = document.body?.innerText || '';
    const normalizedText = text.replace(/\s+/g, '');
    const ended = /本次游戏已自动结束|游戏已自动结束/.test(normalizedText);
    const starting = /游戏启动中[，,]?请耐心等待/.test(normalizedText);
    const loginForm = [...document.querySelectorAll('input')].some(e => visible(e) &&
        (e.type === 'password' || /手机号|验证码|手机号码/.test(e.placeholder)));
    const loginPrompt = /扫码登录|扫描二维码|短信登录|密码登录|账号登录|手机号登录/.test(text) || loginForm;
    const userCenterLabel = [...document.querySelectorAll('a,button,span,div')].find(e =>
        visible(e) && e.children.length === 0 && e.textContent.trim() === '用户中心');
    // 只有已登录的个人菜单才会有这个下拉箭头；光有「用户中心」四个字是公开页面。
    const userCenter = userCenterLabel?.closest('li');
    const hasAccountMenu = !!userCenter?.querySelector(':scope > svg');
    const hasLogout = [...document.querySelectorAll('a,button,span,div')].some(e =>
        visible(e) && e.children.length === 0 && e.textContent.trim() === '退出登录');
    const hasLogin = [...document.querySelectorAll('a,button,span,div')].some(e =>
        visible(e) && e.children.length === 0 && /^(登录|立即登录|登 录)$/.test(e.textContent.trim()));
    const startButton = [...document.querySelectorAll('button,a,div,span')].find(e =>
        visible(e) && e.textContent.trim() === '开始游戏' &&
        ![...e.children].some(child => child.textContent.trim() === '开始游戏'));
    const clickTarget = element => {
        if (!element || !visible(element) || element.disabled || element.closest('[aria-disabled="true"]')) return null;
        const rect = element.getBoundingClientRect();
        const x = rect.x + rect.width / 2, y = rect.y + rect.height / 2;
        const hit = document.elementFromPoint(x, y);
        return hit && (element === hit || element.contains(hit) ||
            (hit.contains(element) && hit.textContent.trim() === element.textContent.trim())) ? {x, y} : null;
    };
    const startTarget = clickTarget(startButton);
    const ready = document.readyState === 'complete';
    const videoReady = !ended && !starting && !!video && video.readyState >= 2 && !video.paused &&
        !video.ended && video.videoWidth > 0 && video.videoHeight > 0;
    const authenticated = ready && !loginPrompt && !hasLogin &&
        (hasAccountMenu || hasLogout || videoReady);
    const queue = /正在排队|排队中|前方还有|预计等待/.test(text);
    const startupResourceFailed = !authenticated && !loginPrompt && !video &&
        (window.__maaCloudStartupErrors || []).some(error => error.type === 'resource' && (
            error.source === 'https://web.hycdn.cn/hg_web_sdk/lib/sdk.entry.js' ||
            error.source === 'https://web.hycdn.cn/static/js/umd/react/react@18.3.1.js' ||
            error.source === 'https://web.hycdn.cn/static/js/umd/react-dom/react-dom@18.3.1.js' ||
            /^https:\/\/cloud-game-web-static\.hycdn\.cn\/cloud-game\/prod\/[\w.-]+\.js$/.test(error.source)));
    const busyMessage = '您上次游戏的数据正在火速处理中，请稍后再试';
    const message = [...document.querySelectorAll('div,span,p')].find(e => visible(e) &&
        e.textContent.replace(/\s+/g, '') === busyMessage &&
        ![...e.children].some(child => child.textContent.replace(/\s+/g, '') === busyMessage));
    const sessionBusy = !!message;
    const busyConfirmTarget = (() => {
        // 只在这次官方报错的祖先链里找「知道了」，不碰页面上别处的同类按钮。
        for (let parent = message?.parentElement; parent && parent !== document.body; parent = parent.parentElement) {
            const confirm = [...parent.querySelectorAll('button,a,div,span')].find(e =>
                visible(e) && e.textContent.trim() === '知道了' &&
                ![...e.children].some(child => child.textContent.trim() === '知道了'));
            if (confirm) return clickTarget(confirm);
        }
        return null;
    })();
    return {account: authenticated ? 'signed_in' : (ready && (loginPrompt || hasLogin) ? 'signed_out' : 'unknown'),
        page: ended ? 'ended' : startupResourceFailed ? 'startup_error' : loginPrompt ? 'login' : sessionBusy ? 'session_busy' : queue ? 'queue' : starting ? 'starting' : video ? 'stream' : startButton ? 'landing' : 'loading',
        video_ready: !queue && !sessionBusy && videoReady,
        ended, startup_resource_failed: startupResourceFailed,
        video_width: video?.videoWidth || 0, video_height: video?.videoHeight || 0,
        game_surface: gameSurface?.tagName.toLowerCase() || 'none',
        screen_width: Math.round(screen.width * devicePixelRatio),
        screen_height: Math.round(screen.height * devicePixelRatio),
        viewport_width: innerWidth, viewport_height: innerHeight,
        device_pixel_ratio: devicePixelRatio,
        start_available: !!startTarget, start_target: startTarget,
        session_busy_confirm_target: busyConfirmTarget, document_ready: ready,
        document_epoch: performance.timeOrigin};
})()
"""

# 输入策略：在页面里修掉「自动化输入」这一类问题，而不是在外部加重试。
INPUT_POLICY_JS = r"""
(() => {
    if (window.__maaPolicyInstalled) return 'already';
    window.__maaPolicyInstalled = true;
    // 站点的「画质增强」在有 WebGL2 的 GPU 上会把解码后的 <video> 换成 OffscreenCanvas，
    // 取帧和键盘门控都会失效。只禁 WebGL2 这一个能力，传输方式、硬解、WebGL1、2D 拷贝都还在。
    const getContext = HTMLCanvasElement.prototype.getContext;
    Object.defineProperty(HTMLCanvasElement.prototype, 'getContext', {
        value: function(type, ...args) {
            return type === 'webgl2' ? null : getContext.call(this, type, ...args);
        }, configurable: false, writable: false
    });
    // 启动失败的现场（资源/脚本/未处理的 promise），只记来源，不读表单内容。
    const startupErrors = [];
    Object.defineProperty(window, '__maaCloudStartupErrors', {value: startupErrors});
    window.addEventListener('error', event => {
        if (startupErrors.length >= 20) return;
        if (event.target?.src || event.target?.href) {
            const url = new URL(event.target.src || event.target.href, location.href);
            startupErrors.push({type: 'resource', source: url.origin + url.pathname});
        } else {
            startupErrors.push({type: 'script', name: event.error?.name || 'Error',
                line: event.lineno, column: event.colno});
        }
    }, true);
    window.addEventListener('unhandledrejection', event => {
        if (startupErrors.length < 20) startupErrors.push({type: 'promise', name: event.reason?.name || typeof event.reason});
    });
    window.addEventListener('keydown', event => {
        if (!event.isTrusted) return;
        // 串流 SDK 在 video mouseleave / 窗口 blur 之后会门控 keydown。
        // 在同一个事件里、在它的 document 监听器之前把页面本地状态补回来——
        // 这样两个 RPC 之间没有竞态，也不需要额外输入或桌面焦点。
        const video = document.getElementById('WelinkGameVideo');
        if (video && video.readyState >= 2 && !video.paused) {
            const target = document.getElementById('gamePlayLayer') || video;
            target.dispatchEvent(new MouseEvent('mouseenter', {view: window}));
        }
    }, true);
    window.addEventListener('mousedown', event => {
        if (event.button !== 1) return;
        const target = document.getElementById('gamePlayLayer') || document.getElementById('WelinkGameVideo');
        // Chromium 的中键自动滚屏会吃掉下一次 keydown。保留游戏的中键事件，只压掉浏览器滚动。
        if (target?.contains(event.target)) event.preventDefault();
    }, true);
    // CDP 只能给绝对坐标。把相对位移挂在可信 mousemove 上，视口中心做锚点，
    // 页面读到的 movementX/Y 就是我们要的增量——不用移真实光标，也不会撞到视口边缘。
    let relativeMove = null;
    Object.defineProperty(window, '__maaCloudRelativeMove', {
        value: (dx, dy) => { relativeMove = dx === null ? null : {dx, dy}; return true; },
        configurable: false, writable: false
    });
    window.addEventListener('mousemove', event => {
        if (!relativeMove || !event.isTrusted || event.clientX !== 640 || event.clientY !== 360) return;
        const {dx, dy} = relativeMove;
        relativeMove = null;
        Object.defineProperties(event, {
            movementX: {value: dx}, movementY: {value: dy}
        });
    }, true);
    Object.defineProperty(window, 'focus', {
        value: () => {}, configurable: false, writable: false
    });
    Object.defineProperty(Element.prototype, 'requestPointerLock', {
        value: () => Promise.reject(new DOMException(
            'Desktop pointer capture is disabled in this cloud host.', 'NotAllowedError')),
        configurable: false, writable: false
    });
})();
"""

# 相对移动的锚点：策略脚本里写死 (640,360)，即 1280x720 视口的中心。
RELATIVE_ANCHOR = (640, 360)

# 抹平注入：把「网页外壳」藏掉、把画面铺满视口，让串流画面尽量等于 PC 客户端。
# 目标不是好看，是**让上游那 650 个按 PC 1280x720 标定的模板/颜色直接可用**，
# 从而把覆盖层缩到最小（理想：0 个结构覆盖）。
#
# 2026-11-02 合并：aethersrv 部署侧的 hide_cloud_overlay.py 语义并进来，修掉本版两处漏。
#   1) 延迟角标只藏文本节点本身 → 容器的信号条仍压在按钮图标上（10-29 实测 [1210,666..674] 那 9 行）；
#      现在文本命中后向上 lift 最多两层，把容器一起藏。
#   2) 要求命中元素自己是 fixed/absolute → React 把定位放在容器上、span 是 static，这条分支从未命中；
#      现在不要求自身定位，改用「尺寸 + 可见性 + 文本严格匹配 + lift 上限」做护栏。
FLATTEN_JS = r"""
(() => {
    if (window.__maaFlattenInstalled) return 'already';
    window.__maaFlattenInstalled = true;

    const VERSION = 'linux-2';
    const BALL_SEL = ['[class*="hbU_7F"]', '[class*="e4MbkW"]'];
    const PING_SEL = ['[class*="_gEApb"]', '[class*="K_iy0u"]'];
    // 延迟角标的文本形态。游戏内 UI 是画进视频流的像素，DOM 里出现这种短文本只可能是网页外壳。
    const PING_TEXT = /^\s*\d{1,4}\s*(ms|fps)\s*$/i;

    const CSS = `
    /* 云端悬浮球：容器 e4MbkW / 球体 hbU_7F（2026-10-23 实测） */
    [class*="hbU_7F"], [class*="e4MbkW"] { display: none !important; visibility: hidden !important; }
    /* 网络延迟指示器：容器 _gEApb / 文本 K_iy0u（2026-10-29 实测）。
       CSS Modules 哈希随云前端改版会变，JS 里另有文本 + 几何兜底。 */
    [class*="_gEApb"], [class*="K_iy0u"] { display: none !important; visibility: hidden !important; }
    html, body { overflow: hidden !important; }
    /* 串流画面铺满视口：几何和 PC 客户端 1280x720 对齐，模板不用重裁 */
    #WelinkGameVideo { width: 100vw !important; height: 100vh !important; object-fit: fill !important; }
    #gamePlayLayer, #WelinkGameVideo { touch-action: none !important; user-select: none !important; }
    `;

    function ensureStyle() {
        // 迁移期：2026-10-29 的部署侧脚本用 hermes-hide-overlay 这个 id。先清掉再插自己的，
        // 否则两份 CSS 各写各的，改一处忘一处。
        const stale = document.getElementById('hermes-hide-overlay');
        if (stale && stale.remove) stale.remove();
        if (document.getElementById('maaend-flatten')) return;
        const s = document.createElement('style');
        s.id = 'maaend-flatten';
        s.textContent = CSS;
        (document.head || document.documentElement).appendChild(s);
    }

    const visible = e => !!(e && e.getClientRects && e.getClientRects().length &&
        getComputedStyle(e).visibility !== 'hidden' && getComputedStyle(e).display !== 'none');

    const mark = (e, kind) => { try { if (e.dataset) e.dataset.maaFlatten = kind; } catch (err) {} };

    function hideBall() {
        let n = 0;
        for (const sel of BALL_SEL) {
            for (const e of document.querySelectorAll(sel)) {
                mark(e, 'ball');
                e.style.setProperty('display', 'none', 'important');
                n++;
            }
        }
        return n;
    }

    // class 没出现时的兜底：左上角 20~90px 的 fixed/absolute 小方块就是球
    function hideBallByGeometry() {
        let n = 0;
        for (const e of document.querySelectorAll('div')) {
            const st = getComputedStyle(e);
            if (st.position !== 'fixed' && st.position !== 'absolute') continue;
            const r = e.getBoundingClientRect();
            if (r.width >= 20 && r.width <= 90 && r.height >= 20 && r.height <= 90 &&
                r.left >= -60 && r.left <= 120 && r.top >= -5 && r.top <= 150) {
                mark(e, 'ball-geo');
                e.style.setProperty('display', 'none', 'important');
                n++;
            }
        }
        return n;
    }

    // 祖先判定：自己实现，避免依赖 DOM 的 contains（fake DOM 里没有）
    const containsDeep = (a, b) => {
        for (let n = b; n; n = n.parentElement) if (n === a) return true;
        return false;
    };

    // 文本命中后向上 lift 最多两层，取第一个「尺寸仍像角标/计数条」的祖先。
    // 上限 420x220 保证不会爬到 body / 整页容器上去（那些尺寸远超，直接 break）。
    function liftTarget(e) {
        let target = e;
        for (let i = 0; i < 2 && target.parentElement; i++) {
            const pr = target.parentElement.getBoundingClientRect();
            if (pr && pr.width > 0 && pr.height > 0 && pr.width <= 420 && pr.height <= 220) {
                target = target.parentElement;
            } else {
                break;
            }
        }
        return target;
    }

    // 延迟角标：文本命中 → 藏容器（信号条与数字一起消失）。
    // 2026-10-29 实测：容器 div._gEApb.b9Vf6r [1208,666,40,38] 里装 span.K_iy0u "9ms" 与三根信号条，
    // 只藏 span 时信号条仍压在「开启挑战」按钮右端图标命中框 [1210,649,26,26] 的下 9 行上，
    // WhiteConfirmButtonType1 停在 0.84979（阈值 0.9）；整块藏掉后回到 0.9569。
    function hidePingByText() {
        const hits = [];
        for (const e of document.querySelectorAll('div,span,p,label')) {
            const t = (e.textContent || '').trim();
            if (!PING_TEXT.test(t)) continue;
            if (e.children && e.children.length > 2) continue;   // 子元素太多就是块容器，不是角标
            if (!visible(e)) continue;
            const r = e.getBoundingClientRect();
            if (!r || r.width === 0 || r.height === 0) continue;
            if (r.width > 400 || r.height > 200) continue;       // 太大不像计数条
            hits.push(e);
        }
        // 去重：外层容器的 textContent 往往也是同一个数字（子文本拼接），而 lift 本来就会把容器藏掉。
        // 不过滤祖先的话，同一块浮层会被 lift 两次，甚至爬到页面容器上。
        let n = 0;
        for (const e of hits) {
            if (hits.some(o => o !== e && containsDeep(e, o))) continue;   // 有命中的后代 → 交给后代处理
            const target = liftTarget(e);
            mark(target, 'ping');
            target.style.setProperty('display', 'none', 'important');
            n++;
        }
        return n;
    }

    // 几何兜底：右下角 300x160 内、<=300x140、纯文本 <=12 字的小浮层。
    // 10-29 的容器 [1208,666,40,38] 落在窗口 1280x720 的这块区域里；
    // 游戏内 UI 不在 DOM 里，所以这块区域的 DOM 只可能是网页外壳。
    function hidePingByGeometry() {
        const W = window.innerWidth, H = window.innerHeight;
        let n = 0;
        for (const e of document.querySelectorAll('div,span')) {
            const st = getComputedStyle(e);
            if (st.position !== 'fixed' && st.position !== 'absolute') continue;
            const r = e.getBoundingClientRect();
            if (!r || r.width === 0 || r.height === 0) continue;
            if (r.width > 300 || r.height > 140) continue;
            if (r.left < W - 300 || r.top < H - 160) continue;
            if (((e.textContent || '').trim()).length > 12) continue;
            mark(e, 'ping-geo');
            e.style.setProperty('display', 'none', 'important');
            n++;
        }
        return n;
    }

    function apply() {
        ensureStyle();
        const prev = window.__maaFlatten || {ball: 0, ping: 0, geo: 0, at: 0};
        const ball = hideBall() || hideBallByGeometry();
        const pingText = hidePingByText();
        const geo = pingText ? 0 : hidePingByGeometry();
        const ping = pingText + geo;
        // 记累计值：第二轮以后元素已经是 display:none，单轮计数会回到 0，日志看着像没生效。
        // latency 是 8ec9c8fb2 时代的字段名，保留同值，老日志/老测试不用改。
        window.__maaFlatten = {
            ball: Math.max(prev.ball || 0, ball),
            ping: Math.max(prev.ping || 0, ping),
            latency: Math.max(prev.ping || prev.latency || 0, ping),
            geo: Math.max(prev.geo || 0, geo),
            at: (prev.at || 0) + 1,
            version: VERSION,
        };
        return ball + ping;
    }

    window.__maaFlattenApply = apply;
    apply();
    document.addEventListener('DOMContentLoaded', apply);
    try {
        new MutationObserver(apply).observe(document.documentElement,
            {childList: true, subtree: true, attributes: true, attributeFilter: ['class', 'style']});
    } catch (e) {}
    setInterval(apply, 1000);
})();
"""

# 浮层探测：只读，返回 JSON 字符串（CDP Runtime.evaluate 直接取回）。
# 用途是长期运维的命门——class 哈希随云前端改版就变，`--check` 是 30 秒内判断
# 「选择器失效」还是「真没有浮层」的唯一手段；返回 ping 为空但截图仍有「xx ms」，
# 说明延迟指示器已经改成 canvas 绘制，DOM 方案整体失效，得换图像域兜底。
PROBE_JS = r"""
(() => {
    const VERSION = 'linux-2';
    const PING_TEXT = /^\s*\d{1,4}\s*(ms|fps)\s*$/i;
    const shownOf = e => {
        const st = getComputedStyle(e);
        return st.display !== 'none' && st.visibility !== 'hidden';
    };
    const rectOf = e => {
        const r = e.getBoundingClientRect();
        return {x: Math.round(r.x), y: Math.round(r.y), w: Math.round(r.width), h: Math.round(r.height)};
    };
    const out = {version: VERSION, url: location.href, size: [innerWidth, innerHeight], ball: [], ping: [], geo: []};

    for (const sel of ['[class*="hbU_7F"]', '[class*="e4MbkW"]']) {
        for (const e of document.querySelectorAll(sel)) {
            out.ball.push(Object.assign({cls: String(e.className).slice(0, 60), shown: shownOf(e)}, rectOf(e)));
        }
    }

    // 与 FLATTEN_JS 同一套去重：祖先的 textContent 也等于同一个数字，不能把同一块浮层报两次
    const containsDeep = (a, b) => {
        for (let n = b; n; n = n.parentElement) if (n === a) return true;
        return false;
    };
    const pingHits = [];
    for (const e of document.querySelectorAll('div,span,p,label')) {
        const t = (e.textContent || '').trim();
        if (!PING_TEXT.test(t)) continue;
        if (e.children && e.children.length > 2) continue;
        pingHits.push({e, t});
    }
    for (const {e, t} of pingHits) {
        if (pingHits.some(o => o.e !== e && containsDeep(e, o.e))) continue;
        // 已经被抹平藏掉的元素 rect 全 0、lift 也判不出来，先看祖先上的标记。
        // marker 命中就说明「这条规则已经生效」，lifted 报 -1 表示不再有意义。
        let marked = null;
        for (let n = e; n; n = n.parentElement) {
            if (n.dataset && n.dataset.maaFlatten) { marked = n; break; }
        }
        let target = marked || e;
        let lifted = -1;
        if (!marked) {
            lifted = 0;
            while (lifted < 2 && target.parentElement) {
                const pr = target.parentElement.getBoundingClientRect();
                if (pr.width > 0 && pr.height > 0 && pr.width <= 420 && pr.height <= 220) {
                    target = target.parentElement;
                    lifted++;
                } else {
                    break;
                }
            }
        }
        out.ping.push(Object.assign({
            text: t,
            cls: String(e.className).slice(0, 60),
            tag: e.tagName,
            parentCls: String((e.parentElement && e.parentElement.className) || '').slice(0, 60),
            lifted,
            marker: (marked && marked.dataset && marked.dataset.maaFlatten) || '',
            hiddenByFlatten: !!marked,
            shown: marked ? false : shownOf(target),
        }, rectOf(target)));
    }

    const W = innerWidth, H = innerHeight;
    for (const e of document.querySelectorAll('div,span')) {
        const st = getComputedStyle(e);
        if (st.position !== 'fixed' && st.position !== 'absolute') continue;
        const r = e.getBoundingClientRect();
        if (r.width === 0 || r.height === 0 || r.width > 300 || r.height > 140) continue;
        if (r.left < W - 300 || r.top < H - 160) continue;
        if (((e.textContent || '').trim()).length > 12) continue;
        out.geo.push(Object.assign({cls: String(e.className).slice(0, 60), shown: shownOf(e)}, rectOf(e)));
    }

    return JSON.stringify(out);
})()
"""
