<script setup>
import { computed } from 'vue';
const props=defineProps({modelValue:{type:Object,default:null}});
const emit=defineEmits(['update:modelValue']);
const methods={cash:'Tiền mặt',bank_transfer:'Chuyển khoản',cod:'Thanh toán khi nhận hàng (COD)'};
const kinds={goods:'Hàng hóa',service:'Dịch vụ đặt lịch',rental:'Cho thuê'};
const contact=[{key:'name',label:'Họ tên',type:'text'},{key:'phone',label:'Số liên hệ',type:'phone'}];
const profile=computed(()=>props.modelValue || {default_offering_type:'goods',default_billing_unit:null,timezone:'Asia/Ho_Chi_Minh',payment_methods:['cash','bank_transfer'],collection_fields:{
  goods:[...contact,{key:'quantity',label:'Số lượng',type:'quantity'}],
  service:[...contact,{key:'starts_at',label:'Thời gian mong muốn',type:'datetime',future_only:true}],
  rental:[...contact,{key:'start_date',label:'Ngày bắt đầu thuê',type:'date',future_only:true}]}});
const defaultPolicies={goods:{mode:'order_total',label:'Giá hàng',fixed_charges:[]},service:{mode:'order_total',label:'Giá dịch vụ',fixed_charges:[]},rental:{mode:'manual',label:'Tiền kỳ đầu',fixed_charges:[]}};
function policy(kind){return profile.value.payment_policies?.[kind] || defaultPolicies[kind];}
function setPolicy(kind,key,value){update('payment_policies',{...defaultPolicies,...profile.value.payment_policies,[kind]:{...policy(kind),[key]:value}});}
function charge(kind,index,key,value){setPolicy(kind,'fixed_charges',policy(kind).fixed_charges.map((line,i)=>i===index?{...line,[key]:value}:line));}
function update(key,value){emit('update:modelValue',{...profile.value,[key]:value});}
function paymentMethod(key,checked){const selected=profile.value.payment_methods || ['cash','bank_transfer'];update('payment_methods',checked?[...selected,key]:selected.filter(v=>v!==key));}
function fields(kind,value){update('collection_fields',{...profile.value.collection_fields,[kind]:value});}
function field(kind,index,key,value){fields(kind,profile.value.collection_fields[kind].map((f,i)=>i===index?{...f,[key]:value}:f));}
function add(kind){const list=profile.value.collection_fields[kind];let n=1;while(list.some(f=>f.key===`field_${n}`))n++;fields(kind,[...list,{key:`field_${n}`,label:'Thông tin bổ sung',type:'text'}]);}
</script>
<template>
  <fieldset class="business-profile">
    <legend>Cách doanh nghiệp tiếp nhận yêu cầu</legend>
    <p class="business-profile-intro">Trợ lý hỏi thông tin khách, hỏi hình thức thanh toán, rồi tóm tắt và xin khách xác nhận gửi yêu cầu.</p>
    <div class="business-profile-base-grid">
      <label>Loại cung cấp mặc định<select :value="profile.default_offering_type" @change="update('default_offering_type',$event.target.value)"><option v-for="(label,key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
      <label>Đơn vị giá mặc định<input :value="profile.default_billing_unit || ''" maxlength="40" placeholder="Ví dụ: chiếc, lượt, giờ, ngày, tháng" @input="update('default_billing_unit',$event.target.value || null)" /><small>Đơn vị khai báo trên từng sản phẩm được ưu tiên.</small></label>
      <label>Múi giờ của doanh nghiệp<input :value="profile.timezone" required maxlength="80" placeholder="Asia/Ho_Chi_Minh" @input="update('timezone',$event.target.value)" /></label>
    </div>
    <fieldset class="business-profile-payments">
      <legend>Hình thức thanh toán khách có thể chọn</legend>
      <div class="business-profile-payment-options">
        <label v-for="(label,key) in methods" :key="key" class="business-profile-payment-option"><input type="checkbox" :checked="(profile.payment_methods || ['cash','bank_transfer']).includes(key)" @change="paymentMethod(key,$event.target.checked)" /><span>{{ label }}</span></label>
      </div>
      <small>Hỏi sau thông tin khách, trước bước xác nhận. Chọn hình thức chưa phải đã thanh toán.</small>
    </fieldset>
    <div class="business-profile-kinds">
      <details v-for="(label,kind) in kinds" :key="kind" class="business-profile-kind">
        <summary>{{ label }}<span>{{ profile.collection_fields[kind].length }} thông tin cần hỏi</span></summary>
        <div class="business-profile-kind-body">
          <div v-for="(item,index) in profile.collection_fields[kind]" :key="`${kind}-${index}`" class="profile-field">
            <label>Tên thông tin cần hỏi<input :value="item.label" required maxlength="100" @input="field(kind,index,'label',$event.target.value)" /></label>
            <label>Mã thông tin<input :value="item.key" required pattern="[a-z][a-z0-9_]{0,39}" maxlength="40" @input="field(kind,index,'key',$event.target.value)" /></label>
            <label>Loại dữ liệu<select :value="item.type" @change="field(kind,index,'type',$event.target.value)"><option value="text">Văn bản</option><option value="phone">Số điện thoại</option><option value="date">Ngày</option><option value="datetime">Ngày và giờ</option><option value="quantity">Số lượng</option></select></label>
            <label v-if="['date','datetime'].includes(item.type)" class="business-profile-future-field"><input type="checkbox" :checked="item.future_only" @change="field(kind,index,'future_only',$event.target.checked)" /> Chỉ nhận lịch từ hôm nay</label>
            <button type="button" class="business-profile-remove" :aria-label="`Bỏ thông tin ${item.label} trong ${label}`" :disabled="profile.collection_fields[kind].length<=1" @click="fields(kind,profile.collection_fields[kind].filter((_,i)=>i!==index))">Bỏ</button>
          </div>
          <button class="business-profile-add" type="button" :disabled="profile.collection_fields[kind].length>=12" @click="add(kind)">Thêm thông tin cần hỏi</button>
          <fieldset class="business-profile-payment-policy">
            <legend>Khoản thu trước khi nhân viên xác nhận</legend>
            <label>Cách tính<select :value="policy(kind).mode" @change="setPolicy(kind,'mode',$event.target.value)"><option value="order_total">Giá trong CRM + khoản cố định bên dưới</option><option value="manual">Lập bảng kê cho từng đơn trước khi gửi QR</option></select></label>
            <template v-if="policy(kind).mode==='order_total'">
              <label>Tên khoản giá cơ sở<input :value="policy(kind).label" maxlength="120" required @input="setPolicy(kind,'label',$event.target.value)" /></label>
              <div v-for="(line,index) in policy(kind).fixed_charges" :key="index" class="profile-field profile-charge-row">
                <label>Khoản thu thêm<input :value="line.label" required maxlength="120" @input="charge(kind,index,'label',$event.target.value)" /></label>
                <label>Số tiền (đ)<input :value="line.amount" type="number" min="1" max="9999999999" step="1" required @input="charge(kind,index,'amount',$event.target.value)" /></label>
                <button class="business-profile-remove" type="button" :aria-label="`Bỏ khoản thu ${index+1}`" @click="setPolicy(kind,'fixed_charges',policy(kind).fixed_charges.filter((_,i)=>i!==index))">Bỏ</button>
              </div>
              <button class="business-profile-add" type="button" :disabled="policy(kind).fixed_charges.length>=12" @click="setPolicy(kind,'fixed_charges',[...policy(kind).fixed_charges,{label:'',amount:''}])">Thêm khoản thu cố định</button>
            </template>
            <small>Chỉ dùng cách tự tính khi giá CRM là khoản phải trả cho một yêu cầu. Phí theo thời hạn, chỉ số sử dụng hoặc báo giá riêng cần lập bảng kê từng đơn. Bot không tự đoán tiền cọc. Khách báo đã chuyển khoản vẫn cần đối soát; COD cho phép trả sau.</small>
          </fieldset>
        </div>
      </details>
    </div>
    <small class="business-profile-footnote">Giá, tồn kho và trạng thái đơn lấy từ CRM; chính sách ghi trong kho tri thức. Nhân viên xác nhận đơn/lịch; không cần viết sẵn từng câu trả lời.</small>
  </fieldset>
