// flatten.test.mjs —— 抹平注入：藏掉网页外壳、铺满串流画面。
//
// 目标：让上游按 PC 1280x720 标的模板/颜色直接可用，从而把覆盖层缩到最小。
// 2026-11-02 起策略升级为 linux-2：延迟角标改成「文本命中 → 向上 lift 容器」，
// 并在测试里固定 10-29 那轮的真实结构（容器 40x38 @1208,666 + 三根信号条 + span "9ms"）。
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../page_js.py", import.meta.url), "utf8");
const script = source.match(/FLATTEN_JS = r"""([\s\S]*?)"""/)?.[1];
assert.ok(script, "没能从 page_js.py 抽出 FLATTEN_JS");
const probeScript = source.match(/PROBE_JS = r"""([\s\S]*?)"""/)?.[1];
assert.ok(probeScript, "没能从 page_js.py 抽出 PROBE_JS");

function el(tag, spec = {}) {
    const node = {
        tagName: tag.toUpperCase(),
        className: spec.className ?? "",
        children: [],
        dataset: {},
        rect: spec.rect ?? {left: 0, top: 0, width: 10, height: 10},
        pos: spec.pos ?? "static",
        hidden: false,
        parentElement: spec.parent ?? null,
        style: {
            setProperty(k, v) {
                this[k] = v;
                node.hidden = k === "display" && v === "none";
            },
        },
        getClientRects() {
            return spec.visible === false ? [] : [{}];
        },
        getBoundingClientRect() {
            const r = this.rect;
            return {left: r.left, top: r.top, width: r.width, height: r.height,
                x: r.left, y: r.top, right: r.left + r.width, bottom: r.top + r.height};
        },
        appendChild(child) {
            this.children.push(child);
            child.parentElement = this;
            return child;
        },
        remove() {
            const p = this.parentElement;
            if (!p) return;
            const i = p.children.indexOf(this);
            if (i >= 0) p.children.splice(i, 1);
            this.parentElement = null;
        },
        addEventListener() {},
    };
    Object.defineProperty(node, "textContent", {
        get() {
            const own = spec.text ?? "";
            if (!this.children.length) return own;
            return this.children.map((c) => c.textContent).join("");
        },
        set(v) {
            spec.text = v;
        },
    });
    for (const c of spec.children ?? []) node.appendChild(c);
    return node;
}

function walk(list, out = []) {
    for (const n of list) {
        out.push(n);
        if (n.children?.length) walk(n.children, out);
    }
    return out;
}

function makeEnv({nodes = [], width = 1280, height = 720, preHead = [], withFlatten = true} = {}) {
    const head = {children: [...preHead], appendChild(n) { this.children.push(n); n.parentElement = this; return n; }};
    for (const n of preHead) n.parentElement = head;

    const document = {
        head,
        documentElement: head,
        createElement(tag) {
            const n = el(tag, {});
            if (tag === "style") {
                n.textContent = "";
                n.id = "";
            }
            return n;
        },
        getElementById(id) {
            for (const s of head.children) if (s.id === id) return s;
            return null;
        },
        querySelectorAll(sel) {
            const parts = sel.split(",").map((s) => s.trim());
            const out = [];
            for (const n of walk(nodes)) {
                for (const p of parts) {
                    if (p.startsWith('[class*="')) {
                        const needle = p.match(/\[class\*="([^"]+)"\]/)[1];
                        if (String(n.className).includes(needle)) { out.push(n); break; }
                    } else if (p.toUpperCase() === n.tagName) { out.push(n); break; }
                }
            }
            return out;
        },
        addEventListener() {},
    };

    const sandbox = {
        document,
        window: {innerWidth: width, innerHeight: height},
        innerWidth: width,
        innerHeight: height,
        location: {href: "https://cloud.example/endfield"},
        getComputedStyle: (e) => ({position: e.pos, visibility: e.hidden ? "hidden" : "visible",
            display: e.hidden ? "none" : "block"}),
        MutationObserver: class { observe() {} },
        setInterval: () => 0,
        JSON,
        console,
    };
    sandbox.window.document = document;
    sandbox.window.__maaFlatten = undefined;
    if (withFlatten) vm.runInNewContext(script, sandbox);
    return {sandbox, head, document};
}

