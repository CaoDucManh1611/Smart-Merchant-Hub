function asText(value) {
  return String(value || "").trim();
}

export function maskCustomerName(value) {
  return asText(value);
}

export function maskCustomerEmail(value) {
  const email = asText(value);
  const [localPart, domain] = email.split("@");

  if (!email) return "";
  if (!localPart || !domain) return `${email.slice(0, 2)}***`;

  return `${localPart.slice(0, Math.min(2, localPart.length))}***@${domain}`;
}

export function maskCustomerPhone(value) {
  const digits = asText(value).replace(/\D/g, "");
  if (!digits) return "";
  if (digits.length <= 4) return "*".repeat(digits.length);

  return `${"*".repeat(digits.length - 4)}${digits.slice(-4)}`;
}
