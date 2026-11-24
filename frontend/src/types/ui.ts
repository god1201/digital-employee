import type { Component } from "vue";

export type FieldType =
  | "text"
  | "textarea"
  | "number"
  | "date"
  | "select"
  | "multiselect"
  | "json"
  | "password";

export interface ModalField {
  name: string;
  label: string;
  type?: FieldType;
  required?: boolean;
  value?: unknown;
  options?: Array<string | { value: string | number; label: string }>;
  placeholder?: string;
  help?: string;
  rows?: number;
  step?: string | number;
  size?: number;
  numeric?: boolean;
  full?: boolean;
}

export interface FormModalOptions {
  title: string;
  sub?: string;
  wide?: boolean;
  fields: ModalField[];
  submitLabel?: string;
  onSubmit: (values: Record<string, any>) => Promise<void> | void;
}

export interface CustomModalOptions {
  component: Component;
  props?: Record<string, unknown>;
}

export interface DrawerOptions {
  component: Component;
  props?: Record<string, unknown>;
}