// ── 原有 8 例 ───────────────────────────────────────────────────────────────

test("悬浮球：按 class 前缀直接藏掉", () => {
    const ball = el("div", {className: "hbU_7F abc", pos: "fixed",
        rect: {left: 20, top: 20, width: 56, height: 56}});
    const env = makeEnv({nodes: [ball]});
    assert.equal(ball.hidden, true);
    assert.equal(env.head.children.some((s) => s.id === "maaend-flatten"), true);
});

test("悬浮球：class 还没生成时按几何位置兜底", () => {
    const ball = el("div", {className: "", pos: "fixed",
        rect: {left: 30, top: 30, width: 60, height: 60}});
    makeEnv({nodes: [ball]});
    assert.equal(ball.hidden, true);
});

test("右下角延迟角标被藏掉", () => {
    const latency = el("div", {text: "23 ms", pos: "fixed",
        rect: {left: 1180, top: 690, width: 60, height: 20}});
    makeEnv({nodes: [latency]});
    assert.equal(latency.hidden, true);
});

// 语义变更（2026-11-02）：延迟判定只认「文本 + 尺寸」，不再看屏幕位置。
// 理由：游戏内 UI 是画进视频流的像素，DOM 里出现纯 "xx ms" 只可能是网页外壳；
// 加位置限制反而会在云厂商挪动角标后漏掉（10-29 那版就只在右下 320x220 内找）。
test("「23 ms」不管在页面哪个位置都藏（DOM 里的 ms 只可能是网页外壳）", () => {
    const latency = el("div", {text: "23 ms", pos: "fixed",
        rect: {left: 400, top: 300, width: 60, height: 20}});
    makeEnv({nodes: [latency]});
    assert.equal(latency.hidden, true);
});

test("普通小方块 / 静态定位元素不受影响", () => {
    const staticBox = el("div", {pos: "static", rect: {left: 30, top: 30, width: 60, height: 60}});
    const bigBox = el("div", {pos: "fixed", rect: {left: 30, top: 30, width: 300, height: 60}});
    makeEnv({nodes: [staticBox, bigBox]});
    assert.equal(staticBox.hidden, false);
    assert.equal(bigBox.hidden, false);
});

