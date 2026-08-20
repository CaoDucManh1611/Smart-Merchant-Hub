<script setup>
import {
  computed,
  onMounted,
  onUnmounted,
  ref,
  nextTick,
} from "vue";

import "./style.css";
import logoUrl from "./assets/lunari-logo.jpg";

const API_BASE = "http://127.0.0.1:8000/api";


/* =========================================================
   STATE
========================================================= */

const conversations = ref([]);
const messages = ref([]);

const selectedId = ref(null);

const activeFilter = ref("all");

const search = ref("");
const draft = ref("");

const loading = ref(false);
const sending = ref(false);
const sendingImage = ref(false);

const error = ref("");

/* IMAGE */

const imageFile = ref(null);
const imagePreview = ref("");
const fileInput = ref(null);

let pollingTimer = null;
let socket = null;
let reconnectTimer = null;

/* RAG & TAB STATE */
const currentTab = ref("inbox"); // 'inbox' | 'documents' | 'rag_chat'

const documents = ref([]);
const docsLoading = ref(false);
const docUploading = ref(false);
const docUploadError = ref("");
const docFileInput = ref(null);
let docPollingTimer = null;

const ragMessages = ref([
  {
    role: "assistant",
    content: "Xin chào! Tôi là trợ lý AI RAG. Bạn có thể đặt câu hỏi để tôi tra cứu thông tin từ Kho tri thức của cửa hàng.",
    sources: [],
  }
]);
const ragQuery = ref("");
const ragTopK = ref(5);
const ragSending = ref(false);
const autoReplyEnabled = ref(false);
const ragChatBox = ref(null);

const metaStatus = ref({
  connected: false,
  facebook_page_id: "",
  facebook_page_name: "",
  instagram_account_id: "",
  subscription_status: "",
});
const metaLoading = ref(false);
const metaNotice = ref("");


/* META OAUTH */
async function fetchMetaStatus() {
  try {
    const res = await fetch(`${API_BASE}/oauth/meta/status`);
    if (res.ok) metaStatus.value = await res.json();
  } catch (e) {
    console.error("Fetch Meta OAuth status error:", e);
  }
}

function connectMeta() {
  window.location.href = `${API_BASE}/oauth/meta/start`;
}

function openSettings() {
  currentTab.value = "settings";
  void fetchMetaStatus();
}

async function disconnectMeta() {
  if (!confirm("Ngắt kết nối Facebook/Instagram khỏi hệ thống?")) return;
  metaLoading.value = true;
  try {
    const res = await fetch(`${API_BASE}/oauth/meta/disconnect`, {
      method: "DELETE",
    });
    if (res.ok) {
      metaStatus.value = { connected: false };
      metaNotice.value = "Đã ngắt kết nối Meta.";
    }
  } catch (e) {
    metaNotice.value = "Không thể ngắt kết nối Meta.";
  } finally {
    metaLoading.value = false;
  }
}


/* RAG DOCUMENTS METHODS */
async function fetchDocuments() {
  docsLoading.value = true;
  try {
    const res = await fetch(`${API_BASE}/documents`);
    if (res.ok) {
      const data = await res.json();
      documents.value = data.documents || [];
      const hasProcessing = documents.value.some(
        d => d.status === "pending" || d.status === "processing"
      );
      if (hasProcessing && !docPollingTimer) {
        docPollingTimer = setInterval(fetchDocuments, 3000);
      } else if (!hasProcessing && docPollingTimer) {
        clearInterval(docPollingTimer);
        docPollingTimer = null;
      }
    }
  } catch (err) {
    console.error("Fetch documents error:", err);
  } finally {
    docsLoading.value = false;
  }
}

async function uploadDocumentFile(file) {
  if (!file) return;
  docUploading.value = true;
  docUploadError.value = "";
  try {
    const formData = new FormData();
    formData.append("file", file);
    const res = await fetch(`${API_BASE}/documents/upload`, {
      method: "POST",
      body: formData,
    });
    if (!res.ok) {
      let errText = await res.text();
      try {
        const errJson = JSON.parse(errText);
        errText = errJson.detail || errText;
      } catch {}
      throw new Error(errText);
    }
    await fetchDocuments();
  } catch (err) {
    docUploadError.value = err.message || "Upload tài liệu thất bại";
  } finally {
    docUploading.value = false;
    if (docFileInput.value) docFileInput.value.value = "";
  }
}

function handleDocFileSelect(e) {
  const file = e.target.files?.[0];
  if (file) uploadDocumentFile(file);
}

function handleDocDrop(e) {
  e.preventDefault();
  const file = e.dataTransfer?.files?.[0];
  if (file) uploadDocumentFile(file);
}

async function deleteDoc(docId) {
  if (!confirm("Bạn có chắc muốn xóa tài liệu này khỏi Kho tri thức?")) return;
  try {
    const res = await fetch(`${API_BASE}/documents/${docId}`, {
      method: "DELETE",
    });
    if (res.ok) {
      documents.value = documents.value.filter(d => d.id !== docId);
    }
  } catch (err) {
    console.error("Delete doc error:", err);
  }
}

function formatFileSize(bytes) {
  if (!bytes) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}


/* RAG CHAT PLAYGROUND METHODS */
async function fetchAutoReplySetting() {
  try {
    const res = await fetch(`${API_BASE}/conversations/auto-reply-status`);
    if (res.ok) {
      const data = await res.json();
      autoReplyEnabled.value = Boolean(data.auto_reply_enabled);
    }
  } catch (e) {
    console.error("Fetch auto reply error:", e);
  }
}

async function toggleAutoReply() {
  try {
    const nextState = !autoReplyEnabled.value;
    const res = await fetch(`${API_BASE}/conversations/auto-reply-status`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ auto_reply_enabled: nextState }),
    });
    if (res.ok) {
      const data = await res.json();
      autoReplyEnabled.value = Boolean(data.auto_reply_enabled);
    }
  } catch (e) {
    console.error("Toggle auto reply error:", e);
  }
}

async function sendRagQuery(presetText = null) {
  const query = (presetText || ragQuery.value).trim();
  if (!query || ragSending.value) return;

  const conversationHistory = ragMessages.value
    .filter(m => m.content && !m.loading)
    .slice(-6)
    .map(m => ({ role: m.role, content: m.content }));

  ragQuery.value = "";
  ragMessages.value.push({
    role: "user",
    content: query,
  });

  const assistantMsg = {
    role: "assistant",
    content: "",
    sources: [],
    loading: true,
  };
  ragMessages.value.push(assistantMsg);
  ragSending.value = true;

  await nextTick();
  scrollRagChatToBottom();

  try {
    const response = await fetch(`${API_BASE}/chat/stream`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        query: query,
        top_k: Number(ragTopK.value) || 5,
        conversation_history: conversationHistory,
      }),
    });

    if (!response.ok) {
      throw new Error(await response.text());
    }

    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    assistantMsg.loading = false;

    while (true) {
      const { done, value } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() || "";

      for (const line of lines) {
        const trimmed = line.trim();
        if (trimmed.startsWith("data: ")) {
          const jsonStr = trimmed.slice(6).trim();
          if (!jsonStr) continue;
          try {
            const data = JSON.parse(jsonStr);
            if (data.type === "sources") {
              assistantMsg.sources = data.sources || [];
            } else if (data.type === "chunk") {
              assistantMsg.content += data.content || "";
              scrollRagChatToBottom();
            } else if (data.type === "error") {
              assistantMsg.content += `\n[Lỗi: ${data.message}]`;
            }
          } catch (e) {
            console.error("SSE parse error", e);
          }
        }
      }
    }
  } catch (err) {
    assistantMsg.loading = false;
    assistantMsg.content = `❌ Trả lời thất bại: ${err.message || err}`;
  } finally {
    ragSending.value = false;
    scrollRagChatToBottom();
  }
}

function scrollRagChatToBottom() {
  nextTick(() => {
    if (ragChatBox.value) {
      ragChatBox.value.scrollTop = ragChatBox.value.scrollHeight;
    }
  });
}



/* =========================================================
   COMPUTED
========================================================= */

const selected = computed(() => {

  return conversations.value.find(
    (item) =>
      item.conversation_id === selectedId.value
  );

});


const filtered = computed(() => {

  const keyword = search.value
    .trim()
    .toLowerCase();

  return conversations.value.filter(
    (item) => {

      const channelOk =
        activeFilter.value === "all"
        || item.channel === activeFilter.value;

      const text = [
        item.customer_name,
        item.external_user_id,
        item.last_message,
        item.channel,
      ]
        .filter(Boolean)
        .join(" ")
        .toLowerCase();

      return (
        channelOk
        &&
        (
          !keyword
          ||
          text.includes(keyword)
        )
      );

    }
  );

});


