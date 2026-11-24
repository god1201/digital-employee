export const approvalCategoryLabel = (value?: string | null): string =>
  ({ finance: "财务", contract: "合同", document: "文书", custom: "自定义" } as Record<string, string>)[
    value || ""
  ] || value || "—";

export const approvalNodeTypeLabel = (value?: string | null): string =>
  ({ approval: "审批", condition: "条件", cc: "抄送", end: "结束" } as Record<string, string>)[
    value || ""
  ] || value || "—";

export const approvalModeLabel = (value?: string | null): string =>
  ({ any: "或签", all: "会签", sequence: "依次" } as Record<string, string>)[value || ""] ||
  value ||
  "—";

export const approvalActionLabel = (value?: string | null): string =>
  ({
    submit: "提交",
    node_enter: "进入节点",
    approve: "通过",
    reject: "驳回",
    transfer: "转办",
    add_sign: "加签",
    remind: "催办",
    timeout_remind: "超时提醒",
    timeout_approve: "超时自动通过",
    timeout_reject: "超时自动驳回",
    timeout_escalate: "超时升级",
    cancel: "取消",
    complete: "流程结束",
    launch_task: "创建员工任务",
  } as Record<string, string>)[value || ""] || value || "—";

export const approvalUserLabel = (users: any[], id?: number | null): string => {
  const user = (users || []).find((item) => item.id === Number(id));
  return user ? user.full_name || user.username : id ? `#${id}` : "—";
};

export const approvalFormatFieldValue = (field: any, value: any, users: any[]): string => {
  if (value === null || value === undefined || value === "") return "—";
  if (field?.type === "select") {
    const option = (field.options || []).find(
      (item: any) => String(item?.value ?? item) === String(value),
    );
    return option ? option.label || option.value || option : String(value);
  }
  if (field?.type === "user") return approvalUserLabel(users, value);
  if (field?.type === "users") {
    return (value || []).map((item: number) => approvalUserLabel(users, item)).join("、") || "—";
  }
  if (field?.type === "json") return JSON.stringify(value);
  if (Array.isArray(value)) return value.join("、");
  if (typeof value === "object") return JSON.stringify(value);
  return String(value);
};
