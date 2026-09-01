/* Web Push 接收：只负责弹系统通知与点击回跳，不缓存任何资源 */
self.addEventListener("push", (e) => {
  let d = {};
  try { d = e.data ? e.data.json() : {}; } catch { /* 非 JSON 负载走默认文案 */ }
  e.waitUntil(self.registration.showNotification(d.title || "每日提醒", {
    body: d.body || "今天的学习目标还没完成",
    icon: "/favicon.png",
    data: { url: d.url || "/" },
  }));
});

self.addEventListener("notificationclick", (e) => {
  e.notification.close();
  const url = (e.notification.data && e.notification.data.url) || "/";
  e.waitUntil(clients.matchAll({ type: "window", includeUncontrolled: true }).then((wins) => {
    const hit = wins.find((w) => w.url.startsWith(self.location.origin));
    if (hit) { hit.focus(); hit.navigate(url); return; }
    return clients.openWindow(url);
  }));
});
