<script setup>
import { computed, onMounted, ref } from "vue";

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

const error = ref("");


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
   API - LOAD CONVERSATIONS
========================================================= */

async function loadConversations() {

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

    const data = await response.json();

    conversations.value =
      data.items || [];


    if (
      !selectedId.value
      &&
      conversations.value.length
    ) {

      await selectConversation(
        conversations.value[0]
          .conversation_id
      );

    }

  } catch (err) {

    console.error(err);

    error.value =
      "Không tải được hội thoại.";

  }
}


/* =========================================================
   API - LOAD MESSAGES
========================================================= */

async function selectConversation(id) {

  selectedId.value = id;

  loading.value = true;

  try {

    error.value = "";

    const response = await fetch(
      `${API_BASE}/conversations/${id}/messages`
    );

    if (!response.ok) {
      throw new Error(
        `HTTP ${response.status}`
      );
    }

    const data = await response.json();

    messages.value =
      data.items || [];


    /* tự scroll xuống message cuối */

    requestAnimationFrame(
      () => {

        const element =
          document.querySelector(
            ".messages-scroll"
          );

        if (element) {

          element.scrollTop =
            element.scrollHeight;

        }

      }
    );

  } catch (err) {

    console.error(err);

    error.value =
      "Không tải được tin nhắn.";

  } finally {

    loading.value = false;

  }

}


/* =========================================================
   API - SEND MESSAGE
========================================================= */

async function sendMessage() {

  const text =
    draft.value.trim();

  if (
    !text
    ||
    !selectedId.value
    ||
    sending.value
  ) {
    return;
  }


  sending.value = true;


  try {

    error.value = "";

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


    await selectConversation(
      selectedId.value
    );


    await loadConversations();


  } catch (err) {

    console.error(err);

    error.value =
      "Gửi tin nhắn thất bại.";

  } finally {

    sending.value = false;

  }

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

onMounted(
  loadConversations
);
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


      <!-- ===================================================
           TOP BAR
      ==================================================== -->

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
             CONVERSATION LIST
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


          <!-- FILTER -->

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
                  activeFilter
                  === 'facebook'
              }"
              @click="
                activeFilter =
                  'facebook'
              "
            >
              Facebook
            </button>


            <button
              :class="{
                active:
                  activeFilter
                  === 'instagram'
              }"
              @click="
                activeFilter =
                  'instagram'
              "
            >
              Instagram
            </button>

          </div>


          <!-- SEARCH -->

          <div class="search-box">

            <span>
              ⌕
            </span>

            <input
              v-model="search"
              placeholder="Tìm hội thoại..."
            />

          </div>


          <!-- LIST -->

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

                {{ initials(item) }}

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


                <!-- SOCIAL -->

                <div class="channel">


                  <span
                    class="social-icon"
                    :class="item.channel"
                  >


                    <!-- FACEBOOK -->

                    <svg
                      v-if="
                        item.channel
                        === 'facebook'
                      "
                      viewBox="0 0 24 24"
                      aria-hidden="true"
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


                    <!-- INSTAGRAM -->

                    <svg
                      v-else
                      viewBox="0 0 24 24"
                      aria-hidden="true"
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
                    item.last_message
                    ||
                    "Chưa có tin nhắn"
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


                <div
                  class="avatar avatar-lg"
                >

                  {{ initials(selected) }}

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


                      <!-- FB -->

                      <svg
                        v-if="
                          selected.channel
                          === 'facebook'
                        "
                        viewBox="0 0 24 24"
                        aria-hidden="true"
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


                      <!-- IG -->

                      <svg
                        v-else
                        viewBox="0 0 24 24"
                        aria-hidden="true"
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

                <button>
                  ⋮
                </button>

                <button>
                  !
                </button>

                <button>
                  ♡
                </button>

              </div>

            </header>


            <!-- =================================================
                 MESSAGES
            ================================================== -->

            <div class="messages-scroll">


              <!-- DECORATION -->

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


              <!-- MESSAGE -->

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

                  {{ initials(selected) }}

                </div>


                <!-- BUBBLE -->

                <div class="bubble">


                  <p>

                    {{
                      message.content
                      ||
                      "(Tin nhắn không có text)"
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
                      "
                    >
                      ✓✓
                    </b>

                  </small>

                </div>


                <!-- SHOP LOGO -->

                <img
                  v-if="
                    message.direction
                    === 'outbound'
                  "
                  :src="logoUrl"
                  class="brand-mini"
                  alt="Lunari"
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


              <textarea
                v-model="draft"
                placeholder="Nhập tin nhắn... (Shift + Enter để xuống dòng)"
                @keydown.enter.exact.prevent="sendMessage"
              />


              <div class="composer-bottom">


                <div class="left-actions">

                  <button>
                    ☺
                  </button>

                  <button>
                    ▧
                  </button>

                  <button>
                    ⌕
                  </button>

                  <button>
                    ♡
                  </button>

                  <button class="template">
                    Mẫu trả lời
                  </button>

                </div>


                <div class="right-actions">


                  <button class="voucher">

                    🎁
                    Tạo mã giảm giá

                  </button>


                  <button
                    class="send"
                    :disabled="
                      !draft.trim()
                      ||
                      sending
                    "
                    @click="
                      sendMessage
                    "
                  >

                    {{
                      sending
                      ? "Đang gửi..."
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
            class="empty-chat"
          >

            <img
              :src="logoUrl"
              alt="Lunari"
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

                {{ initials(selected) }}

              </div>


              <div>


                <h3>
                  {{ nameOf(selected) }}
                </h3>


                <p>


                  <span
                    class="social-icon"
                    :class="
                      selected.channel
                    "
                  >


                    <!-- FACEBOOK -->

                    <svg
                      v-if="
                        selected.channel
                        === 'facebook'
                      "
                      viewBox="0 0 24 24"
                      aria-hidden="true"
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


                    <!-- INSTAGRAM -->

                    <svg
                      v-else
                      viewBox="0 0 24 24"
                      aria-hidden="true"
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