import { ElMessageBox } from "element-plus";

export interface ConfirmOptions {
  title?: string;
  confirmText?: string;
  cancelText?: string;
  /** 危险操作（删除、报废、离职回收）用 error 类型，按钮显示为红色。 */
  danger?: boolean;
}

/**
 * 破坏性操作统一二次确认。
 *
 * 返回 true 表示用户确认；取消或关闭一律返回 false，调用方直接 return 即可，
 * 不需要自己写 try/catch 包 ElMessageBox。
 */
export async function confirmAction(message: string, options: ConfirmOptions = {}): Promise<boolean> {
  try {
    await ElMessageBox.confirm(message, options.title || "操作确认", {
      type: options.danger ? "error" : "warning",
      confirmButtonText: options.confirmText || "确认",
      cancelButtonText: options.cancelText || "取消",
      closeOnClickModal: false,
    });
    return true;
  } catch {
    return false;
  }
}