const inboundCount = computed(() => {

  return messages.value.filter(
    (message) =>
      message.direction === "inbound"
  ).length;

});


const outboundCount = computed(() => {

  return messages.value.filter(
    (message) =>
      message.direction === "outbound"
  ).length;

});


/* =========================================================
   HELPER FUNCTIONS
========================================================= */

function nameOf(item) {

  return (
    item?.customer_name
    ||
    `Khách #${item?.customer_id ?? "?"}`
  );

}


function initials(item) {

  return nameOf(item)
    .split(/\s+/)
    .slice(0, 2)
    .map(
      (word) =>
        word[0]?.toUpperCase() || ""
    )
    .join("");

}


function channelLabel(channel) {

  return channel === "instagram"
    ? "Instagram"
    : "Facebook";

}


function formatTime(value) {

  if (!value) {
    return "";
  }

  const date = new Date(value);

  if (
    Number.isNaN(
      date.getTime()
    )
  ) {
    return "";
  }

  return new Intl.DateTimeFormat(
    "vi-VN",
    {
      hour: "2-digit",
      minute: "2-digit",
    }
  ).format(date);

}


/* =========================================================
   MESSAGE / MEDIA HELPERS
========================================================= */

function conversationPreview(item) {

  if (item?.last_message) {
    return item.last_message;
  }

  if (
    item?.last_media_type === "image"
  ) {
    return "📷 Hình ảnh";
  }

  if (
    item?.last_media_type === "video"
  ) {
    return "🎥 Video";
  }

  if (
    item?.last_media_url
  ) {
    return "📎 Tệp đính kèm";
  }

  return "Chưa có tin nhắn";

}


function mediaFallback(message) {

  if (
    message?.media_type === "image"
  ) {
    return "📷 Hình ảnh";
  }

  if (
    message?.media_type === "video"
  ) {
    return "🎥 Video";
  }

  if (
    message?.media_url
  ) {
    return "📎 Tệp đính kèm";
  }

  return "(Tin nhắn không có text)";

}


function normalizedMediaType(message) {

  return String(
    message?.media_type
    || message?.mediaType
    || ""
  )
    .trim()
    .toLowerCase();

}


function mediaUrl(message) {

  return String(
    message?.media_url
    || message?.mediaUrl
    || ""
  ).trim();

}


function looksLikeImageUrl(url) {

  const value = String(
    url
    || ""
  )
    .trim()
    .toLowerCase();

  if (!value) {
    return false;
  }

  if (
    /\.(jpe?g|png|gif|webp|bmp)(\?|#|$)/.test(
      value
    )
  ) {
    return true;
  }

  return (
    value.includes(
      "/api/conversations/uploads/"
    )
    ||
    value.includes(
      "lookaside.fbsbx.com/ig_messaging_cdn"
    )
    ||
    (
      value.includes(
        "instagram."
      )
      &&
      value.includes(
        "fbcdn.net"
      )
    )
  );

}


function hasImage(message) {

  const type =
    normalizedMediaType(
      message
    );

  const url =
    mediaUrl(
      message
    );

  return Boolean(
    url
    &&
    (
      type === "image"
      ||
      type === "photo"
      ||
      (
        !type
        &&
        looksLikeImageUrl(
          url
        )
      )
    )
  );

}


function hasVideo(message) {

  const type =
    normalizedMediaType(
      message
    );

  return Boolean(
    mediaUrl(
      message
    )
    &&
    (
      type === "video"
      ||
      type === "reel"
    )
  );

}


function normalizeMessage(message) {

  const url =
    mediaUrl(
      message
    );

  let type =
    normalizedMediaType(
      message
    );

  if (
    url
    &&
    !type
    &&
    looksLikeImageUrl(
      url
    )
  ) {
    type = "image";
  }

  return {
    ...message,
    media_type:
      type
      || message?.media_type
      || null,
    media_url:
      url
      || message?.media_url
      || null,
  };

}


function makeClientId() {

  return `client-${Date.now()}-${Math.random()
    .toString(16)
    .slice(2)}`;

}


function upsertMessage(message) {

  const normalized =
    normalizeMessage(
      message
    );

  const index =
    messages.value.findIndex(
      (item) =>
        (
          normalized.external_message_id
          &&
          item.external_message_id
          === normalized.external_message_id
        )
        ||
        (
          normalized.client_id
          &&
          item.client_id
          === normalized.client_id
        )
    );

  if (index >= 0) {
    messages.value[index] = {
      ...messages.value[index],
      ...normalized,
      status:
        normalized.status
        || "sent",
    };
  } else {
    messages.value.push(
      {
        ...normalized,
        status:
          normalized.status
          || "sent",
      }
    );
  }

}


function markOptimistic(
  clientId,
  status,
) {

  messages.value =
    messages.value.map(
      (message) =>
        message.client_id === clientId
          ? {
              ...message,
              status,
            }
          : message
    );

}


function handleRealtimeEvent(event) {

  if (
    event?.type !== "message_created"
    ||
    !event.message
  ) {
    return;
  }

  if (
    event.conversation_id
    === selectedId.value
  ) {
    upsertMessage(
      event.message
    );

    nextTick(
      scrollToBottom
    );
  }

  loadConversations(
    false
  );

}


function connectRealtime() {

  if (
    socket
    &&
    (
      socket.readyState === WebSocket.OPEN
      ||
      socket.readyState === WebSocket.CONNECTING
    )
  ) {
    return;
  }

  const wsUrl =
    API_BASE
      .replace(
        /^http/,
        "ws"
      )
      .replace(
        /\/api$/,
        ""
      )
    + "/ws/conversations";

  socket = new WebSocket(
    wsUrl
  );

  socket.onmessage = (event) => {
    try {
      handleRealtimeEvent(
        JSON.parse(
          event.data
        )
      );
    } catch (err) {
      console.error(err);
    }
  };

  socket.onclose = () => {
    reconnectTimer = setTimeout(
      connectRealtime,
      2000
    );
  };

  socket.onerror = () => {
    socket?.close();
  };

}


/* =========================================================
   IMAGE HELPERS
========================================================= */

function openImagePicker() {

  if (!selectedId.value) {

    error.value =
      "Hãy chọn một cuộc hội thoại trước.";

    return;
  }

  fileInput.value?.click();

}


function clearImage() {

  if (
    imagePreview.value
    &&
    imagePreview.value.startsWith(
      "blob:"
    )
  ) {

    URL.revokeObjectURL(
      imagePreview.value
    );

  }

  imageFile.value = null;
  imagePreview.value = "";

  if (fileInput.value) {
    fileInput.value.value = "";
  }

}


function setImageFile(file) {

  if (!file) {
    return;
  }

  const allowedTypes = [
    "image/jpeg",
    "image/jpg",
    "image/png",
  ];


  if (
    !allowedTypes.includes(
      file.type
    )
  ) {

    error.value =
      "Chỉ hỗ trợ ảnh JPG, JPEG hoặc PNG.";

    return;
  }


  const maxSize =
    10
    * 1024
    * 1024;


  if (
    file.size > maxSize
  ) {

    error.value =
      "Ảnh quá lớn. Tối đa 10MB.";

    return;
  }


  clearImage();


  imageFile.value =
    file;


  imagePreview.value =
    URL.createObjectURL(
      file
    );


  error.value = "";

}


function handleFileChange(event) {

  const file =
    event.target.files?.[0];

  if (!file) {
    return;
  }

  setImageFile(
    file
  );

}


/* =========================================================
   CTRL + V IMAGE
========================================================= */

function handlePaste(event) {

  const clipboardItems =
    event.clipboardData?.items
    || [];


  for (
    const item of clipboardItems
  ) {

    if (
      item.type
      &&
      item.type.startsWith(
        "image/"
      )
    ) {

      const file =
        item.getAsFile();


      if (file) {

        /*
          Nếu clipboard là ảnh:
          không paste text rác vào textarea.
        */

        event.preventDefault();

        setImageFile(
          file
        );

        return;

      }

    }

  }

}


/* =========================================================
   AUTO SCROLL
========================================================= */

async function scrollToBottom() {

  await nextTick();

  const element =
    document.querySelector(
      ".messages-scroll"
    );

  if (element) {

    element.scrollTop =
      element.scrollHeight;

  }

}


/* =========================================================
   API - LOAD CONVERSATIONS
========================================================= */

async function loadConversations(
  showLoading = true
) {

  if (showLoading) {
    loading.value = true;
  }

  try {

    error.value = "";

    const response = await fetch(
      `${API_BASE}/conversations`
    );


    if (!response.ok) {

      throw new Error(
        `HTTP ${response.status}`
      );

    }


    const data =
      await response.json();


    conversations.value =
      Array.isArray(data)
        ? data
        : data.items || [];


  } catch (err) {

    console.error(err);


    if (showLoading) {

      error.value =
        "Không tải được danh sách hội thoại.";

    }


  } finally {

    if (showLoading) {
      loading.value = false;
    }

  }

}


