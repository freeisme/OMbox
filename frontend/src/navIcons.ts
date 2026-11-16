/** 侧边栏图标：内联 SVG path（24x24 视图框，描边风格）。
 *  故意不引入图标库：侧栏是首屏资源，16 个 path 只有几 KB，也不增加依赖。 */
export const NAV_ICON_PATHS: Record<string, string> = {
  dashboard: "M4 4h7v7H4zM13 4h7v4h-7zM13 10h7v10h-7zM4 13h7v7H4z",
  computers: "M4 6h16v9H4zM2 18h20",
  employees: "M9 11a3 3 0 100-6 3 3 0 000 6zM3 20c0-3 2.7-5 6-5s6 2 6 5M17.5 11a2.5 2.5 0 100-5 2.5 2.5 0 000 5M16 20c0-2 .8-3.6 2-4.5",
  leftEmployees: "M8 11a3 3 0 100-6 3 3 0 000 6zM2 20c0-3 2.7-5 6-5 1.2 0 2.2.3 3.1.8M15 18h6M18 15l3 3-3 3",
  organizations: "M9 3h6v4H9zM3 16h6v4H3zM15 16h6v4h-6zM12 7v4M6 16v-3h12v3",
  datacenter: "M4 4h16v6H4zM4 14h16v6H4zM7 7h2M7 17h2",
  inspection: "M8 4h8v3H8zM5 7h14v14H5zM9 13l2 2 4-4",
  meetingRooms: "M4 4h16v12H4zM9 20h6M12 16v4",
  lineguard: "M7 7h10v10H7zM4 10h3M4 14h3M17 10h3M17 14h3M10 4v3M14 4v3M10 17v3M14 17v3",
  lineguardDevices: "M5 5h14v10H5zM9 19h6M12 15v4M8 9h8M8 12h5",
  lineguardAlerts: "M12 4a5 5 0 00-5 5v4l-2 3h14l-2-3V9a5 5 0 00-5-5zM10 19a2 2 0 004 0",
  inventoryHub: "M3 8l9-4 9 4v8l-9 4-9-4zM3 8l9 4 9-4M12 12v8",
  dictionary: "M6 4h8a3 3 0 013 3v13H9a3 3 0 01-3-3zM9 8h5M9 12h5",
  tickets: "M4 7h16v3a2 2 0 000 4v3H4v-3a2 2 0 000-4zM11 7v10",
  audit: "M8 6h12M8 12h12M8 18h12M4 6h.01M4 12h.01M4 18h.01",
  serviceManagement: "M12 9a3 3 0 100 6 3 3 0 000-6zM12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6L7 7M17 17l1.4 1.4M18.4 5.6L17 7M7 17l-1.4 1.4",
  governance: "M4 12a8 8 0 0113.6-5.7M20 12a8 8 0 01-13.6 5.7M17 3v4h-4M7 21v-4h4",
};

/** 未知页面用的兜底图标（一个圆点方框），避免菜单缺图标导致对齐错位。 */
export const NAV_ICON_FALLBACK = "M5 5h14v14H5zM9 12h6";
