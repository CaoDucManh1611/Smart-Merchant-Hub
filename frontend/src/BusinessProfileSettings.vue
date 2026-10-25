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
    <p>Trợ lý hỏi thông tin khách, hỏi hình thức thanh toán, rồi tóm tắt và xin khách xác nhận gửi yêu cầu.</p>
    <label>Loại cung cấp mặc định<select :value="profile.default_offering_type" @change="update('default_offering_type',$event.target.value)"><option v-for="(label,key) in kinds" :key="key" :value="key">{{ label }}</option></select></label>
    <label>Đơn vị giá mặc định<input :value="profile.default_billing_unit || ''" maxlength="40" placeholder="Ví dụ: chiếc, lượt, giờ, ngày, tháng" @input="update('default_billing_unit',$event.target.value || null)" /></label>
    <small>Đơn vị khai báo trên từng sản phẩm được ưu tiên. Để trống nếu chưa xác định.</small>
    <label>Múi giờ của doanh nghiệp<input :value="profile.timezone" required maxlength="80" placeholder="Asia/Ho_Chi_Minh" @input="update('timezone',$event.target.value)" /></label>
    <fieldset>
      <legend>Hình thức thanh toán khách có thể chọn</legend>
      <label v-for="(label,key) in methods" :key="key"><input type="checkbox" :checked="(profile.payment_methods || ['cash','bank_transfer']).includes(key)" @change="paymentMethod(key,$event.target.checked)" /> {{ label }}</label>
      <small>Hỏi sau thông tin khách, trước bước xác nhận. Chọn hình thức chưa phải đã thanh toán.</small>
    </fieldset>
    <details v-for="(label,kind) in kinds" :key="kind">
      <summary>{{ label }} · {{ profile.collection_fields[kind].length }} thông tin bắt buộc</summary>
      <div v-for="(item,index) in profile.collection_fields[kind]" :key="`${kind}-${index}`" class="profile-field">
        <label>Tên thông tin cần hỏi<input :value="item.label" required maxlength="100" @input="field(kind,index,'label',$event.target.value)" /></label>
        <label>Mã thông tin<input :value="item.key" required pattern="[a-z][a-z0-9_]{0,39}" maxlength="40" @input="field(kind,index,'key',$event.target.value)" /></label>
        <label>Loại dữ liệu<select :value="item.type" @change="field(kind,index,'type',$event.target.value)"><option value="text">Văn bản</option><option value="phone">Số điện thoại</option><option value="date">Ngày</option><option value="datetime">Ngày và giờ</option><option value="quantity">Số lượng</option></select></label>
        <label v-if="['date','datetime'].includes(item.type)"><input type="checkbox" :checked="item.future_only" @change="field(kind,index,'future_only',$event.target.checked)" /> Chỉ nhận lịch từ hôm nay</label>
        <button type="button" :aria-label="`Bỏ thông tin ${item.label} trong ${label}`" :disabled="profile.collection_fields[kind].length<=1" @click="fields(kind,profile.collection_fields[kind].filter((_,i)=>i!==index))">Bỏ</button>
      </div>
      <button type="button" :disabled="profile.collection_fields[kind].length>=12" @click="add(kind)">Thêm thông tin cần hỏi</button>
      <fieldset>
        <legend>Khoản thu trước khi nhân viên xác nhận</legend>
        <label>Cách tính<select :value="policy(kind).mode" @change="setPolicy(kind,'mode',$event.target.value)"><option value="order_total">Giá trong CRM + khoản cố định bên dưới</option><option value="manual">Lập bảng kê cho từng đơn trước khi gửi QR</option></select></label>
        <template v-if="policy(kind).mode==='order_total'">
          <label>Tên khoản giá cơ sở<input :value="policy(kind).label" maxlength="120" required @input="setPolicy(kind,'label',$event.target.value)" /></label>
          <div v-for="(line,index) in policy(kind).fixed_charges" :key="index" class="profile-field">
            <label>Khoản thu thêm<input :value="line.label" required maxlength="120" @input="charge(kind,index,'label',$event.target.value)" /></label>
            <label>Số tiền (đ)<input :value="line.amount" type="number" min="1" max="9999999999" step="1" required @input="charge(kind,index,'amount',$event.target.value)" /></label>
            <button type="button" :aria-label="`Bỏ khoản thu ${index+1}`" @click="setPolicy(kind,'fixed_charges',policy(kind).fixed_charges.filter((_,i)=>i!==index))">Bỏ</button>
          </div>
          <button type="button" :disabled="policy(kind).fixed_charges.length>=12" @click="setPolicy(kind,'fixed_charges',[...policy(kind).fixed_charges,{label:'',amount:''}])">Thêm khoản thu cố định</button>
        </template>
        <small>Chỉ dùng cách tự tính khi giá CRM là khoản phải trả cho một yêu cầu. Phí theo thời hạn, chỉ số sử dụng hoặc báo giá riêng cần lập bảng kê từng đơn. Bot không tự đoán tiền cọc. Khách báo đã chuyển khoản vẫn cần đối soát; COD cho phép trả sau.</small>
      </fieldset>
    </details>
    <small>Giá, tồn kho và trạng thái đơn lấy từ CRM; chính sách ghi trong kho tri thức. Nhân viên xác nhận đơn/lịch; không cần viết sẵn từng câu trả lời.</small>
  </fieldset>
</template>
<style scoped>
.business-profile{min-width:0;display:grid;gap:12px;border:1px solid var(--border-color,#ccd8db);border-radius:12px;padding:16px;grid-column:1/-1}
.business-profile input[type=checkbox]{width:auto;justify-self:start}.business-profile p{margin:0}.business-profile label{display:grid;gap:6px;min-width:0}.business-profile input,.business-profile select{width:100%;min-width:0;box-sizing:border-box;min-height:40px;padding:8px 10px;border:1px solid var(--border-color,#ccd8db);border-radius:8px;background:var(--input-bg,#fff);color:inherit}.business-profile input[type=checkbox]{min-height:0}.business-profile fieldset{min-width:0;border:1px solid var(--border-color,#ccd8db);border-radius:8px;display:grid;gap:10px}.business-profile button{min-height:40px;padding:8px 12px;border:1px solid var(--border-color,#ccd8db);border-radius:8px;background:var(--input-bg,#fff);color:inherit}.business-profile small{line-height:1.5}
summary{cursor:pointer;padding:10px 0;font-weight:600}.profile-field{display:grid;grid-template-columns:2fr 1fr 1fr auto;gap:8px;align-items:end;margin:10px 0}
@media(max-width:640px){.business-profile button,.business-profile input:not([type=checkbox]),.business-profile select{min-height:44px}.profile-field{grid-template-columns:1fr 1fr}.business-profile{padding:12px}.profile-field>label:first-child{grid-column:1/-1}}
</style>