/* =========================================================
   API - LOAD MESSAGES
========================================================= */

async function loadMessages(
  conversationId,
  showLoading = true,
  autoScroll = true
) {

  if (!conversationId) {
    return;
  }


  if (showLoading) {
    loading.value = true;
  }


  try {

    if (showLoading) {
      error.value = "";
    }


    const response = await fetch(
      `${API_BASE}/conversations/${conversationId}/messages`
    );


    if (!response.ok) {

      throw new Error(
        `HTTP ${response.status}`
      );

    }


    const data =
      await response.json();


    const rawMessages =
      Array.isArray(data)
        ? data
        : data.items || [];


    const newMessages =
      rawMessages.map(
        normalizeMessage
      );


    const oldSignature =
      messages.value
        .map(
          (message) =>
            [
              message.message_id,
              message.content,
              message.direction,
              message.media_type,
              message.media_url,
            ].join(":")
        )
        .join("|");


    const newSignature =
      newMessages
        .map(
          (message) =>
            [
              message.message_id,
              message.content,
              message.direction,
              message.media_type,
              message.media_url,
            ].join(":")
        )
        .join("|");


    if (
      oldSignature !==
      newSignature
    ) {

      messages.value =
        newMessages;


      if (autoScroll) {

        await scrollToBottom();

      }

    }


  } catch (err) {

    console.error(err);


    if (showLoading) {

      error.value =
        "Không tải được tin nhắn.";

    }


  } finally {

    if (showLoading) {
      loading.value = false;
    }

  }

}


/* =========================================================
   SELECT CONVERSATION
========================================================= */

async function selectConversation(id) {

  selectedId.value = id;

  clearImage();


  await loadMessages(
    id,
    true,
    true
  );

}


/* =========================================================
   API - SEND TEXT MESSAGE
========================================================= */

async function sendTextMessage() {

  const text =
    draft.value.trim();


  if (
    !text
    ||
    !selectedId.value
  ) {
    return;
  }


  const response = await fetch(
    `${API_BASE}/conversations/${selectedId.value}/messages`,
    {
      method: "POST",

      headers: {
        "Content-Type":
          "application/json",
      },

      body: JSON.stringify({
        text,
      }),
    }
  );


  if (!response.ok) {

    throw new Error(
      await response.text()
    );

  }


  draft.value = "";

}


/* =========================================================
   API - UPLOAD + SEND IMAGE
========================================================= */

async function sendImageMessage() {

  if (
    !imageFile.value
    ||
    !selectedId.value
  ) {
    return;
  }

  if (sendingImage.value) {
    return;
  }

  sendingImage.value = true;

  try {

    const formData =
      new FormData();


    formData.append(
      "file",
      imageFile.value
    );


    const response = await fetch(
      `${API_BASE}/conversations/${selectedId.value}/media/upload`,
      {
        method: "POST",

        body:
          formData,
      }
    );


    if (!response.ok) {

      let responseText =
        await response.text();

      try {

        const data =
          JSON.parse(
            responseText
          );

        responseText =
          data?.detail?.message
          || data?.detail?.meta_message
          || responseText;

      } catch {
        // Keep raw backend response.
      }

      throw new Error(
        responseText
      );

    }


    clearImage();

  } finally {

    sendingImage.value = false;

  }

}


/* =========================================================
   SEND REPLY
========================================================= */

async function sendReply() {

  if (
    !selectedId.value
    ||
    sending.value
  ) {
    return;
  }


  const hasText =
    Boolean(
      draft.value.trim()
    );


  const hasImage =
    Boolean(
      imageFile.value
    );


  if (
    !hasText
    &&
    !hasImage
  ) {
    return;
  }


  sending.value = true;


  try {

    error.value = "";


    /*
      Nếu có ảnh:
      gửi ảnh trước.
    */

    if (hasImage) {

      await sendImageMessage();

    }


    /*
      Nếu đồng thời có text:
      gửi text tiếp theo.
    */

    if (hasText) {

      await sendTextMessage();

    }


    await loadMessages(
      selectedId.value,
      false,
      true
    );


    await loadConversations(
      false
    );


  } catch (err) {

    console.error(err);


    error.value =
      err?.message
      || "Gửi tin nhắn/ảnh thất bại.";


  } finally {

    sending.value = false;

  }

}


async function sendUnifiedReply() {

  if (
    !selectedId.value
    ||
    sending.value
  ) {
    return;
  }

  const text =
    draft.value.trim();

  const hasText =
    Boolean(
      text
    );

  const hasImage =
    Boolean(
      imageFile.value
    );

  if (
    !hasText
    &&
    !hasImage
  ) {
    return;
  }

  const fileToSend =
    imageFile.value;

  const previewToSend =
    imagePreview.value;

  const clientId =
    makeClientId();

  const optimisticIds = [];

  if (hasImage) {
    const imageClientId =
      `${clientId}-image`;

    optimisticIds.push(
      imageClientId
    );

    upsertMessage(
      {
        client_id:
          imageClientId,
        message_id:
          imageClientId,
        conversation_id:
          selectedId.value,
        direction:
          "outbound",
        content:
          null,
        media_type:
          "image",
        media_url:
          previewToSend,
        received_at:
          new Date().toISOString(),
        status:
          "sending",
        retry_file:
          fileToSend,
        retry_preview:
          previewToSend,
      }
    );
  }

  if (hasText) {
    const textClientId =
      `${clientId}-text`;

    optimisticIds.push(
      textClientId
    );

    upsertMessage(
      {
        client_id:
          textClientId,
        message_id:
          textClientId,
        conversation_id:
          selectedId.value,
        direction:
          "outbound",
        content:
          text,
        media_type:
          null,
        media_url:
          null,
        received_at:
          new Date().toISOString(),
        status:
          "sending",
        retry_text:
          text,
      }
    );
  }

  await scrollToBottom();

  sending.value = true;

  try {
    error.value = "";

    const formData =
      new FormData();

    formData.append(
      "client_id",
      clientId
    );

    if (hasText) {
      formData.append(
        "text",
        text
      );
    }

    if (
      hasImage
      &&
      fileToSend
    ) {
      formData.append(
        "file",
        fileToSend
      );
    }

    const response = await fetch(
      `${API_BASE}/conversations/${selectedId.value}/send`,
      {
        method:
          "POST",
        body:
          formData,
      }
    );

    if (!response.ok) {
      throw new Error(
        await response.text()
      );
    }

    const data =
      await response.json();

    messages.value =
      messages.value.filter(
        (message) =>
          !optimisticIds.includes(
            message.client_id
          )
      );

    (
      data.messages
      || []
    ).forEach(
      upsertMessage
    );

    draft.value = "";
    clearImage();

    await loadConversations(
      false
    );

  } catch (err) {
    console.error(err);

    error.value =
      err?.message
      || "Send failed.";

    optimisticIds.forEach(
      (id) =>
        markOptimistic(
          id,
          "failed"
        )
    );

  } finally {
    sending.value = false;
  }

}


async function retryMessage(message) {

  if (sending.value) {
    return;
  }

  if (message.retry_text) {
    draft.value =
      message.retry_text;
  }

  if (message.retry_file) {
    imageFile.value =
      message.retry_file;
    imagePreview.value =
      message.retry_preview
      || "";
  }

  messages.value =
    messages.value.filter(
      (item) =>
        item.client_id
        !== message.client_id
    );

  await sendUnifiedReply();

}


/* =========================================================
   QUICK REPLY
========================================================= */

function quick(text) {

  draft.value = text;

}


/* =========================================================
   START APP
========================================================= */

onMounted(async () => {

  await loadConversations(
    true
  );

  connectRealtime();
  fetchDocuments();
  fetchAutoReplySetting();
  fetchMetaStatus();

  const metaResult = new URLSearchParams(window.location.search).get("meta");
  if (metaResult === "connected") {
    metaNotice.value = "Kết nối Meta thành công.";
    fetchMetaStatus();
  } else if (metaResult === "error") {
    metaNotice.value = "Kết nối Meta thất bại. Kiểm tra cấu hình App ID/Secret và Redirect URI.";
  }

  pollingTimer = setInterval(

    async () => {

      await loadConversations(
        false
      );


      if (selectedId.value) {

        await loadMessages(
          selectedId.value,
          false,
          true
        );

      }

    },
    25000
  );

});


/* =========================================================
   STOP POLLING
========================================================= */

onUnmounted(() => {

  if (pollingTimer) {

    clearInterval(
      pollingTimer
    );

    pollingTimer = null;

  }


  clearImage();

  if (reconnectTimer) {
    clearTimeout(
      reconnectTimer
    );
  }

  if (socket) {
    socket.close();
  }

});
</script>


