export function captureMessageScrollPosition(container, threshold = 96) {
  if (!container) return null;

  const containerTop = container.getBoundingClientRect().top;
  const firstVisible = [...container.querySelectorAll(".msg-line[data-message-id]")]
    .find((message) => message.getBoundingClientRect().bottom > containerTop);

  return {
    atLatest: container.scrollHeight - container.clientHeight - container.scrollTop <= threshold,
    scrollTop: container.scrollTop,
    messageId: firstVisible?.getAttribute("data-message-id") || null,
    offset: firstVisible ? firstVisible.getBoundingClientRect().top - containerTop : 0,
  };
}

export function restoreMessageScrollPosition(container, position) {
  if (!container || !position) return;

  if (position.atLatest) {
    container.scrollTop = container.scrollHeight;
    return;
  }

  const anchor = position.messageId
    ? [...container.querySelectorAll(".msg-line[data-message-id]")]
      .find((message) => message.getAttribute("data-message-id") === position.messageId)
    : null;
  if (anchor) {
    const offset = anchor.getBoundingClientRect().top - container.getBoundingClientRect().top;
    container.scrollTop += offset - position.offset;
    return;
  }

  container.scrollTop = Math.max(0, Math.min(position.scrollTop, container.scrollHeight - container.clientHeight));
}

export function scrollMessageContainerToLatest(container) {
  if (container) container.scrollTop = container.scrollHeight;
}
