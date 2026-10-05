<script setup>
import { computed, nextTick, onMounted, onUnmounted, ref } from 'vue';
import BrandLogo from './BrandLogo.vue';
import MarketingStory from './MarketingStory.vue';
import { locale, setLocale } from './i18n.js';

const props = defineProps({ darkMode: Boolean });
const emit = defineEmits(['login', 'signup', 'plans', 'toggle-dark-mode']);
const menuOpen = ref(false);
const selectedTour = ref(0);
const motionPaused = ref(false);
const revealReady = ref(false);
const page = ref(null);
const tourButtons = ref([]);
let observer;
let motionPreference;
const text = computed(() => locale.value === 'en' ? {
  nav: ['Product', 'Solutions', 'Connections', 'Questions'], login: 'Sign in', signup: 'Start for free', plans: 'Explore plans', language: 'Interface language', menu: 'Open navigation', close: 'Close navigation', themeDark: 'Switch to dark mode', themeLight: 'Switch to light mode',
  eyebrow: 'A CONNECTED WORKSPACE FOR YOUR SHOP', title: 'Good conversations.', titleAccent: 'Better relationships.',
  intro: 'Bring messages, customer knowledge, and daily work together. Give your team the context to make every customer feel understood.',
  start: 'Get started with your shop', note: 'Explore the Demo plan. Connect channels when you choose a suitable plan.',
  inbox: 'Customer inbox', all: 'All conversations', search: 'Search customers', customer: 'Minh Anh', owner: 'Customer care', active: 'In progress',
  question: 'Hi! I need a bottle to take to work.', followup: 'Something compact that keeps water warm.', reply: 'Of course. Let me check a suitable bottle and its available colors for you.',
  typing: 'Shop is preparing a reply', input: 'Write a message', team: 'Your team, on the same page', handoff: 'Context stays with the conversation',
  caption: 'Illustrative product preview',
  channelsEyebrow: 'MEET CUSTOMERS WHERE THEY ALREADY ARE', channelsTitle: 'Many channels. One place to care.', channelsCopy: 'Set up the supported channels your shop uses, then follow conversations in your shared inbox.', channelNote: 'Availability depends on your plan and the setup required by each platform.',
  storyEyebrow: 'MADE FOR EVERYDAY SHOP WORK', storyTitle: 'Behind every growing shop', storyAccent: 'is a team that cares.', storyCopy: 'A busy day should not mean a missed message. Keep conversations clear, hand work to the right person, and carry customer context into the next interaction.', photoAlt: 'Illustration of a shop team preparing parcels and reviewing customer work together',
  tourEyebrow: 'TAKE A CLOSER LOOK', tourTitle: 'From the first hello', tourAccent: 'to the next visit.', tourIntro: 'Explore three parts of your workspace. Select a view to see how they fit into your day.',
  tabs: ['Shared inbox', 'Knowledge assistant', 'Daily operations'],
  tourTitles: ['The conversation belongs to your whole team.', 'Your shop knowledge, ready to help.', 'See the next step, not just the last message.'],
  tourDescriptions: ['Read previous messages, assign an owner, and leave internal notes so the next colleague can pick up naturally.', 'Use product information and shop documents to support answers. Review sources and bring in a colleague when needed.', 'Keep orders, appointments, and follow-up tasks visible alongside the customer relationship.'],
  tourBullets: [['Conversation history in one place', 'Assignment and internal notes', 'Customer profile beside the inbox'], ['Documents organized in the knowledge base', 'Answers with source context', 'Staff can review and take over'], ['Order and appointment tracking', 'Tasks that need attention', 'A clear handoff between colleagues']],
  knowledgeTitle: 'Shop knowledge', documents: ['Product guide', 'Delivery & returns', 'Customer care notes'], ready: 'Ready to search', source: 'Source: product guide', answer: 'I can check the bottle’s size, colors, and care instructions in the product guide.', review: 'Staff review',
  boardTitle: 'Today’s work', boardColumns: ['To follow up', 'In progress', 'Completed'], boardTasks: ['Check available color', 'Confirm appointment', 'Prepare a quotation', 'Answer delivery question', 'Follow up after purchase', 'Customer helped'],
  humanEyebrow: 'PERSONAL CARE, WITH CONTEXT', humanTitle: 'Remember the person.', humanAccent: 'Not just the message.', humanCopy: 'A customer profile brings past interactions, labels, preferences, and follow-up work together. Staff can see what is known and what still needs to be asked.', humanBullets: ['Continue with the conversation history', 'Keep preferences linked to their source', 'Follow up with the right person at the right time'], profileTitle: 'Customer 360', profileLabels: ['Returning customer', 'Prefers compact products'], profileFacts: ['Conversation history', 'Recorded preferences', 'Purchased products', 'Follow-up tasks'], profileNote: 'Preference recorded by staff',
  solutionsEyebrow: 'FITS THE WAY YOU WORK', solutionsTitle: 'Start with your team’s', solutionsAccent: 'everyday needs.', solutionsIntro: 'Choose the tools and level of support that fit your business.', solutions: [
    { title: 'Online retail', body: 'Bring product questions, order conversations, and customer care into a shared workflow.', tags: ['Products', 'Orders', 'Inbox'], icon: 'bag' },
    { title: 'Appointment services', body: 'Keep customer conversations connected to appointments and the staff member responsible.', tags: ['Appointments', 'Staff', 'Follow-up'], icon: 'calendar' },
    { title: 'Growing teams', body: 'Share context, assign work, and build a consistent way to support customers together.', tags: ['Assignments', 'Permissions', 'History'], icon: 'people' }
  ],
  setupEyebrow: 'FROM SIGNUP TO YOUR FIRST CONVERSATION', setupTitle: 'A clear path', setupAccent: 'to getting started.', steps: [
    { title: 'Create your shop', body: 'Sign up and verify your email to open your own workspace.' },
    { title: 'Choose your setup', body: 'Select a plan, add your team, and prepare your knowledge base.' },
    { title: 'Connect and review', body: 'Set up supported channels and review conversations before everyday use.' }
  ],
  faqEyebrow: 'A FEW THINGS YOU MAY WANT TO KNOW', faqTitle: 'Before you get started.', faqs: [
    { q: 'Can I explore before connecting a channel?', a: 'Yes. Create your shop and explore the Demo plan first. Social channel connections become available according to the plan you choose.' },
    { q: 'Can a staff member take over from the chatbot?', a: 'Yes. Your team can review the conversation and take over when a customer needs direct assistance.' },
    { q: 'What knowledge does the assistant use?', a: 'Product information and documents prepared for your shop. Keep them up to date and review answers before using the assistant with customers.' },
    { q: 'How are Shopee and TikTok connected?', a: 'These channels use a local connector with pairing and a platform session on the connector machine. Setup and a working session are required.' },
    { q: 'Where can I see the current plans?', a: 'Choose Explore plans to view the available options. Create a shop or sign in when you are ready to request a service.' }
  ],
  finalTitle: 'Make room for', finalAccent: 'better customer care.', finalCopy: 'Start with your shop. Build a workspace your team can make its own.', footerCopy: 'Customer conversations, connected.', footerProduct: 'Explore', footerAccount: 'Your workspace', footerNote: 'Smart Merchant Hub · Customer management & sales support',
} : {
  nav: ['Sản phẩm', 'Giải pháp', 'Kết nối', 'Giải đáp'], login: 'Đăng nhập', signup: 'Bắt đầu miễn phí', plans: 'Khám phá các gói', language: 'Ngôn ngữ giao diện', menu: 'Mở menu điều hướng', close: 'Đóng menu điều hướng', themeDark: 'Bật chế độ tối', themeLight: 'Tắt chế độ tối',
  eyebrow: 'KHÔNG GIAN LÀM VIỆC CHO SHOP CỦA BẠN', title: 'Trò chuyện gần gũi.', titleAccent: 'Chăm khách dài lâu.',
  intro: 'Tin nhắn, thông tin khách hàng và công việc cùng ở một nơi. Để đội ngũ của bạn hiểu khách hơn và tiếp nối mỗi cuộc trò chuyện thật tự nhiên.',
  start: 'Bắt đầu với shop của bạn', note: 'Khám phá gói Demo. Kết nối kênh khi chọn gói phù hợp.',
  inbox: 'Hộp thư khách hàng', all: 'Tất cả hội thoại', search: 'Tìm khách hàng', customer: 'Minh Anh', owner: 'Chăm sóc khách hàng', active: 'Đang xử lý',
  question: 'Shop ơi, mình cần một chiếc bình để mang đi làm.', followup: 'Gọn nhẹ và giữ được nước ấm ấy ạ.', reply: 'Dạ, để shop kiểm tra mẫu bình phù hợp và những màu đang có cho mình nhé.',
  typing: 'Shop đang chuẩn bị trả lời', input: 'Nhập tin nhắn', team: 'Cả đội ngũ cùng một nhịp', handoff: 'Ngữ cảnh luôn đi cùng hội thoại',
  caption: 'Minh họa trải nghiệm sản phẩm',
  channelsEyebrow: 'GẶP KHÁCH Ở NƠI HỌ QUEN THUỘC', channelsTitle: 'Nhiều kênh. Một nơi chăm khách.', channelsCopy: 'Thiết lập các kênh shop đang dùng, rồi theo dõi cuộc trò chuyện trong hộp thư chung của đội ngũ.', channelNote: 'Kênh khả dụng tùy theo gói và yêu cầu thiết lập của từng nền tảng.',
  storyEyebrow: 'DÀNH CHO CÔNG VIỆC MỖI NGÀY', storyTitle: 'Phía sau một shop phát triển', storyAccent: 'là một đội ngũ tận tâm.', storyCopy: 'Một ngày bận rộn không nên đi cùng tin nhắn bị bỏ lỡ. Giữ hội thoại rõ ràng, giao việc đúng người và mang theo ngữ cảnh khi khách quay lại.', photoAlt: 'Ảnh minh họa đội ngũ shop cùng chuẩn bị đơn hàng và xem công việc chăm sóc khách hàng',
  tourEyebrow: 'KHÁM PHÁ KHÔNG GIAN CỦA BẠN', tourTitle: 'Từ lời chào đầu tiên', tourAccent: 'đến lần khách quay lại.', tourIntro: 'Ba phần kết nối công việc trong ngày của shop. Chọn một màn hình để khám phá.',
  tabs: ['Hộp thư chung', 'Trợ lý kiến thức', 'Công việc mỗi ngày'],
  tourTitles: ['Một cuộc trò chuyện, cả đội ngũ cùng hiểu.', 'Kiến thức của shop, sẵn sàng hỗ trợ.', 'Biết bước tiếp theo cần làm với khách.'],
  tourDescriptions: ['Xem tin nhắn trước đó, phân công người phụ trách và để lại ghi chú nội bộ để đồng nghiệp tiếp nối tự nhiên.', 'Dùng thông tin sản phẩm và tài liệu của shop để hỗ trợ trả lời. Kiểm tra nguồn và chuyển cho nhân viên khi cần.', 'Theo dõi đơn bán, lịch hẹn và việc cần xử lý cùng với hành trình chăm sóc khách hàng.'],
  tourBullets: [['Lịch sử hội thoại ở một nơi', 'Phân công và ghi chú nội bộ', 'Hồ sơ khách ngay cạnh hộp thư'], ['Tài liệu được tổ chức trong kho kiến thức', 'Câu trả lời đi cùng ngữ cảnh nguồn', 'Nhân viên xem lại và tiếp quản'], ['Theo dõi đơn bán và lịch hẹn', 'Những việc cần được xử lý', 'Bàn giao rõ ràng giữa nhân viên']],
  knowledgeTitle: 'Kiến thức của shop', documents: ['Hướng dẫn sản phẩm', 'Giao hàng & đổi trả', 'Ghi chú chăm sóc khách'], ready: 'Sẵn sàng tra cứu', source: 'Nguồn: hướng dẫn sản phẩm', answer: 'Shop có thể kiểm tra kích thước, màu sắc và cách bảo quản bình trong tài liệu sản phẩm.', review: 'Nhân viên xem lại',
  boardTitle: 'Công việc hôm nay', boardColumns: ['Cần theo dõi', 'Đang xử lý', 'Hoàn tất'], boardTasks: ['Kiểm tra màu còn hàng', 'Xác nhận lịch hẹn', 'Chuẩn bị báo giá', 'Trả lời về giao hàng', 'Chăm sóc sau mua', 'Đã hỗ trợ khách'],
  humanEyebrow: 'CHĂM SÓC CÓ NGỮ CẢNH', humanTitle: 'Nhớ một người khách.', humanAccent: 'Không chỉ một tin nhắn.', humanCopy: 'Hồ sơ khách hàng kết nối lịch sử tương tác, nhãn, sở thích và việc cần theo dõi. Nhân viên biết điều gì đã được ghi nhận và điều gì còn cần hỏi thêm.', humanBullets: ['Tiếp nối từ lịch sử trò chuyện', 'Sở thích gắn với nguồn ghi nhận', 'Theo dõi đúng người, đúng thời điểm'], profileTitle: 'Hồ sơ khách hàng 360', profileLabels: ['Khách quay lại', 'Thích sản phẩm gọn nhẹ'], profileFacts: ['Lịch sử tương tác', 'Sở thích đã ghi nhận', 'Sản phẩm đã mua', 'Việc cần theo dõi'], profileNote: 'Sở thích được nhân viên ghi nhận',
  solutionsEyebrow: 'PHÙ HỢP CÁCH BẠN VẬN HÀNH', solutionsTitle: 'Bắt đầu từ nhu cầu', solutionsAccent: 'thật của đội ngũ.', solutionsIntro: 'Chọn công cụ và mức hỗ trợ phù hợp với công việc của doanh nghiệp.', solutions: [
    { title: 'Shop bán hàng online', body: 'Kết nối câu hỏi sản phẩm, hội thoại đơn hàng và chăm sóc khách trong một luồng làm việc.', tags: ['Sản phẩm', 'Đơn bán', 'Hộp thư'], icon: 'bag' },
    { title: 'Dịch vụ có lịch hẹn', body: 'Gắn cuộc trò chuyện với lịch hẹn và nhân viên phụ trách để đội ngũ theo dõi thuận tiện.', tags: ['Lịch hẹn', 'Nhân viên', 'Theo dõi'], icon: 'calendar' },
    { title: 'Đội ngũ đang mở rộng', body: 'Chia sẻ ngữ cảnh, phân công rõ ràng và xây dựng cách phục vụ khách thống nhất.', tags: ['Phân công', 'Phân quyền', 'Lịch sử'], icon: 'people' }
  ],
  setupEyebrow: 'TỪ ĐĂNG KÝ ĐẾN CUỘC TRÒ CHUYỆN ĐẦU TIÊN', setupTitle: 'Một lộ trình rõ ràng', setupAccent: 'để bắt đầu.', steps: [
    { title: 'Tạo không gian shop', body: 'Đăng ký và xác minh email để mở không gian làm việc của riêng bạn.' },
    { title: 'Chuẩn bị cách vận hành', body: 'Chọn gói, thêm đội ngũ và chuẩn bị tài liệu trong kho kiến thức.' },
    { title: 'Kết nối và kiểm tra', body: 'Thiết lập các kênh được hỗ trợ, xem lại hội thoại trước khi vận hành mỗi ngày.' }
  ],
  faqEyebrow: 'NHỮNG ĐIỀU BẠN CÓ THỂ MUỐN BIẾT', faqTitle: 'Trước khi bắt đầu.', faqs: [
    { q: 'Tôi có thể xem thử trước khi kết nối kênh không?', a: 'Có. Bạn có thể tạo shop và khám phá gói Demo trước. Kết nối mạng xã hội được mở theo gói dịch vụ bạn chọn.' },
    { q: 'Nhân viên có thể tiếp quản từ chatbot không?', a: 'Có. Đội ngũ có thể xem hội thoại và tiếp quản khi khách cần được hỗ trợ trực tiếp.' },
    { q: 'Trợ lý dùng kiến thức từ đâu?', a: 'Từ thông tin sản phẩm và tài liệu được chuẩn bị cho shop. Bạn nên cập nhật nội dung và kiểm tra câu trả lời trước khi đưa trợ lý vào phục vụ khách.' },
    { q: 'Shopee và TikTok được kết nối thế nào?', a: 'Các kênh này dùng ứng dụng kết nối trên máy, ghép nối với hệ thống và phiên đăng nhập nền tảng trên máy chạy ứng dụng. Cần thiết lập và duy trì phiên kết nối hoạt động.' },
    { q: 'Xem các gói hiện tại ở đâu?', a: 'Chọn Khám phá các gói để xem lựa chọn hiện có. Tạo shop hoặc đăng nhập khi bạn muốn đăng ký dịch vụ.' }
  ],
  finalTitle: 'Dành thêm thời gian', finalAccent: 'cho những người khách.', finalCopy: 'Bắt đầu từ shop của bạn. Xây dựng một không gian đội ngũ có thể làm việc cùng nhau.', footerCopy: 'Kết nối những cuộc trò chuyện.', footerProduct: 'Khám phá', footerAccount: 'Không gian của bạn', footerNote: 'Smart Merchant Hub · Quản lý khách hàng & hỗ trợ bán hàng',
});

