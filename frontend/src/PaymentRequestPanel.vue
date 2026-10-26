<script setup>
import { computed, ref, watch } from 'vue';
import { apiFetch } from './api-client.js';
import { formatMoney } from './i18n.js';
const props=defineProps({order:{type:Object,required:true},endpoint:{type:String,required:true},paymentEndpoint:{type:String,default:''}});
const emit=defineEmits(['saved']);
const lines=ref([]),error=ref(''),busy=ref(false),verified=ref(false),amount=ref(''),reference=ref('');
const method=ref('bank_transfer');
let paymentAttempt=null;
watch(()=>props.order,order=>{lines.value=(order.metadata?.payment_request?.lines || [{label:order.metadata?.offering_name || 'Khoản thu',amount:order.metadata?.base_order_amount || order.total_amount}]).map(line=>({...line}));}, {immediate:true});
const editable=computed(()=>props.order.status==='draft' && Number(props.order.paid_amount || 0)===0);
const total=computed(()=>lines.value.reduce((sum,line)=>sum+Number(line.amount || 0),0));
const remaining=computed(()=>Math.max(0,Number(props.order.total_amount)-Number(props.order.paid_amount || 0)+Number(props.order.refunded_amount || 0)));
async function save(payment=false){
  error.value='';busy.value=true;
  try{
    let body;
    if(payment){
      if(!verified.value || !(Number(amount.value)>0))throw new Error('Kiểm tra khoản tiền thực nhận và nhập số tiền trước.');
      const signature=JSON.stringify([amount.value,method.value,reference.value]);
      if(paymentAttempt?.signature!==signature)paymentAttempt={signature,key:crypto.randomUUID()};
      body={amount:amount.value,method:method.value,reference:reference.value || null,status:'paid',idempotency_key:paymentAttempt.key};
    }else{
      if(!lines.value.length || lines.value.some(line=>!line.label.trim() || !Number.isInteger(Number(line.amount)) || Number(line.amount)<=0))throw new Error('Mỗi khoản cần tên và số tiền nguyên dương.');
      body={lines:lines.value,label:'Bảng kê khoản thu'};
    }
    const response=await apiFetch(payment?props.paymentEndpoint:props.endpoint,{method:payment?'POST':'PUT',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
    const result=await response.json().catch(()=>({}));
    if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'Chưa lưu được khoản thu. Vui lòng kiểm tra dữ liệu.');
    if(payment){amount.value='';verified.value=false;paymentAttempt=null;}
    emit('saved');
  }catch(e){error.value=e.message;}finally{busy.value=false;}
}
</script>
<template>
  <details class="payment-request-panel">
    <summary>Bảng kê khoản thu · {{ order.metadata?.payment_request ? formatMoney(order.total_amount) : 'Chưa lập' }}</summary>
    <p>Gửi khoản thu trước, đối soát tiền rồi nhân viên xác nhận đơn/lịch. COD được trả sau.</p>
    <div v-for="(line,index) in lines" :key="index" class="charge-row">
      <label>Khoản thu<input v-model="line.label" :disabled="!editable || busy" maxlength="120" /></label>
      <label>Số tiền (đ)<input v-model="line.amount" :disabled="!editable || busy" type="number" min="1" max="9999999999" step="1" /></label>
      <button v-if="editable" type="button" :disabled="busy || lines.length<=1" :aria-label="`Xóa khoản thu ${index+1}`" @click="lines.splice(index,1)">×</button>
    </div>
    <strong>Tổng: {{ formatMoney(total) }}</strong>
    <div v-if="editable" class="charge-actions"><button type="button" :disabled="busy || lines.length>=20" @click="lines.push({label:'',amount:''})">Thêm khoản</button><button type="button" :disabled="busy" @click="save()">Lưu bảng kê</button></div>
    <small>Lưu bảng kê cho phép bot gửi đúng số tiền/QR khi khách hỏi thanh toán. Không tự chuyển tiền hay đánh dấu đã thu.</small>
    <fieldset v-if="paymentEndpoint && order.metadata?.payment_request && remaining>0 && !['cancelled','refunded'].includes(order.status)">
      <legend>Ghi nhận tiền thực nhận</legend>
      <label>Số tiền<input v-model="amount" type="number" min="1" :max="remaining" step="1" /></label>
      <label>Hình thức<select v-model="method"><option value="bank_transfer">Chuyển khoản</option><option value="cash">Tiền mặt</option></select></label>
      <label>Mã đối soát<input v-model="reference" maxlength="255" /></label>
      <label class="verified"><input v-model="verified" type="checkbox" /> Tôi đã kiểm tra tiền thực nhận</label>
      <button type="button" :disabled="busy || !verified" @click="save(true)">Ghi nhận thu</button>
    </fieldset>
    <p v-if="error" role="alert">{{ error }}</p>
  </details>
</template>
<style scoped>
.payment-request-panel{min-width:220px;max-width:100%;padding:8px 0}.payment-request-panel summary{cursor:pointer;font-weight:600}.payment-request-panel p,.payment-request-panel small{display:block;white-space:normal;line-height:1.5}.charge-row{display:flex;gap:6px;align-items:end;margin:8px 0;flex-wrap:wrap}.charge-row label{flex:1 1 100px;min-width:0}.payment-request-panel label{display:grid;gap:4px}.payment-request-panel input,.payment-request-panel select{width:100%;min-width:0;box-sizing:border-box;padding:8px;border:1px solid var(--border-color,#ccd8db);border-radius:8px;background:var(--input-bg,#fff);color:inherit}.charge-actions{display:flex;gap:8px;margin:8px 0;flex-wrap:wrap}.verified{display:flex!important;align-items:center}.verified input{width:auto}.payment-request-panel button{min-height:36px}.payment-request-panel fieldset{display:grid;gap:8px;margin-top:12px;min-width:0}
@media(max-width:640px){.payment-request-panel button,.payment-request-panel input:not([type=checkbox]),.payment-request-panel select{min-height:44px}}
</style>