</template>
<style scoped>
.business-profile{display:grid;gap:16px;min-width:0;grid-column:1/-1;box-sizing:border-box;margin:8px 0 0;padding:16px 18px 18px;border:1px solid #d4e1df;border-radius:14px;color:#243638;background:#f5f9f8;color-scheme:light}
.business-profile>legend,.business-profile fieldset>legend{display:table;max-width:100%;padding:0 8px;line-height:1.4;font-weight:700}
.business-profile>legend{font-size:16px;color:#203e40}
.business-profile-intro{margin:0;color:#52696a;font-size:14px;line-height:1.5}
.business-profile-base-grid{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:12px}
.business-profile label{display:grid;gap:6px;min-width:0;color:inherit;font-size:14px;font-weight:650}
.business-profile input:not([type=checkbox]),.business-profile select{width:100%;min-width:0;box-sizing:border-box;min-height:42px;padding:9px 11px;border:1px solid #cbd9d8;border-radius:9px;background:#fff;color:inherit;font:inherit;font-weight:500}
.business-profile input[type=checkbox]{width:17px;height:17px;min-height:0;flex:0 0 auto;margin:0;accent-color:#0d8b84}
.business-profile-base-grid small,.business-profile small{color:#52696a;font-size:13px;font-weight:400;line-height:1.5}
.business-profile fieldset{display:grid;gap:12px;min-width:0;margin:0;padding:15px;border:1px solid #d4e1df;border-radius:12px;background:#fff}
.business-profile-payments{gap:10px!important}
.business-profile-payment-options{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:10px}
.business-profile .business-profile-payment-option{display:flex;min-height:46px;align-items:center;gap:10px;padding:10px 12px;border:1px solid #d4e1df;border-radius:10px;background:#f5f9f8;cursor:pointer;font-size:14px}
.business-profile-payment-option span{line-height:1.4}
.business-profile-kinds{display:grid;gap:10px}
.business-profile-kind{overflow:hidden;border:1px solid #d4e1df;border-radius:12px;background:#fff}
.business-profile-kind>summary{display:flex;min-height:48px;align-items:center;gap:8px;padding:10px 14px;color:#243638;cursor:pointer;font-size:14px;font-weight:700;list-style-position:inside}
.business-profile-kind>summary span{margin-left:auto;color:#52696a;font-size:13px;font-weight:500}
.business-profile-kind[open]>summary{border-bottom:1px solid #d4e1df;background:#f5f9f8}
.business-profile-kind>summary:focus-visible{outline:2px solid #18a49c;outline-offset:-3px}
.business-profile-kind-body{display:grid;gap:12px;padding:14px}
.profile-field{display:grid;grid-template-columns:repeat(3,minmax(0,1fr)) auto;gap:10px;align-items:end;margin:0 0 10px}
.profile-charge-row{grid-template-columns:minmax(0,2fr) minmax(140px,1fr) auto}
.business-profile .business-profile-future-field{display:flex;min-height:42px;align-items:center;gap:8px;color:#52696a;font-weight:500}
.business-profile .business-profile-remove,.business-profile .business-profile-add{min-height:40px;padding:8px 12px;border:1px solid #cbd9d8;border-radius:9px;background:#fff;color:inherit;font:inherit;cursor:pointer}
.business-profile .business-profile-remove{color:#a14b4b}
.business-profile .business-profile-add{width:fit-content;border-color:#87c9c1;color:#087b75;background:#edf8f6;font-weight:700}
.business-profile button:disabled{cursor:not-allowed;opacity:.55}
.business-profile-footnote{display:block}
:global(.crm-app.crm-dark .business-profile),:global(body.crm-dark .business-profile){border-color:#39474a!important;background:#20282a!important;color:#e5eeee!important;color-scheme:dark}
:global(.crm-app.crm-dark .business-profile>legend),:global(body.crm-dark .business-profile>legend){color:#f1f7f6}
:global(.crm-app.crm-dark .business-profile-intro),:global(.crm-app.crm-dark .business-profile small),:global(.crm-app.crm-dark .business-profile-kind>summary span),:global(body.crm-dark .business-profile-intro),:global(body.crm-dark .business-profile small),:global(body.crm-dark .business-profile-kind>summary span){color:#b8c7c8}
:global(.crm-app.crm-dark .business-profile label),:global(.crm-app.crm-dark .business-profile .business-profile-future-field),:global(body.crm-dark .business-profile label),:global(body.crm-dark .business-profile .business-profile-future-field){color:#e5eeee}
:global(.crm-app.crm-dark .business-profile input:not([type=checkbox])),:global(.crm-app.crm-dark .business-profile select),:global(body.crm-dark .business-profile input:not([type=checkbox])),:global(body.crm-dark .business-profile select){border-color:#465457;background:#171d1f;color:#edf6f5}
:global(.crm-app.crm-dark .business-profile fieldset),:global(.crm-app.crm-dark .business-profile-kind),:global(body.crm-dark .business-profile fieldset),:global(body.crm-dark .business-profile-kind){border-color:#39474a;background:#1b2123}
:global(.crm-app.crm-dark .business-profile .business-profile-payment-option),:global(body.crm-dark .business-profile .business-profile-payment-option){border-color:#39474a;background:#252d2f}
:global(.crm-app.crm-dark .business-profile-kind>summary),:global(.crm-app.crm-dark .business-profile-kind[open]>summary),:global(body.crm-dark .business-profile-kind>summary),:global(body.crm-dark .business-profile-kind[open]>summary){border-color:#39474a;background:#252d2f;color:#f1f7f6}
:global(.crm-app.crm-dark .business-profile .business-profile-remove),:global(body.crm-dark .business-profile .business-profile-remove){border-color:#614449;color:#f0b8b5;background:#302427}
:global(.crm-app.crm-dark .business-profile .business-profile-add),:global(body.crm-dark .business-profile .business-profile-add){border-color:#356c69;color:#c4eeea;background:#193d3b}
@media(max-width:900px){.business-profile-base-grid{grid-template-columns:repeat(2,minmax(0,1fr))}.business-profile-payment-options{grid-template-columns:repeat(2,minmax(0,1fr))}.profile-field{grid-template-columns:repeat(2,minmax(0,1fr))}.profile-field>label:first-child{grid-column:span 2}.profile-field>button{justify-self:start}}
@media(max-width:560px){.business-profile{gap:12px;padding:14px}.business-profile-base-grid,.business-profile-payment-options,.profile-field,.profile-charge-row{grid-template-columns:1fr}.profile-field>label:first-child{grid-column:auto}.business-profile .business-profile-add{width:100%;min-height:44px}.business-profile .business-profile-remove{min-height:44px}.business-profile-kind-body{padding:11px}.business-profile-kind>summary{padding:10px;gap:5px}.business-profile-kind>summary span{font-size:11px}}
</style>
