import { reactive } from "vue";
import { api } from "./core";

export const Account = reactive({
  loading: true,
  authenticated: false,
  guest: true,
  username: null,
  accountProtected: false,
});

export function applyAccount(data = {}) {
  Account.authenticated = Boolean(data.authenticated);
  Account.guest = !Account.authenticated;
  Account.username = data.username || null;
  Account.accountProtected = Boolean(data.account_protected);
  Account.loading = false;
  return Account;
}

export async function refreshAccount() {
  Account.loading = true;
  try {
    return applyAccount(await api("/auth/me"));
  } catch (error) {
    Account.loading = false;
    Account.accountProtected = Boolean(error.accountProtected);
    throw error;
  }
}

export async function logout() {
  applyAccount(await api("/auth/logout", { method: "POST" }));
}
