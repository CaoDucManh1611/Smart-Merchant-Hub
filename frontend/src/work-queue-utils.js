const finishedTicketStatuses = new Set(["resolved", "closed"]);
const finishedConversationStatuses = new Set(["resolved", "closed"]);
const finishedAppointmentStatuses = new Set(["completed", "cancelled", "no_show"]);

export function workQueueItems({ tickets = [], conversations = [], appointments = [], quotes = [], documents = [], runs = {} }, now = new Date()) {
  const today = now.getTime();
  const upcomingEnd = today + 7 * 24 * 60 * 60 * 1000;
  const isValidTime = (value) => value != null && value !== "" && Number.isFinite(new Date(value).getTime());

  return {
    overdue: tickets.filter((item) => !finishedTicketStatuses.has(item.status)
      && isValidTime(item.sla_due_at) && new Date(item.sla_due_at).getTime() < today)
      .map((item) => ({ kind: "ticket", id: item.id, title: item.title || `#${item.id}`, time: item.sla_due_at })),
    unassigned: conversations.filter((item) => !item.assigned_user_id
      && !finishedConversationStatuses.has(item.status))
      .map((item) => ({ kind: "conversation", id: item.conversation_id, title: item.customer_name || `#${item.conversation_id}`, time: item.updated_at, record: item })),
    appointments: appointments.filter((item) => !finishedAppointmentStatuses.has(item.status)
      && isValidTime(item.starts_at) && new Date(item.starts_at).getTime() >= today
      && new Date(item.starts_at).getTime() <= upcomingEnd)
      .map((item) => ({ kind: "appointment", id: item.id, title: item.customer_name || `#${item.id}`, time: item.starts_at })),
    quotes: quotes.filter((item) => item.status === "sent")
      .map((item) => ({ kind: "quote", id: item.id, title: item.title || item.quote_number || `#${item.id}`, time: item.valid_until })),
    documents: documents.filter((item) => item.status === "failed" || runs[item.id]?.status === "failed")
      .map((item) => ({ kind: "document", id: item.id, title: item.filename || `#${item.id}`, time: item.uploaded_at })),
  };
}
