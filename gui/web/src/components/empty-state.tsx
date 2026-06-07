// SPDX-License-Identifier: Apache-2.0
// Illustrated empty state — icon badge + title + guidance + optional recovery
// action. Used on primary content areas in place of bare muted "No X" text.
// Extracted from App.tsx (modularization) with no behavior change.
import { type ReactNode } from "react";

export function EmptyState({ icon, title, message, action }: {
  icon?: ReactNode;
  title: string;
  message?: ReactNode;
  action?: { label: string; onClick: () => void; icon?: ReactNode };
}) {
  return (
    <div className="empty-state" role="status">
      {icon && <span className="empty-state-icon">{icon}</span>}
      <strong>{title}</strong>
      {message && <span className="empty-state-msg">{message}</span>}
      {action && (
        <button className="ghost-button" onClick={action.onClick}>
          {action.icon}{action.label}
        </button>
      )}
    </div>
  );
}