<template>

  <div class="lunari-app">


    <!-- =====================================================
         SIDEBAR
    ====================================================== -->

    <aside class="side">

      <div class="logo-wrap">

        <img
          :src="logoUrl"
          class="logo"
          alt="Lunari Food"
        />

      </div>


      <nav class="menu">

        <button
          class="menu-item"
          :class="{ active: currentTab === 'inbox' }"
          @click="currentTab = 'inbox'"
        >

          <span>💬</span>

          <b>Hộp thư</b>

          <em>
            {{ conversations.length }}
          </em>

        </button>


        <button
          class="menu-item"
          :class="{ active: currentTab === 'documents' }"
          @click="currentTab = 'documents'; fetchDocuments()"
        >
          <span>📚</span>
          <b>Kho tri thức</b>
          <em>{{ documents.length }}</em>
        </button>


        <button
          class="menu-item"
          :class="{ active: currentTab === 'rag_chat' }"
          @click="currentTab = 'rag_chat'; fetchAutoReplySetting()"
        >
          <span>🤖</span>
          <b>AI Assistant</b>
        </button>


        <button
          class="menu-item"
          :class="{ active: currentTab === 'settings' }"
          @click="openSettings"
        >
          <span>⚙</span>
          <b>Cài đặt</b>
        </button>

      </nav>



      <div class="side-card">

        <div class="side-card-copy">

          <strong>
            Gắn kết
            <br />
            khách hàng
            <br />
            mỗi ngày!
          </strong>

          <small>
            Một chút dễ thương
            cho mỗi cuộc trò chuyện.
          </small>

        </div>


        <div class="food-cup">
          🍗
        </div>


        <div class="side-heart">
          ♥
        </div>

      </div>


      <button class="collapse">

        ‹

        <span>
          Thu gọn
        </span>

      </button>

    </aside>


    <!-- =====================================================
         MAIN
    ====================================================== -->

    <main class="main">


      <!-- TOP -->

      <header class="top">

        <div class="welcome">

          <strong>
            Xin chào, Lunari! 👋
          </strong>

          <span>
            Hôm nay là một ngày tuyệt vời
            để mang đến trải nghiệm ngon miệng!
          </span>

        </div>


        <div class="top-actions">

          <div class="top-search">

            Tìm kiếm khách hàng,
            tin nhắn, đơn hàng...

            <span>
              ⌕
            </span>

          </div>


          <button class="bell">

            ♢

            <i>
              12
            </i>

          </button>


          <div class="team">

            <div class="team-avatar">
              L
            </div>

            <div>

              <b>
                Lunari Team
              </b>

              <small>
                Quản trị viên
              </small>

            </div>

          </div>

        </div>

      </header>


      <!-- ERROR -->

      <div
        v-if="error"
        class="error"
      >
        {{ error }}
      </div>


      <!-- ===================================================
           3 CỘT
      ==================================================== -->

      <section v-if="currentTab === 'inbox'" class="layout">



        <!-- =================================================
             INBOX
        ================================================== -->

        <aside class="inbox">


          <div class="inbox-title">

            <h2>
              Hộp thư khách hàng
            </h2>

            <button>
              ⌄
            </button>

          </div>


          <div class="inbox-tabs">

            <button
              :class="{
                active:
                  activeFilter === 'all'
              }"
              @click="
                activeFilter = 'all'
              "
            >

              Tất cả

              <i>
                {{ conversations.length }}
              </i>

            </button>


            <button
              :class="{
                active:
                  activeFilter === 'facebook'
              }"
              @click="
                activeFilter = 'facebook'
              "
            >
              Facebook
            </button>


            <button
              :class="{
                active:
                  activeFilter === 'instagram'
              }"
              @click="
                activeFilter = 'instagram'
              "
            >
              Instagram
            </button>

          </div>


          <div class="search-box">

            <span>
              ⌕
            </span>

            <input
              v-model="search"
              placeholder="Tìm hội thoại..."
            />

          </div>


          <div class="conversation-scroll">

            <button
              v-for="item in filtered"
              :key="
                item.conversation_id
              "
              class="conversation"

              :class="{
                selected:
                  item.conversation_id
                  === selectedId
              }"

              @click="
                selectConversation(
                  item.conversation_id
                )
              "
            >


              <div class="avatar">

                <img
                  v-if="
                    item.avatar_url
                  "
                  :src="
                    item.avatar_url
                  "
                  :alt="
                    nameOf(item)
                  "
                />

                <span v-else>
                  {{ initials(item) }}
                </span>

              </div>


              <div class="conv-copy">


                <div class="conv-head">

                  <strong>
                    {{ nameOf(item) }}
                  </strong>

                  <time>
                    {{
                      formatTime(
                        item.last_message_at
                      )
                    }}
                  </time>

                </div>


                <div class="channel">

                  <span
                    class="social-icon"
                    :class="
                      item.channel
                    "
                  >

                    <svg
                      v-if="
                        item.channel
                        === 'facebook'
                      "
                      viewBox="0 0 24 24"
                    >

                      <path
                        fill="currentColor"
                        d="
                          M13.6 22v-9h3
                          l.5-3.5h-3.5V7.2
                          c0-1 .3-1.8 1.8-1.8
                          h1.9V2.3
                          c-.3 0-1.5-.1-2.8-.1
                          -2.8 0-4.7 1.7-4.7 4.8
                          v2.5H6.7V13h3.1v9h3.8Z
                        "
                      />

                    </svg>


                    <svg
                      v-else
                      viewBox="0 0 24 24"
                    >

                      <rect
                        x="3"
                        y="3"
                        width="18"
                        height="18"
                        rx="5"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                      />

                      <circle
                        cx="12"
                        cy="12"
                        r="4"
                        fill="none"
                        stroke="currentColor"
                        stroke-width="2"
                      />

                      <circle
                        cx="17.2"
                        cy="6.8"
                        r="1.2"
                        fill="currentColor"
                      />

                    </svg>

                  </span>


                  {{
                    channelLabel(
                      item.channel
                    )
                  }}

                </div>


                <p>
                  {{
                    conversationPreview(
                      item
                    )
                  }}
                </p>

              </div>

            </button>

          </div>


          <div class="conversation-footer">

            Hiển thị
            {{ filtered.length }}
            cuộc trò chuyện

          </div>

        </aside>


        <!-- =================================================
             CHAT
        ================================================== -->

        <section class="chat">


          <template v-if="selected">


            <!-- CHAT HEADER -->

            <header class="chat-head">


              <div class="chat-person">


                <div class="avatar avatar-lg">

                  <img
                    v-if="
                      selected.avatar_url
                    "
                    :src="
                      selected.avatar_url
                    "
                    :alt="
                      nameOf(selected)
                    "
                  />

                  <span v-else>
                    {{ initials(selected) }}
                  </span>

                </div>


                <div>


                  <h2>

                    {{ nameOf(selected) }}

                    <span>
                      ☆
                    </span>

                  </h2>


                  <p>

                    <span
                      class="social-icon"
                      :class="
                        selected.channel
                      "
                    >

                      <svg
                        v-if="
                          selected.channel
                          === 'facebook'
                        "
                        viewBox="0 0 24 24"
                      >

                        <path
                          fill="currentColor"
                          d="
                            M13.6 22v-9h3
                            l.5-3.5h-3.5V7.2
                            c0-1 .3-1.8 1.8-1.8
                            h1.9V2.3
                            c-.3 0-1.5-.1-2.8-.1
                            -2.8 0-4.7 1.7-4.7 4.8
                            v2.5H6.7V13h3.1v9h3.8Z
                          "
                        />

                      </svg>


                      <svg
                        v-else
                        viewBox="0 0 24 24"
                      >

                        <rect
                          x="3"
                          y="3"
                          width="18"
                          height="18"
                          rx="5"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                        />

                        <circle
                          cx="12"
                          cy="12"
                          r="4"
                          fill="none"
                          stroke="currentColor"
                          stroke-width="2"
                        />

                        <circle
                          cx="17.2"
                          cy="6.8"
                          r="1.2"
                          fill="currentColor"
                        />

                      </svg>

                    </span>


                    {{
                      channelLabel(
                        selected.channel
                      )
                    }}

                    ·

                    {{
                      selected.status
                      === "open"
                      ? "Khách hàng mới"
                      : selected.status
                    }}

                  </p>

                </div>

              </div>


              <div class="chat-tools">

                <button>⋮</button>
                <button>!</button>
                <button>♡</button>

              </div>

            </header>


            <!-- =================================================
                 MESSAGES
            ================================================== -->

            <div class="messages-scroll">


              <div
                class="
                  chat-decoration
                  decor-heart-one
                "
              >
                ♡
              </div>


              <div
                class="
                  chat-decoration
                  decor-heart-two
                "
              >
                ♥
              </div>


              <div
                class="
                  chat-decoration
                  decor-star-one
                "
              >
                ✦
              </div>


              <div
                class="
                  chat-decoration
                  decor-star-two
                "
              >
                ✧
              </div>


              <div
                class="
                  chat-doodle
                  doodle-one
                "
              >
                ♡
              </div>


              <div
                class="
                  chat-doodle
                  doodle-two
                "
              >
                ✿
              </div>


              <div
                class="
                  chat-doodle
                  doodle-three
                "
              >
                ♡
              </div>


              <div class="today">
                Hôm nay
              </div>


              <div
                v-if="loading"
                class="loading"
              >
                Đang tải tin nhắn...
              </div>


              <div
                v-for="message in messages"

                :key="
                  message.message_id
                "

                class="msg-line"

                :class="
                  message.direction
                "
              >


                <!-- CUSTOMER AVATAR -->

                <div
                  v-if="
                    message.direction
                    === 'inbound'
                  "

                  class="
                    avatar
                    avatar-sm
                  "
                >

                  <img
                    v-if="
                      selected.avatar_url
                    "

                    :src="
                      selected.avatar_url
                    "

                    :alt="
                      nameOf(selected)
                    "
                  />

                  <span v-else>
                    {{
                      initials(
                        selected
                      )
                    }}
                  </span>

                </div>


                <!-- BUBBLE -->

                <div class="bubble">


                  <!-- IMAGE -->

                  <a
                    v-if="
                      hasImage(
                        message
                      )
                    "

                    :href="
                      mediaUrl(
                        message
                      )
                    "

                    target="_blank"

                    rel="
                      noopener
                      noreferrer
                    "

                    class="
                      message-media-link
                    "
                  >

                    <img
                      :src="
                        mediaUrl(
                          message
                        )
                      "

                      alt="Ảnh"

                      class="
                        message-image
                      "
                    />

                  </a>


                  <!-- VIDEO -->

                  <video
                    v-else-if="
                      hasVideo(
                        message
                      )
                    "

                    :src="
                      mediaUrl(
                        message
                      )
                    "

                    controls

                    class="
                      message-video
                    "
                  />


                  <!-- OTHER FILE -->

                  <a
                    v-else-if="
                      mediaUrl(
                        message
                      )
                    "

                    :href="
                      mediaUrl(
                        message
                      )
                    "

                    target="_blank"

                    class="
                      message-attachment
                    "
                  >

                    📎 Mở tệp đính kèm

                  </a>


                  <!-- TEXT -->

                  <p
                    v-if="
                      message.content
                    "

                    class="
                      message-text
                    "
                  >

                    {{
                      message.content
                    }}

                  </p>


                  <!-- FALLBACK -->

                  <p
                    v-else-if="
                      !mediaUrl(
                        message
                      )
                    "

                    class="
                      message-text
                    "
                  >

                    {{
                      mediaFallback(
                        message
                      )
                    }}

                  </p>


                  <small>

                    {{
                      formatTime(
                        message.received_at
                      )
                    }}


                    <b
                      v-if="
                        message.direction
                        === 'outbound'
                        &&
                        message.status
                        !== 'sending'
                        &&
                        message.status
                        !== 'failed'
                      "
                    >
                      ✓✓
                    </b>

                    <b
                      v-if="
                        message.status
                        === 'sending'
                      "
                    >
                      sending
                    </b>

                    <button
                      v-if="
                        message.status
                        === 'failed'
                      "
                      class="retry-message"
                      @click="
                        retryMessage(
                          message
                        )
                      "
                    >
                      retry
                    </button>

                  </small>

                </div>


                <img
                  v-if="
                    message.direction
                    === 'outbound'
                  "

                  :src="
                    logoUrl
                  "

                  class="
                    brand-mini
                  "

                  alt="
                    Lunari
                  "
                />

              </div>

            </div>


            <!-- =================================================
                 COMPOSER
            ================================================== -->

            <footer class="composer">


              <div class="composer-tabs">

                <button class="active">
                  Trả lời
                </button>

                <button>
                  Ghi chú nội bộ
                </button>

              </div>


              <!-- TEXTAREA -->

              <textarea
                v-model="draft"

                placeholder="
                  Nhập tin nhắn...
                  Ctrl+V để dán ảnh
                "

                @paste="
                  handlePaste
                "

                @keydown.enter.exact.prevent="
                  sendReply
                "
              />


              <!-- IMAGE PREVIEW -->

              <div
                v-if="
                  imagePreview
                "

                class="
                  image-preview-box
                "
              >

                <img
                  :src="
                    imagePreview
                  "

                  alt="
                    Ảnh chuẩn bị gửi
                  "
                />


                <div
                  class="
                    image-preview-info
                  "
                >

                  <span>

                    {{
                      imageFile?.name
                      ||
                      "Ảnh từ clipboard"
                    }}

                  </span>


                  <button
                    type="button"

                    @click="
                      clearImage
                    "
                  >
                    ✕ Xóa ảnh
                  </button>

                </div>

              </div>


              <!-- HIDDEN FILE INPUT -->

              <input
                ref="fileInput"

                type="file"

                accept="
                  image/jpeg,
                  image/png
                "

                class="
                  hidden-file-input
                "

                @change="
                  handleFileChange
                "
              />


              <div class="composer-bottom">


                <div class="left-actions">

                  <button>
                    ☺
                  </button>


                  <!-- IMAGE BUTTON -->

                  <button
                    type="button"

                    title="
                      Chọn ảnh
                    "

                    @click="
                      openImagePicker
                    "
                  >

                    📷

                  </button>


                  <button>
                    ⌕
                  </button>


                  <button>
                    ♡
                  </button>


                  <button
                    class="
                      template
                    "
                  >
                    Mẫu trả lời
                  </button>

                </div>


                <div class="right-actions">


                  <button
                    class="
                      voucher
                    "
                  >

                    🎁
                    Tạo mã giảm giá

                  </button>


                  <button
                    class="
                      send
                    "

                    :disabled="
                      (
                        !draft.trim()
                        &&
                        !imageFile
                      )
                      ||
                      sending
                      ||
                      sendingImage
                    "

                    @click="
                      sendUnifiedReply
                    "
                  >

                    {{
                      sending
                      ? "Đang gửi..."
                      : imageFile
                        ? "➤ Gửi ảnh"
                        : "➤ Gửi phản hồi"
                    }}

                  </button>

                </div>

              </div>


              <div class="quick">

                <button
                  @click="
                    quick(
                      'Xin chào 👋'
                    )
                  "
                >
                  Xin chào 👋
                </button>


                <button
                  @click="
                    quick(
                      'Cảm ơn bạn ❤️'
                    )
                  "
                >
                  Cảm ơn bạn ❤️
                </button>


                <button
                  @click="
                    quick(
                      'Dạ bên mình đã nhận đơn rồi ạ ✅'
                    )
                  "
                >
                  Đã nhận đơn ✅
                </button>


                <button
                  @click="
                    quick(
                      'Bạn muốn hẹn giờ giao lúc mấy giờ ạ? ⏰'
                    )
                  "
                >
                  Hẹn giờ giao ⏰
                </button>

              </div>

            </footer>

          </template>


          <!-- EMPTY CHAT -->

          <div
            v-else
            class="
              empty-chat
            "
          >

            <img
              :src="
                logoUrl
              "

              alt="
                Lunari
              "
            />

            <h2>
              Chọn một hội thoại nhé
            </h2>

          </div>

        </section>


        <!-- =================================================
             CUSTOMER PANEL
        ================================================== -->

        <aside class="customer">


          <template v-if="selected">


            <div class="customer-title">

              <h3>
                Thông tin khách hàng
              </h3>

              <button>
                ⌃
              </button>

            </div>


            <div class="customer-profile">


              <div
                class="
                  avatar
                  customer-avatar
                "
              >

                <img
                  v-if="
                    selected.avatar_url
                  "

                  :src="
                    selected.avatar_url
                  "

                  :alt="
                    nameOf(selected)
                  "
                />

                <span v-else>

                  {{
                    initials(
                      selected
                    )
                  }}

                </span>

              </div>


              <div>


                <h3>
                  {{
                    nameOf(
                      selected
                    )
                  }}
                </h3>


                <p>

                  <span
                    class="
                      social-icon
                    "

                    :class="
                      selected.channel
                    "
                  >

                    <svg
                      v-if="
                        selected.channel
                        === 'facebook'
                      "

                      viewBox="
                        0 0 24 24
                      "
                    >

                      <path
                        fill="
                          currentColor
                        "

                        d="
                          M13.6 22v-9h3
                          l.5-3.5h-3.5V7.2
                          c0-1 .3-1.8 1.8-1.8
                          h1.9V2.3
                          c-.3 0-1.5-.1-2.8-.1
                          -2.8 0-4.7 1.7-4.7 4.8
                          v2.5H6.7V13h3.1v9h3.8Z
                        "
                      />

                    </svg>


                    <svg
                      v-else

                      viewBox="
                        0 0 24 24
                      "
                    >

                      <rect
                        x="3"
                        y="3"
                        width="18"
                        height="18"
                        rx="5"

                        fill="none"

                        stroke="
                          currentColor
                        "

                        stroke-width="2"
                      />

                      <circle
                        cx="12"
                        cy="12"
                        r="4"

                        fill="none"

                        stroke="
                          currentColor
                        "

                        stroke-width="2"
                      />

                      <circle
                        cx="17.2"
                        cy="6.8"
                        r="1.2"

                        fill="
                          currentColor
                        "
                      />

                    </svg>

                  </span>


                  {{
                    channelLabel(
                      selected.channel
                    )
                  }}

                </p>


                <small>

                  ID:
                  {{
                    selected.external_user_id
                  }}

                </small>

              </div>

            </div>


            <!-- TAGS -->

            <div class="section">

              <div class="section-head">

                <h4>
                  Tags
                </h4>

                <button>
                  + Thêm tag
                </button>

              </div>


              <div class="tags">

                <span>
                  Khách mới
                </span>

                <span>
                  Yêu thích ♥
                </span>

                <span>
                  Order online
                </span>

              </div>

            </div>


            <!-- STATS -->

            <div class="section">

              <div class="section-head">

                <h4>
                  Thống kê hội thoại
                </h4>

              </div>


              <div class="stats">

                <div>

                  <span>
                    Khách gửi
                  </span>

                  <b>
                    {{ inboundCount }}
                  </b>

                </div>


                <div>

                  <span>
                    Shop gửi
                  </span>

                  <b>
                    {{ outboundCount }}
                  </b>

                </div>

              </div>

            </div>


            <!-- ORDER -->

            <div class="section">

              <div class="section-head">

                <h4>
                  Đơn gần nhất
                </h4>

                <a>
                  Xem tất cả
                </a>

              </div>


              <div class="order">

                <div class="order-top">

                  <b>
                    #LNR-DEMO
                  </b>

                  <span>
                    Đã giao
                  </span>

                </div>


                <div class="order-item">

                  <div class="dish">
                    🍗
                  </div>


                  <div>

                    <b>
                      Combo gà sốt phô mai
                    </b>

                    <small>
                      x 1
                    </small>

                  </div>


                  <strong>
                    119.000đ
                  </strong>

                </div>


                <div class="total">

                  <span>
                    Tổng cộng
                  </span>

                  <b>
                    119.000đ
                  </b>

                </div>

              </div>

            </div>


            <!-- FAVORITE -->

            <div class="section">

              <h4>
                Món yêu thích
              </h4>


              <div class="foods">

                <div>

                  <div>
                    🍗
                  </div>

                  <span>
                    Gà sốt phô mai
                  </span>

                </div>


                <div>

                  <div>
                    🍜
                  </div>

                  <span>
                    Tokbokki phô mai
                  </span>

                </div>


                <div>

                  <div>
                    🍟
                  </div>

                  <span>
                    Khoai tây lắc
                  </span>

                </div>

              </div>

            </div>


            <!-- NOTE -->

            <div class="note">

              <b>
                Ghi chú của đội ngũ
              </b>


              <p>
                Khách hàng thân thiện,
                thường đặt món vào buổi tối.
                Ưa thích combo phô mai.
              </p>

            </div>

          </template>

        </aside>

      </section>

      <!-- ===================================================
           KHO TRI THỨC (DOCUMENTS)
      ==================================================== -->
      <section v-if="currentTab === 'documents'" class="rag-docs-layout">
        <div class="rag-header-panel">
          <div>
            <h2>📚 Kho tri thức tài liệu (RAG Knowledge Base)</h2>
            <p>Nạp tài liệu sản phẩm, FAQ, chính sách... để AI tự động học và trả lời khách hàng qua Facebook/Instagram.</p>
          </div>
          <div class="rag-stats">
            <div class="stat-card">
              <span class="stat-num">{{ documents.length }}</span>
              <span class="stat-label">Tài liệu</span>
            </div>
            <div class="stat-card">
              <span class="stat-num">{{ documents.reduce((acc, d) => acc + (d.chunk_count || 0), 0) }}</span>
              <span class="stat-label">Vector Chunks</span>
            </div>
            <div class="stat-card">
              <span class="stat-num font-green">{{ documents.filter(d => d.status === 'ready').length }}</span>
              <span class="stat-label">Sẵn sàng (Ready)</span>
            </div>
          </div>
        </div>

        <!-- UPLOAD DROPZONE -->
        <div
          class="upload-dropzone"
          @dragover.prevent
          @drop.prevent="handleDocDrop"
          @click="$refs.docFileInput.click()"
        >
          <input
            type="file"
            ref="docFileInput"
            class="hidden-file-input"
            accept=".pdf,.docx,.txt,.csv,.md,.html"
            @change="handleDocFileSelect"
          />
          <div class="dropzone-content" v-if="!docUploading">
            <span class="upload-icon">☁️</span>
            <strong>Kéo thả file vào đây hoặc nhấp để chọn file upload</strong>
            <small>Hỗ trợ định dạng: PDF, DOCX, TXT, CSV, MD, HTML (Tối đa 20MB)</small>
          </div>
          <div class="dropzone-content" v-else>
            <span class="spinner-icon">⚙️</span>
            <strong>Đang upload & xử lý vector embeddings...</strong>
          </div>
        </div>

        <div v-if="docUploadError" class="error-banner">
          ⚠️ {{ docUploadError }}
        </div>

        <!-- DOCUMENT LIST TABLE -->
        <div class="docs-table-card">
          <div class="card-header">
            <h3>Danh sách tài liệu đã nạp</h3>
            <button class="btn-refresh" @click="fetchDocuments" :disabled="docsLoading">
              🔄 Làm mới
            </button>
          </div>

          <div v-if="docsLoading && !documents.length" class="loading-state">
            Đang tải danh sách tài liệu...
          </div>

          <div v-else-if="!documents.length" class="empty-docs-state">
            📭 Chưa có tài liệu nào trong Kho tri thức. Hãy upload file PDF/DOCX/TXT ở trên!
          </div>

          <table v-else class="docs-table">
            <thead>
              <tr>
                <th>ID</th>
                <th>Tên tài liệu</th>
                <th>Định dạng</th>
                <th>Dung lượng</th>
                <th>Chunks</th>
                <th>Trạng thái</th>
                <th>Ngày tạo</th>
                <th>Thao tác</th>
              </tr>
            </thead>
            <tbody>
              <tr v-for="doc in documents" :key="doc.id">
                <td>#{{ doc.id }}</td>
                <td class="font-medium">
                  <span class="doc-file-icon">📄</span> {{ doc.filename }}
                </td>
                <td><span class="badge-type">{{ doc.file_type.toUpperCase() }}</span></td>
                <td>{{ formatFileSize(doc.file_size) }}</td>
                <td><strong>{{ doc.chunk_count || 0 }}</strong></td>
                <td>
                  <span class="status-badge" :class="'status-' + doc.status">
                    <span v-if="doc.status === 'ready'">✅ Sẵn sàng</span>
                    <span v-else-if="doc.status === 'processing'">⚙️ Đang xử lý</span>
                    <span v-else-if="doc.status === 'pending'">⏳ Chờ xử lý</span>
                    <span v-else>❌ Lỗi</span>
                  </span>
                </td>
                <td class="text-sm text-gray">{{ formatTime(doc.uploaded_at) }}</td>
                <td>
                  <button class="btn-delete" @click="deleteDoc(doc.id)" title="Xóa tài liệu">
                    🗑️ Xóa
                  </button>
                </td>
              </tr>
            </tbody>
          </table>
        </div>
      </section>

      <!-- ===================================================
           AI ASSISTANT (RAG CHAT PLAYGROUND)
      ==================================================== -->
      <section v-if="currentTab === 'rag_chat'" class="rag-chat-layout">
        <div class="rag-chat-sidebar">
          <div class="setting-card">
            <h3>⚡ AI Auto-Reply (Meta Channels)</h3>
            <p class="setting-desc">Tự động dùng RAG trả lời tin nhắn từ khách Facebook & Instagram Webhook.</p>
            
            <div class="toggle-row">
              <span>Auto-Reply:</span>
              <button
                class="toggle-switch"
                :class="{ active: autoReplyEnabled }"
                @click="toggleAutoReply"
              >
                <span class="toggle-knob"></span>
                <span class="toggle-text">{{ autoReplyEnabled ? 'ĐANG BẬT' : 'TẮT' }}</span>
              </button>
            </div>
          </div>

          <div class="setting-card">
            <h3>🎛️ RAG Config</h3>
            <div class="config-item">
              <label>Top-K Context Chunks: <strong>{{ ragTopK }}</strong></label>
              <input type="range" min="1" max="10" v-model="ragTopK" class="range-slider" />
            </div>
            <div class="config-item">
              <label>Embedding Model:</label>
               <span class="config-val">Gemini gemini-embedding-001 (3072d)</span>
            </div>
            <div class="config-item">
              <label>LLM Engine:</label>
               <span class="config-val">Groq GPT-OSS 20B</span>
            </div>
          </div>

          <div class="setting-card">
            <h3>💡 Câu hỏi mẫu nhanh</h3>
            <div class="quick-questions">
              <button @click="sendRagQuery('Cửa hàng có những sản phẩm gì và giá bao nhiêu?')">
                💬 Danh sách sản phẩm & Giá
              </button>
              <button @click="sendRagQuery('Chính sách đổi trả và hoàn tiền như thế nào?')">
                💬 Chính sách đổi trả & Hoàn tiền
              </button>
              <button @click="sendRagQuery('Thời gian giao hàng và phí ship tính sao?')">
                💬 Phí vận chuyển & Giao hàng
              </button>
            </div>
          </div>
        </div>

        <div class="rag-chat-main">
          <div class="rag-chat-header">
            <div>
              <h2>🤖 RAG AI Assistant Playground</h2>
              <small>Hỏi đáp trực tiếp với Kho tri thức – Hỗ trợ Streaming response (SSE)</small>
            </div>
            <span class="badge-online">● Online</span>
          </div>

          <div class="rag-chat-messages" ref="ragChatBox">
            <div
              v-for="(m, idx) in ragMessages"
              :key="idx"
              class="rag-msg-row"
              :class="m.role"
            >
              <div class="rag-msg-avatar">
                {{ m.role === 'user' ? '👤' : '🤖' }}
              </div>
              <div class="rag-msg-bubble">
                <div class="rag-msg-sender">
                  {{ m.role === 'user' ? 'Bạn' : 'RAG AI Assistant' }}
                </div>
                <div class="rag-msg-text" v-if="m.content">
                  {{ m.content }}
                </div>
                <div class="rag-msg-loading" v-if="m.loading">
                  <span class="dot-pulse">●</span> Đang truy vấn vector database & suy luận...
                </div>
              </div>
            </div>
          </div>

          <div class="rag-chat-inputzone">
            <textarea
              v-model="ragQuery"
              placeholder="Nhập câu hỏi tại đây... (VD: Áo thun nam giá bao nhiêu?)"
              rows="2"
              @keydown.enter.prevent="sendRagQuery()"
            ></textarea>
            <button
              class="btn-send-rag"
              @click="sendRagQuery()"
              :disabled="ragSending || !ragQuery.trim()"
            >
              <span>Gửi</span> 🚀
            </button>
          </div>
        </div>
      </section>

      <!-- ===================================================
           SETTINGS / META OAUTH
      ==================================================== -->
      <section v-if="currentTab === 'settings'" class="settings-layout">
        <div class="settings-card">
          <div class="settings-card-header">
            <div>
              <h2>🔗 Kết nối kênh bán hàng</h2>
              <p>Kết nối Facebook Page và Instagram Professional bằng OAuth.</p>
            </div>
            <span
              class="connection-badge"
              :class="{ connected: metaStatus.connected }"
            >
              {{ metaStatus.connected ? 'ĐÃ KẾT NỐI' : 'CHƯA KẾT NỐI' }}
            </span>
          </div>

          <div v-if="metaNotice" class="settings-notice">
            {{ metaNotice }}
          </div>

          <div v-if="metaStatus.connected" class="meta-connection-details">
            <div><strong>Facebook Page:</strong> {{ metaStatus.facebook_page_name || 'Đã kết nối' }}</div>
            <div><strong>Page ID:</strong> {{ metaStatus.facebook_page_id }}</div>
            <div><strong>Instagram ID:</strong> {{ metaStatus.instagram_account_id || 'Chưa liên kết' }}</div>
            <div><strong>Webhook:</strong> {{ metaStatus.subscription_status || 'Chưa kiểm tra' }}</div>
          </div>

          <p v-else class="settings-empty">
            Người bán cần cấp quyền một lần để hệ thống tự lấy Page Access Token,
            đồng bộ Page và đăng ký webhook messages.
          </p>

          <div class="settings-actions">
            <button
              v-if="!metaStatus.connected"
              class="btn-meta-connect"
              type="button"
              @click="connectMeta"
            >
              Kết nối với Facebook
            </button>
            <button
              v-else
              class="btn-meta-disconnect"
              type="button"
              :disabled="metaLoading"
              @click="disconnectMeta"
            >
              Ngắt kết nối
            </button>
          </div>
        </div>
      </section>


    </main>

  </div>