function act(action) {
  menuOpen.value = false;
  emit(action);
}
function scrollToSection(id) {
  menuOpen.value = false;
  const container = page.value?.closest('.crm-app.public-home');
  const target = document.getElementById(id);
  if (!container || !target) return;
  const top = target.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 96;
  container.scrollTo({ top: Math.max(0, top), behavior: motionPaused.value ? 'auto' : 'smooth' });
}
function changeLocale(nextLocale) {
  const container = page.value?.closest('.crm-app.public-home');
  const top = container?.scrollTop || 0;
  setLocale(nextLocale);
  nextTick(() => { if (container) container.scrollTop = top; });
}
function selectTour(index) { selectedTour.value = index; }
function onTourKey(event, index) {
  let next = index;
  if (event.key === 'ArrowRight') next = (index + 1) % 3;
  else if (event.key === 'ArrowLeft') next = (index + 2) % 3;
  else if (event.key === 'Home') next = 0;
  else if (event.key === 'End') next = 2;
  else return;
  event.preventDefault();
  selectTour(next);
  nextTick(() => tourButtons.value[next]?.focus());
}
function handleMotionPreference(event) { motionPaused.value = event.matches; }
onMounted(() => {
  motionPreference = window.matchMedia('(prefers-reduced-motion: reduce)');
  motionPaused.value = motionPreference.matches;
  motionPreference.addEventListener?.('change', handleMotionPreference);
  if ('IntersectionObserver' in window) {
    observer = new IntersectionObserver(entries => {
      for (const entry of entries) if (entry.isIntersecting) {
        entry.target.classList.add('is-visible');
        observer.unobserve(entry.target);
      }
    }, { threshold: 0.08, rootMargin: '0px 0px 40px 0px' });
    page.value.querySelectorAll('[data-reveal]').forEach(element => observer.observe(element));
    revealReady.value = true;
  }
});
onUnmounted(() => {
  observer?.disconnect();
  motionPreference?.removeEventListener?.('change', handleMotionPreference);
});
</script>

