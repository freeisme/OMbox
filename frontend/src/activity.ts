/**
 * 用户活动跟踪：会话的“无操作超时”以真实操作为准。
 *
 * 服务端按最后一次请求判定空闲，因此页面里的定时轮询（如消息未读数）必须
 * 在用户已经空闲时停下来，否则轮询会不断刷新会话，超时永远不会触发。
 */

let lastActivityAt = Date.now();
let installed = false;

const ACTIVITY_EVENTS = ["pointerdown", "keydown", "wheel", "touchstart"] as const;

/** 记录一次用户操作。 */
export function markActivity(): void {
  lastActivityAt = Date.now();
}

/** 距上次用户操作的毫秒数。 */
export function idleMs(): number {
  return Date.now() - lastActivityAt;
}

/** 用户是否已经空闲超过给定分钟数；分钟数缺失时不判定为空闲。 */
export function isIdleBeyond(minutes: number | undefined): boolean {
  if (!minutes || minutes <= 0) return false;
  return idleMs() > minutes * 60_000;
}

/** 挂载全局活动监听（只挂一次）。 */
export function installActivityTracking(): void {
  if (installed) return;
  installed = true;
  ACTIVITY_EVENTS.forEach((name) => {
    window.addEventListener(name, markActivity, { passive: true });
  });
  document.addEventListener("visibilitychange", () => {
    // 切回页面也算一次活动：用户回来了
    if (document.visibilityState === "visible") markActivity();
  });
}