</template>


<style scoped>

/* =========================================================
   MEDIA MESSAGE
========================================================= */

.message-media-link {
  display: block;
  max-width: 100%;
  text-decoration: none;
}


.message-image {
  display: block;

  width: clamp(160px, 32vw, 320px);
  max-width: 100%;

  height: auto;
  max-height: 420px;

  object-fit: cover;

  border-radius: 14px;

  cursor: pointer;
}


.message-video {
  display: block;

  width: 100%;
  max-width: 320px;

  max-height: 420px;

  border-radius: 14px;

  background: #000;
}


.message-attachment {
  display: inline-block;

  padding: 8px 10px;

  text-decoration: none;

  font-weight: 600;

  border-radius: 10px;
}


.message-text {
  margin-top: 6px;
}


.retry-message {
  margin-left: 6px;
  padding: 0;
  color: #d62432;
  background: transparent;
  border: 0;
  font-size: 9px;
  font-weight: 800;
  text-decoration: underline;
}


/* =========================================================
   IMAGE PREVIEW
========================================================= */

.hidden-file-input {
  display: none;
}


.image-preview-box {
  display: flex;
  align-items: center;
  gap: 12px;

  margin: 8px 14px;
  padding: 10px;

  border: 1px solid
    rgba(0, 0, 0, 0.08);

  border-radius: 14px;

  background: #fff;
}


