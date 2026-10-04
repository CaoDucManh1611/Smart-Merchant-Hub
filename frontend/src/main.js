import { createApp } from "vue";
import App from "./App.vue";
import "./signup-design.css";
import "./inbox-design.css";
import "./operations-design.css";
import "./admin-design.css";
import { t } from "./i18n.js";

const app = createApp(App);
app.config.globalProperties.$t = t;
app.mount("#app");
