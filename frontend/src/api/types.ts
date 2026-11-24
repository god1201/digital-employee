export interface Paged<T> {
  items: T[];
  total: number;
  page: number;
  page_size: number;
}

export interface User {
  id: number;
  tenant_id: number;
  username: string;
  email?: string | null;
  full_name?: string | null;
  is_active: boolean;
  is_superuser: boolean;
  last_login_at?: string | null;
  created_at?: string;
}

export interface LoginResponse {
  access_token: string;
  token_type: string;
  user: User;
}

export interface SelectOption {
  value: string | number;
  label: string;
}