.image-preview-box img {
  width: 85px;
  height: 85px;

  object-fit: cover;

  border-radius: 12px;
}


.image-preview-info {
  display: flex;
  flex-direction: column;
  align-items: flex-start;

  gap: 8px;

  min-width: 0;
}


.image-preview-info span {
  max-width: 250px;

  overflow: hidden;

  text-overflow: ellipsis;

  white-space: nowrap;

  font-size: 13px;
}


.image-preview-info button {
  border: none;
  background: transparent;

  cursor: pointer;

  font-size: 12px;
  font-weight: 700;
}


/* =========================================================
   AVATAR
========================================================= */

.avatar {
  overflow: hidden;
}



/* =========================================================
   RAG KNOWLEDGE BASE & CHAT STYLES
========================================================= */

.rag-docs-layout,
.rag-chat-layout {
  display: flex;
  flex-direction: column;
  gap: 20px;
  padding: 24px;
  height: calc(100vh - 90px);
  overflow-y: auto;
  box-sizing: border-box;
}

.rag-header-panel {
  display: flex;
  justify-content: space-between;
  align-items: center;
  background: #ffffff;
  padding: 20px 24px;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.rag-header-panel h2 {
  margin: 0 0 6px 0;
  font-size: 20px;
  color: #1a202c;
}

.rag-header-panel p {
  margin: 0;
  color: #718096;
  font-size: 13px;
  max-width: 600px;
}

.rag-stats {
  display: flex;
  gap: 16px;
}

.stat-card {
  display: flex;
  flex-direction: column;
  align-items: center;
  background: #f7fafc;
  padding: 12px 20px;
  border-radius: 12px;
  min-width: 90px;
  border: 1px solid #e2e8f0;
}

.stat-num {
  font-size: 22px;
  font-weight: 800;
  color: #2b6cb0;
}

.font-green {
  color: #38a169;
}

.stat-label {
  font-size: 11px;
  color: #718096;
  font-weight: 600;
}

/* DROPZONE */
.upload-dropzone {
  border: 2px dashed #cbd5e0;
  border-radius: 16px;
  padding: 32px;
  text-align: center;
  background: #ffffff;
  cursor: pointer;
  transition: all 0.2s ease;
}

.upload-dropzone:hover {
  border-color: #3182ce;
  background: #ebf8ff;
}

.dropzone-content {
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 8px;
}

.upload-icon, .spinner-icon {
  font-size: 36px;
}

.dropzone-content strong {
  font-size: 15px;
  color: #2d3748;
}

.dropzone-content small {
  color: #a0aec0;
  font-size: 12px;
}

.error-banner {
  background: #fed7d7;
  color: #9b2c2c;
  padding: 12px 16px;
  border-radius: 10px;
  font-size: 13px;
}

/* DOCS TABLE CARD */
.docs-table-card {
  background: #ffffff;
  border-radius: 16px;
  padding: 20px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.card-header {
  display: flex;
  justify-content: space-between;
  align-items: center;
  margin-bottom: 16px;
}

.card-header h3 {
  margin: 0;
  font-size: 16px;
  color: #2d3748;
}

.btn-refresh {
  background: #edf2f7;
  border: none;
  padding: 8px 14px;
  border-radius: 8px;
  cursor: pointer;
  font-weight: 600;
  font-size: 13px;
  color: #4a5568;
}

.btn-refresh:hover {
  background: #e2e8f0;
}

.docs-table {
  width: 100%;
  border-collapse: collapse;
  text-align: left;
}

.docs-table th {
  background: #f7fafc;
  padding: 12px 16px;
  font-size: 12px;
  color: #718096;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  border-bottom: 2px solid #edf2f7;
}

.docs-table td {
  padding: 14px 16px;
  border-bottom: 1px solid #edf2f7;
  font-size: 13px;
  color: #2d3748;
}

.badge-type {
  background: #eef2ff;
  color: #4f46e5;
  padding: 3px 8px;
  border-radius: 6px;
  font-weight: 700;
  font-size: 11px;
}

.status-badge {
  padding: 4px 10px;
  border-radius: 12px;
  font-size: 12px;
  font-weight: 600;
}

.status-ready { background: #c6f6d5; color: #22543d; }
.status-processing { background: #feebc8; color: #744210; }
.status-pending { background: #e2e8f0; color: #4a5568; }
.status-error { background: #fed7d7; color: #742a2a; }

.btn-delete {
  background: #fff5f5;
  color: #e53e3e;
  border: 1px solid #feb2b2;
  padding: 6px 12px;
  border-radius: 8px;
  cursor: pointer;
  font-size: 12px;
  font-weight: 600;
}

.btn-delete:hover {
  background: #fed7d7;
}

.empty-docs-state, .loading-state {
  text-align: center;
  padding: 40px;
  color: #a0aec0;
  font-size: 14px;
}

/* RAG CHAT PLAYGROUND */
.rag-chat-layout {
  flex-direction: row;
}

.rag-chat-sidebar {
  width: 320px;
  display: flex;
  flex-direction: column;
  gap: 16px;
}

.setting-card {
  background: #ffffff;
  border-radius: 16px;
  padding: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
}

.setting-card h3 {
  margin: 0 0 8px 0;
  font-size: 15px;
  color: #2d3748;
}

.setting-desc {
  font-size: 12px;
  color: #718096;
  margin: 0 0 12px 0;
  line-height: 1.4;
}

.toggle-row {
  display: flex;
  justify-content: space-between;
  align-items: center;
  font-size: 13px;
  font-weight: 600;
}

.toggle-switch {
  width: 100px;
  height: 32px;
  background: #cbd5e0;
  border: none;
  border-radius: 16px;
  cursor: pointer;
  position: relative;
  transition: background 0.3s;
  display: flex;
  align-items: center;
  padding: 0 8px;
}

.toggle-switch.active {
  background: #38a169;
}

.toggle-knob {
  width: 24px;
  height: 24px;
  background: #ffffff;
  border-radius: 50%;
  position: absolute;
  left: 4px;
  transition: transform 0.3s;
}

.toggle-switch.active .toggle-knob {
  transform: translateX(68px);
}

.toggle-text {
  font-size: 10px;
  font-weight: 800;
  color: #ffffff;
  margin-left: 28px;
}

.toggle-switch.active .toggle-text {
  margin-left: 8px;
}

.config-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  margin-bottom: 12px;
  font-size: 12px;
  color: #4a5568;
}

.range-slider {
  width: 100%;
}

.config-val {
  font-weight: 700;
  color: #2b6cb0;
}

.quick-questions {
  display: flex;
  flex-direction: column;
  gap: 8px;
}

.quick-questions button {
  background: #f7fafc;
  border: 1px solid #e2e8f0;
  padding: 8px 12px;
  border-radius: 8px;
  text-align: left;
  font-size: 12px;
  cursor: pointer;
  color: #2d3748;
}

.quick-questions button:hover {
  background: #ebf8ff;
  border-color: #bee3f8;

}

.rag-chat-main {
  flex: 1;
  display: flex;
  flex-direction: column;
  background: #ffffff;
  border-radius: 16px;
  box-shadow: 0 4px 16px rgba(0, 0, 0, 0.04);
  overflow: hidden;
}

.rag-chat-header {
  padding: 16px 24px;
  border-bottom: 1px solid #edf2f7;
  display: flex;
  justify-content: space-between;
  align-items: center;
}

.rag-chat-header h2 {
  margin: 0;
  font-size: 17px;
  color: #1a202c;
}

.badge-online {
  color: #38a169;
  font-size: 12px;
  font-weight: 700;
}

.rag-chat-messages {
  flex: 1;
  padding: 20px;
  overflow-y: auto;
  display: flex;
  flex-direction: column;
  gap: 16px;
  background: #f8fafc;
}

.rag-msg-row {
  display: flex;
  gap: 12px;

}

.rag-msg-row.user {
  flex-direction: row-reverse;
}

.rag-msg-avatar {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  background: #e2e8f0;
  display: flex;
  align-items: center;
  justify-content: center;
  font-size: 18px;
}

.rag-msg-bubble {
  max-width: 75%;
  background: #ffffff;
  padding: 12px 16px;
  border-radius: 16px;
  box-shadow: 0 2px 8px rgba(0,0,0,0.04);
  font-size: 14px;
  line-height: 1.5;
  color: #2d3748;
}

.user .rag-msg-bubble {
  background: #3182ce;
  color: #ffffff;
}

.rag-msg-sender {
  font-size: 11px;
  font-weight: 700;
  color: #a0aec0;
  margin-bottom: 4px;
}

.user .rag-msg-sender {
  color: #ebf8ff;
}

.rag-chat-inputzone {
  padding: 16px;
  border-top: 1px solid #edf2f7;
  display: flex;
  gap: 12px;
  background: #ffffff;
}

.rag-chat-inputzone textarea {
  flex: 1;
  border: 1px solid #cbd5e0;
  border-radius: 12px;
  padding: 10px 14px;
  font-size: 14px;
  resize: none;
  font-family: inherit;
}

.btn-send-rag {
  background: #3182ce;
  color: #ffffff;
  border: none;
  padding: 0 20px;
  border-radius: 12px;
  font-weight: 700;
  cursor: pointer;
  display: flex;
  align-items: center;
  gap: 6px;
}

.btn-send-rag:disabled {
  background: #cbd5e0;
  cursor: not-allowed;
}

.settings-layout {
  padding: 28px;
  min-height: 560px;
  background: #fff8f4;
}

.settings-card {
  max-width: 820px;
  margin: 0 auto;
  padding: 28px;
  border: 1px solid #f3c9bd;
  border-radius: 22px;
  background: #ffffff;
  box-shadow: 0 8px 24px rgba(135, 54, 36, 0.08);
}

.settings-card-header {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 20px;
}

.settings-card-header h2 {
  margin: 0 0 8px;
  color: #8d271d;
}

.settings-card-header p,
.settings-empty {
  margin: 0;
  color: #8b6b64;
  line-height: 1.6;
}

.connection-badge {
  padding: 8px 12px;
  border-radius: 999px;
  color: #9b6b31;
  background: #fff0d8;
  font-size: 12px;
  font-weight: 800;
  white-space: nowrap;
}

.connection-badge.connected {
  color: #237443;
  background: #e4f7e9;
}

.settings-notice {
  margin: 22px 0;
  padding: 12px 14px;
  border-radius: 12px;
  color: #7b4e00;
  background: #fff6d9;
}

.meta-connection-details {
  display: grid;
  gap: 10px;
  margin: 24px 0;
  padding: 18px;
  border-radius: 14px;
  background: #fff5f0;
  color: #5e423a;
}

.settings-actions {
  margin-top: 24px;
}

.btn-meta-connect,
.btn-meta-disconnect {
  border: 0;
  border-radius: 12px;
  padding: 12px 18px;
  color: #fff;
  font-weight: 800;
  cursor: pointer;
}

.btn-meta-connect {
  background: #1877f2;
}

.btn-meta-disconnect {
  background: #a94b3b;
}

.btn-meta-disconnect:disabled {
  opacity: 0.6;
  cursor: not-allowed;
}

</style>
