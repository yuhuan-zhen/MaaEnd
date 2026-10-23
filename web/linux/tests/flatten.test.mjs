// flatten.test.mjs —— 抹平注入：藏掉网页外壳、铺满串流画面。
//
// 目标：让上游按 PC 1280x720 标的模板/颜色直接可用，从而把覆盖层缩到最小。
import assert from "node:assert/strict";
import {readFileSync} from "node:fs";
import test from "node:test";
import vm from "node:vm";

const source = readFileSync(new URL("../page_js.py", import.meta.url), "utf8");
const script = source.match(/FLATTEN_JS = r"""([\s\S]*?)"""/)?.[1];
assert.ok(script, "没能从 page_js.py 抽出 FLATTEN_JS");

function el(tag, spec = {}) {
    const node = {
        tagName: tag.toUpperCase(),
        className: spec.className ?? "",
        textContent: spec.text ?? "",
        children: spec.children ?? [],
        rect: spec.rect ?? {left: 0, top: 0, width: 10, height: 10},
        pos: spec.pos ?? "static",
        hidden: false,
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
            return this.rect;
        },
    };
    return node;
}

function makeEnv({nodes = [], width = 1280, height = 720} = {}) {
    const head = {children: [], appendChild(n) { this.children.push(n); }};
    const tags = {};

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
            for (const n of allNodes()) {
                for (const p of parts) {
                    if (p.startsWith("[class*=")) {
                        const needle = p.match(/\[class\*="([^"]+)"\]/)[1];
                        if (String(n.className).includes(needle)) { out.push(n); break; }
                    } else if (p.toUpperCase() === n.tagName) { out.push(n); break; }
                }
            }
            return out;
        },
        addEventListener() {},
    };
    function allNodes() {
        return nodes;
    }

    const sandbox = {
        document,
        window: {innerWidth: width, innerHeight: height},
        innerWidth: width,
        innerHeight: height,
        getComputedStyle: (e) => ({position: e.pos, visibility: e.hidden ? "hidden" : "visible",
            display: e.hidden ? "none" : "block"}),
        MutationObserver: class { observe() {} },
        setInterval: () => 0,
        documentElement: head,
        console,
    };
    sandbox.window.document = document;
    sandbox.window.__maaFlatten = undefined;
    vm.runInNewContext(script, sandbox);
    return {sandbox, head, document};
}

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

test("「23 ms」出现在页面中间 → 不藏（可能是游戏内元素）", () => {
    const latency = el("div", {text: "23 ms", pos: "fixed",
        rect: {left: 400, top: 300, width: 60, height: 20}});
    makeEnv({nodes: [latency]});
    assert.equal(latency.hidden, false);
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
});
