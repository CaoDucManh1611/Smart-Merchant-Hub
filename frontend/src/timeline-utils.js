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
