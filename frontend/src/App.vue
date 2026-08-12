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
          class="menu-item active"
        >

          <span>💬</span>

          <b>Hộp thư</b>

          <em>
            {{ conversations.length }}
          </em>

        </button>


        <button class="menu-item">
          <span>♧</span>
          <b>Khách hàng</b>
        </button>


        <button class="menu-item">
          <span>🛒</span>
          <b>Đơn hàng</b>
        </button>


        <button class="menu-item">
          <span>◈</span>
          <b>Sản phẩm</b>
        </button>


        <button class="menu-item">
          <span>✿</span>
          <b>Mã giảm giá</b>
        </button>


        <button class="menu-item">
          <span>⌁</span>
          <b>Chiến dịch</b>
        </button>


        <button class="menu-item">
          <span>▥</span>
          <b>Thống kê</b>
        </button>


        <button class="menu-item">
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

      <section class="layout">


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


.avatar img {
  width: 100%;
  height: 100%;

  display: block;

  object-fit: cover;

  border-radius: 50%;
}

</style>
