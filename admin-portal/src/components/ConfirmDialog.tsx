"use client";

import * as AlertDialog from "@radix-ui/react-alert-dialog";
import { cn } from "@/lib/cn";

export interface ConfirmDialogProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  title: string;
  description: string;
  confirmLabel: string;
  cancelLabel?: string;
  tone?: "danger" | "warning" | "default";
  busy?: boolean;
  onConfirm: () => void | Promise<void>;
}

export function ConfirmDialog({
  open,
  onOpenChange,
  title,
  description,
  confirmLabel,
  cancelLabel = "Cancel",
  tone = "danger",
  busy = false,
  onConfirm,
}: ConfirmDialogProps) {
  return (
    <AlertDialog.Root open={open} onOpenChange={onOpenChange}>
      <AlertDialog.Portal>
        <AlertDialog.Overlay className="fixed inset-0 z-50 bg-black/40" />
        <AlertDialog.Content className="fixed left-1/2 top-1/2 z-50 w-[calc(100%-2rem)] max-w-md -translate-x-1/2 -translate-y-1/2 rounded-lg border border-line bg-surface p-6 shadow-lg focus:outline-none">
          <AlertDialog.Title className="text-base font-semibold text-ink text-balance">
            {title}
          </AlertDialog.Title>
          <AlertDialog.Description className="mt-2 text-sm leading-relaxed text-muted text-pretty">
            {description}
          </AlertDialog.Description>
          <div className="mt-6 flex items-center justify-end gap-2">
            <AlertDialog.Cancel asChild>
              <button
                type="button"
                disabled={busy}
                className="inline-flex h-9 items-center justify-center rounded-md border border-line bg-surface px-3.5 text-sm font-medium text-ink hover:bg-canvas disabled:opacity-50"
              >
                {cancelLabel}
              </button>
            </AlertDialog.Cancel>
            <AlertDialog.Action asChild>
              <button
                type="button"
                disabled={busy}
                onClick={(e) => {
                  e.preventDefault();
                  void onConfirm();
                }}
                className={cn(
                  "inline-flex h-9 items-center justify-center rounded-md px-3.5 text-sm font-medium text-white disabled:opacity-50",
                  tone === "danger" && "bg-red-600 hover:bg-red-700",
                  tone === "warning" && "bg-amber-600 hover:bg-amber-700",
                  tone === "default" && "bg-emerald-600 hover:bg-emerald-700"
                )}
              >
                {busy ? "Working..." : confirmLabel}
              </button>
            </AlertDialog.Action>
          </div>
        </AlertDialog.Content>
      </AlertDialog.Portal>
    </AlertDialog.Root>
  );
}