<template>
  <div ref="page" class="smh-site" :class="{ 'has-reveal': revealReady, 'motion-paused': motionPaused }" data-testid="marketing-page">
    <svg class="smh-symbols" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">
      <symbol id="smh-shop" viewBox="0 0 24 24"><path d="M4 10v10h16V10M3 10l2-7h14l2 7M3 10c0 3 4 3 4 0 0 3 5 3 5 0 0 3 5 3 5 0 0 3 4 3 4 0M9 20v-6h6v6"/></symbol>
      <symbol id="smh-chat" viewBox="0 0 24 24"><path d="M21 11.5a9 9 0 0 1-9 9H3l2-4a9 9 0 1 1 16-5ZM8 9h8M8 13h5"/></symbol>
      <symbol id="smh-book" viewBox="0 0 24 24"><path d="M12 5C9 3 5 3 2 4v15c3-1 7-1 10 1 3-2 7-2 10-1V4c-3-1-7-1-10 1v15M6 8h2M16 8h2M6 12h2M16 12h2"/></symbol>
      <symbol id="smh-bag" viewBox="0 0 24 24"><path d="M5 7h14l2 14H3L5 7ZM8 8V6a4 4 0 0 1 8 0v2M8 13h8"/></symbol>
      <symbol id="smh-calendar" viewBox="0 0 24 24"><rect x="3" y="5" width="18" height="16" rx="2"/><path d="M7 2v6M17 2v6M3 11h18M7 15h3M14 15h3"/></symbol>
      <symbol id="smh-people" viewBox="0 0 24 24"><circle cx="9" cy="7" r="4"/><path d="M2 21v-3a7 7 0 0 1 14 0v3M17 3a4 4 0 0 1 0 8M19 14a6 6 0 0 1 3 5v2"/></symbol>
      <symbol id="smh-check" viewBox="0 0 24 24"><path d="m5 12 4 4L19 6"/></symbol>
      <symbol id="smh-menu" viewBox="0 0 24 24"><path d="M4 7h16M4 12h16M4 17h16"/></symbol>
      <symbol id="smh-close" viewBox="0 0 24 24"><path d="m6 6 12 12M18 6 6 18"/></symbol>
      <symbol id="smh-translate" viewBox="0 0 24 24"><path d="M4 5h10M9 3v2m3 0c-.7 4.5-3.3 7.5-7 9m1-6c1 2.4 3.4 4.5 6.4 5.7M14 20l4-9 4 9m-6.3-3h4.6"/></symbol>
    </svg>
    <header class="smh-header" :class="{ 'menu-open': menuOpen }">
      <a class="smh-brand" href="#smh-home" aria-label="Smart Merchant Hub"><BrandLogo icon/><span><strong>Smart Merchant Hub</strong><small>{{ text.footerCopy }}</small></span></a>
      <div class="smh-header-quick-tools">
        <label class="smh-language"><span class="smh-sr-only">{{ text.language }}</span><svg class="smh-language-icon" aria-hidden="true"><use href="#smh-translate"/></svg><select :value="locale" :aria-label="text.language" @change="changeLocale($event.target.value)"><option value="vi">Tiếng Việt</option><option value="en">English</option></select></label>
        <button class="smh-theme-toggle" type="button" :aria-label="props.darkMode ? text.themeLight : text.themeDark" :aria-pressed="props.darkMode" @click="emit('toggle-dark-mode')">{{ props.darkMode ? '☀' : '☾' }}</button>
      </div>
      <button class="smh-menu-button" type="button" :aria-label="menuOpen ? text.close : text.menu" :aria-expanded="menuOpen" aria-controls="smh-navigation" @click="menuOpen = !menuOpen"><svg aria-hidden="true"><use :href="menuOpen ? '#smh-close' : '#smh-menu'"/></svg></button>
      <nav id="smh-navigation" class="smh-nav" :class="{ 'is-open': menuOpen }" :aria-label="text.menu">
        <div class="smh-mobile-menu-head">
          <a class="smh-brand smh-mobile-brand" href="#smh-home" aria-label="Smart Merchant Hub" @click="menuOpen = false"><BrandLogo icon/><span><strong>Smart Merchant Hub</strong></span></a>
          <div class="smh-nav-tools">
            <label class="smh-language"><span class="smh-sr-only">{{ text.language }}</span><svg class="smh-language-icon" aria-hidden="true"><use href="#smh-translate"/></svg><select :value="locale" :aria-label="text.language" @change="changeLocale($event.target.value)"><option value="vi">Tiếng Việt</option><option value="en">English</option></select></label>
            <button class="smh-theme-toggle" type="button" :aria-label="props.darkMode ? text.themeLight : text.themeDark" :aria-pressed="props.darkMode" @click="emit('toggle-dark-mode')">{{ props.darkMode ? '☀' : '☾' }}</button>
          </div>
          <button class="smh-menu-close" type="button" :aria-label="text.close" @click="menuOpen = false"><svg aria-hidden="true"><use href="#smh-close"/></svg></button>
        </div>
        <div class="smh-nav-links"><a v-for="(target, index) in ['smh-product', 'smh-solutions', 'smh-channels', 'smh-faq']" :key="target" :href="`#${target}`" @click.prevent="scrollToSection(target)"><svg aria-hidden="true"><use :href="['#smh-bag', '#smh-people', '#smh-chat', '#smh-book'][index]"/></svg>{{ text.nav[index] }}</a></div>
        <div class="smh-nav-account">
          <button class="smh-login" type="button" @click="act('login')">{{ text.login }}</button>
          <button class="smh-button smh-button-primary smh-nav-cta" type="button" @click="act('signup')">{{ text.signup }}</button>
        </div>
      </nav>
    </header>
    <main id="smh-home">
      <section class="smh-hero smh-container">
        <div class="smh-hero-copy" data-reveal><p class="smh-eyebrow">{{ text.eyebrow }}</p><h1>{{ text.title }}<br/><em>{{ text.titleAccent }}</em></h1><p class="smh-lead">{{ text.intro }}</p><div class="smh-actions"><button class="smh-button smh-button-primary" type="button" @click="act('signup')">{{ text.start }}</button><button class="smh-button smh-button-secondary" type="button" @click="act('plans')">{{ text.plans }}</button></div><p class="smh-small-note">{{ text.note }}</p></div>
        <div class="smh-hero-visual" data-reveal>
          <div class="smh-inbox-window">
            <div class="smh-window-top"><span class="smh-window-dots" aria-hidden="true"><i/><i/><i/></span><span>Smart Merchant Hub</span><BrandLogo icon /></div>
            <div class="smh-window-content"><aside class="smh-mini-sidebar"><svg aria-hidden="true"><use href="#smh-chat"/></svg><svg aria-hidden="true"><use href="#smh-people"/></svg><svg aria-hidden="true"><use href="#smh-bag"/></svg><svg aria-hidden="true"><use href="#smh-calendar"/></svg></aside><div class="smh-chat-preview"><div class="smh-chat-heading"><span class="smh-avatar">MA</span><div><strong>{{ text.customer }}</strong><small>{{ text.active }}</small></div><span class="smh-status-dot"/></div><div class="smh-message-list"><div class="smh-bubble smh-bubble-in smh-enter-one">{{ text.question }}</div><div class="smh-bubble smh-bubble-in smh-enter-two">{{ text.followup }}</div><div class="smh-typing smh-enter-three" :aria-label="text.typing"><i/><i/><i/></div><div class="smh-bubble smh-bubble-out smh-enter-four">{{ text.reply }}</div></div><div class="smh-chat-composer">{{ text.input }}<svg aria-hidden="true"><use href="#smh-chat"/></svg></div></div></div>
          </div>
          <div class="smh-context-note"><span class="smh-note-icon"><svg aria-hidden="true"><use href="#smh-people"/></svg></span><span><strong>{{ text.team }}</strong><small>{{ text.handoff }}</small></span><span class="smh-team-avatars" aria-hidden="true"><i>LN</i><i>HT</i><i>MA</i></span></div>
          <div class="smh-preview-caption"><span>{{ text.caption }}</span></div>
        </div>
      </section>

      <section id="smh-channels" class="smh-channels"><div class="smh-container" data-reveal><p class="smh-eyebrow">{{ text.channelsEyebrow }}</p><h2>{{ text.channelsTitle }}</h2><p>{{ text.channelsCopy }}</p><div class="smh-channel-row smh-channel-brands"><span v-for="(channel,index) in ['Facebook','Instagram','Telegram','Zalo','TikTok','Shopee']" :key="channel" class="smh-channel" :style="{ '--channel-delay': index * -.8 + 's' }"><img :src="'/brand/platforms/' + channel.toLowerCase() + '.svg'" width="40" height="40" alt="" decoding="async"/>{{ channel }}</span></div><small>{{ text.channelNote }}</small></div></section>

      <MarketingStory :paused="motionPaused"/>

      <section id="smh-product" class="smh-product-section"><div class="smh-container"><div class="smh-section-heading" data-reveal><p class="smh-eyebrow">{{ text.tourEyebrow }}</p><h2>{{ text.tourTitle }}<br/><em>{{ text.tourAccent }}</em></h2><p>{{ text.tourIntro }}</p></div><div class="smh-tour-tabs" role="tablist" :aria-label="text.nav[0]"><button v-for="(tab, index) in text.tabs" :id="`smh-tour-tab-${index}`" :key="index" :ref="el => tourButtons[index] = el" type="button" role="tab" :aria-selected="selectedTour === index" :tabindex="selectedTour === index ? 0 : -1" aria-controls="smh-tour-panel" @click="selectTour(index)" @keydown="onTourKey($event,index)"><svg aria-hidden="true"><use :href="['#smh-chat','#smh-book','#smh-calendar'][index]"/></svg>{{ tab }}</button></div>
        <div id="smh-tour-panel" class="smh-tour" role="tabpanel" :aria-labelledby="`smh-tour-tab-${selectedTour}`" tabindex="0">
          <div :key="selectedTour" class="smh-tour-copy"><span class="smh-section-number">0{{ selectedTour + 1 }}</span><h3>{{ text.tourTitles[selectedTour] }}</h3><p>{{ text.tourDescriptions[selectedTour] }}</p><ul><li v-for="item in text.tourBullets[selectedTour]" :key="item"><svg aria-hidden="true"><use href="#smh-check"/></svg>{{ item }}</li></ul><button class="smh-button smh-button-primary" type="button" @click="act('signup')">{{ text.signup }}</button></div>
          <div class="smh-tour-visual" :class="`smh-tour-visual-${selectedTour}`">
            <div v-if="selectedTour === 0" class="smh-demo-inbox smh-demo-surface"><div class="smh-demo-title"><svg aria-hidden="true"><use href="#smh-chat"/></svg>{{ text.inbox }}<span class="smh-demo-dot"/></div><div class="smh-demo-inbox-grid"><div class="smh-demo-contacts"><span class="smh-search-line">{{ text.search }}</span><div v-for="(name,index) in ['Minh Anh','Hà Linh','Quốc Tuấn']" :key="name" :class="{active:index===0}"><span class="smh-avatar">{{ ['MA','HL','QT'][index] }}</span><span><strong>{{ name }}</strong><small>{{ text.active }}</small></span></div></div><div class="smh-demo-chat"><strong>{{ text.customer }}</strong><div class="smh-bubble smh-bubble-in">{{ text.question }}</div><div class="smh-bubble smh-bubble-out">{{ text.reply }}</div><div class="smh-internal-note"><svg aria-hidden="true"><use href="#smh-people"/></svg>{{ text.handoff }}</div></div></div></div>
            <div v-else-if="selectedTour === 1" class="smh-demo-knowledge smh-demo-surface"><div class="smh-demo-title"><svg aria-hidden="true"><use href="#smh-book"/></svg>{{ text.knowledgeTitle }}</div><div v-for="(document,index) in text.documents" :key="document" class="smh-document"><span class="smh-document-icon"><svg aria-hidden="true"><use href="#smh-book"/></svg></span><span><strong>{{ document }}</strong><small>{{ text.ready }}</small></span><span class="smh-document-lines" aria-hidden="true"><i/><i/></span></div><div class="smh-grounded-answer"><small>{{ text.source }}</small><p>{{ text.answer }}</p><span>{{ text.review }}</span></div></div>
            <div v-else class="smh-demo-board smh-demo-surface"><div class="smh-demo-title"><svg aria-hidden="true"><use href="#smh-calendar"/></svg>{{ text.boardTitle }}</div><div class="smh-board-columns"><div v-for="(column,index) in text.boardColumns" :key="column"><h4><i/>{{ column }}</h4><div v-for="offset in [0,1]" :key="offset" class="smh-board-task"><span class="smh-task-line"/><strong>{{ text.boardTasks[index*2+offset] }}</strong><small>{{ ['Minh Anh','Hà Linh','Quốc Tuấn'][index] }}</small><span class="smh-task-avatar">{{ ['MA','HL','QT'][index] }}</span></div></div></div></div>
          </div>
        </div><p class="smh-demo-footnote">{{ text.caption }}</p>
      </div></section>

      <section class="smh-human smh-container"><div class="smh-profile-scene" data-reveal><div class="smh-profile-halo" aria-hidden="true"/><div class="smh-profile-card"><div class="smh-profile-top"><svg aria-hidden="true"><use href="#smh-people"/></svg><strong>{{ text.profileTitle }}</strong></div><div class="smh-profile-person"><span>MA</span><h3>Minh Anh</h3><small>{{ text.profileNote }}</small></div><div class="smh-profile-tags"><span v-for="tag in text.profileLabels" :key="tag">{{ tag }}</span></div><div v-for="(fact,index) in text.profileFacts" :key="fact" class="smh-profile-fact"><svg aria-hidden="true"><use :href="['#smh-chat','#smh-book','#smh-bag','#smh-calendar'][index]"/></svg>{{ fact }}<span aria-hidden="true"/></div></div><div class="smh-profile-orbit smh-profile-orbit-one" aria-hidden="true"><svg><use href="#smh-chat"/></svg></div><div class="smh-profile-orbit smh-profile-orbit-two" aria-hidden="true"><svg><use href="#smh-bag"/></svg></div></div><div class="smh-human-copy" data-reveal><p class="smh-eyebrow">{{ text.humanEyebrow }}</p><h2>{{ text.humanTitle }}<br/><em>{{ text.humanAccent }}</em></h2><p>{{ text.humanCopy }}</p><ul class="smh-check-list"><li v-for="item in text.humanBullets" :key="item"><svg aria-hidden="true"><use href="#smh-check"/></svg>{{ item }}</li></ul></div></section>

      <section id="smh-solutions" class="smh-solutions"><div class="smh-container"><div class="smh-section-heading" data-reveal><p class="smh-eyebrow">{{ text.solutionsEyebrow }}</p><h2>{{ text.solutionsTitle }}<br/><em>{{ text.solutionsAccent }}</em></h2><p>{{ text.solutionsIntro }}</p></div><div class="smh-solution-grid"><article v-for="(solution,index) in text.solutions" :key="index" data-reveal><div class="smh-solution-art" :class="`smh-solution-art-${index}`" aria-hidden="true"><div class="smh-art-grid"/><svg><use :href="`#smh-${solution.icon}`"/></svg><span class="smh-art-circle"/></div><div class="smh-solution-copy"><h3>{{ solution.title }}</h3><p>{{ solution.body }}</p><div><span v-for="tag in solution.tags" :key="tag">{{ tag }}</span></div></div></article></div></div></section>

      <section class="smh-setup smh-container"><div class="smh-section-heading" data-reveal><p class="smh-eyebrow">{{ text.setupEyebrow }}</p><h2>{{ text.setupTitle }}<br/><em>{{ text.setupAccent }}</em></h2></div><ol class="smh-setup-steps"><li v-for="(step,index) in text.steps" :key="index" data-reveal><span>0{{ index+1 }}</span><h3>{{ step.title }}</h3><p>{{ step.body }}</p></li></ol></section>

      <section id="smh-faq" class="smh-faq"><div class="smh-container smh-faq-grid"><div data-reveal><p class="smh-eyebrow">{{ text.faqEyebrow }}</p><h2>{{ text.faqTitle }}</h2><button class="smh-button smh-button-secondary" type="button" @click="act('plans')">{{ text.plans }}</button></div><div class="smh-faq-list"><details v-for="faq in text.faqs" :key="faq.q"><summary>{{ faq.q }}<span aria-hidden="true"/></summary><p>{{ faq.a }}</p></details></div></div></section>

      <section class="smh-final"><div class="smh-container" data-reveal><p class="smh-eyebrow">SMART MERCHANT HUB</p><h2>{{ text.finalTitle }}<br/><em>{{ text.finalAccent }}</em></h2><p>{{ text.finalCopy }}</p><div class="smh-actions"><button class="smh-button smh-button-light" type="button" @click="act('signup')">{{ text.start }}</button><button class="smh-button smh-button-on-dark" type="button" @click="act('plans')">{{ text.plans }}</button></div></div><div class="smh-final-line" aria-hidden="true"/></section>
    </main>
    <footer class="smh-footer"><div class="smh-container smh-footer-main"><div><a class="smh-brand" href="#smh-home" @click.prevent="scrollToSection('smh-home')"><BrandLogo icon/><span><strong>Smart Merchant Hub</strong><small>{{ text.footerCopy }}</small></span></a><p>{{ text.footerNote }}</p></div><div><strong>{{ text.footerProduct }}</strong><a href="#smh-product" @click.prevent="scrollToSection('smh-product')">{{ text.nav[0] }}</a><a href="#smh-solutions" @click.prevent="scrollToSection('smh-solutions')">{{ text.nav[1] }}</a><a href="#smh-channels" @click.prevent="scrollToSection('smh-channels')">{{ text.nav[2] }}</a></div><div><strong>{{ text.footerAccount }}</strong><button type="button" @click="act('login')">{{ text.login }}</button><button type="button" @click="act('signup')">{{ text.signup }}</button><button type="button" @click="act('plans')">{{ text.plans }}</button></div></div><div class="smh-container smh-footer-bottom"><span>© {{ new Date().getFullYear() }} Smart Merchant Hub</span><a href="#smh-faq" @click.prevent="scrollToSection('smh-faq')">{{ text.nav[3] }}</a></div></footer>
  </div>
