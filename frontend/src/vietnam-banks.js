export const VIETNAM_BANK_OPTIONS = [
  ["970415", "VietinBank"], ["970436", "Vietcombank"], ["970418", "BIDV"],
  ["970405", "Agribank"], ["970448", "OCB"], ["970422", "MBBank"],
  ["970407", "Techcombank"], ["970416", "ACB"], ["970432", "VPBank"],
  ["970423", "TPBank"], ["970403", "Sacombank"], ["970437", "HDBank"],
  ["970454", "VietCapitalBank"], ["970429", "SCB"], ["970441", "VIB"],
  ["970443", "SHB"], ["970431", "Eximbank"], ["970426", "MSB"],
  ["546034", "CAKE"], ["546035", "Ubank"], ["963388", "Timo"],
  ["970400", "SaigonBank"], ["970409", "BacABank"], ["971025", "MoMo"],
  ["971133", "PVcomBank Pay"], ["970412", "PVcomBank"], ["970414", "MBV"],
  ["970419", "NCB"], ["970424", "ShinhanBank"], ["970425", "ABBANK"],
  ["970427", "VietABank"], ["970428", "NamABank"], ["970430", "PGBank"],
  ["970433", "VietBank"], ["970438", "BaoVietBank"], ["970440", "SeABank"],
  ["970446", "COOPBANK"], ["970449", "LPBank"], ["970452", "KienLongBank"],
  ["668888", "KBank"], ["971032", "MVAS"], ["970444", "CBBank"],
  ["422589", "CIMB"], ["970434", "IndovinaBank"], ["970457", "Woori"],
  ["970462", "KookminHN"], ["970463", "KookminHCM"],
].map(([bin, name]) => ({ bin, name }));

export function mergeVietnamBankOptions(serverOptions) {
  const options = new Map(VIETNAM_BANK_OPTIONS.map((bank) => [bank.bin, bank]));
  if (Array.isArray(serverOptions)) {
    for (const bank of serverOptions) {
      if (bank?.bin && bank?.name) options.set(String(bank.bin), { bin: String(bank.bin), name: String(bank.name) });
    }
  }
  return [...options.values()];
}
