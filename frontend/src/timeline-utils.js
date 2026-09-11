export function timelineActor(event = {}) {
  const kind = event.actor_type
    || (event.created_by ? "staff" : event.event_type === "message" && event.direction === "inbound" ? "customer" : "system");

  if (kind === "customer") return { kind, label: "Khách hàng" };
  if (kind === "bot") return { kind, label: "Chatbot" };
  if (kind === "staff") {
    return { kind, label: `Nhân viên · ${event.actor_name || event.created_by || "CRM"}` };
  }
  return { kind: "system", label: "Hệ thống" };
}

export function conversationBotStatus(mode) {
  if (mode === "human") {
    return {
      kind: "human",
      label: "Nhân viên đang tiếp quản",
      description: "Chatbot đang tạm dừng để nhân viên xử lý hội thoại này.",
    };
  }
  return {
    kind: "bot",
    label: "Bot đang xử lý",
    description: "Chatbot đang phản hồi tự động cho hội thoại này.",
  };
}