</template>

<style>
/* The public site owns its scroll container; the CRM keeps its fixed workspace layout. */
.crm-app.public-home { display:block; height:100dvh; min-height:0; width:100%; overflow-x:hidden; overflow-y:auto; background:#f8faf6; scroll-behavior:smooth; scroll-padding-top:100px; }
.smh-site { --smh-ink:#163d3e; --smh-muted:#596f70; --smh-teal:#087e77; --smh-line:#d8e5df; --smh-cream:#f8faf6; color:var(--smh-ink); background:var(--smh-cream); font-family:var(--font-ui); line-height:1.6; overflow-x:clip; }
.smh-site * { box-sizing:border-box; }.smh-site svg { width:24px; height:24px; fill:none; stroke:currentColor; stroke-width:1.6; stroke-linecap:round; stroke-linejoin:round; flex-shrink:0; }.smh-site .smh-symbols { position:absolute; width:0; height:0; overflow:hidden; }
.smh-site :is(h1,h2,h3,h4,p) { margin:0; }.smh-site button,.smh-site select { font:inherit; }.smh-site button { cursor:pointer; }.smh-site a { color:inherit; text-decoration:none; }.smh-site :is(a,button,select,summary,[tabindex]):focus-visible { outline:3px solid #b17736; outline-offset:5px; }.smh-site .smh-sr-only { position:absolute; width:1px; height:1px; margin:-1px; overflow:hidden; clip:rect(0,0,0,0); white-space:nowrap; }
.smh-container { width:min(1200px,calc(100% - 80px)); margin-inline:auto; }.smh-announcement { min-height:32px; padding:6px 20px; background:#153f40; color:#edf8ef; text-align:center; font-size:11px; letter-spacing:.035em; }
.smh-header { position:sticky; top:0; z-index:30; display:flex; align-items:center; justify-content:space-between; min-height:83px; gap:24px; padding:12px max(32px,calc((100% - 1200px)/2)); border-bottom:1px solid #dfe9e3; background:rgba(248,250,246,.96); backdrop-filter:blur(12px); }
.smh-brand { display:inline-flex; align-items:center; gap:10px; flex-shrink:0; }.smh-brand-mark { display:grid; place-items:center; width:42px; height:42px; border-radius:11px; color:#fff; background:#087e77; }.smh-brand-mark svg { width:26px; height:26px; }.smh-brand strong { display:block; font-size:15px; font-weight:800; letter-spacing:-.04em; }.smh-brand small { display:block; color:var(--smh-muted); font-size:10px; }
.smh-nav { display:flex; align-items:center; gap:22px; font-size:12px; font-weight:650; }.smh-nav > a { white-space:nowrap; }.smh-nav > a:hover,.smh-login:hover { color:#0a8b80; }.smh-language { position:relative; display:inline-flex; align-items:center; flex:0 0 auto; }.smh-language::after { position:absolute; right:14px; width:7px; height:7px; border-right:1.5px solid #416b66; border-bottom:1.5px solid #416b66; content:""; pointer-events:none; transform:translateY(-2px) rotate(45deg); }.smh-language select { min-width:124px; min-height:42px; padding:0 36px 0 14px; appearance:none; border:1px solid #d0e1db; border-radius:10px; color:var(--smh-ink); background:#fff; font-size:13px; font-weight:700; line-height:1; cursor:pointer; transition:background .16s,border-color .16s,box-shadow .16s; }.smh-language select:hover { border-color:#96beb4; background:#f5faf8; }.smh-language select:focus-visible { border-color:#0a8980; outline:2px solid rgba(10,137,128,.24); outline-offset:2px; }.smh-login { border:0; background:transparent; padding:10px 0; color:var(--smh-ink); white-space:nowrap; font-weight:750; }.smh-menu-button { display:none; width:44px; height:44px; place-items:center; border:1px solid var(--smh-line); border-radius:8px; color:var(--smh-ink); background:white; }
.smh-button { display:inline-flex; align-items:center; justify-content:center; min-height:49px; padding:12px 22px; border:1px solid transparent; border-radius:7px; font-size:13px; font-weight:750; text-align:center; line-height:1.4; transition:background .2s,color .2s,box-shadow .2s; }.smh-button-primary { color:#fff; background:var(--smh-teal); }.smh-button-primary:hover { background:#076a65; box-shadow:0 5px 18px #086f6b20; }.smh-button-secondary { color:#195451; border-color:#88b4aa; background:transparent; }.smh-button-secondary:hover { background:#e6f2eb; }.smh-nav-cta { min-height:42px; padding:9px 15px; font-size:12px; }.smh-actions { display:flex; flex-wrap:wrap; gap:12px; margin-top:29px; }.smh-small-note { margin-top:17px!important; color:#647b77; font-size:11px; max-width:410px; }
.smh-eyebrow { color:#357871; font-size:10px; font-weight:800; letter-spacing:.13em; line-height:1.7; }.smh-hero { display:grid; grid-template-columns:.9fr 1.1fr; gap:70px; align-items:center; padding-block:88px 100px; }.smh-hero h1 { margin-top:19px; font-family:var(--font-ui); font-size:clamp(43px,4.4vw,66px); line-height:1.09; font-weight:700; letter-spacing:-.05em; text-wrap:balance; }.smh-site h1 em,.smh-site h2 em { color:#13847b; font-style:italic; font-weight:650; }.smh-lead { margin-top:23px!important; font-size:15px; line-height:1.85; color:var(--smh-muted); max-width:445px; }
.smh-hero-visual { position:relative; min-width:0; padding:20px 0 45px; }.smh-hero-visual::before { content:""; position:absolute; inset:-5px -15px 10px 20px; border:1px solid #c1dcd0; border-radius:20px; background:#e6f0e9; transform:rotate(4deg); }.smh-inbox-window { position:relative; border:1px solid #c7ded4; border-radius:13px; overflow:hidden; background:white; box-shadow:0 20px 50px #23565320; }.smh-window-top { display:flex; align-items:center; justify-content:space-between; gap:10px; height:43px; padding:0 15px; color:#6b8580; border-bottom:1px solid #e4ece7; font-size:9px; }.smh-window-top > svg { width:15px;height:15px; }.smh-window-dots { display:flex; gap:5px; }.smh-window-dots i { width:6px; height:6px; border-radius:50%; background:#c9d9d1; }.smh-window-dots i:first-child { background:#dcaf86; }
.smh-window-content { display:grid; grid-template-columns:51px minmax(0,1fr); min-height:346px; }.smh-mini-sidebar { display:flex; flex-direction:column; align-items:center; gap:27px; padding-top:22px; color:#99b4ab; border-right:1px solid #e3ece6; background:#f7faf6; }.smh-mini-sidebar svg { width:18px; height:18px; }.smh-mini-sidebar svg:first-child { color:#087e77; }.smh-chat-preview { min-width:0; display:flex; flex-direction:column; }.smh-chat-heading { display:flex; align-items:center; gap:9px; padding:13px 19px; border-bottom:1px solid #e7eeea; }.smh-avatar { display:grid; place-items:center; width:32px; height:32px; border-radius:50%; background:#ddede4; color:#386d65; font-size:10px; font-weight:700; flex-shrink:0; }.smh-chat-heading strong { display:block; font-size:11px; }.smh-chat-heading small { display:block; color:#6d847d; font-size:9px; }.smh-status-dot { margin-left:auto; width:6px; height:6px; border-radius:50%; background:#259582; }.smh-message-list { display:flex; flex:1; flex-direction:column; align-items:flex-start; gap:9px; padding:23px 20px; background:#fcfdfb; }.smh-bubble { padding:11px 13px; max-width:85%; font-size:11px; line-height:1.7; border-radius:10px; }.smh-bubble-in { background:#f0f3ed; border:1px solid #e5ebe1; border-bottom-left-radius:2px; color:#47605b; }.smh-bubble-out { align-self:flex-end; background:#d8eee5; color:#305e53; border-bottom-right-radius:2px; }.smh-typing { display:flex; align-items:center; gap:4px; height:18px; margin-left:5px; }.smh-typing i { width:4px; height:4px; border-radius:50%; background:#8bad9e; animation:smh-dot 1.8s ease-in-out infinite; }.smh-typing i:nth-child(2) { animation-delay:.18s; }.smh-typing i:nth-child(3) { animation-delay:.36s; }.smh-chat-composer { display:flex; align-items:center; justify-content:space-between; height:38px; padding:0 19px; border-top:1px solid #e5ede7; font-size:9px; color:#8b9f94; }.smh-chat-composer svg { width:15px; height:15px; }
.smh-context-note { position:absolute; display:flex; align-items:center; gap:10px; right:-15px; bottom:15px; padding:13px 16px; background:#fff; border:1px solid #d5e3da; border-radius:10px; box-shadow:0 15px 35px #16463f16; }.smh-note-icon { display:grid; place-items:center; width:34px; height:34px; color:#658356; background:#edf2df; border-radius:8px; }.smh-note-icon svg { width:19px; height:19px; }.smh-context-note strong { display:block; font-size:10px; }.smh-context-note small { display:block; color:#758b7f; font-size:8px; }.smh-team-avatars { display:flex; margin-left:15px; }.smh-team-avatars i { display:grid; place-items:center; width:24px; height:24px; margin-left:-6px; border:2px solid white; border-radius:50%; background:#dde6d7; color:#657756; font-size:6px; font-style:normal; }.smh-team-avatars i:nth-child(2) { background:#eee0d0; }.smh-team-avatars i:nth-child(3) { background:#d2e8e1; }
.smh-preview-caption { position:absolute; bottom:-18px; left:0; right:0; display:flex; justify-content:space-between; align-items:center; gap:10px; color:#698077; font-size:9px; }.smh-enter-one { animation:smh-message .7s both .15s; }.smh-enter-two { animation:smh-message .7s both .5s; }.smh-enter-three { animation:smh-message .7s both .8s; }.smh-enter-four { animation:smh-message .7s both 1.1s; }
.smh-channels { padding-block:46px 50px; text-align:center; background:#edf4ee; border-block:1px solid #dce7de; }.smh-channels h2 { margin-top:10px; font-size:25px; font-weight:500; letter-spacing:-.035em; }.smh-channels p:not(.smh-eyebrow) { max-width:570px; margin:11px auto 0; color:var(--smh-muted); font-size:13px; }.smh-channel-row { display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:22px 38px; margin:30px 0 20px; }.smh-channel { display:flex; gap:9px; align-items:center; font-size:13px; font-weight:750; }.smh-channel i { display:grid; place-items:center; width:28px; height:28px; border-radius:7px; font-style:normal; font-size:17px; color:white; }.smh-channel .facebook { background:#1877f2; font-family:Arial,sans-serif; font-weight:800; }.smh-channel .instagram { background:linear-gradient(35deg,#e7a653,#cc4f8b); }.smh-channel .telegram { background:#3296c0; font-size:12px; }.smh-channel .zalo { background:#1d7bde; }.smh-channel .tiktok { background:#20232c; }.smh-channel .shopee { background:#ec6541; }.smh-channels small { color:#637a6c; font-size:10px; }
.smh-story { display:grid; grid-template-columns:1.14fr .86fr; gap:65px; align-items:center; padding-block:105px; }.smh-story-photo { position:relative; overflow:hidden; border-radius:12px; aspect-ratio:1.28; }.smh-story-photo img { display:block; width:100%; height:100%; object-fit:cover; object-position:51% 45%; transition:transform .8s ease; }.smh-story-photo:hover img { transform:scale(1.035); }.smh-photo-label { position:absolute; left:20px; bottom:18px; padding:7px 11px; color:#fff; background:#17473cbd; backdrop-filter:blur(4px); border-radius:5px; font-size:10px; }.smh-site h2 { font-family:var(--font-ui); font-size:clamp(32px,3.2vw,46px); font-weight:700; line-height:1.2; letter-spacing:-.035em; text-wrap:balance; }.smh-story h2 { margin-top:16px; }.smh-story-copy > p:not(.smh-eyebrow) { margin-top:23px; color:var(--smh-muted); font-size:14px; line-height:1.85; }.smh-story-line { display:flex; gap:7px; margin-top:35px; }.smh-story-line span { width:38px; height:3px; border-radius:3px; background:#c7d8c4; }.smh-story-line span:first-child { width:80px; background:#168675; }
.smh-product-section { padding-block:85px 72px; background:#f0f4ec; border-block:1px solid #dde5d8; }.smh-section-heading { text-align:center; max-width:650px; margin-inline:auto; }.smh-section-heading h2 { margin-top:14px; }.smh-section-heading > p:not(.smh-eyebrow) { margin:19px auto 0; max-width:500px; color:var(--smh-muted); font-size:14px; }.smh-tour-tabs { display:flex; align-items:center; justify-content:center; gap:7px; margin:35px 0; }.smh-tour-tabs button { display:flex; align-items:center; gap:8px; padding:11px 18px; min-height:46px; border:1px solid transparent; border-radius:7px; color:#627c6c; background:transparent; font-size:12px; font-weight:650; }.smh-tour-tabs button[aria-selected="true"] { color:#1f5f53; background:white; border-color:#cbdcd0; box-shadow:0 4px 11px #234b3010; }.smh-tour-tabs svg { width:18px; height:18px; }
.smh-tour { display:grid; grid-template-columns:.8fr 1.2fr; gap:65px; align-items:center; }.smh-tour-copy { animation:smh-message .4s both; }.smh-section-number { font-family:Georgia,serif; font-size:19px; color:#94aa88; }.smh-tour h3 { margin-top:15px; max-width:360px; font-size:28px; line-height:1.35; font-weight:550; letter-spacing:-.04em; }.smh-tour-copy p { margin-top:17px; color:var(--smh-muted); font-size:13px; line-height:1.8; }.smh-tour-copy ul,.smh-check-list { list-style:none; padding:0; margin:22px 0 27px; }.smh-tour-copy li,.smh-check-list li { display:flex; align-items:flex-start; gap:9px; margin-top:11px; font-size:12px; color:#40665a; }.smh-tour-copy li svg,.smh-check-list svg { width:16px; height:19px; color:#20836d; }.smh-tour-visual { display:grid; align-items:center; min-height:365px; padding:28px; background:#dce8d9; border-radius:12px; overflow:hidden; }.smh-tour-visual-1 { background:#e6e8f0; }.smh-tour-visual-2 { background:#f2e6d4; }.smh-demo-surface { overflow:hidden; min-width:0; border:1px solid #d2dfd5; border-radius:9px; background:white; box-shadow:0 15px 25px #314b3114; animation:smh-message .4s both; }.smh-demo-title { display:flex; align-items:center; gap:8px; padding:13px 15px; border-bottom:1px solid #e6eee8; font-size:11px; font-weight:750; }.smh-demo-title svg { width:17px; height:17px; color:#468778; }.smh-demo-dot { width:5px; height:5px; margin-left:auto; background:#348b6d; border-radius:50%; }.smh-demo-inbox-grid { display:grid; grid-template-columns:38% 62%; min-height:265px; }.smh-demo-contacts { padding:12px 7px; border-right:1px solid #e4eee5; }.smh-search-line { display:block; padding:4px 8px 12px; color:#8b9d90; font-size:9px; }.smh-demo-contacts > div { display:flex; align-items:center; gap:6px; padding:10px 7px; border-radius:5px; }.smh-demo-contacts > div.active { background:#e6f2e9; }.smh-demo-contacts .smh-avatar { width:25px; height:25px; font-size:8px; }.smh-demo-contacts strong { display:block; font-size:9px; }.smh-demo-contacts small { display:block; font-size:8px; color:#758b7d; }.smh-demo-chat { display:flex; flex-direction:column; align-items:flex-start; gap:13px; padding:17px 13px; background:#f9fbf7; }.smh-demo-chat > strong { font-size:10px; }.smh-demo-chat .smh-bubble { padding:9px; max-width:95%; font-size:9px; }.smh-internal-note { display:flex; align-items:center; gap:5px; padding:6px 8px; border:1px solid #e5d4a9; border-radius:5px; background:#faf4df; color:#8a7646; font-size:8px; }.smh-internal-note svg { width:13px;height:13px; }
.smh-demo-knowledge { padding-bottom:16px; }.smh-document { display:flex; align-items:center; gap:10px; margin:11px 16px; padding:7px 0; border-bottom:1px solid #eef0f3; }.smh-document-icon { display:grid; place-items:center; width:31px; height:35px; border-radius:5px; background:#eceef5; color:#7c89a5; }.smh-document-icon svg { width:17px;height:17px; }.smh-document strong { display:block; font-size:10px; }.smh-document small { display:block; font-size:8px; color:#7b8d7b; }.smh-document-lines { display:grid; gap:5px; width:48px; margin-left:auto; }.smh-document-lines i { height:3px; background:#e3e7ec; border-radius:3px; }.smh-document-lines i:last-child { width:70%; }.smh-grounded-answer { padding:13px; margin:15px 16px 0; background:#f1f4fb; border:1px solid #dce3ef; border-radius:7px; }.smh-grounded-answer small { color:#76829b; font-size:8px; }.smh-grounded-answer p { margin-block:5px 10px; font-size:10px; color:#5a6780; line-height:1.8; }.smh-grounded-answer > span { padding:3px 6px; background:white; color:#6b7991; border-radius:4px; font-size:8px; }
.smh-demo-board { padding-bottom:12px; }.smh-board-columns { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:9px; padding:14px 12px; background:#fafbf8; }.smh-board-columns h4 { display:flex; align-items:center; gap:4px; margin-bottom:11px; font-size:8px; color:#6d806c; }.smh-board-columns h4 i { width:5px;height:5px;background:#cea76b;border-radius:50%; }.smh-board-columns > div:nth-child(2) h4 i { background:#8198b5; }.smh-board-columns > div:nth-child(3) h4 i { background:#7aab83; }.smh-board-task { padding:10px 8px; margin-top:8px; border:1px solid #e1e8df; border-radius:5px; background:white; }.smh-task-line { display:block; width:22px;height:3px;background:#d9c69e;border-radius:3px;margin-bottom:8px; }.smh-board-task strong { display:block; font-size:9px; font-weight:650; line-height:1.5; }.smh-board-task small { display:block; margin:9px 0 5px; color:#91a08e; font-size:8px; }.smh-task-avatar { display:grid;place-items:center;width:18px;height:18px;border-radius:50%;background:#e9eee3;color:#738467;font-size:6px; }.smh-demo-footnote { margin-top:22px!important;text-align:right;color:#72866d;font-size:9px; }
.smh-human { display:grid; grid-template-columns:1fr 1fr; align-items:center; gap:90px; padding-block:105px; }.smh-human-copy h2 { margin-top:15px; }.smh-human-copy > p:not(.smh-eyebrow) { margin-top:23px; font-size:14px; color:var(--smh-muted); line-height:1.85; }.smh-profile-scene { position:relative; padding:30px 65px; }.smh-profile-halo { position:absolute; inset:14px 6px; background:#eef1de; border-radius:50%; }.smh-profile-card { position:relative; padding:20px; border:1px solid #d6dfcb; border-radius:12px; background:white; box-shadow:0 20px 40px #45603112; }.smh-profile-top { display:flex; align-items:center; gap:8px; padding-bottom:15px; border-bottom:1px solid #e5ebdf; font-size:11px; }.smh-profile-top svg { width:18px;height:18px;color:#7f9165; }.smh-profile-person { text-align:center; padding-top:21px; }.smh-profile-person > span { display:grid;place-items:center;width:65px;height:65px;margin:0 auto 8px;border-radius:50%;background:#e8eedb;color:#788f56;font-family:Georgia,serif;font-size:23px; }.smh-profile-person h3 { font-size:15px;font-weight:650; }.smh-profile-person small { color:#899875;font-size:9px; }.smh-profile-tags { display:flex;flex-wrap:wrap;justify-content:center;gap:5px;margin:15px 0 20px; }.smh-profile-tags span { padding:4px 8px; color:#6a8060; background:#f1f5e9; border-radius:4px; font-size:8px; }.smh-profile-fact { display:flex;align-items:center;gap:7px;min-height:40px;border-top:1px solid #eaf0e4;color:#728069;font-size:10px; }.smh-profile-fact svg { width:15px;height:15px; }.smh-profile-fact > span { width:22px;height:3px;margin-left:auto;background:#dce6cc;border-radius:3px; }.smh-profile-orbit { position:absolute;display:grid;place-items:center;width:53px;height:53px;border:1px solid #dce3d1;border-radius:13px;background:#fff;box-shadow:0 10px 20px #566a3b12;color:#829759;animation:smh-float 6s ease-in-out infinite; }.smh-profile-orbit-one { left:12px;top:25%; }.smh-profile-orbit-two { right:7px;bottom:22%;animation-delay:-3s; }
.smh-solutions { padding-block:85px 95px; background:#f6f1e8; border-block:1px solid #e8e0d1; }.smh-solution-grid { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:22px;margin-top:38px; }.smh-solution-grid article { overflow:hidden;border:1px solid #e5dece;border-radius:10px;background:#fffcf7; }.smh-solution-art { position:relative;display:grid;place-items:center;height:180px;background:#e3eade;overflow:hidden; }.smh-solution-art-1 { background:#e1e8ed; }.smh-solution-art-2 { background:#eee1d0; }.smh-art-grid { position:absolute;inset:0;background-image:linear-gradient(#ffffff52 1px,transparent 1px),linear-gradient(90deg,#ffffff52 1px,transparent 1px);background-size:33px 33px;mask-image:radial-gradient(ellipse,#000,transparent 72%); }.smh-solution-art > svg { z-index:1;width:67px;height:67px;stroke-width:.9;color:#527258;transform:rotate(-6deg); }.smh-solution-art-1 > svg { color:#647c92;transform:rotate(6deg); }.smh-solution-art-2 > svg { color:#aa8560; }.smh-art-circle { position:absolute;left:calc(50% - 68px);top:calc(50% - 58px);width:116px;height:116px;border:1px solid #9bb290;border-radius:50%; }.smh-solution-art-1 .smh-art-circle { border-color:#a3b5c4; }.smh-solution-art-2 .smh-art-circle { border-color:#d2b595; }.smh-solution-copy { padding:25px; }.smh-solution-copy h3 { font-size:18px;font-weight:600;letter-spacing:-.025em; }.smh-solution-copy p { margin-top:11px;font-size:12px;line-height:1.85;color:#787566; }.smh-solution-copy > div { display:flex;flex-wrap:wrap;gap:5px;margin-top:20px; }.smh-solution-copy > div span { padding:4px 7px;background:#f1ece0;color:#837c68;border-radius:4px;font-size:9px; }
.smh-setup { padding-block:95px; }.smh-setup-steps { display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:45px;list-style:none;margin:43px 0 0;padding:0; }.smh-setup-steps li { padding-top:22px;border-top:1px solid #bcd4c4; }.smh-setup-steps li > span { color:#4b8e7b;font-family:Georgia,serif;font-size:25px; }.smh-setup-steps h3 { margin-top:16px;font-size:17px;font-weight:600; }.smh-setup-steps p { margin-top:10px;color:var(--smh-muted);font-size:12px;line-height:1.85; }
.smh-faq { padding-block:75px 90px;border-top:1px solid var(--smh-line);background:#f1f5ee; }.smh-faq-grid { display:grid;grid-template-columns:.82fr 1.18fr;gap:90px; }.smh-faq h2 { margin-block:16px 29px; }.smh-faq-list details { border-bottom:1px solid #d5e2d6; }.smh-faq-list details:first-child { border-top:1px solid #d5e2d6; }.smh-faq-list summary { display:flex;justify-content:space-between;align-items:center;gap:20px;min-height:72px;padding:18px 0;list-style:none;cursor:pointer;font-size:13px;font-weight:650;color:#345b4d; }.smh-faq-list summary::-webkit-details-marker { display:none; }.smh-faq-list summary > span { position:relative;flex-shrink:0;width:15px;height:15px; }.smh-faq-list summary > span::before,.smh-faq-list summary > span::after { content:"";position:absolute;top:7px;left:2px;width:11px;height:1px;background:#739781; }.smh-faq-list summary > span::after { transform:rotate(90deg);transition:transform .2s; }.smh-faq-list details[open] summary > span::after { transform:rotate(0); }.smh-faq-list details > p { padding:0 27px 22px 0;color:#687d6c;font-size:12px;line-height:1.9; }
.smh-final { position:relative;overflow:hidden;padding-block:86px 94px;background:#174e49;color:#eef8ed;text-align:center; }.smh-final .smh-container { position:relative;z-index:1; }.smh-final .smh-eyebrow { color:#aad4bb; }.smh-final h2 { margin-top:17px;font-size:clamp(37px,4vw,55px); }.smh-final h2 em { color:#bbdfbd; }.smh-final > div > p:not(.smh-eyebrow) { max-width:475px;margin:22px auto 0;color:#c2d8c8;font-size:13px; }.smh-final .smh-actions { justify-content:center; }.smh-button-light { color:#18564b;background:#e6f3df; }.smh-button-light:hover { background:white; }.smh-button-on-dark { color:#e6f2e5;border-color:#86ac94;background:transparent; }.smh-button-on-dark:hover { background:#28665c; }.smh-final-line { position:absolute;width:850px;height:850px;border:1px solid #9ebd8620;border-radius:50%;right:-550px;top:-200px;box-shadow:0 0 0 70px #9ebd8608,0 0 0 140px #9ebd8605; }
.smh-footer { background:#f8faf6; }.smh-footer-main { display:grid;grid-template-columns:2fr 1fr 1fr;gap:55px;padding-block:55px; }.smh-footer-main > div > p { margin-top:18px;max-width:280px;color:#7e8e7c;font-size:10px; }.smh-footer-main > div > strong { display:block;margin-bottom:13px;font-size:11px; }.smh-footer-main > div > a:not(.smh-brand),.smh-footer-main button { display:block;width:fit-content;padding:5px 0;border:0;background:transparent;color:#6e8074;font-size:11px;text-align:left; }.smh-footer-main button:hover,.smh-footer-main a:hover { color:#087e77; }.smh-footer-bottom { display:flex;justify-content:space-between;padding-block:19px;border-top:1px solid #dfe8dd;color:#82917d;font-size:9px; }
.smh-site.has-reveal [data-reveal] { opacity:0;transform:translateY(20px);transition:opacity .7s ease,transform .7s cubic-bezier(.2,.7,.3,1); }.smh-site.has-reveal [data-reveal].is-visible { opacity:1;transform:none; }.smh-site.motion-paused [data-reveal] { opacity:1;transform:none;transition:none; }.smh-site.motion-paused * { animation:none!important; }.smh-site.motion-paused .smh-story-photo img { transition:none; }
.smh-site :is(h1,h2) { font-family:var(--font-ui); letter-spacing:-.025em; }
@keyframes smh-message { from { opacity:0;transform:translateY(8px); } to { opacity:1;transform:translateY(0); } }@keyframes smh-dot { 0%,65%,100% { transform:translateY(0);opacity:.5; } 30% { transform:translateY(-3px);opacity:1; } }@keyframes smh-float { 0%,100% { transform:translateY(0); } 50% { transform:translateY(-7px); } }
@media(max-width:1100px) { .smh-nav { gap:14px; }.smh-header { padding-inline:28px; }.smh-hero { gap:40px; }.smh-human { gap:40px; }.smh-profile-scene { padding-inline:45px; }.smh-story,.smh-tour { gap:40px; }.smh-faq-grid { gap:45px; } }
@media(max-width:900px) { .smh-container { width:calc(100% - 48px); }.smh-menu-button { display:grid; }.smh-header { min-height:72px;padding-inline:24px; }.smh-nav { display:none;position:absolute;top:100%;left:0;right:0;flex-direction:column;align-items:stretch;gap:0;padding:12px 24px 22px;background:#f8faf6;border-bottom:1px solid var(--smh-line);box-shadow:0 12px 20px #23412e10; }.smh-nav.is-open { display:flex; }.smh-nav > a,.smh-login { min-height:44px;display:flex;align-items:center;padding:9px 0; }.smh-language { padding-block:5px; }.smh-nav-cta { margin-top:8px; }.smh-hero { grid-template-columns:1fr 1fr;gap:25px;padding-block:65px 85px; }.smh-hero h1 { font-size:45px; }.smh-lead { font-size:13px; }.smh-actions { flex-direction:column;align-items:stretch; }.smh-context-note { right:-7px;padding:10px; }.smh-team-avatars { display:none; }.smh-bubble { max-width:95%;font-size:10px; }.smh-window-content { grid-template-columns:37px minmax(0,1fr); }.smh-message-list { padding-inline:11px; }.smh-story { gap:28px;padding-block:80px; }.smh-tour { gap:25px;grid-template-columns:.8fr 1.2fr; }.smh-tour-visual { padding:18px; }.smh-tour h3 { font-size:24px; }.smh-human { gap:25px;padding-block:80px; }.smh-profile-scene { padding-inline:25px; }.smh-profile-orbit { width:39px;height:39px; }.smh-solution-grid { gap:14px; }.smh-solution-copy { padding:19px; }.smh-solution-copy h3 { font-size:16px; }.smh-solution-art { height:150px; }.smh-setup-steps { gap:25px; }.smh-final .smh-actions { flex-direction:row; }.smh-faq-grid { gap:35px; }.smh-site h2 { font-size:34px; } }
@media(max-width:680px) { .smh-container { width:calc(100% - 40px); }.smh-announcement { font-size:9px;padding-inline:18px; }.smh-header { padding-inline:20px;min-height:67px; }.smh-brand strong { font-size:14px; }.smh-brand small { font-size:9px; }.smh-hero { grid-template-columns:1fr;gap:38px;padding-block:49px 72px; }.smh-hero h1 { font-size:clamp(42px,9.5vw,59px); }.smh-lead { font-size:14px;max-width:490px; }.smh-hero .smh-actions { flex-direction:row; }.smh-hero .smh-actions .smh-button { flex:1; }.smh-hero-visual { width:min(100%,470px);margin:auto; }.smh-window-content { min-height:325px;grid-template-columns:43px minmax(0,1fr); }.smh-bubble { font-size:11px; }.smh-message-list { padding-inline:17px; }.smh-context-note { right:-5px; }.smh-channels { padding-block:37px; }.smh-channels h2 { font-family:Inter,sans-serif;font-size:21px; }.smh-channel-row { gap:20px 27px; }.smh-channel { font-size:11px; }.smh-story { grid-template-columns:1fr;gap:30px;padding-block:65px; }.smh-story-photo { aspect-ratio:1.36; }.smh-story h2 { font-size:35px; }.smh-story-line { margin-top:23px; }.smh-product-section { padding-block:63px 52px; }.smh-site h2 { font-size:34px; }.smh-eyebrow { font-size:9px; }.smh-tour-tabs { gap:4px;align-items:stretch;margin:27px 0; }.smh-tour-tabs button { flex:1;flex-direction:column;justify-content:center;gap:5px;padding:9px 5px;min-width:0;font-size:10px; }.smh-tour { grid-template-columns:1fr;gap:27px; }.smh-tour h3 { max-width:none;font-size:25px; }.smh-tour-copy > .smh-button { width:100%; }.smh-tour-visual { min-height:325px;padding:18px; }.smh-human { grid-template-columns:1fr;gap:30px;padding-block:62px; }.smh-profile-scene { width:min(100%,425px);margin-inline:auto;padding:25px 42px; }.smh-profile-orbit { width:47px;height:47px; }.smh-human-copy h2 { font-size:35px; }.smh-solutions { padding-block:61px; }.smh-solution-grid { grid-template-columns:1fr;gap:21px; }.smh-solution-art { height:190px; }.smh-solution-copy { padding:24px; }.smh-solution-copy h3 { font-size:19px; }.smh-solution-copy p { font-size:13px; }.smh-setup { padding-block:65px; }.smh-setup-steps { grid-template-columns:1fr;gap:27px;margin-top:29px; }.smh-setup-steps li { display:grid;grid-template-columns:45px 1fr;gap:6px 15px; }.smh-setup-steps li > span { grid-row:span 2; }.smh-setup-steps h3 { margin:0; }.smh-setup-steps p { margin:0; }.smh-faq { padding-block:58px; }.smh-faq-grid { grid-template-columns:1fr;gap:30px; }.smh-faq h2 { margin-bottom:22px; }.smh-faq-list summary { font-size:12px; }.smh-final { padding-block:65px; }.smh-final h2 { font-size:37px; }.smh-final .smh-actions { flex-direction:column; }.smh-footer-main { grid-template-columns:1fr 1fr;gap:30px;padding-block:39px; }.smh-footer-main > div:first-child { grid-column:1/-1; }.smh-footer-main > div > a:not(.smh-brand),.smh-footer-main button { min-height:36px; } }
@media(prefers-reduced-motion:reduce) { .crm-app.public-home { scroll-behavior:auto; }.smh-site *, .smh-site *::before,.smh-site *::after { animation:none!important;transition:none!important; }.smh-site.has-reveal [data-reveal] { opacity:1;transform:none; } }
</style>
<style>
/* Typography is deliberately uniform: chat, CRM and public pages use the same Vietnamese-first family. */
.smh-site :is(.smh-section-number, .smh-profile-person > span, .smh-setup-steps li > span) { font-family:var(--font-ui); font-weight:650; }
.smh-site .smh-tour h3 { font-weight:600; }
@media(max-width:680px) { .smh-site .smh-channels h2 { font-family:var(--font-ui); } }
</style>
<style>
.smh-channel-brands{gap:18px!important;margin:36px 0 28px!important}.smh-channel-brands .smh-channel{flex-direction:column;justify-content:center;gap:14px;width:138px;min-height:120px;border:1px solid #d8e6df;border-radius:14px;background:#fff;box-shadow:0 8px 22px #174f4310;animation:smh-brand-float 5s ease-in-out infinite;animation-delay:var(--channel-delay)}.smh-channel-brands img{width:40px;height:40px;object-fit:contain}.smh-channel-brands:hover .smh-channel{animation-play-state:paused}@keyframes smh-brand-float{0%,100%{transform:translateY(0)}50%{transform:translateY(-6px)}}@media(max-width:680px){.smh-channel-brands{display:grid!important;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px!important}.smh-channel-brands .smh-channel{width:auto;min-height:106px;font-size:12px}}@media(prefers-reduced-motion:reduce){.smh-channel-brands .smh-channel{animation:none}}
</style>
<style>
.smh-theme-toggle { display:grid;place-items:center;width:40px;height:40px;flex:none;border:1px solid var(--smh-line);border-radius:9px;background:transparent;color:var(--smh-ink);font-size:20px; }
.smh-theme-toggle:hover { background:#e7f1eb; }
.smh-nav { font-size:13px; }
.smh-site .smh-announcement { font-size:12px; }
.smh-site .smh-eyebrow { font-size:11px; }
.smh-footer-main > div > p { font-size:12px;line-height:1.7; }
.smh-footer-main > div > strong,.smh-footer-main > div > a:not(.smh-brand),.smh-footer-main button { font-size:13px; }
.smh-footer-bottom { font-size:12px; }
.smh-site .smh-small-note,.smh-site .smh-pricing-note { font-size:12px; }
.smh-site [id^="smh-"] { scroll-margin-top:100px; }
.crm-app.public-home.crm-dark { color:#e8f0ec;background:#14191b; }
.crm-app.public-home.crm-dark .smh-site { --smh-ink:#edf4f0;--smh-muted:#bdcbc4;--smh-line:#3e514c;--smh-cream:#171e20;color:var(--smh-ink);background:#171e20; }
.crm-app.public-home.crm-dark .smh-announcement { color:#eaf5ef;background:#173d3c; }
.crm-app.public-home.crm-dark .smh-header,.crm-app.public-home.crm-dark .smh-footer { color:#eaf2ed;background:#1b2324;border-color:#3b4948; }
.crm-app.public-home.crm-dark .smh-nav { color:#e3ece7; }
.crm-app.public-home.crm-dark .smh-language select { color:#e3ece7;background:#222d2e;border-color:#485957;color-scheme:dark; }
.crm-app.public-home.crm-dark .smh-language::after { border-color:#b1ddd2; }
.crm-app.public-home.crm-dark .smh-language select:hover { background:#293839;border-color:#71b9ab; }
.crm-app.public-home.crm-dark .smh-language select:focus-visible { border-color:#83d8c4;outline-color:rgba(131,216,196,.3); }
.crm-app.public-home.crm-dark .smh-login { color:#e3ece7;background:transparent; }
.crm-app.public-home.crm-dark .smh-menu-button,.crm-app.public-home.crm-dark .smh-theme-toggle { color:#e6f1eb;background:#222d2e;border-color:#485957; }
.crm-app.public-home.crm-dark .smh-channels,.crm-app.public-home.crm-dark .smh-product-section,.crm-app.public-home.crm-dark .smh-solutions,.crm-app.public-home.crm-dark .smh-faq { color:#e7f0eb;background:#20292a;border-color:#3a4a49; }
.crm-app.public-home.crm-dark .smh-hero-visual::before,.crm-app.public-home.crm-dark .smh-tour-visual,.crm-app.public-home.crm-dark .smh-tour-visual-1,.crm-app.public-home.crm-dark .smh-tour-visual-2 { background:#263334;border-color:#435957; }
.crm-app.public-home.crm-dark .smh-inbox-window,.crm-app.public-home.crm-dark .smh-demo-surface,.crm-app.public-home.crm-dark .smh-profile-card,.crm-app.public-home.crm-dark .smh-solution-grid article { color:#eaf1ee;background:#222c2d;border-color:#455653; }
.crm-app.public-home.crm-dark .smh-window-content,.crm-app.public-home.crm-dark .smh-message-list,.crm-app.public-home.crm-dark .smh-demo-chat,.crm-app.public-home.crm-dark .smh-board-columns { color:#e6eeea;background:#1b2425; }
.crm-app.public-home.crm-dark .smh-window-top,.crm-app.public-home.crm-dark .smh-chat-heading,.crm-app.public-home.crm-dark .smh-demo-title,.crm-app.public-home.crm-dark .smh-demo-thread-head,.crm-app.public-home.crm-dark .smh-chat-composer { color:#d3e3dc;background:#263132;border-color:#3a4a49; }
.crm-app.public-home.crm-dark .smh-mini-sidebar,.crm-app.public-home.crm-dark .smh-demo-contacts { color:#c1d4cb;background:#202a2b;border-color:#3b4b4a; }
.crm-app.public-home.crm-dark .smh-bubble-in,.crm-app.public-home.crm-dark .smh-board-task,.crm-app.public-home.crm-dark .smh-document,.crm-app.public-home.crm-dark .smh-profile-fact { color:#dce8e2;background:#2a3536;border-color:#465654; }
.crm-app.public-home.crm-dark .smh-bubble-out { color:#e1f5ec;background:#28534b; }
.crm-app.public-home.crm-dark .smh-context-note,.crm-app.public-home.crm-dark .smh-profile-orbit,.crm-app.public-home.crm-dark .smh-channel-brands .smh-channel { color:#e8f2ed;background:#263132;border-color:#455653; }
.crm-app.public-home.crm-dark .smh-tour-copy li,.crm-app.public-home.crm-dark .smh-check-list li,.crm-app.public-home.crm-dark .smh-solution-copy p,.crm-app.public-home.crm-dark .smh-faq-list summary,.crm-app.public-home.crm-dark .smh-faq-list details > p,.crm-app.public-home.crm-dark .smh-profile-tags span { color:#c6d7cf; }
.crm-app.public-home.crm-dark .smh-document small,.crm-app.public-home.crm-dark .smh-demo-contacts small,.crm-app.public-home.crm-dark .smh-chat-heading small,.crm-app.public-home.crm-dark .smh-context-note small,.crm-app.public-home.crm-dark .smh-profile-person small,.crm-app.public-home.crm-dark .smh-footer-main > div > p,.crm-app.public-home.crm-dark .smh-footer-main > div > a:not(.smh-brand),.crm-app.public-home.crm-dark .smh-footer button,.crm-app.public-home.crm-dark .smh-footer-bottom { color:#b8c9c1; }
.crm-app.public-home.crm-dark .smh-footer-bottom,.crm-app.public-home.crm-dark .smh-faq-list details,.crm-app.public-home.crm-dark .smh-document { border-color:#3b4948; }
.crm-app.public-home.crm-dark .smh-nav.is-open { background:#1b2324;border-color:#3b4948; }
@media(max-width:900px) { .smh-theme-toggle { width:100%;height:44px;justify-content:start;padding-inline:2px;border:0; } }
@media(max-width:680px) { .smh-site .smh-announcement { font-size:11px; }.smh-footer-main > div > p,.smh-footer-main > div > a:not(.smh-brand),.smh-footer-main button,.smh-footer-bottom { font-size:12px; }.smh-footer-bottom { gap:12px;flex-wrap:wrap; } }
.smh-site .smh-eyebrow { font-size:12px; }
.smh-site .smh-lead { font-size:17px; line-height:1.7; }
.smh-site h2 { font-size:clamp(36px,3.4vw,50px); }
.smh-site .smh-channels h2 { font-size:30px; }
.smh-site .smh-channels p:not(.smh-eyebrow),.smh-site .smh-section-heading > p:not(.smh-eyebrow),.smh-site .smh-final > div > p:not(.smh-eyebrow) { font-size:16px; line-height:1.7; }
.smh-site .smh-channel { font-size:14px; }
.smh-site .smh-story-description,.smh-site .smh-tour-copy p,.smh-site .smh-solution-copy p,.smh-site .smh-setup-steps p,.smh-site .smh-faq-list details > p { font-size:15px; line-height:1.75; }
.smh-site .smh-tour h3 { font-size:30px; }
.smh-site .smh-tour-copy li,.smh-site .smh-check-list li { font-size:14px; }
.smh-site .smh-solution-copy h3 { font-size:20px; }
.smh-site .smh-solution-copy > div span { font-size:12px; }
.smh-site .smh-setup-steps h3 { font-size:19px; }
.smh-site .smh-faq-list summary { font-size:16px; }
.smh-site .smh-button { font-size:14px; }
@media(max-width:680px) { .smh-site h2 { font-size:36px; }.smh-site .smh-lead { font-size:16px; }.smh-site .smh-tour h3 { font-size:27px; }.smh-site .smh-tour-tabs button { font-size:12px; }.smh-site .smh-channels h2 { font-size:27px; } }
.smh-header { gap:clamp(24px,4vw,56px); }
.smh-header .smh-brand { gap:12px; align-items:center; }
.smh-header .smh-brand .smh-logo-icon,.smh-footer .smh-brand .smh-logo-icon { width:44px; height:44px; padding:0; border:0; border-radius:0; background:transparent; box-shadow:none; }
.smh-header .smh-brand > span { display:grid; gap:3px; }
.smh-header .smh-brand strong { color:var(--smh-ink); font-size:16px; letter-spacing:-.03em; }
.smh-header .smh-brand small { margin-top:0; color:var(--smh-muted); font-size:11px; }
.smh-nav { margin-left:auto; gap:clamp(14px,1.8vw,24px); font-size:14px; }
.smh-theme-toggle { width:42px; height:42px; border-radius:11px; }
.smh-nav-cta { min-height:44px; padding-inline:18px; border-radius:10px; font-size:13px; }
.crm-app.public-home.crm-dark .smh-site .smh-eyebrow { color:#75d8c4; }
.crm-app.public-home.crm-dark .smh-site h1 em,.crm-app.public-home.crm-dark .smh-site .smh-product-section h2 em,.crm-app.public-home.crm-dark .smh-site .smh-human h2 em,.crm-app.public-home.crm-dark .smh-site .smh-solutions h2 em,.crm-app.public-home.crm-dark .smh-site .smh-setup h2 em,.crm-app.public-home.crm-dark .smh-site .smh-faq h2 em { color:#8fe1c9; }
.crm-app.public-home.crm-dark .smh-site .smh-button-secondary { color:#e8f3ed; border-color:#83bdb0; background:rgba(255,255,255,.03); }
.crm-app.public-home.crm-dark .smh-site .smh-button-secondary:hover { color:#123b39; border-color:#b9e5d7; background:#b9e5d7; }
.smh-site .smh-footer-main > div > p { color:#43564a; font-size:14px; line-height:1.75; }
.smh-site .smh-footer-main > div > strong { color:#173d37; font-size:15px; }
.smh-site .smh-footer-main > div > a:not(.smh-brand),.smh-site .smh-footer-main button { color:#40594b; font-size:14px; }
.smh-site .smh-footer-bottom { color:#4c5e52; font-size:13px; }
.smh-site .smh-channels small { color:#40574b; font-size:14px; line-height:1.6; }
.smh-site .smh-tour-tabs button { color:#425c50; font-size:15px; }
.smh-site .smh-tour-tabs button[aria-selected="true"] { color:#174c42; }
.smh-site .smh-profile-top { color:#173d37; font-size:14px; }
.smh-site .smh-profile-top svg { color:#56723c; }
.smh-site .smh-profile-person > span { color:#455d32; }
.smh-site .smh-profile-person h3 { color:#173d37; font-size:20px; }
.smh-site .smh-profile-person small { color:#465a4d; font-size:12px; }
.smh-site .smh-profile-tags span { color:#345b45; background:#e5eedc; font-size:11px; }
.smh-site .smh-profile-fact { color:#405546; font-size:13px; }
.crm-app.public-home.crm-dark .smh-site .smh-footer-main > div > p,.crm-app.public-home.crm-dark .smh-site .smh-footer-main > div > a:not(.smh-brand),.crm-app.public-home.crm-dark .smh-site .smh-footer button,.crm-app.public-home.crm-dark .smh-site .smh-footer-bottom { color:#d1ded7; }
.crm-app.public-home.crm-dark .smh-site .smh-footer-main > div > strong { color:#f0f6f2; }
.crm-app.public-home.crm-dark .smh-site .smh-channels small { color:#d8e5de; }
.crm-app.public-home.crm-dark .smh-site .smh-tour-tabs button { color:#d6e4dc; }
.crm-app.public-home.crm-dark .smh-site .smh-tour-tabs button[aria-selected="true"] { color:#174c42; background:#eaf3ed; }
.crm-app.public-home.crm-dark .smh-site .smh-profile-top { color:#f0f6f2; }
.crm-app.public-home.crm-dark .smh-site .smh-profile-top svg { color:#bad28e; }
.crm-app.public-home.crm-dark .smh-site .smh-profile-person h3 { color:#f0f6f2; }
.crm-app.public-home.crm-dark .smh-site .smh-profile-person small { color:#d4e1da; }
.crm-app.public-home.crm-dark .smh-site .smh-profile-tags span { color:#193c34; background:#dcece3; }
.crm-app.public-home.crm-dark .smh-site .smh-profile-fact { color:#e5eee9; }
@media(max-width:680px) { .smh-site .smh-tour-tabs button { font-size:13px; }.smh-site .smh-footer-main > div > p,.smh-site .smh-footer-main > div > a:not(.smh-brand),.smh-site .smh-footer-main button { font-size:14px; } }
@media(max-width:900px) { .smh-header { gap:16px; }.smh-nav { margin-left:0; }.smh-header .smh-brand .smh-logo-icon,.smh-footer .smh-brand .smh-logo-icon { width:40px;height:40px; } }

.smh-site { --smh-focus:#087e77; }
.smh-site :is(a,button,select,summary,[tabindex]):focus-visible { outline:2px solid var(--smh-focus); outline-offset:3px; }
.smh-announcement { text-wrap:balance; }
.smh-menu-button { border-radius:12px; transition:background .18s,border-color .18s,transform .18s; }
.smh-menu-button:hover { border-color:#85b9aa; background:#eaf3ed; }
.smh-header .smh-nav { gap:clamp(12px,1.7vw,22px); }
.smh-nav-links { display:flex; align-items:center; gap:clamp(10px,1.2vw,16px); padding:0; border:0; border-radius:0; background:transparent; }
.smh-nav-links > a { position:relative; padding:10px 4px 12px; color:var(--smh-muted); white-space:nowrap; transition:color .18s; }
.smh-nav-links > a::after { position:absolute; right:4px; bottom:5px; left:4px; height:2px; border-radius:2px; background:var(--smh-teal); content:""; transform:scaleX(0); transform-origin:left; transition:transform .2s ease; }
.smh-nav-links > a:hover { color:var(--smh-teal); }
.smh-nav-links > a:hover::after { transform:scaleX(1); }
.smh-nav-tools { display:flex; align-items:center; gap:8px; padding-left:0; border-left:0; }
.smh-nav-account { display:flex; align-items:center; gap:12px; }
.smh-theme-toggle { width:40px; height:40px; border-color:transparent; border-radius:50%; background:transparent; font-size:18px; transition:background .18s,border-color .18s,color .18s; }
.smh-theme-toggle:hover { background:#e7f1eb; }
.smh-language select { min-width:118px; min-height:40px; border-radius:999px; }
.smh-nav-cta { min-height:42px; padding-inline:19px; border-radius:999px; box-shadow:0 5px 16px rgba(8,126,119,.18); }
.smh-nav-cta:hover { transform:translateY(-1px); box-shadow:0 8px 20px rgba(8,126,119,.24); }
.smh-language::after { top:50%; transform:translateY(-50%) rotate(45deg); }
.crm-app.public-home.crm-dark .smh-site { --smh-focus:#8fe1c9; }
.crm-app.public-home.crm-dark .smh-nav-links { border:0; background:transparent; }
.crm-app.public-home.crm-dark .smh-nav-links > a { color:#d4e2dc; }
.crm-app.public-home.crm-dark .smh-nav-links > a::after { background:#8fe1c9; }
.crm-app.public-home.crm-dark .smh-nav-links > a:hover { color:#b6f0df; background:transparent; }
.crm-app.public-home.crm-dark .smh-menu-button:hover { border-color:#76bdae; background:#2a393a; }
.crm-app.public-home.crm-dark .smh-nav.is-open { border-color:#3b4948; background:#1b2324; box-shadow:0 18px 42px #0007; }

@media(max-width:1000px) {
  .smh-header { min-height:72px; padding-inline:24px; }
  .smh-menu-button { display:grid; }
  .smh-header .smh-nav { display:none; position:absolute; top:100%; left:14px; right:14px; flex-direction:column; align-items:stretch; gap:12px; margin:0; padding:12px; max-height:calc(100dvh - 112px); overflow-y:auto; border:1px solid var(--smh-line); border-radius:16px; background:#f8faf6; box-shadow:0 18px 42px #193c3026; }
  .smh-header .smh-nav.is-open { display:flex; }
  .smh-nav-links { display:grid; gap:4px; padding:0; border:0; border-radius:0; background:transparent; }
  .smh-nav-links > a { display:flex; align-items:center; min-height:44px; padding:0 12px; border-radius:10px; }
  .smh-nav-links > a::after { right:12px; bottom:4px; left:12px; }
  .smh-nav-tools { display:grid; grid-template-columns:44px minmax(0,1fr); gap:10px; padding:0; border:0; }
  .smh-theme-toggle { width:44px; height:44px; justify-content:center; padding:0; border:1px solid var(--smh-line); border-radius:12px; }
  .smh-language { display:block; width:100%; padding:0; }
  .smh-language select { width:100%; min-width:0; min-height:44px; }
  .smh-nav-account { display:grid; grid-template-columns:auto minmax(0,1fr); gap:8px; }
  .smh-login { display:flex; align-items:center; justify-content:center; min-height:44px; padding:0 12px; border:1px solid var(--smh-line); border-radius:10px; }
  .smh-nav-cta { width:100%; min-height:44px; margin:0; }
  .crm-app.public-home.crm-dark .smh-nav-links { background:transparent; }
}
@media(max-width:680px) { .smh-header { min-height:67px; padding-inline:20px; } }
.smh-site .smh-footer .smh-brand strong { font-size:18px; }
.smh-site .smh-footer .smh-brand small { font-size:13px; }
.smh-site .smh-footer-main > div > p { font-size:16px; line-height:1.7; }
.smh-site .smh-footer-main > div > strong { font-size:17px; }
.smh-site .smh-footer-main > div > a:not(.smh-brand),.smh-site .smh-footer-main button { font-size:16px; line-height:1.5; padding-block:6px; }
.smh-site .smh-footer-bottom { font-size:14px; }
@media(max-width:680px) {
  .smh-site .smh-footer .smh-brand strong { font-size:16px; }
  .smh-site .smh-footer .smh-brand small { font-size:12px; }
  .smh-site .smh-footer-main > div > p { font-size:15px; }
  .smh-site .smh-footer-main > div > strong { font-size:16px; }
  .smh-site .smh-footer-main > div > a:not(.smh-brand),.smh-site .smh-footer-main button { font-size:15px; }
  .smh-site .smh-footer-bottom { font-size:13px; }
}

/* Compact desktop bar and a full-width, app-like menu on smaller screens. */
.smh-header { min-height:76px; }
.smh-header .smh-nav { gap:14px; }
.smh-mobile-menu-head { display:contents; }
.smh-mobile-brand,.smh-menu-close,.smh-header-quick-tools { display:none; }
.smh-language-icon { display:block; width:22px; height:22px; }
.smh-nav-links { order:0; gap:5px; padding:6px 10px; border:1px solid var(--smh-line); border-radius:999px; background:rgba(255,255,255,.045); }
.smh-nav-links > a > svg { display:none; }
.smh-nav-links > a { padding:8px 7px; color:var(--smh-ink); }
.smh-nav-links > a::after { display:none; }
.smh-nav-links > a:hover { color:var(--smh-teal); }
.smh-nav-tools { order:1; gap:8px; }
.smh-nav-tools .smh-language { position:relative; display:grid; place-items:center; width:42px; height:42px; margin:0; padding:0; border:1px solid var(--smh-line); border-radius:13px; background:transparent; }
.smh-nav-tools .smh-language::after { display:none; }
.smh-nav-tools .smh-language select { position:absolute; inset:0; z-index:1; width:100%; height:100%; min-width:0; min-height:0; padding:0; opacity:0; cursor:pointer; }
.smh-theme-toggle { width:42px; height:42px; border:1px solid var(--smh-line); border-radius:13px; background:transparent; }
.smh-nav-account { order:2; gap:12px; }
.crm-app.public-home.crm-dark .smh-header { color:#edf1ee; background:rgba(22,24,25,.96); border-color:#303538; }
.crm-app.public-home.crm-dark .smh-nav-links { border-color:#363a3d; background:#202225; }
.crm-app.public-home.crm-dark .smh-nav-links > a { color:#e2e5e3; }
.crm-app.public-home.crm-dark .smh-nav-links > a:hover { color:#fff; }
.crm-app.public-home.crm-dark .smh-theme-toggle,.crm-app.public-home.crm-dark .smh-nav-tools .smh-language { color:#edf1ee; background:#17191b; border-color:#3a4144; }

@media(max-width:1000px) {
  .smh-header { min-height:74px; padding:10px 22px; }
  .smh-header-quick-tools { display:flex; align-items:center; gap:9px; margin-left:auto; }
  .smh-menu-button { display:grid; width:46px; height:46px; border-radius:15px; }
  .smh-nav-links { display:grid; order:1; gap:0; padding:0; border:0; border-radius:0; background:transparent; }
  .smh-nav-links > a { display:flex; align-items:center; gap:17px; min-height:54px; padding:6px 12px; border-radius:12px; font-size:19px; font-weight:600; }
  .smh-nav-links > a::after { display:none; }
  .smh-nav-links > a > svg { display:block; width:27px; height:27px; color:#8d9097; }
  .smh-nav-links > a:nth-child(3) { margin-top:18px; padding-top:22px; border-top:1px solid var(--smh-line); border-radius:0; }
  .smh-nav-links > a:hover { color:var(--smh-teal); background:transparent; }
  .smh-mobile-menu-head { display:flex; order:0; align-items:center; gap:10px; width:100%; margin-bottom:22px; }
  .smh-mobile-brand { display:flex; gap:10px; align-items:center; color:var(--smh-ink); }
  .smh-mobile-brand .smh-logo-icon { width:40px; height:40px; }
  .smh-mobile-brand strong { font-size:19px; letter-spacing:-.035em; }
  .smh-header .smh-nav-tools { display:flex; gap:11px; margin-left:auto; padding:0; border:0; }
  .smh-language { display:grid; position:relative; place-items:center; width:50px; height:50px; margin:0; padding:0; border:1px solid var(--smh-line); border-radius:16px; background:rgba(0,0,0,.04); }
  .smh-language::after { display:none; }
  .smh-language-icon { display:block; width:24px; height:24px; }
  .smh-language select { position:absolute; inset:0; z-index:1; width:100%; height:100%; min-width:0; min-height:0; padding:0; opacity:0; cursor:pointer; }
  .smh-header .smh-theme-toggle { display:grid; place-items:center; width:50px; height:50px; padding:0; border:1px solid var(--smh-line); border-radius:16px; background:rgba(0,0,0,.18); font-size:21px; }
  .smh-menu-close { display:grid; place-items:center; flex:0 0 50px; width:50px; height:50px; border:1px solid var(--smh-line); border-radius:16px; color:var(--smh-ink); background:rgba(0,0,0,.18); }
  .smh-header .smh-nav { display:none; position:fixed; top:0; left:0; right:0; z-index:1; flex-direction:column; align-items:stretch; gap:0; max-height:calc(100dvh - env(safe-area-inset-top)); margin:0; padding:calc(25px + env(safe-area-inset-top)) clamp(20px,5vw,38px) 30px; overflow-y:auto; border:1px solid var(--smh-line); border-top:0; border-radius:0 0 28px 28px; background:var(--smh-cream); box-shadow:0 24px 70px #0005; }
  .smh-header .smh-nav.is-open { display:flex; }
  .smh-header.menu-open { background:transparent; border-color:transparent; backdrop-filter:none; }
  .smh-header.menu-open::before { position:fixed; inset:0; z-index:0; background:rgba(5,7,8,.62); content:""; }
  .smh-header.menu-open > .smh-brand,.smh-header.menu-open > .smh-header-quick-tools,.smh-header.menu-open > .smh-menu-button { display:none; }
  .smh-nav-account { display:grid; order:2; grid-template-columns:auto minmax(0,1fr); gap:10px; margin-top:19px; padding-top:18px; border-top:1px solid var(--smh-line); }
  .smh-login { display:flex; align-items:center; justify-content:center; min-height:48px; padding:0 14px; border:1px solid var(--smh-line); border-radius:14px; }
  .smh-nav-cta { width:100%; min-height:48px; margin:0; border-radius:14px; }
  .crm-app.public-home.crm-dark .smh-header.menu-open::before { background:rgba(0,0,0,.68); }
  .crm-app.public-home.crm-dark .smh-header .smh-nav { color:#eff1f0; border-color:#303235; background:#171719; box-shadow:0 24px 70px #0009; }
  .crm-app.public-home.crm-dark .smh-mobile-brand,.crm-app.public-home.crm-dark .smh-nav-links > a { color:#eff1f0; }
  .crm-app.public-home.crm-dark .smh-nav-links > a > svg { color:#a6a8ad; }
  .crm-app.public-home.crm-dark .smh-language,.crm-app.public-home.crm-dark .smh-header .smh-theme-toggle,.crm-app.public-home.crm-dark .smh-menu-close { color:#f1f2f2; border-color:#242629; background:#101113; }
  .crm-app.public-home.crm-dark .smh-nav-account { border-color:#383a3e; }
  .crm-app.public-home.crm-dark .smh-login { color:#f1f2f2; border-color:#393b40; }
}
@media(max-width:480px) {
  .smh-header { gap:8px; padding-inline:16px; }
  .smh-header .smh-brand { gap:8px; }
  .smh-header .smh-brand .smh-logo-icon { width:34px; height:32px; }
  .smh-header .smh-brand strong { font-size:14px; }
  .smh-header .smh-brand small { display:none; }
  .smh-header-quick-tools { gap:6px; }
  .smh-header .smh-header-quick-tools .smh-language,.smh-header .smh-header-quick-tools .smh-theme-toggle,.smh-header .smh-menu-button { width:40px; height:40px; }
  .smh-mobile-menu-head { gap:6px; }
  .smh-header .smh-mobile-brand .smh-logo-icon { width:34px; height:32px; }
  .smh-header .smh-mobile-brand strong { font-size:14px; }
  .smh-header .smh-nav-tools { gap:6px; }
  .smh-header .smh-nav-tools .smh-language,.smh-header .smh-nav-tools .smh-theme-toggle,.smh-menu-close { flex-basis:40px; width:40px; height:40px; }
}
</style>
