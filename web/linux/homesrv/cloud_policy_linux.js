// 云·终末地页面策略（Linux/网页端移植版）
// 移植自 MaaEnd CloudShell: scripts/cloud_policy.js（97 行）
// 差异：去掉外壳 IPC 依赖（__maaShellExpect / __maaShellSetForeground）——
//       Linux 侧所有输入都来自 CDP，没有"用户物理鼠标"需要区分。
//
// 五条策略：
//   ① 无按键移动时 movementX/Y 归零 —— 定位移动不带动镜头（指针归位的前置条件）
//   ② keydown 时给视频补发 mouseenter —— 鼠标离开视频后 SDK 会停止发送按键
//   ③ 覆盖 document.hidden / visibilityState —— 防止 SDK 判定页面隐藏而停发心跳
//   ④ 拒绝 requestPointerLock —— 锁定后所有移动都转镜头，且光标消失
//   ⑤ 禁用 WebGL2 —— 画质增强层的像素随显卡而变，会破坏模板匹配
(() => {
  if (window.__hermesCloudPolicy) return "already";

  // ③ 页面永不"隐藏"
  for (const [name, value] of [["hidden", false], ["visibilityState", "visible"]]) {
    try {
      Object.defineProperty(Document.prototype, name, { configurable: true, get: () => value });
    } catch (e) {}
  }

  // ⑤ 禁用 WebGL2（webgl/2d 保留）
  try {
    const getContext = HTMLCanvasElement.prototype.getContext;
    HTMLCanvasElement.prototype.getContext = function (type, ...args) {
      return String(type).toLowerCase() === "webgl2" ? null : getContext.call(this, type, ...args);
    };
  } catch (e) {}

  // ① 所有无按键的移动事件 movement 归零
  const kMoveTypes = new Set(["mousemove", "pointermove", "pointerrawupdate"]);
  for (const type of kMoveTypes) {
    window.addEventListener(
      type,
      (event) => {
        if (!event.isTrusted) return;
        if (event.buttons) return;          // 拖动保留位移（转视角要用）
        try {
          Object.defineProperties(event, { movementX: { value: 0 }, movementY: { value: 0 } });
        } catch (e) {}
      },
      { capture: true, passive: false },
    );
  }

  // ④ 拒绝指针锁定（必须在严格模式下也可写，见原版注释）
  try {
    const native = Element.prototype.requestPointerLock;
    Element.prototype.requestPointerLock = function () {
      return Promise.reject(
        new DOMException("Pointer lock is not available after automated input.", "NotAllowedError"),
      );
    };
    Element.prototype.__hermesNativePointerLock = native;
  } catch (e) {}

  // ② keydown 时给视频补发 mouseenter，唤醒 SDK 的按键发送
  window.addEventListener(
    "keydown",
    (event) => {
      if (!event.isTrusted) return;
      const video = document.getElementById("WelinkGameVideo");
      if (video && video.readyState >= 2 && !video.paused) {
        const target = document.getElementById("gamePlayLayer") || video;
        try {
          target.dispatchEvent(new MouseEvent("mouseenter", { view: window }));
        } catch (e) {}
      }
    },
    true,
  );

  window.__hermesCloudPolicy = {
    installed: true,
    t: Date.now(),
    version: "linux-1",
  };
  return "installed";
})();
