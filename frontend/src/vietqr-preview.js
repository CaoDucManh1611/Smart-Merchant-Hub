function tlv(tag, value) {
  const text = String(value);
  if (text.length > 99) throw new RangeError(`VietQR field ${tag} is too long`);
  return `${tag}${String(text.length).padStart(2, "0")}${text}`;
}

function crc16Ccitt(text) {
  let crc = 0xffff;
  for (const byte of new TextEncoder().encode(text)) {
    crc ^= byte << 8;
    for (let bit = 0; bit < 8; bit += 1) {
      crc = crc & 0x8000 ? (crc << 1) ^ 0x1021 : crc << 1;
      crc &= 0xffff;
    }
  }
  return crc.toString(16).toUpperCase().padStart(4, "0");
}

export function buildVietQrPreviewPayload(bankBin, accountNumber, accountName) {
  const bin = String(bankBin || "").trim();
  const account = String(accountNumber || "").trim();
  const name = String(accountName || "").trim();
  if (!/^\d{6}$/.test(bin) || !/^\d{6,34}$/.test(account)) return "";
  if (!name || name.length > 100 || /[\u0000-\u001f\u007f]/.test(name)) return "";

  const recipient = tlv("00", bin) + tlv("01", account);
  const merchant = tlv("00", "A000000727") + tlv("01", recipient) + tlv("02", "QRIBFTTA");
  const payload = "000201010211"
    + tlv("38", merchant)
    + tlv("53", "704")
    + tlv("54", "1000")
    + tlv("58", "VN")
    + tlv("62", tlv("08", "SMHCHECK"))
    + "6304";
  return `${payload}${crc16Ccitt(payload)}`;
}