test("注入的样式把 <video> 铺满视口（几何与 PC 1280x720 对齐）", () => {
    const env = makeEnv();
    const style = env.head.children.find((s) => s.id === "maaend-flatten");
    assert.ok(style, "必须插入 style 标签");
    assert.match(style.textContent, /#WelinkGameVideo\s*{[^}]*width:\s*100vw/);
    assert.match(style.textContent, /object-fit:\s*fill/);
    assert.match(style.textContent, /\[class\*="hbU_7F"\]/);
});

test("重复执行不会插第二份样式", () => {
    const env = makeEnv();
    env.sandbox.window.__maaFlattenApply();
    env.sandbox.window.__maaFlattenApply();
    assert.equal(env.head.children.filter((s) => s.id === "maaend-flatten").length, 1);
});

test("上报统计：__maaFlatten 记录藏了几个", () => {
    const ball = el("div", {className: "e4MbkW", pos: "fixed",
        rect: {left: 20, top: 20, width: 56, height: 56}});
    const latency = el("span", {text: "45ms", pos: "fixed",
        rect: {left: 1200, top: 700, width: 40, height: 18}});
    const env = makeEnv({nodes: [ball, latency]});
    assert.equal(env.sandbox.window.__maaFlatten.ball, 1);
    assert.equal(env.sandbox.window.__maaFlatten.latency, 1);
    assert.equal(env.sandbox.window.__maaFlatten.ping, 1);
    assert.equal(env.sandbox.window.__maaFlatten.version, "linux-2");
});

// ── linux-2 新增：容器 lift、class 失效退路、迁移清理、探测 ────────────────

test("10-29 真实结构：span \"9ms\" 命中后连容器（含三根信号条）一起藏", () => {
    const bar = (h) => el("i", {rect: {left: 1212, top: 668, width: 3, height: h}});
    const span = el("span", {text: "9ms", rect: {left: 1216, top: 689, width: 23, height: 13}});
    const box = el("div", {className: "", pos: "fixed",
        rect: {left: 1208, top: 666, width: 40, height: 38},
        children: [bar(6), bar(9), bar(12), span]});
    const env = makeEnv({nodes: [box]});

    assert.equal(box.hidden, true, "容器必须被藏掉，信号条才会跟着消失");
    assert.equal(span.hidden, false, "藏的是容器，不是单独把 span 摘掉");
    assert.equal(box.dataset.maaFlatten, "ping");
    assert.equal(env.sandbox.window.__maaFlatten.geo, 0, "必须是文本 lift 命中，不能靠几何兜底");
});

test("lift 不会爬到整页容器上：文本在 1280x720 的页面容器里时只藏自己", () => {
    const span = el("span", {text: "9ms", rect: {left: 1216, top: 689, width: 23, height: 13}});
    const page = el("div", {pos: "static", rect: {left: 0, top: 0, width: 1280, height: 720}, children: [span]});
    makeEnv({nodes: [page]});
    assert.equal(span.hidden, true);
    assert.equal(page.hidden, false, "整页容器不能动");
});

test("class 哈希全换掉时走几何兜底：右下角 40x38 小浮层被藏", () => {
    const box = el("div", {className: "zzNEWhash", pos: "fixed",
        rect: {left: 1208, top: 666, width: 40, height: 38}});
    const env = makeEnv({nodes: [box]});
    assert.equal(box.hidden, true);
    assert.equal(env.sandbox.window.__maaFlatten.geo, 1);
    assert.equal(box.dataset.maaFlatten, "ping-geo");
});

test("迁移期清掉部署侧旧 style（hermes-hide-overlay）", () => {
    const stale = el("style", {});
    stale.id = "hermes-hide-overlay";
    const env = makeEnv({preHead: [stale]});
    assert.equal(env.head.children.some((s) => s.id === "hermes-hide-overlay"), false);
    assert.equal(env.head.children.some((s) => s.id === "maaend-flatten"), true);
});

test("PROBE_JS：注入后探测报「已被抹平隐藏」与标记类型", () => {
    const span = el("span", {text: "9ms", rect: {left: 1216, top: 689, width: 23, height: 13}});
    const box = el("div", {pos: "fixed", rect: {left: 1208, top: 666, width: 40, height: 38}, children: [span]});
    const env = makeEnv({nodes: [box]});
    const raw = vm.runInNewContext(probeScript, env.sandbox);
    const out = JSON.parse(raw);
    assert.equal(out.version, "linux-2");
    assert.equal(out.ping.length, 1);
    assert.equal(out.ping[0].text, "9ms");
    assert.equal(out.ping[0].marker, "ping");
    assert.equal(out.ping[0].hiddenByFlatten, true);
    assert.equal(out.ping[0].shown, false, "已经被抹平藏掉的要报 shown=false");
    assert.equal(out.ping[0].lifted, -1, "已被标记时不再计算 lift 层数");
    assert.ok(Array.isArray(out.geo));
});

test("PROBE_JS：未注入时能报出 lift 层数与「还可见」", () => {
    const span = el("span", {text: "9ms", rect: {left: 1216, top: 689, width: 23, height: 13}});
    const box = el("div", {pos: "fixed", rect: {left: 1208, top: 666, width: 40, height: 38}, children: [span]});
    const env = makeEnv({nodes: [box], withFlatten: false});
    const out = JSON.parse(vm.runInNewContext(probeScript, env.sandbox));
    assert.equal(out.ping.length, 1);
    assert.equal(out.ping[0].lifted, 1);
    assert.equal(out.ping[0].marker, "");
    assert.equal(out.ping[0].hiddenByFlatten, false);
    assert.equal(out.ping[0].shown, true);
});
