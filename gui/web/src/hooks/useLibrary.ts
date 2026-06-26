// SPDX-License-Identifier: Apache-2.0
// TanStack Query hooks for the operator-managed prompt + tool library. One shared
// cache: the chat's prompt selector and the LibraryManager both read ["prompts"],
// so a mutation invalidates a single key and every consumer updates — no manual
// refetch wiring, no stale selectors.
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, type ManagedTool } from "../api";

const PROMPTS = ["prompts"] as const;
const TOOLS = ["managed-tools"] as const;

export function usePrompts() {
  return useQuery({ queryKey: PROMPTS, queryFn: () => api.listPrompts().then((r) => r.prompts) });
}

export function usePromptMutations() {
  const qc = useQueryClient();
  const onSuccess = () => { void qc.invalidateQueries({ queryKey: PROMPTS }); };
  return {
    create: useMutation({ mutationFn: (p: { name: string; content: string; title?: string }) => api.createPrompt(p), onSuccess }),
    update: useMutation({ mutationFn: ({ id, ...p }: { id: string; name?: string; content?: string; title?: string }) => api.updatePrompt(id, p), onSuccess }),
    remove: useMutation({ mutationFn: (id: string) => api.deletePrompt(id), onSuccess }),
  };
}

export function useManagedTools() {
  return useQuery({ queryKey: TOOLS, queryFn: () => api.listManagedTools().then((r) => r.tools) });
}

export function useToolMutations() {
  const qc = useQueryClient();
  const onSuccess = () => { void qc.invalidateQueries({ queryKey: TOOLS }); };
  return {
    create: useMutation({ mutationFn: (t: Partial<ManagedTool>) => api.createManagedTool(t), onSuccess }),
    update: useMutation({ mutationFn: ({ id, ...t }: { id: string } & Partial<ManagedTool>) => api.updateManagedTool(id, t), onSuccess }),
    remove: useMutation({ mutationFn: (id: string) => api.deleteManagedTool(id), onSuccess }),
  };
}
